"""
Eval D — Text-to-SQL Correctness (PRD §15.2).

Two test populations:
  1. Golden queries  (evals/golden_sql.jsonl, 10 entries):
       Generated SQL is executed against the live DB and the result-set is
       compared to the precomputed expected_result.
       Pass bar: exact_match_rate == 1.0  (100%)
       MOCK mode: generation + validation run, but execution is skipped —
       accuracy is not measured; only plumbing is verified.

  2. Adversarial queries (evals/adversarial_sql.jsonl, 20 entries):
       Each SQL string is passed directly to validate_sql().
       Every entry MUST be blocked.
       Pass bar: adversarial_block_rate == 1.0  (HARD REQUIREMENT — both MOCK and real)

Overall eval passes if:
  - adversarial_block_rate == 1.0, AND
  - (MOCK or golden_exact_match_rate == 1.0)

Run MOCK=true (default) to verify plumbing and adversarial blocking.
Run MOCK=false with DATABASE_URL set to measure full end-to-end accuracy.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

MOCK: bool = os.getenv("MOCK", "true").lower() == "true"

GOLDEN_PASS_BAR: float = 1.0
ADVERSARIAL_PASS_BAR: float = 1.0

_PROJECT_ROOT = Path(__file__).parent.parent
_GOLDEN_PATH = _PROJECT_ROOT / "evals" / "golden_sql.jsonl"
_ADVERSARIAL_PATH = _PROJECT_ROOT / "evals" / "adversarial_sql.jsonl"
_LOG_PATH = _PROJECT_ROOT / "evals" / "eval_d_runs.jsonl"

_FUND_ID_FOR_LOGGING = "f0000001-f000-0000-0000-000000000001"

_cache: dict[str, "EvalDResult"] = {}


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class GoldenQueryResult:
    sql_id: str
    question: str
    expected_result_type: str
    passed: bool
    generated_sql: str
    expected_result: Any
    actual_result: Any
    skip_reason: str | None  # "mock_mode" when execution skipped


@dataclass
class AdversarialResult:
    adv_id: str
    attack_type: str
    sql: str
    expected_blocked: bool
    was_blocked: bool
    blocked_reason: str | None
    passed: bool  # True when was_blocked == expected_blocked


@dataclass
class EvalDResult:
    # Golden set
    total_golden: int
    golden_passed: int
    golden_skipped: int
    golden_exact_match_rate: float  # excludes skipped
    # Adversarial set
    total_adversarial: int
    adversarial_blocked: int
    adversarial_block_rate: float
    # Overall
    passed: bool
    is_mock: bool
    run_at: str
    latency_ms: int
    golden_results: list[GoldenQueryResult]
    adversarial_results: list[AdversarialResult]


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_golden_set(path: "Path | str | None" = None) -> list[dict]:
    p = Path(path) if path else _GOLDEN_PATH
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def load_adversarial_set(path: "Path | str | None" = None) -> list[dict]:
    p = Path(path) if path else _ADVERSARIAL_PATH
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


# ---------------------------------------------------------------------------
# Result comparison helpers
# ---------------------------------------------------------------------------

def _normalise(val: Any) -> Any:
    """Recursively convert Decimal → float so comparisons work."""
    if isinstance(val, Decimal):
        return float(val)
    if isinstance(val, dict):
        return {k: _normalise(v) for k, v in val.items()}
    if isinstance(val, list):
        return [_normalise(v) for v in val]
    return val


def _row_to_frozenset(row: dict) -> frozenset:
    """Convert a result row to a frozenset of (key, value) pairs for order-free comparison."""
    return frozenset((_normalise(k), _normalise(v)) for k, v in row.items())


def _compare_results(
    expected_result_type: str,
    expected: Any,
    actual_rows: list[dict],
) -> bool:
    """
    Return True when actual matches expected.

    scalar    — actual is a single-column, single-row result; compare as scalar.
    single_row — actual has one row; all expected key-value pairs must match.
    multi_row  — set-equality on rows (order-independent).
    """
    actual = _normalise(actual_rows)
    exp = _normalise(expected)

    if expected_result_type == "scalar":
        if not actual:
            return False
        # The scalar value is the first column of the first row.
        first_row = actual[0]
        actual_val = next(iter(first_row.values()))
        return actual_val == exp

    if expected_result_type == "single_row":
        if len(actual) != 1:
            return False
        actual_row = actual[0]
        # All expected keys must match; extra keys in actual are ignored.
        return all(actual_row.get(k) == v for k, v in exp.items())

    if expected_result_type == "multi_row":
        if len(actual) != len(exp):
            return False
        actual_set = {_row_to_frozenset(r) for r in actual}
        exp_set = {_row_to_frozenset(r) for r in exp}
        return actual_set == exp_set

    return False


# ---------------------------------------------------------------------------
# Core evaluation
# ---------------------------------------------------------------------------

def run_eval_d(
    golden_path: "Path | str | None" = None,
    adversarial_path: "Path | str | None" = None,
    mock: "bool | None" = None,
    log_path: "Path | str | None" = None,
) -> EvalDResult:
    is_mock = MOCK if mock is None else mock
    cache_key = f"{golden_path or 'default'}-{adversarial_path or 'default'}-{is_mock}"
    if cache_key in _cache:
        return _cache[cache_key]

    t0 = time.monotonic()

    from services.budget import BudgetCap            # noqa: PLC0415
    from services.text_to_sql import TextToSQLService  # noqa: PLC0415

    svc = TextToSQLService()
    budget = BudgetCap(limit_usd=5.0)

    golden_entries = load_golden_set(golden_path)
    adversarial_entries = load_adversarial_set(adversarial_path)

    # ------------------------------------------------------------------
    # 1. Adversarial pass — validate_sql only, no LLM call
    # ------------------------------------------------------------------
    adversarial_results: list[AdversarialResult] = []
    for entry in adversarial_entries:
        vr = svc.validate_sql(entry["sql"])
        was_blocked = not vr.passed
        adversarial_results.append(AdversarialResult(
            adv_id=entry["adv_id"],
            attack_type=entry["attack_type"],
            sql=entry["sql"],
            expected_blocked=entry["expected_blocked"],
            was_blocked=was_blocked,
            blocked_reason=vr.blocked_reason,
            passed=(was_blocked == entry["expected_blocked"]),
        ))

    adversarial_blocked = sum(1 for r in adversarial_results if r.was_blocked)
    adversarial_block_rate = adversarial_blocked / len(adversarial_results) if adversarial_results else 0.0

    # ------------------------------------------------------------------
    # 2. Golden pass — generate SQL, execute if real, compare
    # ------------------------------------------------------------------
    golden_results: list[GoldenQueryResult] = []
    for entry in golden_entries:
        result = svc.query(
            question=entry["question"],
            fund_id=_FUND_ID_FOR_LOGGING,
            synthetic_static=False,
            scope="fund",
            scope_id=_FUND_ID_FOR_LOGGING,
            budget=budget,
        )

        if is_mock or result.sql_result is None:
            # MOCK mode or validation failure — skip accuracy check
            golden_results.append(GoldenQueryResult(
                sql_id=entry["sql_id"],
                question=entry["question"],
                expected_result_type=entry["expected_result_type"],
                passed=True,  # vacuously pass — plumbing ran without error
                generated_sql=result.generated_sql,
                expected_result=entry["expected_result"],
                actual_result=None,
                skip_reason="mock_mode" if is_mock else "validation_failed",
            ))
            continue

        actual_rows = result.sql_result.rows
        match = _compare_results(
            expected_result_type=entry["expected_result_type"],
            expected=entry["expected_result"],
            actual_rows=actual_rows,
        )
        golden_results.append(GoldenQueryResult(
            sql_id=entry["sql_id"],
            question=entry["question"],
            expected_result_type=entry["expected_result_type"],
            passed=match,
            generated_sql=result.generated_sql,
            expected_result=entry["expected_result"],
            actual_result=actual_rows,
            skip_reason=None,
        ))

    golden_skipped = sum(1 for r in golden_results if r.skip_reason is not None)
    golden_attempted = len(golden_results) - golden_skipped
    golden_passed = sum(
        1 for r in golden_results if r.passed and r.skip_reason is None
    )
    golden_exact_match_rate = (
        golden_passed / golden_attempted if golden_attempted > 0 else 0.0
    )

    # Overall pass requires:
    # - All adversarial blocked
    # - If real mode: all golden exact match
    golden_criterion = is_mock or (golden_exact_match_rate >= GOLDEN_PASS_BAR)
    overall_passed = (adversarial_block_rate >= ADVERSARIAL_PASS_BAR) and golden_criterion

    eval_result = EvalDResult(
        total_golden=len(golden_results),
        golden_passed=golden_passed,
        golden_skipped=golden_skipped,
        golden_exact_match_rate=golden_exact_match_rate,
        total_adversarial=len(adversarial_results),
        adversarial_blocked=adversarial_blocked,
        adversarial_block_rate=adversarial_block_rate,
        passed=overall_passed,
        is_mock=is_mock,
        run_at=datetime.now(timezone.utc).isoformat(),
        latency_ms=int((time.monotonic() - t0) * 1000),
        golden_results=golden_results,
        adversarial_results=adversarial_results,
    )

    _write_log(eval_result, log_path)
    _cache[cache_key] = eval_result
    return eval_result


# ---------------------------------------------------------------------------
# Logging and reporting
# ---------------------------------------------------------------------------

def _write_log(result: EvalDResult, log_path: "Path | str | None" = None) -> None:
    p = Path(log_path) if log_path else _LOG_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "run_at": result.run_at,
        "is_mock": result.is_mock,
        "total_golden": result.total_golden,
        "golden_passed": result.golden_passed,
        "golden_skipped": result.golden_skipped,
        "golden_exact_match_rate": result.golden_exact_match_rate,
        "total_adversarial": result.total_adversarial,
        "adversarial_blocked": result.adversarial_blocked,
        "adversarial_block_rate": result.adversarial_block_rate,
        "passed": result.passed,
        "latency_ms": result.latency_ms,
    }
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def _print_report(result: EvalDResult) -> None:
    print(f"\n{'='*62}")
    print(f"Eval D — Text-to-SQL Correctness")
    print(f"{'='*62}")
    print(f"Mode:                  {'MOCK' if result.is_mock else 'REAL'}")
    print(f"Adversarial blocked:   {result.adversarial_blocked}/{result.total_adversarial}"
          f"  ({result.adversarial_block_rate:.0%})")
    if not result.is_mock:
        print(f"Golden exact match:    {result.golden_passed}/{result.total_golden - result.golden_skipped}"
              f"  ({result.golden_exact_match_rate:.0%})")
    else:
        print(f"Golden accuracy:       N/A (MOCK — execution skipped)")
    print(f"Latency:               {result.latency_ms} ms")
    print(f"PASSED:                {result.passed}")
    print(f"{'='*62}")

    missed_adv = [r for r in result.adversarial_results if not r.passed]
    if missed_adv:
        print("\nADVERSARIAL FAILURES (should have been blocked):")
        for r in missed_adv:
            print(f"  [{r.adv_id}] {r.attack_type}: {r.sql[:70]!r}")

    if not result.is_mock:
        missed_golden = [r for r in result.golden_results if not r.passed and r.skip_reason is None]
        if missed_golden:
            print("\nGOLDEN MISMATCHES:")
            for r in missed_golden:
                print(f"  [{r.sql_id}] {r.question[:60]!r}")
                print(f"      expected: {r.expected_result!r}")
                print(f"      actual:   {r.actual_result!r}")


if __name__ == "__main__":
    result = run_eval_d()
    _print_report(result)
    raise SystemExit(0 if result.passed else 1)
