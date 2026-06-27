"""
Tests for mcp_servers/opensanctions.py — PRD §8.2, §7, §17.

MOCK=true tests: all run in CI without network access.
MOCK=false test: marked @pytest.mark.live — makes a real free-tier API call
  to api.opensanctions.org. Run with:  pytest -m live
"""

import pytest

import mcp_servers.opensanctions as os_srv
from mcp_servers import ToolResult
from services.guards import StaticFundAIError

FUND_A  = "f0000001-f000-0000-0000-000000000001"
FUND_B  = "f0000002-f000-0000-0000-000000000002"
CPT_ID  = "c0000001-c000-0000-0000-000000000001"
CPT_DBS = "c0000003-c000-0000-0000-000000000003"


@pytest.fixture(autouse=True)
def _force_mock(monkeypatch):
    monkeypatch.setattr(os_srv, "MOCK", True)


# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------

def test_tools_list_has_screen_entity():
    names = [t["name"] for t in os_srv.TOOLS]
    assert "screen_entity" in names


def test_tool_has_required_fields():
    tool = next(t for t in os_srv.TOOLS if t["name"] == "screen_entity")
    schema = tool["input_schema"]
    required = schema["required"]
    for field in ("name", "scope", "scope_id", "fund_id", "synthetic_static"):
        assert field in required, f"'{field}' missing from required"


def test_scope_enum_values():
    tool = next(t for t in os_srv.TOOLS if t["name"] == "screen_entity")
    scope_prop = tool["input_schema"]["properties"]["scope"]
    assert set(scope_prop["enum"]) == {"fund", "counterparty"}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_empty_name_raises():
    with pytest.raises(ValueError, match="empty"):
        os_srv.screen_entity("", "fund", FUND_A, FUND_A, False)


def test_whitespace_name_raises():
    with pytest.raises(ValueError, match="empty"):
        os_srv.screen_entity("   ", "fund", FUND_A, FUND_A, False)


def test_invalid_scope_raises():
    with pytest.raises(ValueError, match="scope"):
        os_srv.screen_entity("Bank Rossiya", "ble", CPT_ID, FUND_A, False)


def test_static_fund_raises():
    with pytest.raises(StaticFundAIError):
        os_srv.screen_entity("Bank Rossiya", "counterparty", CPT_ID, FUND_A, True)


# ---------------------------------------------------------------------------
# MOCK mode results — known names
# ---------------------------------------------------------------------------

def test_bank_rossiya_returns_confirmed_hit():
    result = os_srv.screen_entity("Bank Rossiya", "counterparty", CPT_ID, FUND_A, False)
    assert result["result_status"] == "hit"
    assert result["hit_severity"] == "confirmed"
    assert result["hit_type"] == "sanctions"


def test_deutsche_bank_returns_clean():
    result = os_srv.screen_entity("Deutsche Bank AG", "counterparty",
                                   "c0000002-c000-0000-0000-000000000002", FUND_B, False)
    assert result["result_status"] == "clean"
    assert result["hit_severity"] == "none"
    assert result["hit_type"] is None


def test_dbs_bank_returns_clean():
    result = os_srv.screen_entity("DBS Bank Ltd", "counterparty", CPT_DBS, FUND_B, False)
    assert result["result_status"] == "clean"


def test_emirates_nbd_returns_clean():
    result = os_srv.screen_entity(
        "Emirates NBD Bank PJSC", "counterparty",
        "c0000004-c000-0000-0000-000000000004",
        "f0000004-f000-0000-0000-000000000004", False,
    )
    assert result["result_status"] == "clean"


def test_robert_harrington_returns_adverse_hit():
    result = os_srv.screen_entity(
        "Robert Harrington III", "fund", FUND_A,
        "f0000004-f000-0000-0000-000000000004", False,
    )
    assert result["result_status"] == "hit"
    assert result["hit_severity"] == "low"
    assert result["hit_type"] == "adverse"


def test_unknown_name_returns_clean():
    result = os_srv.screen_entity("Completely Unknown Entity XYZ", "fund", FUND_A, FUND_A, False)
    assert result["result_status"] == "clean"
    assert result["hit_severity"] == "none"


# ---------------------------------------------------------------------------
# Result structure
# ---------------------------------------------------------------------------

def test_result_contains_scope_metadata():
    result = os_srv.screen_entity("DBS Bank Ltd", "counterparty", CPT_DBS, FUND_B, False)
    assert result["scope"] == "counterparty"
    assert result["scope_id"] == CPT_DBS
    assert result["screened_name"] == "DBS Bank Ltd"


def test_result_is_mock_flag_true_in_mock_mode():
    result = os_srv.screen_entity("DBS Bank Ltd", "counterparty", CPT_DBS, FUND_B, False)
    assert result["is_mock"] is True


def test_result_has_screened_at_timestamp():
    result = os_srv.screen_entity("DBS Bank Ltd", "counterparty", CPT_DBS, FUND_B, False)
    assert "screened_at" in result
    assert result["screened_at"]  # non-empty


def test_fund_scope_works():
    result = os_srv.screen_entity("John Richardson", "fund", FUND_A, FUND_A, False)
    assert result["scope"] == "fund"
    assert result["result_status"] == "clean"


# ---------------------------------------------------------------------------
# call_tool dispatch
# ---------------------------------------------------------------------------

