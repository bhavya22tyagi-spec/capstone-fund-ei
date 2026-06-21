"""
Tests for mcp_servers/ubo_provider.py — PRD §8.2, §17.
UBO Provider is always mocked (no live vendor). All tests run unconditionally.
"""

import pytest

import mcp_servers.ubo_provider as ubop_srv
from mcp_servers import ToolResult

FUND_1 = "f0000001-f000-0000-0000-000000000001"  # Northgate  — 2 UBOs, all resolved
FUND_2 = "f0000002-f000-0000-0000-000000000002"  # Meridian   — 4 UBOs, 1 unresolved
FUND_3 = "f0000003-f000-0000-0000-000000000003"  # Aldgate    — 1 UBO
FUND_4 = "f0000004-f000-0000-0000-000000000004"  # Harrington — 3 UBOs, PEP T1
FUND_5 = "f0000005-f000-0000-0000-000000000005"  # Queensbridge


# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------

def test_tools_list_has_get_ubo_data():
    names = [t["name"] for t in ubop_srv.TOOLS]
    assert "get_ubo_data" in names


def test_tool_schema_requires_fund_id():
    tool = next(t for t in ubop_srv.TOOLS if t["name"] == "get_ubo_data")
    assert "fund_id" in tool["input_schema"]["required"]


def test_layer_depth_limit_is_optional():
    tool = next(t for t in ubop_srv.TOOLS if t["name"] == "get_ubo_data")
    required = tool["input_schema"].get("required", [])
    assert "layer_depth_limit" not in required


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_empty_fund_id_raises():
    with pytest.raises(ValueError, match="fund_id"):
        ubop_srv.get_ubo_data("")


def test_whitespace_fund_id_raises():
    with pytest.raises(ValueError, match="fund_id"):
        ubop_srv.get_ubo_data("   ")


# ---------------------------------------------------------------------------
# Core results
# ---------------------------------------------------------------------------

def test_northgate_returns_two_ubos():
    result = ubop_srv.get_ubo_data(FUND_1)
    assert len(result["ubos"]) == 2


def test_meridian_returns_four_ubos():
    result = ubop_srv.get_ubo_data(FUND_2)
    assert len(result["ubos"]) == 4


def test_result_structure():
    result = ubop_srv.get_ubo_data(FUND_1)
    assert result["fund_id"] == FUND_1
    assert result["is_mock"] is True
    assert "vendor_interface_version" in result
    assert "ubos" in result
    assert "unresolved_layers" in result


def test_vendor_interface_version_set():
    result = ubop_srv.get_ubo_data(FUND_1)
    assert result["vendor_interface_version"] == "v1-mock"


def test_unknown_fund_returns_empty():
    unknown = "99999999-0000-0000-0000-000000000099"
    result = ubop_srv.get_ubo_data(unknown)
    assert result["ubos"] == []
    assert result["fund_name"] is None


# ---------------------------------------------------------------------------
# Vendor-specific fields
# ---------------------------------------------------------------------------

def test_ubos_have_source_field():
    result = ubop_srv.get_ubo_data(FUND_1)
    for ubo in result["ubos"]:
        assert "source" in ubo, f"Missing 'source' in UBO: {ubo['name']}"


def test_ubos_have_confidence_field():
    result = ubop_srv.get_ubo_data(FUND_1)
    for ubo in result["ubos"]:
        assert "confidence" in ubo


def test_ubos_have_last_verified_date():
    result = ubop_srv.get_ubo_data(FUND_1)
    # Resolved UBOs should have a verification date.
    resolved = [u for u in result["ubos"] if u["resolved"]]
    for ubo in resolved:
        assert ubo.get("last_verified_date"), f"No last_verified_date for {ubo['name']}"


def test_unresolved_ubo_confidence_is_zero():
    result = ubop_srv.get_ubo_data(FUND_2)
    unresolved = [u for u in result["ubos"] if not u["resolved"]]
    for ubo in unresolved:
        assert ubo["confidence"] == 0.0


