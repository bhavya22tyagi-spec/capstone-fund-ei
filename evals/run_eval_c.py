"""
Eval C — Narrative Generation + LLM-as-Judge (PRD §15.2, §8.2, §18).

Metrics:
  judge_pass_rate   — fraction of golden QA entries where the LLM-as-judge
                      confirms the narrative accurately reflects the cited text.
  hallucinations    — count of entries where the narrative makes a claim that
                      CONTRADICTS or is UNSUPPORTED BY the cited document.

Pass bar (PRD §15.2):
  judge_pass_rate >= 0.80  AND  hallucinations_detected == 0

MOCK flow (MOCK=true, default):
  - Narrative = concatenated document texts (all citation_substrings guaranteed present).
  - Judge     = verbatim substring check (no LLM call).
  - Expected: judge_pass_rate = 1.0, hallucinations = 0 → PASSES.

Run with MOCK=false for real evaluation (costs ~$1-2 per full run).
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

MOCK: bool = os.getenv("MOCK", "true").lower() == "true"

JUDGE_PASS_BAR: float = 0.80
HALLUCINATION_LIMIT: int = 0

_PROJECT_ROOT = Path(__file__).parent.parent
_GOLDEN_QA_PATH = _PROJECT_ROOT / "evals" / "golden_qa.jsonl"
_LOG_PATH = _PROJECT_ROOT / "evals" / "eval_c_runs.jsonl"

# ---------------------------------------------------------------------------
# Document manifest (same 12 docs as Eval B — keyed by (scope, scope_id))
# ---------------------------------------------------------------------------

_DOC_MANIFEST: list[dict] = [
    # Fund F1
    {"scope": "fund", "scope_id": "f0000001-f000-0000-0000-000000000001",
     "fund_id": "f0000001-f000-0000-0000-000000000001", "doc_id": "doc-f1-incorp-cert",
     "document_type": "Incorporation Certificate",
     "file_path": "documents/fund/f0000001-f000-0000-0000-000000000001/doc-f1-incorp-cert.txt"},
    {"scope": "fund", "scope_id": "f0000001-f000-0000-0000-000000000001",
     "fund_id": "f0000001-f000-0000-0000-000000000001", "doc_id": "doc-f1-ubo-decl",
     "document_type": "UBO Declaration",
     "file_path": "documents/fund/f0000001-f000-0000-0000-000000000001/doc-f1-ubo-decl.txt"},
    # BLE B11
    {"scope": "ble", "scope_id": "b0001001-b000-0000-0000-000000000001",
     "fund_id": "f0000001-f000-0000-0000-000000000001", "doc_id": "doc-f1-b1-cpty-agmt",
     "document_type": "Counterparty Agreement",
     "file_path": "documents/ble/b0001001-b000-0000-0000-000000000001/doc-f1-b1-cpty-agmt.txt"},
    # Fund F2
    {"scope": "fund", "scope_id": "f0000002-f000-0000-0000-000000000002",
     "fund_id": "f0000002-f000-0000-0000-000000000002", "doc_id": "doc-f2-ubo-decl",
     "document_type": "UBO Declaration",
     "file_path": "documents/fund/f0000002-f000-0000-0000-000000000002/doc-f2-ubo-decl.txt"},
    {"scope": "fund", "scope_id": "f0000002-f000-0000-0000-000000000002",
     "fund_id": "f0000002-f000-0000-0000-000000000002", "doc_id": "doc-f2-annual-report",
     "document_type": "Annual Report",
     "file_path": "documents/fund/f0000002-f000-0000-0000-000000000002/doc-f2-annual-report.txt"},
    # BLE B21
    {"scope": "ble", "scope_id": "b0002001-b000-0000-0000-000000000002",
     "fund_id": "f0000002-f000-0000-0000-000000000002", "doc_id": "doc-f2-b1-framework-agmt",
     "document_type": "Framework Agreement",
     "file_path": "documents/ble/b0002001-b000-0000-0000-000000000002/doc-f2-b1-framework-agmt.txt"},
    # Fund F3
    {"scope": "fund", "scope_id": "f0000003-f000-0000-0000-000000000003",
     "fund_id": "f0000003-f000-0000-0000-000000000003", "doc_id": "doc-f3-incorp-cert",
     "document_type": "Incorporation Certificate",
     "file_path": "documents/fund/f0000003-f000-0000-0000-000000000003/doc-f3-incorp-cert.txt"},
    # Fund F4
    {"scope": "fund", "scope_id": "f0000004-f000-0000-0000-000000000004",
     "fund_id": "f0000004-f000-0000-0000-000000000004", "doc_id": "doc-f4-reg-licence",
     "document_type": "Regulatory Licence",
     "file_path": "documents/fund/f0000004-f000-0000-0000-000000000004/doc-f4-reg-licence.txt"},
    {"scope": "fund", "scope_id": "f0000004-f000-0000-0000-000000000004",
     "fund_id": "f0000004-f000-0000-0000-000000000004", "doc_id": "doc-f4-incorp-cert",
     "document_type": "Incorporation Certificate",
     "file_path": "documents/fund/f0000004-f000-0000-0000-000000000004/doc-f4-incorp-cert.txt"},
    # BLE B41
    {"scope": "ble", "scope_id": "b0004001-b000-0000-0000-000000000005",
     "fund_id": "f0000004-f000-0000-0000-000000000004", "doc_id": "doc-f4-b1-cpty-agmt",
     "document_type": "Counterparty Agreement",
     "file_path": "documents/ble/b0004001-b000-0000-0000-000000000005/doc-f4-b1-cpty-agmt.txt"},
    # Fund F5
    {"scope": "fund", "scope_id": "f0000005-f000-0000-0000-000000000005",
     "fund_id": "f0000005-f000-0000-0000-000000000005", "doc_id": "doc-f5-invest-mgr-agmt",
     "document_type": "Investment Manager Agreement",
     "file_path": "documents/fund/f0000005-f000-0000-0000-000000000005/doc-f5-invest-mgr-agmt.txt"},
    # BLE B51
    {"scope": "ble", "scope_id": "b0005001-b000-0000-0000-000000000006",
     "fund_id": "f0000005-f000-0000-0000-000000000005", "doc_id": "doc-f5-b1-cpty-agmt",
     "document_type": "Counterparty Agreement",
     "file_path": "documents/ble/b0005001-b000-0000-0000-000000000006/doc-f5-b1-cpty-agmt.txt"},
]

# ---------------------------------------------------------------------------
# Escalation context per fund scope group (from seed_truth.json)
# Only fund scopes that are escalated need this; all others are None.
# ---------------------------------------------------------------------------
_FUND_ESCALATION: dict[str, dict] = {
    "f0000001-f000-0000-0000-000000000001": {
        "risk_tier": "critical",
        "direct_tier": "low",
        "escalation_reason": "Escalated to Critical due to BLE(s): Bank Rossiya (Moscow, Russia)",
        "escalated_ble_names": ["Bank Rossiya (Moscow, Russia)"],
    },
    "f0000002-f000-0000-0000-000000000002": {
        "risk_tier": "medium",
        "direct_tier": "medium",
        "escalation_reason": None,
        "escalated_ble_names": None,
    },
    "f0000003-f000-0000-0000-000000000003": {
        "risk_tier": "low",
        "direct_tier": "low",
        "escalation_reason": None,
        "escalated_ble_names": None,
    },
    "f0000004-f000-0000-0000-000000000004": {
        "risk_tier": "high",
        "direct_tier": "high",
        "escalation_reason": None,
        "escalated_ble_names": None,
    },
    "f0000005-f000-0000-0000-000000000005": {
        "risk_tier": "medium",
        "direct_tier": "medium",
        "escalation_reason": None,
        "escalated_ble_names": None,
    },
}

_BLE_RISK_TIERS: dict[str, str] = {
    "b0001001-b000-0000-0000-000000000001": "critical",
    "b0002001-b000-0000-0000-000000000002": "medium",
    "b0004001-b000-0000-0000-000000000005": "medium",
    "b0005001-b000-0000-0000-000000000006": "low",
}


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class QAJudgeResult:
    qa_id: str
    scope: str
    scope_id: str
    citation_substring: str
    judge_passed: bool
    is_hallucination: bool
    skip_reason: Optional[str]  # None normally; "mock_mode_auto_pass" unused (MOCK runs the full judge)


@dataclass
class EvalCResult:
    total_qa: int
    judge_passed: int
    judge_pass_rate: float
    hallucinations_detected: int
    passed: bool
    is_mock: bool
    run_at: str
    latency_ms: int
    qa_results: list[QAJudgeResult]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def load_golden_qa(path: "Path | str | None" = None) -> list[dict]:
    p = Path(path) if path else _GOLDEN_QA_PATH
    entries = []
    with open(p, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def _group_by_scope(entries: list[dict]) -> dict[tuple[str, str], list[dict]]:
    """Group golden QA entries by (scope, scope_id)."""
    groups: dict[tuple[str, str], list[dict]] = {}
    for e in entries:
        key = (e["scope"], e["scope_id"])
        groups.setdefault(key, []).append(e)
    return groups


def _load_documents_for_scope(scope: str, scope_id: str) -> list:
    """Load DocumentInput objects for this scope from the manifest."""
    from services.narrative.service import DocumentInput
    docs = []
    for entry in _DOC_MANIFEST:
        if entry["scope"] == scope and entry["scope_id"] == scope_id:
            file_path = _PROJECT_ROOT / entry["file_path"]
            text = file_path.read_text(encoding="utf-8")
            docs.append(DocumentInput(
                doc_id=entry["doc_id"],
                document_type=entry["document_type"],
                text=text,
            ))
    return docs


# ---------------------------------------------------------------------------
# Core evaluation
# ---------------------------------------------------------------------------


def run_eval_c(
    golden_qa_path: "Path | str | None" = None,
    mock: "bool | None" = None,
    log_path: "Path | str | None" = None,
) -> EvalCResult:
    """
    Run Eval C — generate a narrative per scope group then judge each QA entry.

    Args:
        golden_qa_path: Override default golden_qa.jsonl path.
        mock:           Override the MOCK env-var setting for this run.
        log_path:       Override default eval_c_runs.jsonl log path.

    Returns:
        EvalCResult with pass rate, hallucination count, and per-entry details.
    """
    from services.budget import BudgetCap
    from services.narrative.service import NarrativeService

    is_mock = MOCK if mock is None else mock
    t0 = time.monotonic()

    entries = load_golden_qa(golden_qa_path)
    groups = _group_by_scope(entries)

    svc = NarrativeService()
    budget = BudgetCap(limit_usd=5.00)

    qa_results: list[QAJudgeResult] = []

    for (scope, scope_id), group_entries in groups.items():
        fund_id = group_entries[0]["fund_id"]

        documents = _load_documents_for_scope(scope, scope_id)

        if scope == "fund":
            esc = _FUND_ESCALATION.get(scope_id, {})
            risk_tier = esc.get("risk_tier", "medium")
            direct_tier = esc.get("direct_tier")
            escalation_reason = esc.get("escalation_reason")
            escalated_ble_names = esc.get("escalated_ble_names")
        else:
            risk_tier = _BLE_RISK_TIERS.get(scope_id, "medium")
            direct_tier = None
            escalation_reason = None
            escalated_ble_names = None

        narrative_result = svc.generate(
            scope=scope,
            scope_id=scope_id,
            fund_id=fund_id,
            synthetic_static=False,
            documents=documents,
            risk_tier=risk_tier,
            direct_tier=direct_tier,
            escalation_reason=escalation_reason,
            escalated_ble_names=escalated_ble_names,
            budget=budget,
        )

        for entry in group_entries:
            judge_result = svc.judge(
                narrative_result=narrative_result,
                citation_substring=entry["citation_substring"],
                qa_id=entry["qa_id"],
                fund_id=fund_id,
                synthetic_static=False,
                budget=budget,
            )
            qa_results.append(QAJudgeResult(
                qa_id=entry["qa_id"],
                scope=scope,
                scope_id=scope_id,
                citation_substring=entry["citation_substring"],
                judge_passed=judge_result.passed,
                is_hallucination=judge_result.is_hallucination,
                skip_reason=None,
            ))

    total_qa = len(qa_results)
    judge_passed_count = sum(1 for r in qa_results if r.judge_passed)
    hallucinations = sum(1 for r in qa_results if r.is_hallucination)
    judge_pass_rate = judge_passed_count / total_qa if total_qa > 0 else 0.0

    result = EvalCResult(
        total_qa=total_qa,
        judge_passed=judge_passed_count,
        judge_pass_rate=judge_pass_rate,
        hallucinations_detected=hallucinations,
        passed=(judge_pass_rate >= JUDGE_PASS_BAR and hallucinations == HALLUCINATION_LIMIT),
        is_mock=is_mock,
        run_at=datetime.now(timezone.utc).isoformat(),
        latency_ms=int((time.monotonic() - t0) * 1000),
        qa_results=qa_results,
    )

    _write_log(result, log_path)
    return result


def _write_log(result: EvalCResult, log_path: "Path | str | None" = None) -> None:
    p = Path(log_path) if log_path else _LOG_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "run_at": result.run_at,
        "is_mock": result.is_mock,
        "total_qa": result.total_qa,
        "judge_passed": result.judge_passed,
        "judge_pass_rate": result.judge_pass_rate,
        "hallucinations_detected": result.hallucinations_detected,
        "passed": result.passed,
        "latency_ms": result.latency_ms,
    }
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def _print_report(result: EvalCResult) -> None:
    print(f"\n{'='*60}")
    print(f"Eval C — Narrative Generation + LLM-as-Judge")
    print(f"{'='*60}")
    print(f"Mode:                   {'MOCK' if result.is_mock else 'REAL'}")
    print(f"QA entries evaluated:   {result.total_qa}")
    print(f"Judge passed:           {result.judge_passed}/{result.total_qa}")
    print(f"Judge pass rate:        {result.judge_pass_rate:.1%}  (bar: {JUDGE_PASS_BAR:.0%})")
    print(f"Hallucinations:         {result.hallucinations_detected}  (limit: {HALLUCINATION_LIMIT})")
    print(f"Latency:                {result.latency_ms} ms")
    print(f"PASSED:                 {result.passed}")
    print(f"{'='*60}")

    failures = [r for r in result.qa_results if not r.judge_passed]
    if failures:
        print("\nFailed QA entries:")
        for r in failures:
            tag = " [HALLUCINATION]" if r.is_hallucination else ""
            print(f"  [{r.qa_id}] ({r.scope}/{r.scope_id[:8]}…){tag}")
            print(f"    citation_substring: {r.citation_substring[:80]!r}")


if __name__ == "__main__":
    result = run_eval_c()
    _print_report(result)
    raise SystemExit(0 if result.passed else 1)
