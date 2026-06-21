"""
Eval F — MCP Tool-Selection Accuracy (PRD §15.2, §11, §8.2).

Metric:
  tool_match_rate — fraction of scenarios where the agent's tools_called
                    exactly matches the expected_tools set (order-independent).

Pass bar (PRD §15.2): tool_match_rate == 1.0  AND  all cascade tests pass.

MOCK flow (MOCK=true, default):
  - AgentOrchestrationService runs with no RAG service injected.
  - All MCP calls use canned MOCK results (no external API calls).
  - tool_match_rate is 1.0 by construction (deterministic _TOOL_POLICY).
  - Cascade: ef-02 (Bank Rossiya, confirmed sanctions) → two cards returned.

Note: tool selection is deterministic (_TOOL_POLICY dict, CLAUDE.md rule 1).
Eval F tests that the policy is correct and that the cascade fires for ef-02.
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

TOOL_MATCH_PASS_BAR: float = 1.0

_PROJECT_ROOT = Path(__file__).parent.parent
_GOLDEN_PATH = _PROJECT_ROOT / "evals" / "golden_tool_selection.jsonl"
_LOG_PATH = _PROJECT_ROOT / "evals" / "eval_f_runs.jsonl"


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class ScenarioResult:
    scenario_id: str
    trigger_type: str
    scope: str
    scope_id: str
    expected_tools: list[str]
    actual_tools: list[str]
    tools_matched: bool
    expected_cascade: bool
    cascade_generated: bool
    cascade_matched: bool           # True iff expected_cascade == cascade_generated
    passed: bool                    # tools_matched AND cascade_matched
    skip_reason: Optional[str]


@dataclass
class EvalFResult:
    total_scenarios: int
    scenarios_passed: int
    tool_match_rate: float
    cascade_tests_total: int
    cascade_tests_passed: int
    passed: bool
    is_mock: bool
    run_at: str
    latency_ms: int
    scenario_results: list[ScenarioResult]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_golden_set(path: "Path | str | None" = None) -> list[dict]:
    p = Path(path) if path else _GOLDEN_PATH
    entries = []
    with open(p, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def _build_trigger(entry: dict):
    from services.trigger_engine.models import ReviewTrigger, TriggerScope, TriggerType

    raw_scope = entry["scope"]
    # "both" scope in golden set maps to "ble" (contagion processed at BLE scope)
    try:
        scope = TriggerScope(raw_scope)
    except ValueError:
        scope = TriggerScope.BLE

    try:
        trigger_type = TriggerType(entry["trigger_type"])
    except ValueError:
        trigger_type = entry["trigger_type"]

    ble_id = entry["scope_id"] if raw_scope == "ble" else None

    return ReviewTrigger(
        trigger_type=trigger_type,
        scope=scope,
        fund_id=entry["fund_id"],
        ble_id=ble_id,
        detail=entry.get("trigger_detail", {}),
    )


# ---------------------------------------------------------------------------
# Core evaluation
# ---------------------------------------------------------------------------

def run_eval_f(
    golden_path: "Path | str | None" = None,
    mock: "bool | None" = None,
    log_path: "Path | str | None" = None,
) -> EvalFResult:
    """
    Run Eval F: tool-selection accuracy over all golden scenarios.

    Args:
        golden_path: Override default golden_tool_selection.jsonl path.
        mock:        Override the MOCK env-var setting for this run.
        log_path:    Override default eval_f_runs.jsonl log path.

    Returns:
        EvalFResult with tool_match_rate, cascade test results, and per-scenario detail.
    """
    from services.agent.service import AgentOrchestrationService

    is_mock = MOCK if mock is None else mock
    t0 = time.monotonic()

    entries = load_golden_set(golden_path)
    svc = AgentOrchestrationService(rag_service=None)

    scenario_results: list[ScenarioResult] = []

    for entry in entries:
        trigger = _build_trigger(entry)
        fund_id = entry["fund_id"]

        cards = svc.process_trigger(
            trigger=trigger,
            fund_id=fund_id,
            synthetic_static=False,
        )

        actual_tools = cards[0].tools_called if cards else []
        expected_tools = entry["expected_tools"]

        tools_matched = set(actual_tools) == set(expected_tools)

        expected_cascade: bool = bool(entry.get("expected_cascade", False))
        cascade_generated: bool = (
            len(cards) == 2
            and cards[1].trigger_type == "ble_critical_cascade"
            and cards[1].scope == "fund"
        )
        cascade_matched: bool = expected_cascade == cascade_generated
        passed = tools_matched and cascade_matched

        scenario_results.append(ScenarioResult(
            scenario_id=entry["scenario_id"],
            trigger_type=entry["trigger_type"],
            scope=entry["scope"],
            scope_id=entry["scope_id"],
            expected_tools=expected_tools,
            actual_tools=actual_tools,
            tools_matched=tools_matched,
            expected_cascade=expected_cascade,
            cascade_generated=cascade_generated,
            cascade_matched=cascade_matched,
            passed=passed,
            skip_reason=None,
        ))

    total = len(scenario_results)
    passed_count = sum(1 for r in scenario_results if r.passed)
    tool_match_rate = passed_count / total if total > 0 else 0.0

    cascade_scenarios = [r for r in scenario_results if r.expected_cascade]
    cascade_passed = sum(1 for r in cascade_scenarios if r.cascade_matched)

    result = EvalFResult(
        total_scenarios=total,
        scenarios_passed=passed_count,
        tool_match_rate=tool_match_rate,
        cascade_tests_total=len(cascade_scenarios),
        cascade_tests_passed=cascade_passed,
        passed=(tool_match_rate >= TOOL_MATCH_PASS_BAR and cascade_passed == len(cascade_scenarios)),
        is_mock=is_mock,
        run_at=datetime.now(timezone.utc).isoformat(),
        latency_ms=int((time.monotonic() - t0) * 1000),
        scenario_results=scenario_results,
    )

    _write_log(result, log_path)
    return result


def _write_log(result: EvalFResult, log_path: "Path | str | None" = None) -> None:
    p = Path(log_path) if log_path else _LOG_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "run_at": result.run_at,
        "is_mock": result.is_mock,
        "total_scenarios": result.total_scenarios,
        "scenarios_passed": result.scenarios_passed,
        "tool_match_rate": result.tool_match_rate,
        "cascade_tests_total": result.cascade_tests_total,
        "cascade_tests_passed": result.cascade_tests_passed,
        "passed": result.passed,
        "latency_ms": result.latency_ms,
    }
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def _print_report(result: EvalFResult) -> None:
    print(f"\n{'='*60}")
    print(f"Eval F — MCP Tool-Selection Accuracy")
    print(f"{'='*60}")
    print(f"Mode:                {'MOCK' if result.is_mock else 'REAL'}")
    print(f"Scenarios:           {result.scenarios_passed}/{result.total_scenarios} passed")
    print(f"Tool match rate:     {result.tool_match_rate:.1%}  (bar: {TOOL_MATCH_PASS_BAR:.0%})")
    print(f"Cascade tests:       {result.cascade_tests_passed}/{result.cascade_tests_total} passed")
    print(f"Latency:             {result.latency_ms} ms")
    print(f"PASSED:              {result.passed}")
    print(f"{'='*60}")

    failures = [r for r in result.scenario_results if not r.passed]
    if failures:
        print("\nFailed scenarios:")
        for r in failures:
            if not r.tools_matched:
                print(f"  [{r.scenario_id}] tool mismatch:")
                print(f"    expected: {sorted(r.expected_tools)}")
                print(f"    actual:   {sorted(r.actual_tools)}")
            if not r.cascade_matched:
                print(f"  [{r.scenario_id}] cascade mismatch: "
                      f"expected={r.expected_cascade}, got={r.cascade_generated}")


if __name__ == "__main__":
    result = run_eval_f()
    _print_report(result)
    raise SystemExit(0 if result.passed else 1)
