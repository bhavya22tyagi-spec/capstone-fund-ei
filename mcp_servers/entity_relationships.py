"""
MCP Tool Server: Entity Relationships — PRD §8.2.

Two tools:
  get_ubo_chain            — Full UBO ownership chain for a Fund.
  get_shared_counterparties — BLEs that share a counterparty_profiles record
                               across different Funds (linked-entity graph).

These tools feed the agent and the text-to-SQL "linked entities" use case
(PRD §8.2, §7.4). They also support the counterparty-contagion trigger
(detect_shared_counterparty_contagion in trigger_engine).

MOCK=true (default): returns data derived from seed_truth.json for all 5 live
  Funds and the shared DBS Bank Ltd counterparty_profiles record.
MOCK=false: queries the bles, ubo_records, and counterparty_profiles tables.
  Read-only; no writes.

Static fund guard not applied — reading structural data for a static Fund is
  safe (no LLM call, no external API). The static guard covers AI calls only.
"""

from __future__ import annotations

import os
from typing import Any

from mcp_servers import ToolResult

MOCK: bool = os.getenv("MOCK", "true").lower() == "true"

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_ubo_chain",
        "description": (
            "Return the full UBO ownership chain for a Fund, including all "
            "layers, PEP status, resolution status, and parent-entity links. "
            "Unresolved layers are included with resolved=false."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fund_id": {
                    "type": "string",
                    "description": "UUID of the Fund whose UBO chain to retrieve.",
                },
            },
            "required": ["fund_id"],
        },
    },
    {
        "name": "get_shared_counterparties",
        "description": (
            "Return all counterparty_profiles records that are referenced by "
            "more than one BLE across different Funds. For each shared "
            "counterparty, lists every BLE and its parent Fund. "
            "Optionally filtered to BLEs of a specific Fund."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fund_id": {
                    "type": "string",
                    "description": "Optional. If provided, return only shared counterparties where at least one BLE belongs to this Fund.",
                },
            },
            "required": [],
        },
    },
]


# ---------------------------------------------------------------------------
# Mock data — UBO chains from seed_truth.json (all 5 live Funds)
# ---------------------------------------------------------------------------

_MOCK_UBO_CHAINS: dict[str, list[dict[str, Any]]] = {
    # Fund 1 — Northgate Capital Partners LP
    "f0000001-f000-0000-0000-000000000001": [
        {
            "ubo_id": "u0001001",
            "name": "John Richardson",
            "ownership_pct": 70.0,
            "layer_depth": 1,
            "resolved": True,
            "pep_tier": 0,
            "pep_designation": None,
            "nationality": "GBR",
            "jurisdiction": "GBR",
            "parent_entity": None,
        },
        {
            "ubo_id": "u0001002",
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
        },
    ],
    # Fund 2 — Meridian Strategic Growth Trust
    "f0000002-f000-0000-0000-000000000002": [
        {
            "ubo_id": "u0002001",
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
        },
        {
            "ubo_id": "u0002002",
            "name": "[Layer 2 entity unknown]",
            "ownership_pct": None,
            "layer_depth": 2,
            "resolved": False,
            "pep_tier": 0,
            "pep_designation": None,
            "nationality": None,
            "jurisdiction": None,
            "parent_entity": "Meridian Holdings Ltd",
            "note": "Ultimate beneficial owner of Meridian Holdings Ltd is unresolved — UBO chain incomplete at layer 2",
        },
        {
            "ubo_id": "u0002003",
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
        },
        {
            "ubo_id": "u0002004",
            "name": "Werner Mueller",
            "ownership_pct": 40.0,
            "layer_depth": 2,
            "resolved": True,
            "pep_tier": 2,
            "pep_designation": "Senior Official, European Banking Supervisory Committee (synthetic)",
            "nationality": "DEU",
            "jurisdiction": "DEU",
            "parent_entity": "EU Capital Partners SA",
            "effective_fund_ownership_pct_note": "Werner Mueller owns 100% of EU Capital Partners SA, which holds 40% of the Fund; effective beneficial interest = 40%",
        },
    ],
    # Fund 3 — Aldgate Street Capital Fund
    "f0000003-f000-0000-0000-000000000003": [
        {
            "ubo_id": "u0003001",
            "name": "Patrick O'Brien",
            "ownership_pct": 100.0,
            "layer_depth": 1,
            "resolved": True,
            "pep_tier": 0,
            "pep_designation": None,
            "nationality": "IRL",
            "jurisdiction": "IRL",
            "parent_entity": None,
        },
    ],
    # Fund 4 — Harrington Private Capital
    "f0000004-f000-0000-0000-000000000004": [
        {
            "ubo_id": "u0004001",
            "name": "Robert Harrington III",
            "ownership_pct": 51.0,
            "layer_depth": 1,
            "resolved": True,
            "pep_tier": 1,
            "pep_designation": "Former Minister of Finance, Government of Malta (synthetic)",
            "nationality": "MLT",
            "jurisdiction": "MLT",
            "parent_entity": None,
        },
        {
            "ubo_id": "u0004002",
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
        },
        {
            "ubo_id": "u0004003",
            "name": "Sarah Chen",
            "ownership_pct": 49.0,
            "layer_depth": 2,
            "resolved": True,
            "pep_tier": 0,
            "pep_designation": None,
            "nationality": "SGP",
            "jurisdiction": "SGP",
            "parent_entity": "HAP Holding Ltd",
            "effective_fund_ownership_pct_note": "Sarah Chen owns 100% of HAP Holding Ltd, which holds 49% of the Fund; effective beneficial interest = 49%",
        },
    ],
    # Fund 5 — Queensbridge Emerging Markets Fund LP
    "f0000005-f000-0000-0000-000000000005": [
        {
            "ubo_id": "u0005001",
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
        },
        {
            "ubo_id": "u0005002",
            "name": "James Wentworth",
            "ownership_pct": 60.0,
            "layer_depth": 2,
            "resolved": True,
            "pep_tier": 0,
            "pep_designation": None,
            "nationality": "GBR",
            "jurisdiction": "GBR",
            "parent_entity": "Queensbridge Asset Management Ltd",
            "effective_fund_ownership_pct_note": "James Wentworth holds 60% of Queensbridge Asset Management Ltd, which holds 100% of the Fund; effective beneficial interest = 60%",
        },
        {
            "ubo_id": "u0005003",
            "name": "Victoria Forsythe",
            "ownership_pct": 40.0,
            "layer_depth": 2,
            "resolved": True,
            "pep_tier": 0,
            "pep_designation": None,
            "nationality": "AUS",
            "jurisdiction": "AUS",
            "parent_entity": "Queensbridge Asset Management Ltd",
            "effective_fund_ownership_pct_note": "Victoria Forsythe holds 40% of Queensbridge Asset Management Ltd, which holds 100% of the Fund; effective beneficial interest = 40%",
        },
    ],
}

