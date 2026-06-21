"""
Tests for mcp_servers/audit_history.py — PRD §8.2, §18.
All tests run MOCK=true (internal tool, no DB in test env).
"""

import pytest

import mcp_servers.audit_history as ah_srv
from mcp_servers import ToolResult

FUND_1 = "f0000001-f000-0000-0000-000000000001"  # Northgate — has 5 events
FUND_2 = "f0000002-f000-0000-0000-000000000002"  # Meridian  — has 4 events
FUND_3 = "f0000003-f000-0000-0000-000000000003"  # Aldgate   — has 2 events
BLE_1  = "b0001001-b000-0000-0000-000000000001"  # Bank Rossiya BLE — 4 events
BLE_5  = "b0004001-b000-0000-0000-000000000005"  # Emirates NBD BLE — 3 events
BLE_6  = "b0005001-b000-0000-0000-000000000006"  # ICBC Mumbai BLE  — 2 events


@pytest.fixture(autouse=True)
def _force_mock(monkeypatch):
    monkeypatch.setattr(ah_srv, "MOCK", True)


# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------

def test_tools_list_has_get_audit_history():
    names = [t["name"] for t in ah_srv.TOOLS]
    assert "get_audit_history" in names


def test_tool_schema_required_fields():
    tool = next(t for t in ah_srv.TOOLS if t["name"] == "get_audit_history")
    required = tool["input_schema"]["required"]
    assert "scope" in required
    assert "scope_id" in required


def test_scope_enum_values():
    tool = next(t for t in ah_srv.TOOLS if t["name"] == "get_audit_history")
    assert set(tool["input_schema"]["properties"]["scope"]["enum"]) == {"fund", "ble"}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_invalid_scope_raises():
    with pytest.raises(ValueError, match="scope"):
        ah_srv.get_audit_history("counterparty", FUND_1)


def test_empty_scope_id_raises():
    with pytest.raises(ValueError, match="scope_id"):
        ah_srv.get_audit_history("fund", "")


def test_whitespace_scope_id_raises():
    with pytest.raises(ValueError, match="scope_id"):
        ah_srv.get_audit_history("fund", "   ")


# ---------------------------------------------------------------------------
# MOCK results — known funds
# ---------------------------------------------------------------------------

def test_fund_history_returns_list():
    result = ah_srv.get_audit_history("fund", FUND_1)
    assert isinstance(result["history"], list)
    assert len(result["history"]) >= 1


def test_fund_history_scope_metadata():
    result = ah_srv.get_audit_history("fund", FUND_1)
    assert result["scope"] == "fund"
    assert result["scope_id"] == FUND_1
    assert result["is_mock"] is True


def test_ble_history_returns_list():
    result = ah_srv.get_audit_history("ble", BLE_1)
    assert isinstance(result["history"], list)
    assert len(result["history"]) >= 1


def test_ble_history_scope_metadata():
    result = ah_srv.get_audit_history("ble", BLE_1)
    assert result["scope"] == "ble"
    assert result["scope_id"] == BLE_1


def test_unknown_scope_id_returns_empty_history():
    unknown = "99999999-9999-0000-0000-000000000099"
    result = ah_srv.get_audit_history("fund", unknown)
    assert result["history"] == []
    assert result["total_available"] == 0


# ---------------------------------------------------------------------------
# Scope isolation — history for Fund A must not contain BLE records or Fund B records
# ---------------------------------------------------------------------------

def test_fund_1_history_does_not_contain_fund_2_events(monkeypatch):
    r1 = ah_srv.get_audit_history("fund", FUND_1)
    r2 = ah_srv.get_audit_history("fund", FUND_2)
    # Collect all notes from each result; they must not overlap in a way that
    # indicates cross-scope leakage. The simplest check: scope_id is correct.
    assert r1["scope_id"] == FUND_1
    assert r2["scope_id"] == FUND_2
    # Fund 2 has a document_expiry_detected note; Fund 1 must not contain it.
    fund1_actions = {e["action"] for e in r1["history"]}
    fund2_actions = {e["action"] for e in r2["history"]}
    # "document_expiry_detected" should only appear in Fund 2 history.
    assert "document_expiry_detected" not in fund1_actions
    assert "document_expiry_detected" in fund2_actions


