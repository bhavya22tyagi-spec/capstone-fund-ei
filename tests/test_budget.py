"""
Tests for PRD §17 BudgetCap — per-run spend accumulator with hard cap.
"""
import pytest

from services.budget import BudgetCap, BudgetExceededError


def test_initial_spend_is_zero():
    cap = BudgetCap(limit_usd=1.0)
    assert cap.spent_usd == 0.0


def test_remaining_equals_limit_initially():
    cap = BudgetCap(limit_usd=0.50)
    assert cap.remaining_usd == 0.50


def test_check_passes_under_cap():
    cap = BudgetCap(limit_usd=0.50)
    cap.check(0.49)  # must not raise


def test_check_raises_when_projected_exceeds_cap():
    cap = BudgetCap(limit_usd=0.50)
    with pytest.raises(BudgetExceededError):
        cap.check(0.51)


def test_check_passes_exactly_at_cap():
    cap = BudgetCap(limit_usd=0.50)
    cap.check(0.50)  # projected == limit is still within budget (uses strict >)


def test_check_passes_just_under_cap():
    cap = BudgetCap(limit_usd=0.50)
    cap.check(0.4999)  # must not raise


def test_record_accumulates_spend():
    cap = BudgetCap(limit_usd=1.0)
    cap.record(0.10)
    cap.record(0.20)
    assert round(cap.spent_usd, 10) == 0.30


def test_remaining_decreases_after_record():
    cap = BudgetCap(limit_usd=1.0)
    cap.record(0.30)
    assert round(cap.remaining_usd, 10) == 0.70


def test_accumulated_spend_counted_in_next_check():
    cap = BudgetCap(limit_usd=0.50)
    cap.record(0.40)
    with pytest.raises(BudgetExceededError):
        cap.check(0.11)  # 0.40 + 0.11 = 0.51 > 0.50


def test_custom_cap_respected():
    cap = BudgetCap(limit_usd=2.00)
    cap.check(1.99)  # must not raise
    with pytest.raises(BudgetExceededError):
        cap.check(2.01)


def test_budget_exceeded_error_is_runtime_error():
    cap = BudgetCap(limit_usd=0.10)
    with pytest.raises(RuntimeError):
        cap.check(0.20)


def test_error_message_contains_cap_and_projected():
    cap = BudgetCap(limit_usd=0.50)
    cap.record(0.30)
    with pytest.raises(BudgetExceededError, match="0.50"):
        cap.check(0.30)
