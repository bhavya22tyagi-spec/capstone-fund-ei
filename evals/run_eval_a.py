"""
Eval A Harness — Extraction Accuracy (PRD §15.2).

Pass bar: ≥ 95% field-level exact / tolerance match across all 12 documents.
Hard gate: failing this eval blocks the Extraction Service from "done".

Comparison rules:
  str   → exact match after strip
  float / int → abs(expected - actual) ≤ 0.01
  None  → exact None match
  list  → order-insensitive; UBO arrays matched by name then field-by-field
  missing actual field → fail

MOCK=true (default):
  Mock extractor returns expected_fields verbatim → proves harness machinery
  works and baseline is 100%.  No LLM call, zero cost.

MOCK=false:
  Calls the real Extraction Service (wired in Phase 6).  Raises
  NotImplementedError until that service is built.

Idempotency (PRD §15.3):
  Keyed on (golden_set_hash, mock_flag, "eval_a", "v1"). Re-running with an
  unchanged golden set in the same session is a no-op that returns the cached
  result.

Usage:
  uv run python evals/run_eval_a.py          # MOCK=true
  MOCK=false uv run python evals/run_eval_a.py   # real extraction (Phase 6+)
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PASS_BAR: float = 0.95          # PRD §15.2 — field-level match rate
NUMERIC_TOLERANCE: float = 0.01  # ±0.01 for ownership_pct, amounts, etc.
MOCK: bool = os.getenv("MOCK", "true").lower() == "true"

_PROJECT_ROOT = Path(__file__).parent.parent
GOLDEN_SET_PATH = _PROJECT_ROOT / "evals" / "golden_extraction.jsonl"
LOG_PATH = _PROJECT_ROOT / "logs" / "eval_a_runs.jsonl"

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class FieldResult:
    field_path: str       # e.g. "incorporation_date" or "ubos[0].ownership_pct"
    expected: Any
    actual: Any
    matched: bool


@dataclass
class DocResult:
    doc_id: str
    fund_name: str
    document_type: str
    scope: str
    field_results: list[FieldResult]
    has_imperfection: bool
    imperfection_note: str | None = None

    @property
    def matched(self) -> int:
        return sum(1 for f in self.field_results if f.matched)

    @property
    def total(self) -> int:
        return len(self.field_results)

    @property
    def field_match_rate(self) -> float:
        return self.matched / self.total if self.total else 0.0


@dataclass
class EvalAResult:
    total_fields: int
    matched_fields: int
    score: float
    passed: bool
    doc_results: list[DocResult]
    run_at: str
    is_mock: bool
    cost_usd: float
    latency_ms: int

    def summary_line(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return (
            f"Eval A [{status}]  score={self.score:.1%}  "
            f"({self.matched_fields}/{self.total_fields} fields matched)  "
            f"mock={self.is_mock}  latency={self.latency_ms}ms"
        )


# ---------------------------------------------------------------------------
# Golden set loader
# ---------------------------------------------------------------------------


def load_golden_set(path: Path = GOLDEN_SET_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Golden set not found: {path}")
    entries = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def _golden_set_hash(entries: list[dict[str, Any]]) -> str:
    raw = json.dumps(entries, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Extraction (mock or real)
# ---------------------------------------------------------------------------


def _mock_extract(entry: dict[str, Any]) -> dict[str, Any]:
    """Return expected_fields verbatim — proves harness works at baseline."""
    return json.loads(json.dumps(entry["expected_fields"]))  # deep copy


def _real_extract(entry: dict[str, Any]) -> dict[str, Any]:
    from services.extraction import extract_document_fields
    from services.budget import BudgetCap

    scope = entry["scope"]
    scope_id = entry.get("ble_id") if scope == "ble" else entry["fund_id"]
    doc_id = entry["doc_id"]
    file_path = _PROJECT_ROOT / "documents" / scope / scope_id / f"{doc_id}.txt"

    return extract_document_fields(
        scope=scope,
        scope_id=scope_id,
        fund_id=entry["fund_id"],
        document_type=entry["document_type"],
        file_path=file_path,
        doc_id=doc_id,
        synthetic_static=False,
        budget=BudgetCap(limit_usd=1.00),
    )


def extract(entry: dict[str, Any]) -> dict[str, Any]:
    if MOCK:
        return _mock_extract(entry)
    return _real_extract(entry)


# ---------------------------------------------------------------------------
# Field-level comparison
# ---------------------------------------------------------------------------


def _scalar_match(expected: Any, actual: Any) -> bool:
    """Compare a single scalar value with appropriate tolerance."""
    if expected is None and actual is None:
        return True
    if expected is None or actual is None:
        return False
    # Numeric tolerance
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return abs(float(expected) - float(actual)) <= NUMERIC_TOLERANCE
    # String — strip and exact
    if isinstance(expected, str) and isinstance(actual, str):
        return expected.strip() == actual.strip()
    return expected == actual


def _compare_ubo_array(
    expected_ubos: list[dict],
    actual_ubos: list[dict],
    path_prefix: str,
) -> list[FieldResult]:
    """
    Order-insensitive UBO array comparison.
    Match each expected UBO by 'name'; check all other fields.
    Unmatched expected UBOs are full failures.
    """
    results: list[FieldResult] = []
    actual_by_name = {u.get("name"): u for u in (actual_ubos or [])}

    for i, exp_ubo in enumerate(expected_ubos):
        ubo_name = exp_ubo.get("name", f"ubo_{i}")
        act_ubo = actual_by_name.get(ubo_name)

        for key, exp_val in exp_ubo.items():
            fp = f"{path_prefix}[{ubo_name!r}].{key}"
            if act_ubo is None:
                results.append(FieldResult(fp, exp_val, None, False))
            else:
                act_val = act_ubo.get(key)
                results.append(FieldResult(fp, exp_val, act_val, _scalar_match(exp_val, act_val)))

    return results


def compare_fields(
    expected: dict[str, Any],
    actual: dict[str, Any],
) -> list[FieldResult]:
    """
    Recursively compare expected vs. actual extracted fields.
    Returns one FieldResult per atomic field comparison.
    """
    results: list[FieldResult] = []
    _compare_recursive(expected, actual, "", results)
    return results


def _compare_recursive(
    expected: Any,
    actual: Any,
    path: str,
    results: list[FieldResult],
) -> None:
    if isinstance(expected, dict):
        for key, exp_val in expected.items():
            child_path = f"{path}.{key}" if path else key
            act_val = actual.get(key) if isinstance(actual, dict) else None

            if key == "ubos" and isinstance(exp_val, list):
                act_ubos = act_val if isinstance(act_val, list) else []
                results.extend(_compare_ubo_array(exp_val, act_ubos, child_path))
            elif isinstance(exp_val, dict):
                _compare_recursive(exp_val, act_val or {}, child_path, results)
            elif isinstance(exp_val, list):
                # Non-UBO list: compare element-by-element
                act_list = act_val if isinstance(act_val, list) else []
                for idx, (e, a) in enumerate(
                    zip(exp_val, act_list + [None] * max(0, len(exp_val) - len(act_list)))
                ):
                    results.append(FieldResult(
                        f"{child_path}[{idx}]", e, a, _scalar_match(e, a)
                    ))
            else:
                results.append(FieldResult(
                    child_path, exp_val, act_val, _scalar_match(exp_val, act_val)
                ))
    else:
        results.append(FieldResult(path, expected, actual, _scalar_match(expected, actual)))


# ---------------------------------------------------------------------------
# Core eval runner
# ---------------------------------------------------------------------------

_cache: dict[str, EvalAResult] = {}


def run_eval_a(
    golden_set_path: Path = GOLDEN_SET_PATH,
    mock: bool | None = None,
) -> EvalAResult:
    """
    Run Eval A against the golden extraction set.

    Idempotent: caches result by (golden_set_hash, mock_flag) within a
    process run. Re-running with the same inputs returns cached result
    without re-calling the extractor.

    Args:
      golden_set_path: path to golden_extraction.jsonl
      mock: overrides MOCK env var if provided

    Returns:
      EvalAResult with score, pass/fail, per-doc breakdown.
    """
    is_mock = MOCK if mock is None else mock

    entries = load_golden_set(golden_set_path)
    cache_key = f"{_golden_set_hash(entries)}-{is_mock}"
    if cache_key in _cache:
        return _cache[cache_key]

    doc_results: list[DocResult] = []
    total_cost = 0.0
    t0 = time.monotonic()

    for entry in entries:
        imp = entry.get("_imperfection")

        # Extract (mock or real)
        if is_mock:
            actual_fields = _mock_extract(entry)
        else:
            actual_fields = _real_extract(entry)

        field_results = compare_fields(entry["expected_fields"], actual_fields)

        doc_results.append(DocResult(
            doc_id=entry["doc_id"],
            fund_name=entry.get("fund_name", ""),
            document_type=entry["document_type"],
            scope=entry["scope"],
            field_results=field_results,
            has_imperfection=imp is not None,
            imperfection_note=imp.get("note") if imp else None,
        ))

    latency_ms = int((time.monotonic() - t0) * 1000)

    total_fields   = sum(d.total for d in doc_results)
    matched_fields = sum(d.matched for d in doc_results)
    score = matched_fields / total_fields if total_fields else 0.0

    result = EvalAResult(
        total_fields=total_fields,
        matched_fields=matched_fields,
        score=score,
        passed=score >= PASS_BAR,
        doc_results=doc_results,
        run_at=datetime.now(timezone.utc).isoformat(),
        is_mock=is_mock,
        cost_usd=total_cost,
        latency_ms=latency_ms,
    )

    _log_result(result)
    _cache[cache_key] = result
    return result


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def _log_result(result: EvalAResult) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "eval_category": "A",
        "run_at": result.run_at,
        "score": round(result.score, 6),
        "passed": result.passed,
        "total_fields": result.total_fields,
        "matched_fields": result.matched_fields,
        "is_mock": result.is_mock,
        "cost_usd": result.cost_usd,
        "latency_ms": result.latency_ms,
        "doc_scores": [
            {
                "doc_id": d.doc_id,
                "field_match_rate": round(d.field_match_rate, 4),
                "matched": d.matched,
                "total": d.total,
                "has_imperfection": d.has_imperfection,
            }
            for d in result.doc_results
        ],
    }
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print_report(result: EvalAResult) -> None:
    print()
    print("=" * 72)
    print("  EVAL A — Extraction Accuracy")
    print("=" * 72)
    print(f"  {result.summary_line()}")
    print(f"  Pass bar : >={PASS_BAR:.0%}")
    print(f"  Run at   : {result.run_at}")
    print("-" * 72)
    print(f"  {'doc_id':<30}  {'type':<28}  {'score':>6}  {'imp':>4}")
    print(f"  {'-'*30}  {'-'*28}  {'-'*6}  {'-'*4}")
    for d in result.doc_results:
        imp_flag = " !" if d.has_imperfection else ""
        rate = f"{d.field_match_rate:.0%}"
        print(f"  {d.doc_id:<30}  {d.document_type:<28}  {rate:>6}{imp_flag}")
        if not all(f.matched for f in d.field_results):
            for fr in d.field_results:
                if not fr.matched:
                    print(f"    MISMATCH  {fr.field_path}")
                    print(f"      expected : {fr.expected!r}")
                    print(f"      actual   : {fr.actual!r}")
    print("-" * 72)
    if result.has_imperfection_pending():
        print("  [!] Imperfection rows (Phase 6 planted): expected_fields hold the")
        print("      planted document value, not the seed_truth.json correct value.")
        print("      MOCK=false runs will surface real extraction mismatches here.")
    print("=" * 72)
    print()


# monkey-patch helper so _print_report works
def _has_imperfection_pending(self: EvalAResult) -> bool:
    return any(d.has_imperfection for d in self.doc_results)

EvalAResult.has_imperfection_pending = _has_imperfection_pending  # type: ignore[attr-defined]


if __name__ == "__main__":
    result = run_eval_a()
    _print_report(result)
    raise SystemExit(0 if result.passed else 1)