# Fund ID → Fund name (for display in relationship results)
_FUND_NAMES: dict[str, str] = {
    "f0000001-f000-0000-0000-000000000001": "Northgate Capital Partners LP",
    "f0000002-f000-0000-0000-000000000002": "Meridian Strategic Growth Trust",
    "f0000003-f000-0000-0000-000000000003": "Aldgate Street Capital Fund",
    "f0000004-f000-0000-0000-000000000004": "Harrington Private Capital",
    "f0000005-f000-0000-0000-000000000005": "Queensbridge Emerging Markets Fund LP",
}

# Shared counterparty graph — counterparty_id → metadata + referencing BLEs.
# Only counterparties referenced by ≥2 BLEs across different Funds appear here.
_MOCK_SHARED_COUNTERPARTIES: list[dict[str, Any]] = [
    {
        "counterparty_id": "c0000003-c000-0000-0000-000000000003",
        "institution_name": "DBS Bank Ltd",
        "screening_status": "clean",
        "bles": [
            {
                "ble_id": "b0002002-b000-0000-0000-000000000003",
                "fund_id": "f0000002-f000-0000-0000-000000000002",
                "fund_name": "Meridian Strategic Growth Trust",
                "location": "Singapore",
            },
            {
                "ble_id": "b0003001-b000-0000-0000-000000000004",
                "fund_id": "f0000003-f000-0000-0000-000000000003",
                "fund_name": "Aldgate Street Capital Fund",
                "location": "Hong Kong",
            },
        ],
    },
]


# ---------------------------------------------------------------------------
# Public tool functions
# ---------------------------------------------------------------------------


def get_ubo_chain(fund_id: str) -> dict[str, Any]:
    """
    Return the UBO ownership chain for fund_id.

    MOCK=true: returns synthetic data from seed_truth.json.
    MOCK=false: queries ubo_records table.

    Raises:
      ValueError — empty fund_id.
    """
    if not fund_id or not fund_id.strip():
        raise ValueError("fund_id must not be empty")

    if MOCK:
        ubos = _MOCK_UBO_CHAINS.get(fund_id, [])
        return {
            "fund_id": fund_id,
            "fund_name": _FUND_NAMES.get(fund_id),
            "ubos": ubos,
            "unresolved_layers": [u for u in ubos if not u.get("resolved", True)],
            "is_mock": True,
        }

    return _real_ubo_query(fund_id)


