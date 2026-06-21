"""
MCP Tool Server: UBO Provider — PRD §8.2, §17.

Tool: get_ubo_data
  Returns structured UBO ownership data for a Fund from a UBO data vendor.
  This server is always mocked — there is no live vendor call in this phase.
  The interface matches what a paid vendor (Moody's Orbis, ComplyAdvantage)
  would return so it can be swapped in without changing the agent contract.

Interface design:
  - Returns the same UBO structure as entity_relationships.get_ubo_chain but
    adds vendor-specific metadata: source, confidence, last_verified_date.
  - layer_depth_limit caps how many ownership layers are returned (simulates
    vendor depth tiers in paid plans).
  - Unresolved layers are always included with resolved=false + a note, so the
    agent can surface incomplete chains to the human reviewer.

Static fund guard: reading UBO data for a static Fund is safe (no external
  call, no LLM). Guard not applied here.

MOCK=true and MOCK=false both return the same mocked data in this phase
  (there is no live vendor to call). A future swap-in sets MOCK=false and
  replaces _mock_vendor_call with the vendor SDK.
"""

from __future__ import annotations

import os
from datetime import date
from typing import Any

from mcp_servers import ToolResult

MOCK: bool = os.getenv("MOCK", "true").lower() == "true"

# Vendor interface version — bump when the output schema changes.
_VENDOR_INTERFACE_VERSION = "v1-mock"

# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------

TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_ubo_data",
        "description": (
            "Retrieve structured Ultimate Beneficial Owner (UBO) data for a "
            "Fund from the UBO data vendor. Returns all ownership layers up to "
            "layer_depth_limit, with PEP flags, resolution status, "
            "jurisdiction, and vendor confidence scores. "
            "Unresolved layers are included with resolved=false."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fund_id": {
                    "type": "string",
                    "description": "UUID of the Fund whose UBO data to retrieve.",
                },
                "layer_depth_limit": {
                    "type": "integer",
                    "description": "Maximum ownership layer depth to return (default 3, min 1, max 5).",
                    "default": 3,
                },
            },
            "required": ["fund_id"],
        },
    }
]


# ---------------------------------------------------------------------------
# Mock vendor data — matches seed_truth.json UBOs + adds vendor metadata
# ---------------------------------------------------------------------------

