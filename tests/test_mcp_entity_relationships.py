"""
Tests for mcp_servers/entity_relationships.py — PRD §8.2, §7.4.
All tests run MOCK=true (internal tool, no DB in test env).
"""

import pytest

import mcp_servers.entity_relationships as er_srv
from mcp_servers import ToolResult

FUND_1 = "f0000001-f000-0000-0000-000000000001"  # Northgate — 2 UBOs, all resolved
FUND_2 = "f0000002-f000-0000-0000-000000000002"  # Meridian  — 4 UBOs, 1 unresolved
FUND_3 = "f0000003-f000-0000-0000-000000000003"  # Aldgate   — 1 UBO
FUND_4 = "f0000004-f000-0000-0000-000000000004"  # Harrington — 3 UBOs, PEP T1
FUND_5 = "f0000005-f000-0000-0000-000000000005"  # Queensbridge — 3 UBOs


@pytest.fixture(autouse=True)
def _force_mock(monkeypatch):
    monkeypatch.setattr(er_srv, "MOCK", True)


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

def test_tools_list_has_both_tools():
    names = {t["name"] for t in er_srv.TOOLS}
    assert "get_ubo_chain" in names
    assert "get_shared_counterparties" in names


def test_get_ubo_chain_schema_requires_fund_id():
    tool = next(t for t in er_srv.TOOLS if t["name"] == "get_ubo_chain")
    assert "fund_id" in tool["input_schema"]["required"]


def test_get_shared_counterparties_fund_id_is_optional():
    tool = next(t for t in er_srv.TOOLS if t["name"] == "get_shared_counterparties")
    # fund_id is a filter, not required.
    assert "fund_id" not in tool["input_schema"].get("required", [])


# ---------------------------------------------------------------------------
# get_ubo_chain — validation
# ---------------------------------------------------------------------------

def test_empty_fund_id_raises():
    with pytest.raises(ValueError, match="fund_id"):
        er_srv.get_ubo_chain("")


def test_whitespace_fund_id_raises():
    with pytest.raises(ValueError, match="fund_id"):
        er_srv.get_ubo_chain("   ")


# ---------------------------------------------------------------------------
# get_ubo_chain — structure
# ---------------------------------------------------------------------------

def test_northgate_has_two_ubos():
    result = er_srv.get_ubo_chain(FUND_1)
    assert len(result["ubos"]) == 2


def test_meridian_has_four_ubos():
    result = er_srv.get_ubo_chain(FUND_2)
    assert len(result["ubos"]) == 4


def test_each_ubo_has_required_fields():
    result = er_srv.get_ubo_chain(FUND_1)
    for ubo in result["ubos"]:
        assert "name" in ubo
        assert "ownership_pct" in ubo
        assert "layer_depth" in ubo
        assert "resolved" in ubo
        assert "pep_tier" in ubo


def test_result_contains_fund_id_and_name():
    result = er_srv.get_ubo_chain(FUND_1)
    assert result["fund_id"] == FUND_1
    assert result["fund_name"] == "Northgate Capital Partners LP"
    assert result["is_mock"] is True


def test_unknown_fund_returns_empty_ubos():
    unknown = "99999999-0000-0000-0000-000000000099"
    result = er_srv.get_ubo_chain(unknown)
    assert result["ubos"] == []
    assert result["fund_name"] is None


# ---------------------------------------------------------------------------
# get_ubo_chain — unresolved layer detection (PRD §7.4 test case)
# ---------------------------------------------------------------------------

def test_meridian_has_unresolved_layer():
    result = er_srv.get_ubo_chain(FUND_2)
    unresolved = result["unresolved_layers"]
    assert len(unresolved) >= 1
    assert any("[Layer 2 entity unknown]" in u["name"] for u in unresolved)


def test_northgate_has_no_unresolved_layers():
    result = er_srv.get_ubo_chain(FUND_1)
    assert result["unresolved_layers"] == []


def test_aldgate_has_no_unresolved_layers():
    result = er_srv.get_ubo_chain(FUND_3)
    assert result["unresolved_layers"] == []


# ---------------------------------------------------------------------------
# get_ubo_chain — PEP detection (PRD §9.2)
# ---------------------------------------------------------------------------

def test_harrington_has_pep_tier1_ubo():
    result = er_srv.get_ubo_chain(FUND_4)
    pep_ubos = [u for u in result["ubos"] if u.get("pep_tier", 0) == 1]
    assert len(pep_ubos) == 1
    assert pep_ubos[0]["name"] == "Robert Harrington III"


def test_meridian_has_pep_tier2_ubo():
    result = er_srv.get_ubo_chain(FUND_2)
    pep_ubos = [u for u in result["ubos"] if u.get("pep_tier", 0) >= 2]
    assert any(u["name"] == "Werner Mueller" for u in pep_ubos)