def test_call_tool_screen_entity_clean():
    tr = os_srv.call_tool("screen_entity", {
        "name": "DBS Bank Ltd",
        "scope": "counterparty",
        "scope_id": CPT_DBS,
        "fund_id": FUND_B,
        "synthetic_static": False,
    })
    assert isinstance(tr, ToolResult)
    assert tr.ok
    assert tr.result["result_status"] == "clean"
    assert tr.is_mock is True


def test_call_tool_screen_entity_hit():
    tr = os_srv.call_tool("screen_entity", {
        "name": "Bank Rossiya",
        "scope": "counterparty",
        "scope_id": CPT_ID,
        "fund_id": FUND_A,
        "synthetic_static": False,
    })
    assert tr.ok
    assert tr.result["result_status"] == "hit"
    assert tr.result["hit_severity"] == "confirmed"


def test_call_tool_invalid_scope_returns_error():
    tr = os_srv.call_tool("screen_entity", {
        "name": "Bank Rossiya",
        "scope": "ble",  # invalid
        "scope_id": CPT_ID,
        "fund_id": FUND_A,
        "synthetic_static": False,
    })
    assert not tr.ok
    assert tr.error is not None
    assert tr.result == {}


def test_call_tool_static_fund_returns_error():
    tr = os_srv.call_tool("screen_entity", {
        "name": "Bank Rossiya",
        "scope": "counterparty",
        "scope_id": CPT_ID,
        "fund_id": FUND_A,
        "synthetic_static": True,
    })
    assert not tr.ok
    assert tr.result == {}


def test_call_tool_unknown_tool_raises():
    with pytest.raises(ValueError, match="Unknown tool"):
        os_srv.call_tool("nonexistent_tool", {})


# ---------------------------------------------------------------------------
# Scope independence — same name, different scope metadata preserved
# ---------------------------------------------------------------------------

def test_scope_id_preserved_in_result():
    for scope, sid in [("fund", FUND_A), ("counterparty", CPT_ID)]:
        result = os_srv.screen_entity("DBS Bank Ltd", scope, sid, FUND_A, False)
        assert result["scope_id"] == sid
        assert result["scope"] == scope


# ---------------------------------------------------------------------------
# Live test — real API call (network required; run with: pytest -m live)
# ---------------------------------------------------------------------------

@pytest.mark.live
def test_live_bank_rossiya_is_sanctioned(monkeypatch):
    """
    Real free-tier OpenSanctions call. Bank Rossiya is listed on OFAC SDN
    and EU sanctions lists — this should always return a positive hit.
    """
    monkeypatch.setattr(os_srv, "MOCK", False)
    result = os_srv.screen_entity(
        "Bank Rossiya", "counterparty", CPT_ID, FUND_A, False
    )
    # If the API is unreachable the result_status will be 'error' — acceptable
    # in a network-isolated environment, but should not be 'clean'.
    assert result["result_status"] in ("hit", "error"), (
        f"Unexpected result_status from live API: {result['result_status']}"
    )
    if result["result_status"] == "hit":
        assert result["hit_severity"] in ("high", "confirmed")
        assert result["hit_type"] == "sanctions"
    assert result["is_mock"] is False


@pytest.mark.live
def test_live_dbs_bank_is_clean(monkeypatch):
    """Real free-tier call: DBS Bank Ltd should return clean."""
    monkeypatch.setattr(os_srv, "MOCK", False)
    result = os_srv.screen_entity(
        "DBS Bank Ltd", "counterparty", CPT_DBS, FUND_B, False
    )
    assert result["result_status"] in ("clean", "error")
    assert result["is_mock"] is False


# ---------------------------------------------------------------------------
# _parse_response boundary tests — pin the _MIN_SCORE = 0.6 threshold
# ---------------------------------------------------------------------------

from mcp_servers.opensanctions import _parse_response


def test_parse_response_score_at_new_threshold_is_hit():
    """Score exactly at 0.60 with sanction topic must now be a hit (was clean at 0.7)."""
    data = {
        "results": [{
            "score": 0.60,
            "caption": "Bank Rossiya",
            "schema": "Company",
            "datasets": ["us_ofac_sdn"],
            "properties": {"topics": ["sanction"]},
        }]
    }
    result = _parse_response("Bank Rossiya", data)
    assert result["result_status"] == "hit"
    assert result["hit_type"] == "sanctions"
    assert result["hit_severity"] == "high"   # score < 0.9 → high, not confirmed


def test_parse_response_score_below_new_threshold_is_clean():
    """Score 0.59 is below the 0.60 threshold — must return clean."""
    data = {
        "results": [{
            "score": 0.59,
            "caption": "Bank Rossiya",
            "schema": "Company",
            "datasets": ["us_ofac_sdn"],
            "properties": {"topics": ["sanction"]},
        }]
    }
    result = _parse_response("Bank Rossiya", data)
    assert result["result_status"] == "clean"


def test_parse_response_score_0_65_sanction_is_now_hit():
    """Score 0.65 was in the old dead zone (0.6–0.69 filtered at 0.7). Now a hit."""
    data = {
        "results": [{
            "score": 0.65,
            "caption": "Some Sanctioned Entity",
            "schema": "Company",
            "datasets": ["eu_sanctions"],
            "properties": {"topics": ["sanction"]},
        }]
    }
    result = _parse_response("Some Sanctioned Entity", data)
    assert result["result_status"] == "hit"
    assert result["hit_severity"] == "high"
    assert result["hit_type"] == "sanctions"
