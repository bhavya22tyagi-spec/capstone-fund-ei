"""
Tests for the Eval D harness (run_eval_d.py).

All tests run in MOCK mode. DB execution is skipped, so golden accuracy is
not measured — but harness loading, adversarial blocking logic, comparison
helpers, and pass/fail aggregation are fully exercised.
"""

from __future__ import annotations

import json
import os
import pytest
from pathlib import Path
from decimal import Decimal

os.environ.setdefault("MOCK", "true")

from evals.run_eval_d import (
    EvalDResult,
    GoldenQueryResult,
    AdversarialResult,
    _compare_results,
    _normalise,
    _row_to_frozenset,
    load_adversarial_set,
    load_golden_set,
    run_eval_d,
)


_PROJECT_ROOT = Path(__file__).parent.parent
_GOLDEN_PATH = _PROJECT_ROOT / "evals" / "golden_sql.jsonl"
_ADVERSARIAL_PATH = _PROJECT_ROOT / "evals" / "adversarial_sql.jsonl"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def golden_entries():
    return load_golden_set()


@pytest.fixture()
def adversarial_entries():
    return load_adversarial_set()


@pytest.fixture()
def tmp_adversarial(tmp_path):
    """Write a minimal adversarial set to a temp file."""
    entries = [
        {"adv_id": "t-01", "attack_type": "ddl_drop", "description": "DROP",
         "sql": "DROP TABLE funds", "expected_blocked": True,
         "expected_blocked_reason": "forbidden_statement_type"},
        {"adv_id": "t-02", "attack_type": "dml_delete", "description": "DELETE",
         "sql": "DELETE FROM funds", "expected_blocked": True,
         "expected_blocked_reason": "forbidden_statement_type"},
    ]
    p = tmp_path / "adv.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
    return p


@pytest.fixture()
def tmp_golden(tmp_path):
    """Write a minimal golden set to a temp file."""
    entries = [
        {"sql_id": "t-g01", "question": "How many funds are there?",
         "expected_result_type": "scalar", "expected_result": 5,
         "reference_sql": "SELECT COUNT(*) FROM funds",
         "tables_referenced": ["funds"], "notes": ""},
    ]
    p = tmp_path / "golden.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
    return p


# ===========================================================================
# Section 1 — Load helpers
# ===========================================================================

def test_load_golden_set_count(golden_entries):
    assert len(golden_entries) == 10


def test_load_golden_set_required_fields(golden_entries):
    for e in golden_entries:
        assert "sql_id" in e
        assert "question" in e
        assert "expected_result_type" in e
        assert "expected_result" in e


def test_load_adversarial_set_count(adversarial_entries):
    assert len(adversarial_entries) == 20


def test_load_adversarial_set_required_fields(adversarial_entries):
    for e in adversarial_entries:
        assert "adv_id" in e
        assert "sql" in e
        assert "expected_blocked" in e
        assert e["expected_blocked"] is True  # every entry must be expected blocked


def test_golden_set_has_required_join_entry(golden_entries):
    """sql-06 is the mandatory Fund->BLE->Product join."""
    ids = {e["sql_id"] for e in golden_entries}
    assert "sql-06" in ids


def test_golden_multi_row_has_expected_row_count(golden_entries):
    multi = [e for e in golden_entries if e["expected_result_type"] == "multi_row"]
    for e in multi:
        assert "expected_row_count" in e
        assert isinstance(e["expected_result"], list)
        assert len(e["expected_result"]) == e["expected_row_count"]


def test_adversarial_all_entries_unique_ids(adversarial_entries):
    ids = [e["adv_id"] for e in adversarial_entries]
    assert len(ids) == len(set(ids))


# ===========================================================================
# Section 2 — _normalise helper
# ===========================================================================

def test_normalise_decimal():
    assert _normalise(Decimal("51.5")) == 51.5


def test_normalise_nested_dict():
    result = _normalise({"score": Decimal("32.4"), "name": "Meridian"})
    assert result == {"score": 32.4, "name": "Meridian"}


def test_normalise_list():
    result = _normalise([Decimal("1.0"), Decimal("2.0")])
    assert result == [1.0, 2.0]


def test_normalise_passthrough():
    assert _normalise(42) == 42
    assert _normalise("hello") == "hello"
    assert _normalise(None) is None


# ===========================================================================
# Section 3 — _compare_results
# ===========================================================================

def test_compare_scalar_match():
    assert _compare_results("scalar", 4, [{"loan_product_count": 4}]) is True


def test_compare_scalar_mismatch():
    assert _compare_results("scalar", 5, [{"loan_product_count": 4}]) is False


def test_compare_scalar_empty_rows():
    assert _compare_results("scalar", 1, []) is False


