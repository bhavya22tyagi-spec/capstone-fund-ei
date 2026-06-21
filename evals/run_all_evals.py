"""
Fund EI — Full Eval Suite Orchestrator (PRD §19).

Runs Evals A through G sequentially in MOCK mode, aggregates results,
writes evals/compliance_report.json, and prints a terminal summary.

Exit code 0 if no FAIL (DEFERRED is not a failure).
Exit code 1 if any eval FAIL.

Usage:
    MOCK=true uv run python evals/run_all_evals.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

MOCK: bool = os.getenv("MOCK", "true").lower() == "true"

_REPORT_PATH = _PROJECT_ROOT / "evals" / "compliance_report.json"


@dataclass
class EvalSummary:
    category: str
    label: str
    status: str         # PASS | FAIL | DEFERRED
    passed: Optional[bool]
    pass_rate: Optional[float]
    total_scenarios: int
    latency_ms: int
    cost_usd: float
    is_mock: bool
    cascade_tested: bool
    cascade_passed: Optional[bool]
    notes: str


def _run_a() -> EvalSummary:
    from evals.run_eval_a import run_eval_a
    r = run_eval_a(mock=MOCK)
    return EvalSummary(
        category="A", label="Extraction Accuracy",
        status="PASS" if r.passed else "FAIL",
        passed=r.passed,
        pass_rate=getattr(r, "field_match_rate", None),
        total_scenarios=getattr(r, "total_fields", 0),
        latency_ms=r.latency_ms,
        cost_usd=r.cost_usd,
        is_mock=r.is_mock,
        cascade_tested=False, cascade_passed=None,
        notes="",
    )


def _run_b() -> EvalSummary:
    from evals.run_eval_b import run_eval_b
    r = run_eval_b(mock=MOCK)
    leakage_ok = not getattr(r, "leakage_detected", False)
    return EvalSummary(
        category="B", label="Retrieval + Scope Isolation",
        status="PASS" if r.passed else "FAIL",
        passed=r.passed,
        pass_rate=getattr(r, "retrieval_hit_rate", None),
        total_scenarios=getattr(r, "total_queries", 0),
        latency_ms=r.latency_ms,
        cost_usd=getattr(r, "cost_usd", 0.0),
        is_mock=r.is_mock,
        cascade_tested=False, cascade_passed=None,
        notes="leakage_ok=" + str(leakage_ok),
    )


def _run_c() -> EvalSummary:
    from evals.run_eval_c import run_eval_c
    r = run_eval_c(mock=MOCK)
    return EvalSummary(
        category="C", label="RAG Groundedness",
        status="PASS" if r.passed else "FAIL",
        passed=r.passed,
        pass_rate=getattr(r, "judge_pass_rate", None),
        total_scenarios=getattr(r, "total_qa_pairs", 0),
        latency_ms=r.latency_ms,
        cost_usd=getattr(r, "cost_usd", 0.0),
        is_mock=r.is_mock,
        cascade_tested=False, cascade_passed=None,
        notes="",
    )


def _run_d() -> EvalSummary:
    from evals.run_eval_d import run_eval_d
    r = run_eval_d(mock=MOCK)
    return EvalSummary(
        category="D", label="Text-to-SQL Security",
        status="PASS" if r.passed else "FAIL",
        passed=r.passed,
        pass_rate=getattr(r, "adversarial_block_rate", None),
        total_scenarios=getattr(r, "total_adversarial", 0),
        latency_ms=r.latency_ms,
        cost_usd=getattr(r, "cost_usd", 0.0),
        is_mock=r.is_mock,
        cascade_tested=False, cascade_passed=None,
        notes="",
    )


def _run_e() -> EvalSummary:
    from evals.run_eval_e import run_eval_e
    r = run_eval_e(mock=MOCK)
    return EvalSummary(
        category="E", label="Trigger Detection + Escalation Cascade",
        status="PASS" if r.passed else "FAIL",
        passed=r.passed,
        pass_rate=r.scenario_pass_rate,
        total_scenarios=r.total_scenarios,
        latency_ms=r.latency_ms,
        cost_usd=0.0,
        is_mock=r.is_mock,
        cascade_tested=True,
        cascade_passed=r.cascade_tests_passed == r.cascade_tests_total,
        notes=f"cascade={r.cascade_tests_passed}/{r.cascade_tests_total}",
    )


def _run_f() -> EvalSummary:
    from evals.run_eval_f import run_eval_f
    r = run_eval_f(mock=MOCK)
    return EvalSummary(
        category="F", label="MCP Tool Selection",
        status="PASS" if r.passed else "FAIL",
        passed=r.passed,
        pass_rate=r.tool_match_rate,
        total_scenarios=r.total_scenarios,
        latency_ms=r.latency_ms,
        cost_usd=0.0,
        is_mock=r.is_mock,
        cascade_tested=True,
        cascade_passed=r.cascade_tests_passed == r.cascade_tests_total,
        notes=f"tool_match={r.tool_match_rate:.0%}",
    )


def _run_g() -> EvalSummary:
    from evals.run_eval_g import run_eval_g
    r = run_eval_g(mock=MOCK)
    return EvalSummary(
        category="G", label="Judge Calibration",
        status="DEFERRED",
        passed=None,
        pass_rate=None,
        total_scenarios=0,
        latency_ms=0,
        cost_usd=0.0,
        is_mock=r.is_mock,
        cascade_tested=False, cascade_passed=None,
        notes=r.reason,
    )


_RUNNERS = [_run_a, _run_b, _run_c, _run_d, _run_e, _run_f, _run_g]


def run_all(mock: bool = MOCK) -> list[EvalSummary]:
    global MOCK
    MOCK = mock

    results: list[EvalSummary] = []
    for runner in _RUNNERS:
        t0 = time.monotonic()
        try:
            summary = runner()
        except Exception as exc:
            # Capture unexpected failures so the report still completes
            cat = runner.__name__.replace("_run_", "").upper()
            summary = EvalSummary(
                category=cat, label=f"Eval {cat}",
                status="FAIL",
                passed=False,
                pass_rate=None,
                total_scenarios=0,
                latency_ms=int((time.monotonic() - t0) * 1000),
                cost_usd=0.0,
                is_mock=mock,
                cascade_tested=False, cascade_passed=None,
                notes=f"ERROR: {exc}",
            )
        results.append(summary)
    return results


def _write_report(results: list[EvalSummary], path: Path = _REPORT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mock": MOCK,
        "total_evals": len(results),
        "passed": sum(1 for r in results if r.status == "PASS"),
        "failed": sum(1 for r in results if r.status == "FAIL"),
        "deferred": sum(1 for r in results if r.status == "DEFERRED"),
        "evals": [
            {
                "category": r.category,
                "label": r.label,
                "status": r.status,
                "passed": r.passed,
                "pass_rate": r.pass_rate,
                "total_scenarios": r.total_scenarios,
                "latency_ms": r.latency_ms,
                "cost_usd": r.cost_usd,
                "is_mock": r.is_mock,
                "cascade_tested": r.cascade_tested,
                "cascade_passed": r.cascade_passed,
                "notes": r.notes,
            }
            for r in results
        ],
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)


def _print_summary(results: list[EvalSummary]) -> None:
    width = 56
    line = "=" * width
    n_pass = sum(1 for r in results if r.status == "PASS")
    n_fail = sum(1 for r in results if r.status == "FAIL")
    n_defer = sum(1 for r in results if r.status == "DEFERRED")

    print(f"\n+{line}+")
    mode = "MOCK" if MOCK else "REAL"
    title = f"FUND EI -- COMPLIANCE EVAL REPORT ({mode})"
    print(f"|  {title:<{width - 2}}|")
    print(f"+{line}+")

    for r in results:
        if r.status == "PASS":
            badge = f"PASS  ({mode})"
            if r.cascade_tested:
                badge += " +cascade"
        elif r.status == "FAIL":
            badge = "FAIL  << REVIEW REQUIRED"
        else:
            badge = "DEFERRED"

        row = f"  {r.category}  {r.label:<35} {badge}"
        print(f"|{row:<{width}}|")

    print(f"+{line}+")
    overall = f"  OVERALL: {n_pass} PASS | {n_fail} FAIL | {n_defer} DEFERRED"
    print(f"|{overall:<{width}}|")
    print(f"+{line}+\n")

    if n_fail:
        print("FAILED EVALS:")
        for r in results:
            if r.status == "FAIL":
                print(f"  [{r.category}] {r.label} -- {r.notes}")


if __name__ == "__main__":
    results = run_all()
    _write_report(results)
    _print_summary(results)

    print(f"Report written to: {_REPORT_PATH}")

    n_fail = sum(1 for r in results if r.status == "FAIL")
    sys.exit(1 if n_fail else 0)
