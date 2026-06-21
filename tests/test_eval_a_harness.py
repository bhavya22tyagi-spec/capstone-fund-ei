"""
Tests for evals/run_eval_a.py — Eval A harness machinery (PRD §15.2).

All tests run MOCK=true (no LLM calls, zero cost).
Covers: golden set loading, field comparison rules, UBO matching,
numeric tolerance, pass/fail threshold, per-doc breakdown, idempotency,
and the end-to-end mock run.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import evals.run_eval_a as harness
from evals.run_eval_a import (
    DocResult,
    EvalAResult,
    FieldResult,
    _compare_ubo_array,
    _scalar_match,
    compare_fields,
    load_golden_set,
    run_eval_a,
)

GOLDEN_PATH = Path(__file__).parent.parent / "evals" / "golden_extraction.jsonl"


@pytest.fixture(autouse=True)
def _force_mock(monkeypatch):
    monkeypatch.setattr(harness, "MOCK", True)
    # Clear process-level cache between tests.
    harness._cache.clear()
    yield
    harness._cache.clear()


@pytest.fixture()
def log_path(tmp_path, monkeypatch):
    p = tmp_path / "eval_a_runs.jsonl"
    monkeypatch.setattr(harness, "LOG_PATH", p)
    return p


# ---------------------------------------------------------------------------
# 1. Golden set loading
# ---------------------------------------------------------------------------

def test_golden_set_loads_12_entries():
    entries = load_golden_set(GOLDEN_PATH)
    assert len(entries) == 12


def test_all_entries_have_doc_id():
    for entry in load_golden_set(GOLDEN_PATH):
        assert "doc_id" in entry and entry["doc_id"]


def test_all_entries_have_expected_fields():
    for entry in load_golden_set(GOLDEN_PATH):
        assert "expected_fields" in entry
        assert isinstance(entry["expected_fields"], dict)
        assert len(entry["expected_fields"]) >= 1


def test_all_entries_have_scope():
    for entry in load_golden_set(GOLDEN_PATH):
        assert entry["scope"] in ("fund", "ble")


def test_all_entries_have_fund_id():
    for entry in load_golden_set(GOLDEN_PATH):
        assert entry.get("fund_id"), f"Missing fund_id in {entry['doc_id']}"


def test_ble_scoped_entries_have_ble_id():
    for entry in load_golden_set(GOLDEN_PATH):
        if entry["scope"] == "ble":
            assert entry.get("ble_id"), f"BLE entry missing ble_id: {entry['doc_id']}"


def test_three_imperfection_entries():
    entries = load_golden_set(GOLDEN_PATH)
    imp_entries = [e for e in entries if "_imperfection" in e]
    assert len(imp_entries) == 3


def test_imperfection_entries_have_correct_doc_ids():
    entries = load_golden_set(GOLDEN_PATH)
    imp_ids = {e["doc_id"] for e in entries if "_imperfection" in e}
    expected = {"doc-f2-ubo-decl", "doc-f4-reg-licence", "doc-f5-invest-mgr-agmt"}
    assert imp_ids == expected


def test_load_raises_for_missing_file():
    with pytest.raises(FileNotFoundError):
        load_golden_set(Path("/nonexistent/path/golden.jsonl"))


# ---------------------------------------------------------------------------
# 2. Scalar comparison
# ---------------------------------------------------------------------------

def test_scalar_match_identical_strings():
    assert _scalar_match("DBS Bank Ltd", "DBS Bank Ltd") is True


def test_scalar_match_strips_whitespace():
    assert _scalar_match("  hello  ", "hello") is True


def test_scalar_match_different_strings():
    assert _scalar_match("Bank Rossiya", "DBS Bank Ltd") is False


def test_scalar_match_numeric_exact():
    assert _scalar_match(70.0, 70.0) is True


def test_scalar_match_numeric_within_tolerance():
    assert _scalar_match(40.0, 40.005) is True


def test_scalar_match_numeric_outside_tolerance():
    assert _scalar_match(40.0, 25.0) is False


def test_scalar_match_none_none():
    assert _scalar_match(None, None) is True


def test_scalar_match_none_vs_value():
    assert _scalar_match(None, "something") is False


def test_scalar_match_value_vs_none():
    assert _scalar_match("something", None) is False


def test_scalar_match_bool():
    assert _scalar_match(True, True) is True
    assert _scalar_match(True, False) is False


def test_scalar_match_int_float_same():
    assert _scalar_match(5000000, 5000000.0) is True


# ---------------------------------------------------------------------------
# 3. compare_fields — flat dict
# ---------------------------------------------------------------------------

def test_compare_fields_all_match():
    exp = {"entity_name": "Northgate Capital Partners LP", "incorporation_date": "2019-03-15"}
    act = {"entity_name": "Northgate Capital Partners LP", "incorporation_date": "2019-03-15"}
    results = compare_fields(exp, act)
    assert all(r.matched for r in results)
    assert len(results) == 2


def test_compare_fields_one_mismatch():
    exp = {"entity_name": "Northgate Capital Partners LP", "incorporation_date": "2019-03-15"}
    act = {"entity_name": "Northgate Capital Partners LP", "incorporation_date": "2020-01-01"}
    results = compare_fields(exp, act)
    matched = [r for r in results if r.matched]
    failed  = [r for r in results if not r.matched]
    assert len(matched) == 1
    assert len(failed)  == 1
    assert failed[0].field_path == "incorporation_date"


def test_compare_fields_missing_actual_key_is_fail():
    exp = {"registration_number": "EX-CYM-2019-08742"}
    act = {}
    results = compare_fields(exp, act)
    assert len(results) == 1
    assert results[0].matched is False
    assert results[0].actual is None


def test_compare_fields_null_expected_and_actual():
    exp = {"expiry_date": None}
    act = {"expiry_date": None}
    results = compare_fields(exp, act)
    assert results[0].matched is True


def test_compare_fields_null_expected_non_null_actual():
    exp = {"expiry_date": None}
    act = {"expiry_date": "2026-07-08"}
    results = compare_fields(exp, act)
    assert results[0].matched is False


# ---------------------------------------------------------------------------
# 4. UBO array comparison
# ---------------------------------------------------------------------------

def test_ubo_array_exact_match():
    ubos = [{"name": "John Richardson", "ownership_pct": 70.0, "pep_tier": 0}]
    results = _compare_ubo_array(ubos, ubos, "ubos")
    assert all(r.matched for r in results)


def test_ubo_array_order_insensitive():
    exp = [
        {"name": "John Richardson", "ownership_pct": 70.0},
        {"name": "Cayman Ventures Ltd", "ownership_pct": 30.0},
    ]
    act = [
        {"name": "Cayman Ventures Ltd", "ownership_pct": 30.0},
        {"name": "John Richardson", "ownership_pct": 70.0},
    ]
    results = _compare_ubo_array(exp, act, "ubos")
    assert all(r.matched for r in results)


def test_ubo_array_wrong_ownership_pct():
    exp = [{"name": "Werner Mueller", "ownership_pct": 40.0, "pep_tier": 2}]
    act = [{"name": "Werner Mueller", "ownership_pct": 25.0, "pep_tier": 2}]
    results = _compare_ubo_array(exp, act, "ubos")
    pct_result = next(r for r in results if "ownership_pct" in r.field_path)
    assert pct_result.matched is False
    # pep_tier should still match
    pep_result = next(r for r in results if "pep_tier" in r.field_path)
    assert pep_result.matched is True


def test_ubo_array_missing_ubo_in_actual():
    exp = [{"name": "John Richardson", "ownership_pct": 70.0}]
    act = []
    results = _compare_ubo_array(exp, act, "ubos")
    assert all(not r.matched for r in results)


def test_ubo_array_null_ownership_pct():
    exp = [{"name": "[Layer 2 entity unknown]", "ownership_pct": None, "resolved": False}]
    act = [{"name": "[Layer 2 entity unknown]", "ownership_pct": None, "resolved": False}]
    results = _compare_ubo_array(exp, act, "ubos")
    assert all(r.matched for r in results)


def test_ubo_comparison_via_compare_fields():
    exp = {"ubos": [{"name": "John Richardson", "ownership_pct": 70.0}]}
    act = {"ubos": [{"name": "John Richardson", "ownership_pct": 70.0}]}
    results = compare_fields(exp, act)
    assert all(r.matched for r in results)


# ---------------------------------------------------------------------------
# 5. DocResult helpers
# ---------------------------------------------------------------------------

def test_doc_result_field_match_rate():
    fr = [FieldResult("a", 1, 1, True), FieldResult("b", 2, 9, False)]
    dr = DocResult("doc-x", "Fund X", "Type", "fund", fr, False)
    assert dr.matched == 1
    assert dr.total == 2
    assert abs(dr.field_match_rate - 0.5) < 1e-9


def test_doc_result_empty_fields_rate():
    dr = DocResult("doc-x", "Fund X", "Type", "fund", [], False)
    assert dr.field_match_rate == 0.0


# ---------------------------------------------------------------------------
# 6. End-to-end mock run
# ---------------------------------------------------------------------------

def test_mock_run_passes(log_path):
    result = run_eval_a(GOLDEN_PATH, mock=True)
    assert isinstance(result, EvalAResult)
    assert result.passed is True
    assert result.score >= harness.PASS_BAR


def test_mock_run_score_is_1_0(log_path):
    result = run_eval_a(GOLDEN_PATH, mock=True)
    assert result.score == 1.0


def test_mock_run_total_fields_positive(log_path):
    result = run_eval_a(GOLDEN_PATH, mock=True)
    assert result.total_fields > 0


def test_mock_run_matched_equals_total(log_path):
    result = run_eval_a(GOLDEN_PATH, mock=True)
    assert result.matched_fields == result.total_fields


def test_mock_run_12_doc_results(log_path):
    result = run_eval_a(GOLDEN_PATH, mock=True)
    assert len(result.doc_results) == 12


def test_mock_run_all_docs_pass(log_path):
    result = run_eval_a(GOLDEN_PATH, mock=True)
    for dr in result.doc_results:
        assert dr.field_match_rate == 1.0, f"{dr.doc_id} did not achieve 100%"


def test_mock_run_is_mock_true(log_path):
    result = run_eval_a(GOLDEN_PATH, mock=True)
    assert result.is_mock is True


def test_mock_run_zero_cost(log_path):
    result = run_eval_a(GOLDEN_PATH, mock=True)
    assert result.cost_usd == 0.0


def test_mock_run_imperfection_flagged(log_path):
    result = run_eval_a(GOLDEN_PATH, mock=True)
    imp_docs = [d for d in result.doc_results if d.has_imperfection]
    assert len(imp_docs) == 3


# ---------------------------------------------------------------------------
# 7. Pass/fail threshold
# ---------------------------------------------------------------------------

def test_score_below_threshold_is_fail():
    # 90/100 = 90% which is below the 95% pass bar.
    fr_pass = [FieldResult(f"f{i}", i, i, True)  for i in range(90)]
    fr_fail = [FieldResult(f"f{i}", i, i, False) for i in range(90, 100)]
    dr = DocResult("doc-x", "X", "T", "fund", fr_pass + fr_fail, False)
    score = 90 / 100
    result = EvalAResult(
        total_fields=100,
        matched_fields=90,
        score=score,
        passed=score >= harness.PASS_BAR,
        doc_results=[dr],
        run_at="2026-06-20T00:00:00+00:00",
        is_mock=True,
        cost_usd=0.0,
        latency_ms=0,
    )
    assert result.passed is False


def test_score_exactly_at_threshold_passes():
    n = 100
    fr = [FieldResult(f"f{i}", i, i, True) for i in range(95)] + \
         [FieldResult(f"f{i}", i, i, False) for i in range(95, 100)]
    dr = DocResult("doc-x", "X", "T", "fund", fr, False)
    result = EvalAResult(
        total_fields=n,
        matched_fields=95,
        score=0.95,
        passed=0.95 >= harness.PASS_BAR,
        doc_results=[dr],
        run_at="2026-06-20T00:00:00+00:00",
        is_mock=True,
        cost_usd=0.0,
        latency_ms=0,
    )
    assert result.passed is True


# ---------------------------------------------------------------------------
# 8. Idempotency — second call returns cached result without re-running
# ---------------------------------------------------------------------------

def test_second_run_returns_cached(log_path):
    r1 = run_eval_a(GOLDEN_PATH, mock=True)
    r2 = run_eval_a(GOLDEN_PATH, mock=True)
    assert r1 is r2  # same object — cached


def test_cache_cleared_between_tests(log_path):
    r1 = run_eval_a(GOLDEN_PATH, mock=True)
    harness._cache.clear()
    r2 = run_eval_a(GOLDEN_PATH, mock=True)
    # Different objects (re-ran), same score
    assert r1 is not r2
    assert r1.score == r2.score


# ---------------------------------------------------------------------------
# 9. Logging
# ---------------------------------------------------------------------------

def test_run_writes_to_log(log_path):
    run_eval_a(GOLDEN_PATH, mock=True)
    assert log_path.exists()
    lines = log_path.read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["eval_category"] == "A"
    assert record["passed"] is True
    assert record["score"] == 1.0
    assert record["is_mock"] is True


def test_log_contains_12_doc_scores(log_path):
    run_eval_a(GOLDEN_PATH, mock=True)
    record = json.loads(log_path.read_text().strip())
    assert len(record["doc_scores"]) == 12


def test_log_doc_scores_have_required_fields(log_path):
    run_eval_a(GOLDEN_PATH, mock=True)
    record = json.loads(log_path.read_text().strip())
    for ds in record["doc_scores"]:
        assert "doc_id" in ds
        assert "field_match_rate" in ds
        assert "matched" in ds
        assert "total" in ds
        assert "has_imperfection" in ds


# ---------------------------------------------------------------------------
# 10. Real extractor is wired to extraction service
# ---------------------------------------------------------------------------

def test_real_extractor_returns_dict(monkeypatch):
    """_real_extract calls the extraction service (MOCK=true) and returns a dict."""
    monkeypatch.setattr(harness, "MOCK", False)
    entries = load_golden_set(GOLDEN_PATH)
    # Extraction service defaults to MOCK=true from env — returns canned mock dict
    result = harness._real_extract(entries[0])
    assert isinstance(result, dict)
    assert len(result) > 0