# ---------------------------------------------------------------------------
# layer_depth_limit
# ---------------------------------------------------------------------------

def test_depth_limit_1_returns_only_layer_1():
    result = ubop_srv.get_ubo_data(FUND_2, layer_depth_limit=1)
    for ubo in result["ubos"]:
        assert ubo["layer_depth"] == 1


def test_depth_limit_2_includes_layer_2():
    result = ubop_srv.get_ubo_data(FUND_2, layer_depth_limit=2)
    layers = {u["layer_depth"] for u in result["ubos"]}
    assert 2 in layers


def test_depth_limit_1_meridian_has_two_ubos():
    # Meridian: 2 layer-1 UBOs (Meridian Holdings Ltd + EU Capital Partners SA)
    result = ubop_srv.get_ubo_data(FUND_2, layer_depth_limit=1)
    assert len(result["ubos"]) == 2


def test_depth_limit_clamped_below_1():
    # Should not raise; limit clamped to 1.
    result = ubop_srv.get_ubo_data(FUND_1, layer_depth_limit=0)
    assert isinstance(result["ubos"], list)
    for ubo in result["ubos"]:
        assert ubo["layer_depth"] >= 1


def test_depth_limit_clamped_above_5():
    result = ubop_srv.get_ubo_data(FUND_1, layer_depth_limit=99)
    assert isinstance(result["ubos"], list)
    assert result["layer_depth_limit"] == 5


# ---------------------------------------------------------------------------
# PEP flags
# ---------------------------------------------------------------------------

def test_harrington_pep_tier1_present():
    result = ubop_srv.get_ubo_data(FUND_4)
    pep1 = [u for u in result["ubos"] if u.get("pep_tier") == 1]
    assert len(pep1) == 1
    assert pep1[0]["name"] == "Robert Harrington III"


def test_northgate_no_pep():
    result = ubop_srv.get_ubo_data(FUND_1)
    pep = [u for u in result["ubos"] if u.get("pep_tier", 0) > 0]
    assert pep == []


def test_meridian_werner_mueller_pep_tier2():
    result = ubop_srv.get_ubo_data(FUND_2)
    werner = next((u for u in result["ubos"] if u["name"] == "Werner Mueller"), None)
    assert werner is not None
    assert werner["pep_tier"] == 2


# ---------------------------------------------------------------------------
# Unresolved layer reporting
# ---------------------------------------------------------------------------

def test_meridian_has_unresolved_layer():
    result = ubop_srv.get_ubo_data(FUND_2)
    assert len(result["unresolved_layers"]) >= 1


def test_northgate_no_unresolved_layers():
    result = ubop_srv.get_ubo_data(FUND_1)
    assert result["unresolved_layers"] == []


def test_unresolved_layer_included_in_ubos():
    result = ubop_srv.get_ubo_data(FUND_2)
    ubo_names = [u["name"] for u in result["ubos"]]
    unresolved_names = [u["name"] for u in result["unresolved_layers"]]
    for name in unresolved_names:
        assert name in ubo_names


# ---------------------------------------------------------------------------
# call_tool dispatch
# ---------------------------------------------------------------------------

def test_call_tool_returns_tool_result():
    tr = ubop_srv.call_tool("get_ubo_data", {"fund_id": FUND_1})
    assert isinstance(tr, ToolResult)
    assert tr.ok
    assert tr.is_mock is True


def test_call_tool_with_depth_limit():
    tr = ubop_srv.call_tool("get_ubo_data", {"fund_id": FUND_2, "layer_depth_limit": 1})
    assert tr.ok
    for ubo in tr.result["ubos"]:
        assert ubo["layer_depth"] == 1


def test_call_tool_empty_fund_id_returns_error():
    tr = ubop_srv.call_tool("get_ubo_data", {"fund_id": ""})
    assert not tr.ok
    assert tr.error is not None
    assert tr.result == {}


def test_call_tool_unknown_tool_raises():
    with pytest.raises(ValueError, match="Unknown tool"):
        ubop_srv.call_tool("nonexistent", {})
