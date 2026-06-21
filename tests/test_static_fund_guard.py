"""
Tests for the synthetic_static Fund guard (PRD §17, CLAUDE.md rule 10).

The guard must make it physically impossible for a synthetic_static Fund to
trigger any LLM or embedding call. Tests verify the guard raises on static Funds,
passes on live Funds, and is correctly called before any AI operation.
"""
import pytest

from services.guards import StaticFundAIError, assert_fund_allows_ai


# ---------------------------------------------------------------------------
# Core guard behaviour
# ---------------------------------------------------------------------------

def test_static_fund_raises():
    with pytest.raises(StaticFundAIError):
        assert_fund_allows_ai("fund-static-001", synthetic_static=True)


def test_live_fund_passes():
    assert_fund_allows_ai("fund-live-001", synthetic_static=False)  # must not raise


def test_error_is_static_fund_ai_error_subtype():
    with pytest.raises(StaticFundAIError):
        assert_fund_allows_ai("fund-static-002", synthetic_static=True)


def test_error_message_contains_fund_id():
    with pytest.raises(StaticFundAIError, match="fund-static-999"):
        assert_fund_allows_ai("fund-static-999", synthetic_static=True)


def test_error_message_mentions_synthetic_static():
    with pytest.raises(StaticFundAIError, match="synthetic_static"):
        assert_fund_allows_ai("fund-static-003", synthetic_static=True)


def test_static_fund_ai_error_is_runtime_error():
    """StaticFundAIError must be a RuntimeError so it propagates through AI call stacks."""
    with pytest.raises(RuntimeError):
        assert_fund_allows_ai("fund-static-004", synthetic_static=True)


# ---------------------------------------------------------------------------
# Guard integration: simulated AI operation functions
# ---------------------------------------------------------------------------

def _mock_llm_extract(fund_id: str, synthetic_static: bool, text: str) -> str:
    """Simulates an extraction function that correctly gates on the guard."""
    assert_fund_allows_ai(fund_id, synthetic_static)
    return f"extracted:{text}"


def _mock_embed(fund_id: str, synthetic_static: bool, chunk: str) -> list:
    """Simulates an embedding function that correctly gates on the guard."""
    assert_fund_allows_ai(fund_id, synthetic_static)
    return [0.1, 0.2, 0.3]  # fake embedding


def test_live_fund_llm_extraction_succeeds():
    result = _mock_llm_extract("fund-live-002", False, "document text")
    assert result == "extracted:document text"


def test_static_fund_llm_extraction_blocked():
    with pytest.raises(StaticFundAIError):
        _mock_llm_extract("fund-static-005", True, "document text")


def test_static_fund_embedding_blocked():
    with pytest.raises(StaticFundAIError):
        _mock_embed("fund-static-006", True, "chunk text")


def test_live_fund_embedding_succeeds():
    result = _mock_embed("fund-live-003", False, "chunk text")
    assert result == [0.1, 0.2, 0.3]


# ---------------------------------------------------------------------------
# Exhaustive: all 45 static Funds must be blocked
# ---------------------------------------------------------------------------

def test_all_synthetic_static_flags_blocked():
    """Any fund with synthetic_static=True must be blocked regardless of ID."""
    static_fund_ids = [f"fund-static-{i:03d}" for i in range(1, 46)]
    for fid in static_fund_ids:
        with pytest.raises(StaticFundAIError):
            assert_fund_allows_ai(fid, synthetic_static=True)


def test_all_live_funds_pass():
    """Any fund with synthetic_static=False must pass."""
    live_fund_ids = [f"fund-live-{i:03d}" for i in range(1, 6)]
    for fid in live_fund_ids:
        assert_fund_allows_ai(fid, synthetic_static=False)  # must not raise