def test_compare_single_row_match():
    assert _compare_results(
        "single_row",
        {"fund_name": "Harrington Private Capital", "direct_score": 51.5},
        [{"fund_name": "Harrington Private Capital", "direct_score": 51.5, "extra_col": "x"}],
    ) is True


def test_compare_single_row_mismatch():
    assert _compare_results(
        "single_row",
        {"fund_name": "Harrington Private Capital", "direct_score": 51.5},
        [{"fund_name": "Wrong Fund", "direct_score": 51.5}],
    ) is False


def test_compare_single_row_multiple_actual_rows():
    assert _compare_results(
        "single_row",
        {"fund_name": "A"},
        [{"fund_name": "A"}, {"fund_name": "B"}],
    ) is False


def test_compare_multi_row_match_order_independent():
    expected = [{"fund_name": "A", "ble_count": 2}, {"fund_name": "B", "ble_count": 2}]
    actual = [{"fund_name": "B", "ble_count": 2}, {"fund_name": "A", "ble_count": 2}]
    assert _compare_results("multi_row", expected, actual) is True


def test_compare_multi_row_count_mismatch():
    expected = [{"fund_name": "A"}, {"fund_name": "B"}]
    actual = [{"fund_name": "A"}]
    assert _compare_results("multi_row", expected, actual) is False


def test_compare_multi_row_value_mismatch():
    expected = [{"fund_name": "A", "ble_count": 2}]
    actual = [{"fund_name": "A", "ble_count": 3}]
    assert _compare_results("multi_row", expected, actual) is False


def test_compare_multi_row_decimal_normalised():
    expected = [{"direct_score": 51.5}]
    actual = [{"direct_score": Decimal("51.5")}]
    assert _compare_results("multi_row", expected, actual) is True


# ===========================================================================
# Section 4 — run_eval_d (MOCK mode)
# ===========================================================================

def test_run_eval_d_returns_result():
    result = run_eval_d(mock=True)
    assert isinstance(result, EvalDResult)


def test_run_eval_d_mock_adversarial_all_blocked():
    result = run_eval_d(mock=True)
    assert result.adversarial_block_rate == 1.0, (
        f"Expected all adversarial blocked; "
        f"{result.total_adversarial - result.adversarial_blocked} leaked through"
    )


def test_run_eval_d_mock_golden_skipped():
    result = run_eval_d(mock=True)
    assert result.golden_skipped == result.total_golden  # all skipped in MOCK


def test_run_eval_d_mock_passes():
    result = run_eval_d(mock=True)
    assert result.passed is True


def test_run_eval_d_golden_count():
    result = run_eval_d(mock=True)
    assert result.total_golden == 10


def test_run_eval_d_adversarial_count():
    result = run_eval_d(mock=True)
    assert result.total_adversarial == 20


def test_run_eval_d_adversarial_results_detail():
    result = run_eval_d(mock=True)
    for r in result.adversarial_results:
        assert r.was_blocked is True, (
            f"{r.adv_id} ({r.attack_type}) was NOT blocked: {r.sql!r}"
        )


def test_run_eval_d_custom_paths(tmp_adversarial, tmp_golden):
    result = run_eval_d(
        golden_path=tmp_golden,
        adversarial_path=tmp_adversarial,
        mock=True,
    )
    assert result.total_golden == 1
    assert result.total_adversarial == 2
    assert result.adversarial_block_rate == 1.0


def test_run_eval_d_log_written(tmp_path, tmp_golden, tmp_adversarial):
    # Use unique golden/adversarial paths so this run gets its own cache key
    # and actually executes (rather than returning a cached result from a prior test).
    log = tmp_path / "eval_d_test.jsonl"
    run_eval_d(golden_path=tmp_golden, adversarial_path=tmp_adversarial, mock=True, log_path=log)
    assert log.exists()
    rows = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(rows) >= 1
    assert "adversarial_block_rate" in rows[0]
    assert "passed" in rows[0]


# ===========================================================================
# Section 5 — AdversarialResult dataclass
# ===========================================================================

def test_adversarial_result_passed_when_blocked():
    r = AdversarialResult(
        adv_id="x-01",
        attack_type="ddl_drop",
        sql="DROP TABLE funds",
        expected_blocked=True,
        was_blocked=True,
        blocked_reason="forbidden_statement_type",
        passed=True,
    )
    assert r.passed is True


def test_adversarial_result_failed_when_not_blocked():
    r = AdversarialResult(
        adv_id="x-02",
        attack_type="ddl_drop",
        sql="DROP TABLE funds",
        expected_blocked=True,
        was_blocked=False,
        blocked_reason=None,
        passed=False,
    )
    assert r.passed is False
