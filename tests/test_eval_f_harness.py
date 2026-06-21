"""
Tests for the Eval F harness (evals/run_eval_f.py).

All tests run in MOCK mode. Tool selection is deterministic, so all 8 scenarios
pass by construction. Tests verify golden set structure, harness logic,
cascade detection, pass-bar enforcement, and logging.
"""

from __future__ import annotations

import json
import os
import pytest
from pathlib import Path

os.environ.setdefault("MOCK", "true")

from evals.run_eval_f import (
    EvalFResult,
    ScenarioResult,
    TOOL_MATCH_PASS_BAR,
    _build_trigger,
    load_golden_set,
    run_eval_f,
)


_PROJECT_ROOT = Path(__file__).parent.parent
_GOLDEN_PATH = _PROJECT_ROOT / "evals" / "golden_tool_selection.jsonl"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def golden_entries():
    return load_golden_set()


@pytest.fixture()
def mock_result():
    return run_eval_f(mock=True)


# ===========================================================================
# Section 1 — Golden set loading
# ===========================================================================

def test_load_golden_set_count(golden_entries):
    assert len(golden_entries) == 8


def test_load_golden_set_required_fields(golden_entries):
    for e in golden_entries:
        assert "scenario_id" in e
        assert "trigger_type" in e
        assert "scope" in e
        assert "scope_id" in e
        assert "fund_id" in e
        assert "expected_tools" in e
        assert "expected_cascade" in e


def test_ef_02_expected_cascade_true(golden_entries):
    ef02 = next(e for e in golden_entries if e["scenario_id"] == "ef-02")
    assert ef02["expected_cascade"] is True


def test_all_expected_tools_nonempty(golden_entries):
    for e in golden_entries:
        assert len(e["expected_tools"]) > 0, f"{e['scenario_id']} has empty expected_tools"


def test_all_scenario_ids_unique(golden_entries):
    ids = [e["scenario_id"] for e in golden_entries]
    assert len(ids) == len(set(ids))


# ===========================================================================
# Section 2 — run_eval_f() MOCK run
# ===========================================================================

def test_run_eval_f_returns_result(mock_result):
    assert isinstance(mock_result, EvalFResult)


def test_run_eval_f_total_8(mock_result):
    assert mock_result.total_scenarios == 8


def test_run_eval_f_tool_match_rate_100(mock_result):
    assert mock_result.tool_match_rate == 1.0, (
        f"Expected 100% tool match rate; failures: "
        f"{[r.scenario_id for r in mock_result.scenario_results if not r.tools_matched]}"
    )


def test_run_eval_f_passed_true(mock_result):
    assert mock_result.passed is True


def test_run_eval_f_is_mock_true(mock_result):
    assert mock_result.is_mock is True


def test_run_eval_f_all_scenarios_passed(mock_result):
    failures = [r for r in mock_result.scenario_results if not r.passed]
    assert failures == [], (
        f"Scenarios that failed: {[r.scenario_id for r in failures]}"
    )


# ===========================================================================
# Section 3 — Cascade scenario ef-02
# ===========================================================================

def test_ef_02_cascade_generated(mock_result):
    ef02 = next(r for r in mock_result.scenario_results if r.scenario_id == "ef-02")
    assert ef02.cascade_generated is True


def test_ef_02_cascade_matched(mock_result):
    ef02 = next(r for r in mock_result.scenario_results if r.scenario_id == "ef-02")
    assert ef02.cascade_matched is True


def test_ef_02_tools_matched(mock_result):
    ef02 = next(r for r in mock_result.scenario_results if r.scenario_id == "ef-02")
    assert ef02.tools_matched is True
    assert set(ef02.actual_tools) == set(ef02.expected_tools)


# ===========================================================================
# Section 4 — Pass bar logic
# ===========================================================================

def test_pass_bar_constant():
    assert TOOL_MATCH_PASS_BAR == 1.0


def test_eval_result_fails_when_rate_below_1():
    result = EvalFResult(
        total_scenarios=8, scenarios_passed=7, tool_match_rate=0.875,
        cascade_tests_total=1, cascade_tests_passed=1,
        passed=(0.875 >= TOOL_MATCH_PASS_BAR and 1 == 1),
        is_mock=True, run_at="2026-06-20T00:00:00+00:00",
        latency_ms=10, scenario_results=[],
    )
    assert result.passed is False


def test_eval_result_fails_when_cascade_mismatch():
    result = EvalFResult(
        total_scenarios=8, scenarios_passed=8, tool_match_rate=1.0,
        cascade_tests_total=1, cascade_tests_passed=0,
        passed=(1.0 >= TOOL_MATCH_PASS_BAR and 0 == 1),
        is_mock=True, run_at="2026-06-20T00:00:00+00:00",
        latency_ms=10, scenario_results=[],
    )
    assert result.passed is False


def test_eval_result_passes_when_all_correct():
    result = EvalFResult(
        total_scenarios=8, scenarios_passed=8, tool_match_rate=1.0,
        cascade_tests_total=1, cascade_tests_passed=1,
        passed=(1.0 >= TOOL_MATCH_PASS_BAR and 1 == 1),
        is_mock=True, run_at="2026-06-20T00:00:00+00:00",
        latency_ms=10, scenario_results=[],
    )
    assert result.passed is True


# ===========================================================================
# Section 5 — Logging
# ===========================================================================

def test_log_written(tmp_path):
    log = tmp_path / "eval_f_test.jsonl"
    run_eval_f(mock=True, log_path=log)
    assert log.exists()


def test_log_has_required_fields(tmp_path):
    log = tmp_path / "eval_f_fields.jsonl"
    run_eval_f(mock=True, log_path=log)
    rows = [
        json.loads(line)
        for line in log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(rows) >= 1
    row = rows[0]
    assert "tool_match_rate" in row
    assert "passed" in row
    assert "total_scenarios" in row
    assert "is_mock" in row
    assert "run_at" in row


# ===========================================================================
# Section 6 — ScenarioResult structure
# ===========================================================================

def test_scenario_result_fields_present(mock_result):
    for r in mock_result.scenario_results:
        assert isinstance(r, ScenarioResult)
        assert r.scenario_id != ""
        assert r.trigger_type != ""
        assert r.scope in ("fund", "ble")
        assert isinstance(r.tools_matched, bool)
        assert isinstance(r.cascade_matched, bool)
        assert isinstance(r.passed, bool)


def test_scenario_result_count_matches_total(mock_result):
    assert len(mock_result.scenario_results) == mock_result.total_scenarios


# ===========================================================================
# Section 7 — Non-cascade scenarios have cascade_generated=False
# ===========================================================================

def test_non_cascade_scenarios_have_cascade_generated_false(mock_result):
    non_cascade = [
        r for r in mock_result.scenario_results
        if not r.expected_cascade
    ]
    for r in non_cascade:
        assert r.cascade_generated is False, (
            f"{r.scenario_id} unexpectedly generated a cascade card"
        )


# ===========================================================================
# Section 8 — Cascade test counting
# ===========================================================================

def test_cascade_tests_total_is_1(mock_result):
    # Only ef-02 has expected_cascade=true
    assert mock_result.cascade_tests_total == 1


def test_cascade_tests_passed_is_1(mock_result):
    assert mock_result.cascade_tests_passed == 1