def test_northgate_has_no_pep_ubos():
    result = er_srv.get_ubo_chain(FUND_1)
    pep_ubos = [u for u in result["ubos"] if u.get("pep_tier", 0) > 0]
    assert pep_ubos == []


# ---------------------------------------------------------------------------
# get_ubo_chain — ownership layer structure
# ---------------------------------------------------------------------------

def test_all_layer_depths_are_positive():
    for fund_id in [FUND_1, FUND_2, FUND_3, FUND_4, FUND_5]:
        result = er_srv.get_ubo_chain(fund_id)
        for ubo in result["ubos"]:
            assert ubo["layer_depth"] >= 1


def test_queensbridge_has_layer2_ubos():
    result = er_srv.get_ubo_chain(FUND_5)
    layer2 = [u for u in result["ubos"] if u["layer_depth"] == 2]
    assert len(layer2) == 2  # James Wentworth + Victoria Forsythe


# ---------------------------------------------------------------------------
# get_shared_counterparties — shared DBS Bank Ltd (PRD §7.4 test case)
# ---------------------------------------------------------------------------

def test_shared_counterparties_returns_dbs():
    result = er_srv.get_shared_counterparties()
    names = [cp["institution_name"] for cp in result["shared_counterparties"]]
    assert "DBS Bank Ltd" in names


def test_dbs_counterparty_has_two_bles():
    result = er_srv.get_shared_counterparties()
    dbs = next(cp for cp in result["shared_counterparties"]
               if cp["institution_name"] == "DBS Bank Ltd")
    assert len(dbs["bles"]) == 2


def test_dbs_bles_span_two_different_funds():
    result = er_srv.get_shared_counterparties()
    dbs = next(cp for cp in result["shared_counterparties"]
               if cp["institution_name"] == "DBS Bank Ltd")
    fund_ids = {b["fund_id"] for b in dbs["bles"]}
    assert len(fund_ids) == 2  # Meridian + Aldgate


def test_dbs_bles_correct_locations():
    result = er_srv.get_shared_counterparties()
    dbs = next(cp for cp in result["shared_counterparties"]
               if cp["institution_name"] == "DBS Bank Ltd")
    locations = {b["location"] for b in dbs["bles"]}
    assert "Singapore" in locations
    assert "Hong Kong" in locations


def test_shared_result_has_counterparty_id():
    result = er_srv.get_shared_counterparties()
    for cp in result["shared_counterparties"]:
        assert "counterparty_id" in cp
        assert cp["counterparty_id"]


# ---------------------------------------------------------------------------
# get_shared_counterparties — fund_id filter
# ---------------------------------------------------------------------------

def test_filter_by_meridian_returns_dbs():
    result = er_srv.get_shared_counterparties(fund_id=FUND_2)
    names = [cp["institution_name"] for cp in result["shared_counterparties"]]
    assert "DBS Bank Ltd" in names


def test_filter_by_fund_with_no_shared_returns_empty():
    # Fund 1 (Northgate) has Bank Rossiya — not a shared counterparty.
    result = er_srv.get_shared_counterparties(fund_id=FUND_1)
    assert result["shared_counterparties"] == []


def test_filter_fund_id_in_result():
    result = er_srv.get_shared_counterparties(fund_id=FUND_2)
    assert result["filter_fund_id"] == FUND_2


def test_no_filter_returns_all_shared():
    result = er_srv.get_shared_counterparties()
    assert result["filter_fund_id"] is None
    assert len(result["shared_counterparties"]) >= 1


# ---------------------------------------------------------------------------
# call_tool dispatch
# ---------------------------------------------------------------------------

def test_call_tool_get_ubo_chain():
    tr = er_srv.call_tool("get_ubo_chain", {"fund_id": FUND_1})
    assert isinstance(tr, ToolResult)
    assert tr.ok
    assert len(tr.result["ubos"]) == 2
    assert tr.is_mock is True


def test_call_tool_get_ubo_chain_empty_fund_id_error():
    tr = er_srv.call_tool("get_ubo_chain", {"fund_id": ""})
    assert not tr.ok
    assert tr.error is not None


def test_call_tool_get_shared_counterparties_no_filter():
    tr = er_srv.call_tool("get_shared_counterparties", {})
    assert isinstance(tr, ToolResult)
    assert tr.ok
    assert len(tr.result["shared_counterparties"]) >= 1


def test_call_tool_get_shared_counterparties_with_filter():
    tr = er_srv.call_tool("get_shared_counterparties", {"fund_id": FUND_2})
    assert tr.ok
    assert tr.result["filter_fund_id"] == FUND_2


def test_call_tool_unknown_tool_raises():
    with pytest.raises(ValueError, match="Unknown tool"):
        er_srv.call_tool("nonexistent", {})