def get_shared_counterparties(fund_id: str | None = None) -> dict[str, Any]:
    """
    Return shared counterparty_profiles records (referenced by ≥2 BLEs across
    different Funds). Optionally filtered to counterparties where at least one
    BLE belongs to fund_id.

    MOCK=true: returns data from _MOCK_SHARED_COUNTERPARTIES.
    MOCK=false: queries bles + counterparty_profiles tables.
    """
    if MOCK:
        shared = _MOCK_SHARED_COUNTERPARTIES
        if fund_id:
            shared = [
                cp for cp in shared
                if any(b["fund_id"] == fund_id for b in cp["bles"])
            ]
        return {
            "shared_counterparties": shared,
            "filter_fund_id": fund_id,
            "is_mock": True,
        }

    return _real_shared_query(fund_id)


def _real_ubo_query(fund_id: str) -> dict[str, Any]:
    import psycopg2  # noqa: PLC0415

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL not set")
    conn = psycopg2.connect(db_url)
    try:
        with conn.cursor() as cur:
            # Fund name
            cur.execute("SELECT name FROM funds WHERE fund_id = %s::uuid", (fund_id,))
            row = cur.fetchone()
            fund_name = row[0] if row else None

            cur.execute(
                """
                SELECT ubo_id, ubo_name, ownership_pct, layer_depth,
                       resolved, pep_tier, jurisdiction, parent_ubo_id
                FROM   ubo_records
                WHERE  fund_id = %s::uuid
                ORDER  BY layer_depth, ubo_name
                """,
                (fund_id,),
            )
            rows = cur.fetchall()
        ubos = [
            {
                "ubo_id": str(r[0]),
                "name": r[1],
                "ownership_pct": float(r[2]) if r[2] is not None else None,
                "layer_depth": r[3],
                "resolved": r[4],
                "pep_tier": r[5],
                "jurisdiction": r[6],
                "parent_ubo_id": str(r[7]) if r[7] else None,
            }
            for r in rows
        ]
        return {
            "fund_id": fund_id,
            "fund_name": fund_name,
            "ubos": ubos,
            "unresolved_layers": [u for u in ubos if not u.get("resolved", True)],
            "is_mock": False,
        }
    finally:
        conn.close()


def _real_shared_query(fund_id: str | None) -> dict[str, Any]:
    import psycopg2  # noqa: PLC0415

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL not set")
    conn = psycopg2.connect(db_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT cp.counterparty_id, cp.institution_name, cp.screening_status,
                       b.ble_id, b.parent_fund_id, b.location, f.name
                FROM   counterparty_profiles cp
                JOIN   bles b ON b.counterparty_profile_id = cp.counterparty_id
                JOIN   funds f ON f.fund_id = b.parent_fund_id
                WHERE  cp.counterparty_id IN (
                    SELECT counterparty_profile_id
                    FROM   bles
                    GROUP  BY counterparty_profile_id
                    HAVING COUNT(DISTINCT parent_fund_id) > 1
                )
                ORDER  BY cp.institution_name, f.name
                """
                + (" AND b.parent_fund_id = %s::uuid" if fund_id else ""),
                (fund_id,) if fund_id else (),
            )
            rows = cur.fetchall()

        grouped: dict[str, dict[str, Any]] = {}
        for r in rows:
            cid = str(r[0])
            if cid not in grouped:
                grouped[cid] = {
                    "counterparty_id": cid,
                    "institution_name": r[1],
                    "screening_status": r[2],
                    "bles": [],
                }
            grouped[cid]["bles"].append(
                {
                    "ble_id": str(r[3]),
                    "fund_id": str(r[4]),
                    "fund_name": r[6],
                    "location": r[5],
                }
            )
        return {
            "shared_counterparties": list(grouped.values()),
            "filter_fund_id": fund_id,
            "is_mock": False,
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# MCP dispatch
# ---------------------------------------------------------------------------


def call_tool(name: str, params: dict[str, Any]) -> ToolResult:
    if name == "get_ubo_chain":
        try:
            result = get_ubo_chain(fund_id=params["fund_id"])
            return ToolResult(tool_name=name, params=params, result=result,
                              is_mock=result.get("is_mock", False))
        except ValueError as exc:
            return ToolResult(tool_name=name, params=params, result={},
                              is_mock=MOCK, error=str(exc))

    if name == "get_shared_counterparties":
        result = get_shared_counterparties(fund_id=params.get("fund_id"))
        return ToolResult(tool_name=name, params=params, result=result,
                          is_mock=result.get("is_mock", False))

    raise ValueError(f"Unknown tool: {name!r}. Available: {[t['name'] for t in TOOLS]}")
