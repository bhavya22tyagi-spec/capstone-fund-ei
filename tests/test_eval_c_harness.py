"""
Tests for the Eval C harness (evals/run_eval_c.py).

All tests run in MOCK mode. Narrative generation = concatenated doc texts;
judge = substring check. This verifies harness plumbing, grouping logic,
pass-bar enforcement, log writing, and the planted imperfection entries — not
LLM accuracy (that requires MOCK=false + real API).
"""

from __future__ import annotations

import json
import os
import pytest
from pathlib import Path

os.environ.setdefault("MOCK", "true")

from evals.run_eval_c import (
    EvalCResult,
    JUDGE_PASS_BAR,
    HALLUCINATION_LIMIT,
    QAJudgeResult,
    _group_by_scope,
    load_golden_qa,
    run_eval_c,
)


_PROJECT_ROOT = Path(__file__).parent.parent
_GOLDEN_QA_PATH = _PROJECT_ROOT / "evals" / "golden_qa.jsonl"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def golden_entries():
    return load_golden_qa()


@pytest.fixture()
def mock_result():
    return run_eval_c(mock=True)


# ===========================================================================
# Section 1 — Golden set loading
# ===========================================================================

def test_load_golden_qa_count(golden_entries):
    assert len(golden_entries) == 55


def test_load_golden_qa_required_fields(golden_entries):
    for e in golden_entries:
        assert "qa_id" in e
        assert "scope" in e
        assert "scope_id" in e
        assert "fund_id" in e
        assert "citation_substring" in e
        assert "question" in e


def test_planted_entry_f2_07_exists(golden_entries):
    ids = {e["qa_id"] for e in golden_entries}
    assert "qa-f2-07" in ids


def test_planted_entry_f4_06_exists(golden_entries):
    ids = {e["qa_id"] for e in golden_entries}
    assert "qa-f4-06" in ids


def test_all_entries_have_citation_substring(golden_entries):
    for e in golden_entries:
        assert "citation_substring" in e
        assert len(e["citation_substring"]) > 0


# ===========================================================================
# Section 2 — Scope coverage
# ===========================================================================

def test_fund_scope_entries_present(golden_entries):
    fund_entries = [e for e in golden_entries if e["scope"] == "fund"]
    assert len(fund_entries) > 0


def test_ble_scope_entries_present(golden_entries):
    ble_entries = [e for e in golden_entries if e["scope"] == "ble"]
    assert len(ble_entries) > 0


def test_nine_scope_groups(golden_entries):
    groups = _group_by_scope(golden_entries)
    assert len(groups) == 9


def test_scope_groups_cover_all_funds_and_bles(golden_entries):
    groups = _group_by_scope(golden_entries)
    scopes = {k[0] for k in groups.keys()}
    scope_ids = {k[1] for k in groups.keys()}

    assert "fund" in scopes
    assert "ble" in scopes

    # 5 fund scopes + 4 BLE scopes
    fund_groups = [k for k in groups if k[0] == "fund"]
    ble_groups = [k for k in groups if k[0] == "ble"]
    assert len(fund_groups) == 5
    assert len(ble_groups) == 4


# ===========================================================================
# Section 3 — run_eval_c() MOCK run
# ===========================================================================

def test_run_eval_c_returns_result(mock_result):
    assert isinstance(mock_result, EvalCResult)


def test_run_eval_c_total_qa_55(mock_result):
    assert mock_result.total_qa == 55


def test_run_eval_c_judge_pass_rate_100_percent(mock_result):
    assert mock_result.judge_pass_rate == 1.0, (
        f"Expected 100% pass rate in MOCK; got {mock_result.judge_pass_rate:.2%}. "
        f"Failures: {[r.qa_id for r in mock_result.qa_results if not r.judge_passed]}"
    )


def test_run_eval_c_no_hallucinations(mock_result):
    assert mock_result.hallucinations_detected == 0, (
        f"Hallucinations detected in MOCK run: "
        f"{[r.qa_id for r in mock_result.qa_results if r.is_hallucination]}"
    )


def test_run_eval_c_passed_true(mock_result):
    assert mock_result.passed is True


def test_run_eval_c_is_mock_true(mock_result):
    assert mock_result.is_mock is True


def test_run_eval_c_all_qa_results_passed(mock_result):
    failures = [r for r in mock_result.qa_results if not r.judge_passed]
    assert failures == [], (
        f"QA entries that failed in MOCK: {[r.qa_id for r in failures]}"
    )


# ===========================================================================
# Section 4 — Pass bar logic
# ===========================================================================

def test_pass_bar_constant():
    assert JUDGE_PASS_BAR == 0.80


def test_hallucination_limit_constant():
    assert HALLUCINATION_LIMIT == 0