_MOCK_VENDOR_DATA: dict[str, dict[str, Any]] = {
    # Fund 1 — Northgate Capital Partners LP
    "f0000001-f000-0000-0000-000000000001": {
        "fund_name": "Northgate Capital Partners LP",
        "vendor_entity_id": "MOCK-NCP-001",
        "ubos": [
            {
                "name": "John Richardson",
                "ownership_pct": 70.0,
                "layer_depth": 1,
                "resolved": True,
                "pep_tier": 0,
                "pep_designation": None,
                "nationality": "GBR",
                "jurisdiction": "GBR",
                "parent_entity": None,
                "source": "Companies House UK + vendor registry",
                "confidence": 0.97,
                "last_verified_date": "2026-03-01",
            },
            {
                "name": "Cayman Ventures Ltd",
                "ownership_pct": 30.0,
                "layer_depth": 1,
                "resolved": True,
                "pep_tier": 0,
                "pep_designation": None,
                "nationality": None,
                "jurisdiction": "CYM",
                "registration_number": "EX-CYM-2014-03219",
                "parent_entity": None,
                "source": "Cayman Islands Registrar",
                "confidence": 0.91,
                "last_verified_date": "2026-03-01",
            },
        ],
    },
    # Fund 2 — Meridian Strategic Growth Trust
    "f0000002-f000-0000-0000-000000000002": {
        "fund_name": "Meridian Strategic Growth Trust",
        "vendor_entity_id": "MOCK-MSG-002",
        "ubos": [
            {
                "name": "Meridian Holdings Ltd",
                "ownership_pct": 60.0,
                "layer_depth": 1,
                "resolved": True,
                "pep_tier": 0,
                "pep_designation": None,
                "nationality": None,
                "jurisdiction": "CYM",
                "registration_number": "EX-CYM-2012-77341",
                "parent_entity": None,
                "source": "Cayman Islands Registrar",
                "confidence": 0.89,
                "last_verified_date": "2025-11-01",
            },
            {
                "name": "[Layer 2 entity unknown]",
                "ownership_pct": None,
                "layer_depth": 2,
                "resolved": False,
                "pep_tier": 0,
                "pep_designation": None,
                "nationality": None,
                "jurisdiction": None,
                "parent_entity": "Meridian Holdings Ltd",
                "source": "vendor_lookup",
                "confidence": 0.0,
                "last_verified_date": None,
                "vendor_note": "Ultimate beneficial owner of Meridian Holdings Ltd could not be resolved. Further documentation required.",
            },
            {
                "name": "EU Capital Partners SA",
                "ownership_pct": 40.0,
                "layer_depth": 1,
                "resolved": True,
                "pep_tier": 0,
                "pep_designation": None,
                "nationality": None,
                "jurisdiction": "LUX",
                "registration_number": "LUX-B-189452",
                "parent_entity": None,
                "source": "RCSL Luxembourg",
                "confidence": 0.94,
                "last_verified_date": "2025-11-01",
            },
            {
                "name": "Werner Mueller",
                "ownership_pct": 40.0,
                "layer_depth": 2,
                "resolved": True,
                "pep_tier": 2,
                "pep_designation": "Senior Official, European Banking Supervisory Committee (synthetic)",
                "nationality": "DEU",
                "jurisdiction": "DEU",
                "parent_entity": "EU Capital Partners SA",
                "effective_fund_ownership_pct": 40.0,
                "source": "EU PEP registry + national company register",
                "confidence": 0.88,
                "last_verified_date": "2025-11-01",
            },
        ],
    },
    # Fund 3 — Aldgate Street Capital Fund
    "f0000003-f000-0000-0000-000000000003": {
        "fund_name": "Aldgate Street Capital Fund",
        "vendor_entity_id": "MOCK-ASC-003",
        "ubos": [
            {
                "name": "Patrick O'Brien",
                "ownership_pct": 100.0,
                "layer_depth": 1,
                "resolved": True,
                "pep_tier": 0,
                "pep_designation": None,
                "nationality": "IRL",
                "jurisdiction": "IRL",
                "parent_entity": None,
                "source": "Companies Registration Office Ireland",
                "confidence": 0.99,
                "last_verified_date": "2026-01-15",
            },
        ],
    },
    # Fund 4 — Harrington Private Capital
    "f0000004-f000-0000-0000-000000000004": {
        "fund_name": "Harrington Private Capital",
        "vendor_entity_id": "MOCK-HPC-004",
        "ubos": [
            {
                "name": "Robert Harrington III",
                "ownership_pct": 51.0,
                "layer_depth": 1,
                "resolved": True,
                "pep_tier": 1,
                "pep_designation": "Former Minister of Finance, Government of Malta (synthetic)",
                "nationality": "MLT",
                "jurisdiction": "MLT",
                "parent_entity": None,
                "source": "MFSA Malta + PEP registry",
                "confidence": 0.96,
                "last_verified_date": "2026-04-01",
            },
            {
                "name": "HAP Holding Ltd",
                "ownership_pct": 49.0,
                "layer_depth": 1,
                "resolved": True,
                "pep_tier": 0,
                "pep_designation": None,
                "nationality": None,
                "jurisdiction": "MLT",
                "registration_number": "MLT-C-67891",
                "parent_entity": None,
                "source": "Malta Business Registry",
                "confidence": 0.93,
                "last_verified_date": "2026-04-01",
            },
            {
                "name": "Sarah Chen",
                "ownership_pct": 49.0,
                "layer_depth": 2,
                "resolved": True,
                "pep_tier": 0,
                "pep_designation": None,
                "nationality": "SGP",
                "jurisdiction": "SGP",
                "parent_entity": "HAP Holding Ltd",
                "effective_fund_ownership_pct": 49.0,
                "source": "ACRA Singapore + corporate registry",
                "confidence": 0.90,
                "last_verified_date": "2026-04-01",
            },
        ],
    },
    # Fund 5 — Queensbridge Emerging Markets Fund LP
    "f0000005-f000-0000-0000-000000000005": {
        "fund_name": "Queensbridge Emerging Markets Fund LP",
        "vendor_entity_id": "MOCK-QEM-005",
        "ubos": [
            {
                "name": "Queensbridge Asset Management Ltd",
                "ownership_pct": 100.0,
                "layer_depth": 1,
                "resolved": True,
                "pep_tier": 0,
                "pep_designation": None,
                "nationality": None,
                "jurisdiction": "SGP",
                "registration_number": "SGP-201708901N",
                "parent_entity": None,
                "source": "ACRA Singapore",
                "confidence": 0.98,
                "last_verified_date": "2026-02-10",
            },
            {
                "name": "James Wentworth",
                "ownership_pct": 60.0,
                "layer_depth": 2,
                "resolved": True,
                "pep_tier": 0,
                "pep_designation": None,
                "nationality": "GBR",
                "jurisdiction": "GBR",
                "parent_entity": "Queensbridge Asset Management Ltd",
                "effective_fund_ownership_pct": 60.0,
                "source": "Companies House UK",
                "confidence": 0.95,
                "last_verified_date": "2026-02-10",
            },
            {
                "name": "Victoria Forsythe",
                "ownership_pct": 40.0,
                "layer_depth": 2,
                "resolved": True,
                "pep_tier": 0,
                "pep_designation": None,
                "nationality": "AUS",
                "jurisdiction": "AUS",
                "parent_entity": "Queensbridge Asset Management Ltd",
                "effective_fund_ownership_pct": 40.0,
                "source": "ASIC Australia",
                "confidence": 0.93,
                "last_verified_date": "2026-02-10",
            },
        ],
    },
}


