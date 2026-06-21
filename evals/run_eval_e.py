"""
Eval E — Trigger Detection + Escalation Cascade (PRD §15.2, §10, §9.3).

Metric:
  scenario_pass_rate — fraction of scenarios where the trigger fires (or doesn't)
                       exactly as expected, with the correct trigger_type and scope.

Pass bar (PRD §15.2): scenario_pass_rate == 1.0  AND  all cascade tests pass.

MOCK flow (MOCK=true, default):
  - All trigger functions are deterministic (no LLM, no external calls).
  - scenario_pass_rate is 1.0 by construction.
  - Cascade: ee-09 (Bank Rossiya) → detect_ble_critical_cascade returns 2 triggers.

Note: trigger detection is fully deterministic (PRD §10, CLAUDE.md rule 1).
Eval E tests that the detection logic is correct and the cascade fires for ee-09.
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

MOCK: bool = os.getenv("MOCK", "true").lower() == "true"

PASS_BAR: float = 1.0
_GOLDEN_PATH = _PROJECT_ROOT / "evals" / "golden_trigger_escalation.jsonl"
_LOG_PATH = _PROJECT_ROOT / "evals" / "eval_e_runs.jsonl"


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class ScenarioResult:
    scenario_id: str
    trigger_function: str
    scope: str
    expected_fires: bool
    actual_fires: bool
    fires_matched: bool
    expected_trigger_type: Optional[str]
    actual_trigger_type: Optional[str]
    trigger_type_matched: bool
    expected_scope: Optional[str]
    actual_scope: Optional[str]
    scope_matched: bool
    expected_cascade: bool
    cascade_generated: bool
    cascade_matched: bool
    cascade_trigger_count: int
    passed: bool
    notes: str


@dataclass
class EvalEResult:
    total_scenarios: int
    scenarios_passed: int
    scenario_pass_rate: float
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


def _parse_date(val: str) -> date:
    return date.fromisoformat(val)


def _run_trigger(entry: dict):
    """
    Dispatch to the correct trigger function based on entry["trigger_function"].
    Returns the raw result (None, ReviewTrigger, or list[ReviewTrigger]).
    """
    from services.trigger_engine.triggers import (
        detect_adverse_media_change,
        detect_ble_critical_cascade,
        detect_country_risk_reclassification,
        detect_document_expiry,
        detect_risk_tier_change,
        detect_sanctions_pep_hit,
        detect_shared_counterparty_contagion,
        detect_sla_breach,
        detect_ubo_structure_change,
    )
    from services.rule_engine.models import RiskTier

    fn_name = entry["trigger_function"]
    params = dict(entry["input_params"])  # shallow copy

    if fn_name == "detect_risk_tier_change":
        params["previous_tier"] = RiskTier(params["previous_tier"])
        params["current_tier"] = RiskTier(params["current_tier"])
        return detect_risk_tier_change(**params)

    if fn_name == "detect_sanctions_pep_hit":
        return detect_sanctions_pep_hit(**params)

    if fn_name == "detect_adverse_media_change":
        return detect_adverse_media_change(**params)

    if fn_name == "detect_ubo_structure_change":
        return detect_ubo_structure_change(**params)

    if fn_name == "detect_document_expiry":
        params["expiry_date"] = _parse_date(params["expiry_date"])
        return detect_document_expiry(**params)

    if fn_name == "detect_country_risk_reclassification":
        return detect_country_risk_reclassification(**params)

    if fn_name == "detect_shared_counterparty_contagion":
        return detect_shared_counterparty_contagion(**params)

    if fn_name == "detect_ble_critical_cascade":
        return detect_ble_critical_cascade(**params)

    if fn_name == "detect_sla_breach":
        params["review_due_date"] = _parse_date(params["review_due_date"])
        if params.get("last_review_date") is not None:
            params["last_review_date"] = _parse_date(params["last_review_date"])
        return detect_sla_breach(**params)

    raise ValueError(f"Unknown trigger function: {fn_name!r}")


def _evaluate_scenario(entry: dict) -> ScenarioResult:
    scenario_id = entry["scenario_id"]
    fn_name = entry["trigger_function"]
    expected_fires = entry["expected_fires"]
    expected_type = entry.get("expected_trigger_type")
    expected_scope = entry.get("expected_scope")
    expected_cascade = entry.get("expected_cascade", False)
    expected_cascade_count = entry.get("cascade_trigger_count", 0)

    raw = _run_trigger(entry)

    # Normalise result into (fires, triggers_list)
    if raw is None:
        fires = False
        triggers = []
    elif isinstance(raw, list):
        fires = len(raw) > 0
        triggers = raw
    else:
        fires = True
        triggers = [raw]

    fires_matched = fires == expected_fires

    actual_type = triggers[0].trigger_type.value if triggers else None
    trigger_type_matched = (actual_type == expected_type) if expected_fires else True

    actual_scope = triggers[0].scope.value if triggers else None
    scope_matched = (actual_scope == expected_scope) if expected_fires else True

    # Cascade check: for ble_critical_cascade, expect len==2 with scopes [ble, fund]
    cascade_generated = False
    cascade_matched = True
    cascade_count = 0

    if expected_cascade:
        cascade_generated = len(triggers) >= 2
        if cascade_generated:
            expected_cascade_scopes = entry.get("cascade_scopes", [])
            actual_scopes = [t.scope.value for t in triggers]
            cascade_matched = (
                len(triggers) == expected_cascade_count
                and actual_scopes == expected_cascade_scopes
            )
        else:
            cascade_matched = False
        cascade_count = len(triggers)

    passed = fires_matched and trigger_type_matched and scope_matched and cascade_matched

    return ScenarioResult(
        scenario_id=scenario_id,
        trigger_function=fn_name,
        scope=entry["scope"],
        expected_fires=expected_fires,
        actual_fires=fires,
        fires_matched=fires_matched,
        expected_trigger_type=expected_type,
        actual_trigger_type=actual_type,
        trigger_type_matched=trigger_type_matched,
        expected_scope=expected_scope,
        actual_scope=actual_scope,
        scope_matched=scope_matched,
        expected_cascade=expected_cascade,
        cascade_generated=cascade_generated,
        cascade_matched=cascade_matched,
        cascade_trigger_count=cascade_count,
        passed=passed,
        notes=entry.get("notes", ""),
    )


# ---------------------------------------------------------------------------
# Core evaluation
# ---------------------------------------------------------------------------

def run_eval_e(
    golden_path: "Path | str | None" = None,
    mock: "bool | None" = None,
    log_path: "Path | str | None" = None,
) -> EvalEResult:
    """
    Run Eval E: trigger detection + escalation cascade over all golden scenarios.

    Args:
        golden_path: Override default golden_trigger_escalation.jsonl path.
        mock:        Override the MOCK env-var setting for this run.
        log_path:    Override default eval_e_runs.jsonl log path.

    Returns:
        EvalEResult with scenario_pass_rate, cascade results, and per-scenario detail.
    """
    is_mock = MOCK if mock is None else mock
    t0 = time.monotonic()

    entries = load_golden_set(golden_path)
    results: list[ScenarioResult] = [_evaluate_scenario(e) for e in entries]

    scenarios_passed = sum(1 for r in results if r.passed)
    total = len(results)
    pass_rate = scenarios_passed / total if total > 0 else 0.0

    cascade_entries = [e for e in entries if e.get("expected_cascade")]
    cascade_results = [r for r in results if r.expected_cascade]
    cascade_passed = sum(1 for r in cascade_results if r.cascade_matched)

    overall_passed = pass_rate >= PASS_BAR and cascade_passed == len(cascade_results)

    latency_ms = int((time.monotonic() - t0) * 1000)
    run_at = datetime.now(timezone.utc).isoformat()

    result = EvalEResult(
        total_scenarios=total,
        scenarios_passed=scenarios_passed,
        scenario_pass_rate=pass_rate,
        cascade_tests_total=len(cascade_results),
        cascade_tests_passed=cascade_passed,
        passed=overall_passed,
        is_mock=is_mock,
        run_at=run_at,
        latency_ms=latency_ms,
        scenario_results=results,
    )

    # Write log entry
    lp = Path(log_path) if log_path else _LOG_PATH
    lp.parent.mkdir(parents=True, exist_ok=True)
    log_entry = {
        "run_at": run_at,
        "total_scenarios": total,
        "scenarios_passed": scenarios_passed,
        "scenario_pass_rate": pass_rate,
        "cascade_tests_total": len(cascade_results),
        "cascade_tests_passed": cascade_passed,
        "passed": overall_passed,
        "is_mock": is_mock,
        "latency_ms": latency_ms,
        "scenario_results": [asdict(r) for r in results],
    }
    with open(lp, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(log_entry) + "\n")

    return result


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    result = run_eval_e()
    print("\nEval E — Trigger Detection + Escalation Cascade")
    print(f"Mode:              {'MOCK' if result.is_mock else 'REAL'}")
    print(f"Scenarios:         {result.scenarios_passed}/{result.total_scenarios} passed")
    print(f"Pass rate:         {result.scenario_pass_rate * 100:.1f}%  (bar: {PASS_BAR * 100:.0f}%)")
    print(f"Cascade tests:     {result.cascade_tests_passed}/{result.cascade_tests_total} passed")
    print(f"Latency:           {result.latency_ms} ms")
    print(f"PASSED:            {result.passed}")

    if not result.passed:
        print("\nFailed scenarios:")
        for r in result.scenario_results:
            if not r.passed:
                print(f"  {r.scenario_id}: fires={r.actual_fires} (exp {r.expected_fires}), "
                      f"type={r.actual_trigger_type!r} (exp {r.expected_trigger_type!r}), "
                      f"cascade_ok={r.cascade_matched}")
        sys.exit(1)
