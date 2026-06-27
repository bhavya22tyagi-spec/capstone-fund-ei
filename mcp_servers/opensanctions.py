"""
MCP Tool Server: OpenSanctions screening — PRD §8.2, §7, §17.

Tool: screen_entity
  Screens a named entity (Fund UBO or BLE counterparty) against the
  OpenSanctions database. The same API is used for both scopes — scope is
  metadata on the result, not a routing decision.

Reuse rule (PRD §17): callers are responsible for counterparty profile reuse.
  This server is stateless per call. It never knows whether the same
  counterparty_id has been screened before; that guard lives in seed_data.py
  and (Phase 5+) the Ingestion Service.

Static fund guard (CLAUDE.md rule 10): raises StaticFundAIError if
  synthetic_static=True. Static Funds must not trigger any external call.

MOCK=true (default): returns canned results for the 6 live-fund counterparties
  and a safe "clean" default for any unknown name.
MOCK=false: makes a real free-tier GET to api.opensanctions.org. No API key
  required for free tier, but OPENSANCTIONS_API_KEY is used if set.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import requests

from mcp_servers import ToolResult
from services.guards import StaticFundAIError, assert_fund_allows_ai

MOCK: bool = os.getenv("MOCK", "true").lower() == "true"

_API_URL = "https://api.opensanctions.org/search/default"
_API_TIMEOUT = 10  # seconds
_MIN_SCORE = 0.6   # ignore low-confidence matches

# ---------------------------------------------------------------------------
# Tool definition (Anthropic tool_use / MCP schema format)
# ---------------------------------------------------------------------------

TOOLS: list[dict[str, Any]] = [
    {
        "name": "screen_entity",
        "description": (
            "Screen a named entity against the OpenSanctions database for "
            "sanctions, PEP status, and adverse media. Used for both Fund-level "
            "UBO screening (scope='fund') and BLE counterparty screening "
            "(scope='counterparty'). Returns result_status, hit_severity, "
            "hit_type, and the raw API payload."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Full legal name of the entity or individual to screen.",
                },
                "scope": {
                    "type": "string",
                    "enum": ["fund", "counterparty"],
                    "description": (
                        "'fund' when screening a Fund entity or its UBOs; "
                        "'counterparty' when screening a BLE counterparty profile."
                    ),
                },
                "scope_id": {
                    "type": "string",
                    "description": "UUID of the Fund (scope='fund') or counterparty_profiles record (scope='counterparty') being screened.",
                },
                "fund_id": {
                    "type": "string",
                    "description": "UUID of the parent Fund. Used to enforce the static-fund guard.",
                },
                "synthetic_static": {
                    "type": "boolean",
                    "description": "Must be False. Static demo Funds are physically incapable of triggering any external call.",
                },
            },
            "required": ["name", "scope", "scope_id", "fund_id", "synthetic_static"],
        },
    }
]


# ---------------------------------------------------------------------------
# Mock database — canned results for all 6 live-fund counterparties + fund UBOs
# ---------------------------------------------------------------------------

# Keyed by screened name (case-sensitive, exactly as queried in seed_truth.json).
_MOCK_DB: dict[str, dict[str, Any]] = {
    "Bank Rossiya": {
        "result_status": "hit",
        "hit_severity": "confirmed",
        "hit_type": "sanctions",
        "match_name": "Bank Rossiya",
        "match_schema": "Company",
        "datasets": ["us_ofac_sdn", "eu_sanctions"],
    },
    "Deutsche Bank AG": {
        "result_status": "clean",
        "hit_severity": "none",
        "hit_type": None,
    },
    "DBS Bank Ltd": {
        "result_status": "clean",
        "hit_severity": "none",
        "hit_type": None,
    },
    "Emirates NBD Bank PJSC": {
        "result_status": "clean",
        "hit_severity": "none",
        "hit_type": None,
    },
    "ICBC Limited": {
        "result_status": "clean",
        "hit_severity": "none",
        "hit_type": None,
    },
    "Standard Chartered Bank": {
        "result_status": "clean",
        "hit_severity": "none",
        "hit_type": None,
    },
    # Fund UBOs (for scope='fund' calls)
    "John Richardson": {
        "result_status": "clean",
        "hit_severity": "none",
        "hit_type": None,
    },
    "Cayman Ventures Ltd": {
        "result_status": "clean",
        "hit_severity": "none",
        "hit_type": None,
    },
    "Meridian Holdings Ltd": {
        "result_status": "clean",
        "hit_severity": "none",
        "hit_type": None,
    },
    "EU Capital Partners SA": {
        "result_status": "clean",
        "hit_severity": "none",
        "hit_type": None,
    },
    "Werner Mueller": {
        "result_status": "clean",
        "hit_severity": "none",
        "hit_type": None,
    },
    "Patrick O'Brien": {
        "result_status": "clean",
        "hit_severity": "none",
        "hit_type": None,
    },
    "Robert Harrington III": {
        # Synthetic adverse media flag — not a real OpenSanctions hit.
        "result_status": "hit",
        "hit_severity": "low",
        "hit_type": "adverse",
        "match_name": "Robert Harrington",
        "match_schema": "Person",
        "datasets": ["adverse_media_synthetic"],
    },
    "HAP Holding Ltd": {
        "result_status": "clean",
        "hit_severity": "none",
        "hit_type": None,
    },
    "Sarah Chen": {
        "result_status": "clean",
        "hit_severity": "none",
        "hit_type": None,
    },
    "Queensbridge Asset Management Ltd": {
        "result_status": "clean",
        "hit_severity": "none",
        "hit_type": None,
    },
    "James Wentworth": {
        "result_status": "clean",
        "hit_severity": "none",
        "hit_type": None,
    },
    "Victoria Forsythe": {
        "result_status": "clean",
        "hit_severity": "none",
        "hit_type": None,
    },
}

_CLEAN_DEFAULT: dict[str, Any] = {
    "result_status": "clean",
    "hit_severity": "none",
    "hit_type": None,
}


# ---------------------------------------------------------------------------
# Public tool function
# ---------------------------------------------------------------------------


def screen_entity(
    name: str,
    scope: str,
    scope_id: str,
    fund_id: str,
    synthetic_static: bool,
) -> dict[str, Any]:
    """
    Screen an entity or individual against OpenSanctions.

    Returns a result dict with at minimum:
      result_status   'clean' | 'hit' | 'error'
      hit_severity    'none' | 'low' | 'medium' | 'high' | 'confirmed'
      hit_type        'sanctions' | 'pep' | 'adverse' | None
      scope           as passed in
      scope_id        as passed in
      screened_name   as passed in
      is_mock         bool
      screened_at     ISO-8601 UTC timestamp

    Raises:
      ValueError          — empty name or invalid scope
      StaticFundAIError   — fund is synthetic_static (no external calls allowed)
    """
    if not name or not name.strip():
        raise ValueError("name must not be empty")
    if scope not in ("fund", "counterparty"):
        raise ValueError(f"scope must be 'fund' or 'counterparty', got {scope!r}")

    # Static fund guard — matches same pattern as ai_client.py (CLAUDE.md rule 10).
    assert_fund_allows_ai(fund_id, synthetic_static)

    ts = datetime.now(timezone.utc).isoformat()

    if MOCK:
        hit = _MOCK_DB.get(name.strip(), _CLEAN_DEFAULT)
        return {
            **hit,
            "screened_name": name,
            "scope": scope,
            "scope_id": scope_id,
            "is_mock": True,
            "screened_at": ts,
            "raw_result": {"mock": True, "name_queried": name},
        }

    return _real_screen(name.strip(), scope, scope_id, ts)


def _real_screen(name: str, scope: str, scope_id: str, ts: str) -> dict[str, Any]:
    """Make a live free-tier OpenSanctions API call."""
    headers: dict[str, str] = {}
    api_key = os.getenv("OPENSANCTIONS_API_KEY", "")
    if api_key:
        headers["Authorization"] = f"ApiKey {api_key}"

    try:
        resp = requests.get(
            _API_URL,
            params={"q": name, "schema": "LegalEntity", "limit": 5},
            headers=headers,
            timeout=_API_TIMEOUT,
        )
        if resp.status_code in (401, 403):
            return {
                "result_status": "error",
                "hit_severity": "none",
                "hit_type": None,
                "screened_name": name,
                "scope": scope,
                "scope_id": scope_id,
                "is_mock": False,
                "screened_at": ts,
                "raw_result": {"error": f"http_{resp.status_code}"},
            }
        resp.raise_for_status()
        parsed = _parse_response(name, resp.json())
    except requests.exceptions.RequestException as exc:
        return {
            "result_status": "error",
            "hit_severity": "none",
            "hit_type": None,
            "screened_name": name,
            "scope": scope,
            "scope_id": scope_id,
            "is_mock": False,
            "screened_at": ts,
            "raw_result": {"error": str(exc)},
        }

    return {
        **parsed,
        "screened_name": name,
        "scope": scope,
        "scope_id": scope_id,
        "is_mock": False,
        "screened_at": ts,
    }


def _parse_response(name: str, data: dict[str, Any]) -> dict[str, Any]:
    """Parse raw OpenSanctions API response into a normalised result dict."""
    results = data.get("results", [])
    if not results:
        return {"result_status": "clean", "hit_severity": "none", "hit_type": None, "raw_result": data}

    top = results[0]
    score = top.get("score", 0)
    print(f"[OpenSanctions] query={name!r} top_match={top.get('caption')!r} score={score} topics={top.get('properties',{}).get('topics',[])} threshold={_MIN_SCORE}")
    if score < _MIN_SCORE:
        return {"result_status": "clean", "hit_severity": "none", "hit_type": None, "raw_result": data}

    topics = top.get("properties", {}).get("topics", [])
    if "sanction" in topics or "sanction.linked" in topics:
        sev = "confirmed" if score >= 0.9 else "high"
        hit_type = "sanctions"
    elif "role.pep" in topics or "role.rca" in topics:
        sev = "high" if score >= 0.9 else "medium"
        hit_type = "pep"
    else:
        sev = "medium" if score >= 0.9 else "low"
        hit_type = "adverse"

    return {
        "result_status": "hit",
        "hit_severity": sev,
        "hit_type": hit_type,
        "match_name": top.get("caption", name),
        "match_schema": top.get("schema", ""),
        "datasets": top.get("datasets", []),
        "raw_result": data,
    }


# ---------------------------------------------------------------------------
# MCP dispatch
# ---------------------------------------------------------------------------


def call_tool(name: str, params: dict[str, Any]) -> ToolResult:
    """Dispatch an MCP tool call. Called by the agent orchestration layer."""
    if name == "screen_entity":
        try:
            result = screen_entity(
                name=params["name"],
                scope=params["scope"],
                scope_id=params["scope_id"],
                fund_id=params["fund_id"],
                synthetic_static=params["synthetic_static"],
            )
            return ToolResult(
                tool_name=name,
                params=params,
                result=result,
                is_mock=result.get("is_mock", False),
            )
        except (ValueError, StaticFundAIError) as exc:
            return ToolResult(
                tool_name=name,
                params=params,
                result={},
                is_mock=MOCK,
                error=str(exc),
            )
    raise ValueError(f"Unknown tool: {name!r}. Available: {[t['name'] for t in TOOLS]}")