# ---------------------------------------------------------------------------
# Public tool function
# ---------------------------------------------------------------------------


def get_ubo_data(
    fund_id: str,
    layer_depth_limit: int = 3,
) -> dict[str, Any]:
    """
    Return vendor-structured UBO data for fund_id.
    Always returns mock data in this phase (no live vendor call).

    Raises:
      ValueError — empty fund_id or invalid layer_depth_limit.
    """
    if not fund_id or not fund_id.strip():
        raise ValueError("fund_id must not be empty")
    layer_depth_limit = max(1, min(layer_depth_limit, 5))

    vendor_payload = _mock_vendor_call(fund_id, layer_depth_limit)
    return {
        "fund_id": fund_id,
        "vendor_interface_version": _VENDOR_INTERFACE_VERSION,
        "layer_depth_limit": layer_depth_limit,
        **vendor_payload,
        "is_mock": True,
    }


def _mock_vendor_call(fund_id: str, layer_depth_limit: int) -> dict[str, Any]:
    data = _MOCK_VENDOR_DATA.get(fund_id)
    if data is None:
        return {
            "fund_name": None,
            "vendor_entity_id": None,
            "ubos": [],
            "vendor_note": f"No data found for fund_id={fund_id!r}",
        }
    filtered_ubos = [
        u for u in data["ubos"] if u["layer_depth"] <= layer_depth_limit
    ]
    return {
        "fund_name": data["fund_name"],
        "vendor_entity_id": data["vendor_entity_id"],
        "ubos": filtered_ubos,
        "unresolved_layers": [u for u in filtered_ubos if not u.get("resolved", True)],
        "retrieved_at": str(date.today()),
    }


# ---------------------------------------------------------------------------
# MCP dispatch
# ---------------------------------------------------------------------------


def call_tool(name: str, params: dict[str, Any]) -> ToolResult:
    if name == "get_ubo_data":
        try:
            result = get_ubo_data(
                fund_id=params["fund_id"],
                layer_depth_limit=int(params.get("layer_depth_limit", 3)),
            )
            return ToolResult(tool_name=name, params=params, result=result,
                              is_mock=result.get("is_mock", True))
        except ValueError as exc:
            return ToolResult(tool_name=name, params=params, result={},
                              is_mock=True, error=str(exc))
    raise ValueError(f"Unknown tool: {name!r}. Available: {[t['name'] for t in TOOLS]}")
