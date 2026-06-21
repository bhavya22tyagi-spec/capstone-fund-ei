"""
Tests for PRD §17 ai_client — MOCK routing, guard, validation, budget,
retry, backoff, and cost logging.
"""
import json
import os

import pytest

import services.ai_client as ac
import services.cost_logger as cl
from services.budget import BudgetCap, BudgetExceededError
from services.guards import StaticFundAIError


# ---------------------------------------------------------------------------
# Fixture: redirect LOG_FILE to a temp location so tests don't pollute logs/
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _temp_log(tmp_path, monkeypatch):
    monkeypatch.setattr(cl, "LOG_FILE", str(tmp_path / "test_ai_calls.jsonl"))


def _budget(limit: float = 1.0) -> BudgetCap:
    return BudgetCap(limit_usd=limit)


def _live_call_kwargs(**overrides) -> dict:
    base = dict(
        prompt="Extract the UBO name from this document.",
        model="claude-haiku-4-5-20251001",
        prompt_version="v1",
        fund_id="f0000001-f000-0000-0000-000000000001",
        synthetic_static=False,
        scope="fund",
        scope_id="f0000001-f000-0000-0000-000000000001",
        budget=_budget(),
        estimated_cost_usd=0.001,
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# MOCK routing (default)
# ---------------------------------------------------------------------------

def test_mock_returns_mock_flag():
    assert ac.MOCK is True  # default must be on
    result = ac.call_llm(**_live_call_kwargs())
    assert result["is_mock"] is True


def test_mock_returns_content_string():
    result = ac.call_llm(**_live_call_kwargs())
    assert isinstance(result["content"], str)
    assert len(result["content"]) > 0


def test_mock_includes_model_in_response():
    result = ac.call_llm(**_live_call_kwargs(model="claude-sonnet-4-6"))
    assert result["model"] == "claude-sonnet-4-6"


def test_mock_records_zero_spend():
    budget = _budget(limit=0.50)
    ac.call_llm(**_live_call_kwargs(budget=budget))
    assert budget.spent_usd == 0.0


def test_mock_writes_log_entry(tmp_path, monkeypatch):
    log_file = str(tmp_path / "calls.jsonl")
    monkeypatch.setattr(cl, "LOG_FILE", log_file)
    ac.call_llm(**_live_call_kwargs())
    assert os.path.exists(log_file)
    with open(log_file, encoding="utf-8") as fh:
        record = json.loads(fh.readline())
    assert record["is_mock"] is True
    assert record["cost_usd"] == 0.0


def test_mock_log_contains_scope_and_scope_id(tmp_path, monkeypatch):
    log_file = str(tmp_path / "calls.jsonl")
    monkeypatch.setattr(cl, "LOG_FILE", log_file)
    ac.call_llm(**_live_call_kwargs(scope="fund", scope_id="f-xyz"))
    with open(log_file, encoding="utf-8") as fh:
        record = json.loads(fh.readline())
    assert record["scope"] == "fund"
    assert record["scope_id"] == "f-xyz"


# ---------------------------------------------------------------------------
# Embedding — MOCK
# ---------------------------------------------------------------------------

def test_mock_embedding_returns_correct_dimension():
    result = ac.call_embedding(
        text="DBS Bank Ltd counterparty agreement.",
        fund_id="f0000005-f000-0000-0000-000000000005",
        synthetic_static=False,
        scope="ble",
        scope_id="b0005001-b000-0000-0000-000000000006",
        budget=_budget(),
    )
    assert len(result) == ac.EMBEDDING_DIM


def test_mock_embedding_returns_all_zeros():
    result = ac.call_embedding(
        text="some text",
        fund_id="f0000001-f000-0000-0000-000000000001",
        synthetic_static=False,
        scope="fund",
        scope_id="f0000001-f000-0000-0000-000000000001",
        budget=_budget(),
    )
    assert all(v == 0.0 for v in result)


# ---------------------------------------------------------------------------
# Fail-fast input validation
# ---------------------------------------------------------------------------

def test_empty_prompt_raises_value_error():
    with pytest.raises(ValueError, match="empty"):
        ac.call_llm(**_live_call_kwargs(prompt=""))


def test_whitespace_only_prompt_raises():
    with pytest.raises(ValueError, match="empty"):
        ac.call_llm(**_live_call_kwargs(prompt="   "))


def test_invalid_scope_raises_value_error():
    with pytest.raises(ValueError, match="scope"):
        ac.call_llm(**_live_call_kwargs(scope="counterparty"))


def test_empty_embedding_text_raises():
    with pytest.raises(ValueError, match="empty"):
        ac.call_embedding(
            text="",
            fund_id="f0000001-f000-0000-0000-000000000001",
            synthetic_static=False,
            scope="fund",
            scope_id="f0000001-f000-0000-0000-000000000001",
            budget=_budget(),
        )


def test_invalid_embedding_scope_raises():
    with pytest.raises(ValueError, match="scope"):
        ac.call_embedding(
            text="valid text",
            fund_id="f0000001-f000-0000-0000-000000000001",
            synthetic_static=False,
            scope="counterparty",
            scope_id="x",
            budget=_budget(),
        )


# ---------------------------------------------------------------------------
# Static-fund guard
# ---------------------------------------------------------------------------

def test_static_fund_raises_before_any_api_call():
    with pytest.raises(StaticFundAIError):
        ac.call_llm(**_live_call_kwargs(fund_id="static-001", synthetic_static=True))


def test_static_fund_embedding_blocked():
    with pytest.raises(StaticFundAIError):
        ac.call_embedding(
            text="valid text",
            fund_id="static-001",
            synthetic_static=True,
            scope="fund",
            scope_id="static-001",
            budget=_budget(),
        )


# ---------------------------------------------------------------------------
# Budget cap
# ---------------------------------------------------------------------------

def test_budget_exceeded_raises_before_call():
    tiny = BudgetCap(limit_usd=0.0001)
    with pytest.raises(BudgetExceededError):
        ac.call_llm(**_live_call_kwargs(budget=tiny, estimated_cost_usd=0.01))


def test_budget_not_decremented_on_failure():
    tiny = BudgetCap(limit_usd=0.0001)
    try:
        ac.call_llm(**_live_call_kwargs(budget=tiny, estimated_cost_usd=0.01))
    except BudgetExceededError:
        pass
    assert tiny.spent_usd == 0.0  # no spend recorded


# ---------------------------------------------------------------------------
# Retry and backoff (MOCK=False path)
# ---------------------------------------------------------------------------

def test_retry_on_transient_error(monkeypatch, tmp_path):
    monkeypatch.setattr(cl, "LOG_FILE", str(tmp_path / "calls.jsonl"))
    monkeypatch.setattr(ac, "MOCK", False)

    attempts = {"n": 0}

    def _flaky(prompt, model):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("transient network error")
        return {
            "content": "ok",
            "model": model,
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            "is_mock": False,
        }

    monkeypatch.setattr(ac, "_real_llm_call", _flaky)
    monkeypatch.setattr(ac, "_BACKOFF_BASE_S", 0.0)  # no sleep in tests

    result = ac.call_llm(**_live_call_kwargs())
    assert result["content"] == "ok"
    assert attempts["n"] == 3  # 1 initial + 2 retries


def test_fails_after_max_retries(monkeypatch, tmp_path):
    monkeypatch.setattr(cl, "LOG_FILE", str(tmp_path / "calls.jsonl"))
    monkeypatch.setattr(ac, "MOCK", False)

    attempts = {"n": 0}

    def _always_fail(prompt, model):
        attempts["n"] += 1
        raise RuntimeError("persistent error")

    monkeypatch.setattr(ac, "_real_llm_call", _always_fail)
    monkeypatch.setattr(ac, "_BACKOFF_BASE_S", 0.0)

    with pytest.raises(RuntimeError, match="attempt"):
        ac.call_llm(**_live_call_kwargs())

    assert attempts["n"] == ac.MAX_RETRIES + 1  # exactly 3 total attempts


def test_backoff_timing_is_exponential(monkeypatch, tmp_path):
    monkeypatch.setattr(cl, "LOG_FILE", str(tmp_path / "calls.jsonl"))
    monkeypatch.setattr(ac, "MOCK", False)
    monkeypatch.setattr(ac, "_BACKOFF_BASE_S", 0.5)

    sleep_calls: list[float] = []
    monkeypatch.setattr(ac.time, "sleep", lambda s: sleep_calls.append(s))

    monkeypatch.setattr(ac, "_real_llm_call", lambda *_: (_ for _ in ()).throw(RuntimeError("err")))

    with pytest.raises(RuntimeError):
        ac.call_llm(**_live_call_kwargs())

    # With MAX_RETRIES=2 there are 2 sleep calls: 0.5*2^0=0.5, 0.5*2^1=1.0
    assert sleep_calls == [0.5, 1.0]


def test_not_implemented_not_retried(monkeypatch, tmp_path):
    """NotImplementedError (un-wired real API) must never trigger retry."""
    monkeypatch.setattr(cl, "LOG_FILE", str(tmp_path / "calls.jsonl"))
    monkeypatch.setattr(ac, "MOCK", False)

    attempts = {"n": 0}

    def _not_wired(prompt, model):
        attempts["n"] += 1
        raise NotImplementedError("not wired")

    monkeypatch.setattr(ac, "_real_llm_call", _not_wired)

    with pytest.raises(NotImplementedError):
        ac.call_llm(**_live_call_kwargs())

    assert attempts["n"] == 1  # must not retry