def test_eval_result_fails_when_pass_rate_below_bar():
    result = EvalCResult(
        total_qa=10, judge_passed=7, judge_pass_rate=0.70,
        hallucinations_detected=0,
        passed=(0.70 >= JUDGE_PASS_BAR and 0 == HALLUCINATION_LIMIT),
        is_mock=True, run_at="2026-06-20T00:00:00+00:00",
        latency_ms=100, qa_results=[],
    )
    assert result.passed is False


def test_eval_result_fails_when_hallucination_present():
    result = EvalCResult(
        total_qa=10, judge_passed=10, judge_pass_rate=1.0,
        hallucinations_detected=1,
        passed=(1.0 >= JUDGE_PASS_BAR and 1 == HALLUCINATION_LIMIT),
        is_mock=True, run_at="2026-06-20T00:00:00+00:00",
        latency_ms=100, qa_results=[],
    )
    assert result.passed is False


def test_eval_result_passes_when_both_criteria_met():
    result = EvalCResult(
        total_qa=10, judge_passed=9, judge_pass_rate=0.90,
        hallucinations_detected=0,
        passed=(0.90 >= JUDGE_PASS_BAR and 0 == HALLUCINATION_LIMIT),
        is_mock=True, run_at="2026-06-20T00:00:00+00:00",
        latency_ms=100, qa_results=[],
    )
    assert result.passed is True


# ===========================================================================
# Section 5 — Logging
# ===========================================================================

def test_log_written(tmp_path):
    log = tmp_path / "eval_c_test.jsonl"
    run_eval_c(mock=True, log_path=log)
    assert log.exists()


def test_log_has_required_fields(tmp_path):
    log = tmp_path / "eval_c_fields_test.jsonl"
    run_eval_c(mock=True, log_path=log)
    rows = [
        json.loads(line)
        for line in log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(rows) >= 1
    row = rows[0]
    assert "judge_pass_rate" in row
    assert "passed" in row
    assert "hallucinations_detected" in row
    assert "total_qa" in row
    assert "is_mock" in row
    assert "run_at" in row


# ===========================================================================
# Section 6 — QAJudgeResult structure
# ===========================================================================

def test_qa_judge_result_fields(mock_result):
    for r in mock_result.qa_results:
        assert isinstance(r, QAJudgeResult)
        assert r.qa_id != ""
        assert r.scope in ("fund", "ble")
        assert r.scope_id != ""
        assert r.citation_substring != ""
        assert isinstance(r.judge_passed, bool)
        assert isinstance(r.is_hallucination, bool)


def test_qa_results_count_matches_total_qa(mock_result):
    assert len(mock_result.qa_results) == mock_result.total_qa


# ===========================================================================
# Section 7 — Planted imperfection entries
# ===========================================================================

def test_planted_f2_07_passes_mock_judge(mock_result):
    qa_f2_07 = next(r for r in mock_result.qa_results if r.qa_id == "qa-f2-07")
    assert qa_f2_07.judge_passed is True, (
        "qa-f2-07 (planted 25.0%) should pass MOCK judge — "
        "citation_substring IS verbatim in the document text"
    )
    assert qa_f2_07.is_hallucination is False


def test_planted_f4_06_passes_mock_judge(mock_result):
    qa_f4_06 = next(r for r in mock_result.qa_results if r.qa_id == "qa-f4-06")
    assert qa_f4_06.judge_passed is True, (
        "qa-f4-06 (planted 2025-07-08) should pass MOCK judge — "
        "citation_substring IS verbatim in the document text"
    )
    assert qa_f4_06.is_hallucination is False


# ===========================================================================
# Section 8 — F1 escalation scope group
# ===========================================================================

def test_f1_scope_group_present_in_results(mock_result):
    f1_results = [
        r for r in mock_result.qa_results
        if r.scope == "fund"
        and r.scope_id == "f0000001-f000-0000-0000-000000000001"
    ]
    assert len(f1_results) == 6  # qa-f1-01 through qa-f1-06


def test_f1_scope_group_all_pass(mock_result):
    f1_results = [
        r for r in mock_result.qa_results
        if r.scope_id == "f0000001-f000-0000-0000-000000000001"
    ]
    failures = [r for r in f1_results if not r.judge_passed]
    assert failures == [], f"F1 entries that failed: {[r.qa_id for r in failures]}"


# ===========================================================================
# Section 9 — EvalCResult fields completeness
# ===========================================================================

def test_eval_c_result_latency_is_int(mock_result):
    assert isinstance(mock_result.latency_ms, int)


def test_eval_c_result_run_at_nonempty(mock_result):
    assert mock_result.run_at != ""


def test_eval_c_result_judge_passed_count_matches(mock_result):
    manual_count = sum(1 for r in mock_result.qa_results if r.judge_passed)
    assert mock_result.judge_passed == manual_count


def test_eval_c_result_hallucination_count_matches(mock_result):
    manual_count = sum(1 for r in mock_result.qa_results if r.is_hallucination)
    assert mock_result.hallucinations_detected == manual_count