def test_ble_history_does_not_contain_fund_events():
    ble_result = ah_srv.get_audit_history("ble", BLE_1)
    ble_actions = {e["action"] for e in ble_result["history"]}
    # "periodic_review_initiated" is a Fund-level action in our mock data, not BLE.
    assert "periodic_review_initiated" not in ble_actions


def test_fund_history_does_not_contain_ble_events():
    fund_result = ah_srv.get_audit_history("fund", FUND_1)
    fund_actions = {e["action"] for e in fund_result["history"]}
    # "escalation_triggered" and "workflow_declined" are BLE-1-level events.
    assert "workflow_declined" not in fund_actions


# ---------------------------------------------------------------------------
# Ordering — most recent first
# ---------------------------------------------------------------------------

def test_history_returned_most_recent_first():
    result = ah_srv.get_audit_history("fund", FUND_1)
    history = result["history"]
    if len(history) >= 2:
        timestamps = [e["performed_at"] for e in history]
        assert timestamps == sorted(timestamps, reverse=True), (
            "History is not in reverse chronological order"
        )


# ---------------------------------------------------------------------------
# limit parameter
# ---------------------------------------------------------------------------

def test_limit_caps_results():
    result = ah_srv.get_audit_history("fund", FUND_1, limit=2)
    assert len(result["history"]) <= 2


def test_limit_1_returns_one_record():
    result = ah_srv.get_audit_history("fund", FUND_1, limit=1)
    assert len(result["history"]) == 1


def test_limit_clamped_to_max_100():
    result = ah_srv.get_audit_history("fund", FUND_1, limit=999)
    # No error — limit is clamped, not rejected.
    assert isinstance(result["history"], list)


def test_limit_clamped_to_min_1():
    result = ah_srv.get_audit_history("fund", FUND_1, limit=0)
    assert len(result["history"]) >= 1  # returns at least 1


def test_total_available_reflects_full_count():
    result = ah_srv.get_audit_history("fund", FUND_1, limit=1)
    # total_available is the count before limit is applied.
    assert result["total_available"] >= len(result["history"])


# ---------------------------------------------------------------------------
# Event structure
# ---------------------------------------------------------------------------

def test_each_event_has_required_fields():
    result = ah_srv.get_audit_history("fund", FUND_1)
    for event in result["history"]:
        assert "action" in event
        assert "actor" in event
        assert "performed_at" in event


def test_bank_rossiya_ble_has_escalation_event():
    result = ah_srv.get_audit_history("ble", BLE_1)
    actions = [e["action"] for e in result["history"]]
    assert "escalation_triggered" in actions


def test_harrington_ble_has_pep_event():
    result = ah_srv.get_audit_history("ble", BLE_5)
    actions = [e["action"] for e in result["history"]]
    assert "pep_contact_noted" in actions


# ---------------------------------------------------------------------------
# call_tool dispatch
# ---------------------------------------------------------------------------

def test_call_tool_returns_tool_result():
    tr = ah_srv.call_tool("get_audit_history", {
        "scope": "fund",
        "scope_id": FUND_1,
    })
    assert isinstance(tr, ToolResult)
    assert tr.ok
    assert tr.is_mock is True


def test_call_tool_respects_limit():
    tr = ah_srv.call_tool("get_audit_history", {
        "scope": "fund",
        "scope_id": FUND_1,
        "limit": 2,
    })
    assert len(tr.result["history"]) <= 2


def test_call_tool_invalid_scope_error():
    tr = ah_srv.call_tool("get_audit_history", {
        "scope": "counterparty",
        "scope_id": FUND_1,
    })
    assert not tr.ok
    assert tr.error is not None


def test_call_tool_unknown_tool_raises():
    with pytest.raises(ValueError, match="Unknown tool"):
        ah_srv.call_tool("nonexistent", {})
