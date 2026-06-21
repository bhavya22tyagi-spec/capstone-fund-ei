"""
Tests for Eval E harness — trigger detection + escalation cascade (PRD §15.2).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).parent.parent
_GOLDEN_PATH = _PROJECT_ROOT / "evals" / "golden_trigger_escalation.jsonl"

REQUIRED_FIELDS = {
    "scenario_id", "trigger_function", "scope", "fund_id",
    "input_params", "expected_fires", "expected_cascade",
}
VALID_TRIGGER_FUNCTIONS = {
    "detect_risk_tier_change",
    "detect_sanctions_pep_hit",
    "detect_adverse_media_change",
    "detect_ubo_structure_change",
    "detect_document_expiry",
    "detect_country_risk_reclassification",
    "detect_shared_counterparty_contagion",
    "detect_ble_critical_cascade",
    "detect_sla_breach",
}


# ---------------------------------------------------------------------------
# Golden set loading
# ---------------------------------------------------------------------------

def _load() -> list[dict]:
    from evals.run_eval_e import load_golden_set
    return load_golden_set()


def test_golden_set_loads_15_entries():
    entries = _load()
    assert len(entries) == 15


def test_golden_set_required_fields():
    for entry in _load():
        for field in REQUIRED_FIELDS:
            assert field in entry, f"Missing {field!r} in {entry.get('scenario_id')}"


def test_ee09_expected_cascade_is_true():
    entries = {e["scenario_id"]: e for e in _load()}
    assert "ee-09" in entries
    assert entries["ee-09"]["expected_cascade"] is True


def test_ee09_cascade_trigger_count_is_2():
    entries = {e["scenario_id"]: e for e in _load()}
    assert entries["ee-09"].get("cascade_trigger_count") == 2


def test_ee09_cascade_scopes_ble_then_fund():
    entries = {e["scenario_id"]: e for e in _load()}
    assert entries["ee-09"].get("cascade_scopes") == ["ble", "fund"]


def test_all_trigger_functions_valid():
    for entry in _load():
        fn = entry["trigger_function"]
        assert fn in VALID_TRIGGER_FUNCTIONS, f"Unknown trigger function {fn!r}"


def test_all_trigger_functions_importable():
    import importlib
    mod = importlib.import_module("services.trigger_engine.triggers")
    for entry in _load():
        fn = entry["trigger_function"]
        assert hasattr(mod, fn), f"Function {fn!r} not found in trigger engine"


def test_no_fire_scenarios_are_ee12_through_ee15():
    no_fire = [e for e in _load() if not e["expected_fires"]]
    ids = {e["scenario_id"] for e in no_fire}
    assert ids == {"ee-12", "ee-13", "ee-14", "ee-15"}


def test_cascade_scenario_is_ee09_only():
    cascade = [e for e in _load() if e.get("expected_cascade")]
    assert len(cascade) == 1
    assert cascade[0]["scenario_id"] == "ee-09"


def test_all_fire_scenarios_have_expected_trigger_type():
    for entry in _load():
        if entry["expected_fires"]:
            assert entry.get("expected_trigger_type") is not None, (
                f"{entry['scenario_id']} fires but no expected_trigger_type"
            )


# ---------------------------------------------------------------------------
# MOCK run
# ---------------------------------------------------------------------------

def _run(**kwargs):
    from evals.run_eval_e import run_eval_e
    return run_eval_e(mock=True, **kwargs)


def test_mock_run_returns_eval_e_result():
    from evals.run_eval_e import EvalEResult
    result = _run()
    assert isinstance(result, EvalEResult)


def test_mock_run_total_is_15():
    assert _run().total_scenarios == 15


def test_mock_run_all_scenarios_passed():
    result = _run()
    assert result.scenarios_passed == 15


def test_mock_run_pass_rate_is_1_0():
    assert _run().scenario_pass_rate == 1.0


def test_mock_run_passed_is_true():
    assert _run().passed is True


def test_mock_run_is_mock_true():
    assert _run().is_mock is True


def test_mock_run_latency_ms_non_negative():
    assert _run().latency_ms >= 0


def test_mock_run_run_at_nonempty():
    assert _run().run_at


# ---------------------------------------------------------------------------
# Cascade scenario ee-09
# ---------------------------------------------------------------------------

def test_cascade_tests_total_equals_1():
    assert _run().cascade_tests_total == 1


def test_cascade_tests_passed_equals_1():
    assert _run().cascade_tests_passed == 1


def test_cascade_scenario_ee09_fires():
    result = _run()
    ee09 = next(r for r in result.scenario_results if r.scenario_id == "ee-09")
    assert ee09.cascade_generated is True


def test_cascade_scenario_ee09_cascade_matched():
    result = _run()
    ee09 = next(r for r in result.scenario_results if r.scenario_id == "ee-09")
    assert ee09.cascade_matched is True


def test_cascade_scenario_ee09_trigger_count_is_2():
    result = _run()
    ee09 = next(r for r in result.scenario_results if r.scenario_id == "ee-09")
    assert ee09.cascade_trigger_count == 2


def test_cascade_scenario_ee09_passed():
    result = _run()
    ee09 = next(r for r in result.scenario_results if r.scenario_id == "ee-09")
    assert ee09.passed is True


# ---------------------------------------------------------------------------
# No-fire scenarios
# ---------------------------------------------------------------------------

def test_no_fire_scenarios_actual_fires_false():
    result = _run()
    no_fire_ids = {"ee-12", "ee-13", "ee-14", "ee-15"}
    for r in result.scenario_results:
        if r.scenario_id in no_fire_ids:
            assert r.actual_fires is False, f"{r.scenario_id} should not fire"


def test_no_fire_scenarios_all_passed():
    result = _run()
    no_fire_ids = {"ee-12", "ee-13", "ee-14", "ee-15"}
    for r in result.scenario_results:
        if r.scenario_id in no_fire_ids:
            assert r.passed is True, f"{r.scenario_id} no-fire scenario failed"


# ---------------------------------------------------------------------------
# Specific scenario spot-checks
# ---------------------------------------------------------------------------

def test_ee01_fund_scope_fires():
    result = _run()
    ee01 = next(r for r in result.scenario_results if r.scenario_id == "ee-01")
    assert ee01.actual_fires is True
    assert ee01.actual_scope == "fund"
    assert ee01.actual_trigger_type == "risk_tier_change"


def test_ee02_ble_sanctions_fires():
    result = _run()
    ee02 = next(r for r in result.scenario_results if r.scenario_id == "ee-02")
    assert ee02.actual_fires is True
    assert ee02.actual_scope == "ble"
    assert ee02.actual_trigger_type == "new_sanctions_pep_hit"


def test_ee08_contagion_returns_list():
    from evals.run_eval_e import load_golden_set, _run_trigger
    entries = {e["scenario_id"]: e for e in load_golden_set()}
    raw = _run_trigger(entries["ee-08"])
    assert isinstance(raw, list)
    assert len(raw) == 3


def test_ee10_sla_breach_ble_fires():
    result = _run()
    ee10 = next(r for r in result.scenario_results if r.scenario_id == "ee-10")
    assert ee10.actual_fires is True
    assert ee10.actual_scope == "ble"


def test_ee11_sla_breach_fund_fires():
    result = _run()
    ee11 = next(r for r in result.scenario_results if r.scenario_id == "ee-11")
    assert ee11.actual_fires is True
    assert ee11.actual_scope == "fund"


# ---------------------------------------------------------------------------
# Log output
# ---------------------------------------------------------------------------

def test_log_written_after_run(tmp_path):
    log_file = tmp_path / "eval_e_test.jsonl"
    _run(log_path=log_file)
    assert log_file.exists()
    assert log_file.stat().st_size > 0


def test_log_has_required_fields(tmp_path):
    log_file = tmp_path / "eval_e_test.jsonl"
    _run(log_path=log_file)
    with open(log_file) as fh:
        entry = json.loads(fh.readline())
    for field in ("run_at", "total_scenarios", "scenarios_passed",
                  "cascade_tests_total", "cascade_tests_passed", "passed", "latency_ms"):
        assert field in entry, f"Missing {field!r} in log"


def test_scenario_result_fields_present():
    from evals.run_eval_e import ScenarioResult
    result = _run()
    r = result.scenario_results[0]
    assert hasattr(r, "scenario_id")
    assert hasattr(r, "passed")
    assert hasattr(r, "fires_matched")
    assert hasattr(r, "cascade_matched")


# ---------------------------------------------------------------------------
# Pass bar logic
# ---------------------------------------------------------------------------

def test_pass_bar_logic_all_pass():
    from evals.run_eval_e import EvalEResult, ScenarioResult
    dummy = ScenarioResult(
        scenario_id="x", trigger_function="f", scope="fund",
        expected_fires=True, actual_fires=True, fires_matched=True,
        expected_trigger_type="risk_tier_change", actual_trigger_type="risk_tier_change",
        trigger_type_matched=True,
        expected_scope="fund", actual_scope="fund", scope_matched=True,
        expected_cascade=False, cascade_generated=False, cascade_matched=True,
        cascade_trigger_count=0, passed=True, notes="",
    )
    r = EvalEResult(
        total_scenarios=1, scenarios_passed=1, scenario_pass_rate=1.0,
        cascade_tests_total=0, cascade_tests_passed=0, passed=True,
        is_mock=True, run_at="2026-06-20T00:00:00Z", latency_ms=0,
        scenario_results=[dummy],
    )
    assert r.passed is True


def test_pass_bar_logic_one_fail_fails():
    from evals.run_eval_e import EvalEResult, ScenarioResult
    dummy = ScenarioResult(
        scenario_id="x", trigger_function="f", scope="fund",
        expected_fires=True, actual_fires=False, fires_matched=False,
        expected_trigger_type="risk_tier_change", actual_trigger_type=None,
        trigger_type_matched=False,
        expected_scope="fund", actual_scope=None, scope_matched=False,
        expected_cascade=False, cascade_generated=False, cascade_matched=True,
        cascade_trigger_count=0, passed=False, notes="",
    )
    r = EvalEResult(
        total_scenarios=1, scenarios_passed=0, scenario_pass_rate=0.0,
        cascade_tests_total=0, cascade_tests_passed=0, passed=False,
        is_mock=True, run_at="2026-06-20T00:00:00Z", latency_ms=0,
        scenario_results=[dummy],
    )
    assert r.passed is False


def test_cascade_mismatch_fails():
    from evals.run_eval_e import EvalEResult, ScenarioResult
    dummy = ScenarioResult(
        scenario_id="ee-09", trigger_function="detect_ble_critical_cascade", scope="ble",
        expected_fires=True, actual_fires=True, fires_matched=True,
        expected_trigger_type="ble_critical_cascade",
        actual_trigger_type="ble_critical_cascade",
        trigger_type_matched=True,
        expected_scope="ble", actual_scope="ble", scope_matched=True,
        expected_cascade=True, cascade_generated=False, cascade_matched=False,
        cascade_trigger_count=0, passed=False, notes="",
    )
    r = EvalEResult(
        total_scenarios=1, scenarios_passed=0, scenario_pass_rate=0.0,
        cascade_tests_total=1, cascade_tests_passed=0, passed=False,
        is_mock=True, run_at="2026-06-20T00:00:00Z", latency_ms=0,
        scenario_results=[dummy],
    )
    assert r.passed is False


def test_run_twice_idempotent(tmp_path):
    log_file = tmp_path / "eval_e_idem.jsonl"
    r1 = _run(log_path=log_file)
    r2 = _run(log_path=log_file)
    assert r1.passed == r2.passed
    assert r1.scenarios_passed == r2.scenarios_passed
    # two log lines written
    with open(log_file) as fh:
        lines = [l for l in fh if l.strip()]
    assert len(lines) == 2
