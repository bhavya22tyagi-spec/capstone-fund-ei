"""
MCP Tool Server: Audit History — PRD §8.2, §18.

Tool: get_audit_history
  Returns the review audit trail for a Fund or BLE, scoped strictly to the
  requested (scope, scope_id) pair. No cross-scope leakage.

MOCK=true (default): returns synthetic history records keyed by scope_id,
  covering all 5 live Funds and their BLEs.
MOCK=false: queries the review_audit_history table via a psycopg2 connection
  provided by the caller (DATABASE_URL from env). Read-only — no writes.

Static fund guard: static Funds have no AI-generated audit content, but the
  history query itself is safe (read-only, no LLM call). Guard is NOT applied
  here — reading history for a static Fund is permitted; generating narrative
  for one is not. That guard lives in ai_client.py.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from mcp_servers import ToolResult

MOCK: bool = os.getenv("MOCK", "true").lower() == "true"

# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------

TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_audit_history",
        "description": (
            "Retrieve the review audit trail for a Fund or BLE. Returns a list "
            "of audit events (action, actor, notes, timestamp) in reverse "
            "chronological order. Scoped to the specified (scope, scope_id) — "
            "never returns events from a different Fund or BLE."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "enum": ["fund", "ble"],
                    "description": "'fund' for Fund-level history; 'ble' for BLE-level history.",
                },
                "scope_id": {
                    "type": "string",
                    "description": "UUID of the Fund or BLE whose history to retrieve.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of records to return (default 10, max 100).",
                    "default": 10,
                },
            },
            "required": ["scope", "scope_id"],
        },
    }
]


# ---------------------------------------------------------------------------
# Mock database — synthetic audit history for all 5 live Funds + 7 BLEs
# ---------------------------------------------------------------------------

_MOCK_HISTORY: dict[str, list[dict[str, Any]]] = {
    # Fund 1 — Northgate Capital Partners LP
    "f0000001-f000-0000-0000-000000000001": [
        {
            "action": "periodic_review_initiated",
            "actor": "system",
            "notes": "Annual KYB periodic review triggered by scheduler.",
            "performed_at": "2026-05-01T09:00:00+00:00",
        },
        {
            "action": "risk_score_computed",
            "actor": "system",
            "notes": "Fund direct LOW (11.0); escalated to CRITICAL due to Bank Rossiya BLE.",
            "performed_at": "2026-05-01T09:01:00+00:00",
        },
        {
            "action": "reviewer_assigned",
            "actor": "compliance_manager_01",
            "notes": "Assigned to senior compliance analyst for Critical-tier review.",
            "performed_at": "2026-05-01T09:05:00+00:00",
        },
        {
            "action": "narrative_generated",
            "actor": "system",
            "notes": "AI narrative generated for Fund review packet. Pending human acceptance.",
            "performed_at": "2026-05-01T09:10:00+00:00",
        },
        {
            "action": "narrative_accepted",
            "actor": "analyst_jane_doe",
            "notes": "Narrative reviewed and accepted. Proceeding to workflow.",
            "performed_at": "2026-05-02T14:22:00+00:00",
        },
    ],
    # BLE 1 — Northgate x Bank Rossiya
    "b0001001-b000-0000-0000-000000000001": [
        {
            "action": "screening_completed",
            "actor": "system",
            "notes": "OpenSanctions: CONFIRMED sanctions hit. Hard-stop applied. BLE marked Critical.",
            "performed_at": "2026-05-01T09:01:30+00:00",
        },
        {
            "action": "escalation_triggered",
            "actor": "system",
            "notes": "BLE Critical → Fund escalated to Critical (PRD §9.3).",
            "performed_at": "2026-05-01T09:01:45+00:00",
        },
        {
            "action": "workflow_suggested",
            "actor": "system",
            "notes": "Suggested: ble_loan_sanctions_review_v1. Awaiting human decision.",
            "performed_at": "2026-05-01T09:02:00+00:00",
        },
        {
            "action": "workflow_declined",
            "actor": "analyst_jane_doe",
            "notes": "Workflow declined — BLE under legal hold; separate process triggered.",
            "performed_at": "2026-05-03T11:00:00+00:00",
        },
    ],
    # Fund 2 — Meridian Strategic Growth Trust
    "f0000002-f000-0000-0000-000000000002": [
        {
            "action": "document_expiry_detected",
            "actor": "system",
            "notes": "Annual Report expired 2026-05-06. Document_expiry trigger fired.",
            "performed_at": "2026-05-07T08:00:00+00:00",
        },
        {
            "action": "periodic_review_initiated",
            "actor": "system",
            "notes": "Triggered by expired document and UBO resolution gap at layer 2.",
            "performed_at": "2026-05-07T08:01:00+00:00",
        },
        {
            "action": "reviewer_assigned",
            "actor": "compliance_manager_02",
            "notes": "Assigned to mid-tier analyst. MEDIUM risk.",
            "performed_at": "2026-05-07T10:00:00+00:00",
        },
        {
            "action": "document_requested",
            "actor": "analyst_bob_smith",
            "notes": "Requested updated Annual Report (FY2025) from fund administrator.",
            "performed_at": "2026-05-08T09:30:00+00:00",
        },
    ],
    # BLE 2 — Meridian x Deutsche Bank AG
    "b0002001-b000-0000-0000-000000000002": [
        {
            "action": "screening_completed",
            "actor": "system",
            "notes": "OpenSanctions: clean. No matches found.",
            "performed_at": "2026-05-07T08:02:00+00:00",
        },
        {
            "action": "risk_score_computed",
            "actor": "system",
            "notes": "BLE score 1.25 — LOW tier.",
            "performed_at": "2026-05-07T08:02:30+00:00",
        },
    ],
    # BLE 3 — Meridian x DBS Singapore
    "b0002002-b000-0000-0000-000000000003": [
        {
            "action": "screening_completed",
            "actor": "system",
            "notes": "OpenSanctions: clean. Shared counterparty_id with Aldgate BLE (HK) — screened once.",
            "performed_at": "2026-05-07T08:02:00+00:00",
        },
        {
            "action": "risk_score_computed",
            "actor": "system",
            "notes": "BLE score 2.5 — LOW tier.",
            "performed_at": "2026-05-07T08:02:30+00:00",
        },
    ],
    # Fund 3 — Aldgate Street Capital Fund
    "f0000003-f000-0000-0000-000000000003": [
        {
            "action": "periodic_review_completed",
            "actor": "analyst_carol_white",
            "notes": "Annual KYB review completed. No issues. Fund remains LOW tier.",
            "performed_at": "2025-11-15T14:00:00+00:00",
        },
        {
            "action": "next_review_scheduled",
            "actor": "system",
            "notes": "Next periodic review scheduled for 2026-11-15.",
            "performed_at": "2025-11-15T14:01:00+00:00",
        },
    ],
    # BLE 4 — Aldgate x DBS Hong Kong
    "b0003001-b000-0000-0000-000000000004": [
        {
            "action": "screening_completed",
            "actor": "system",
            "notes": "OpenSanctions: clean. Counterparty profile reused from Meridian DBS screening.",
            "performed_at": "2025-11-15T09:00:00+00:00",
        },
    ],
    # Fund 4 — Harrington Private Capital
    "f0000004-f000-0000-0000-000000000004": [
        {
            "action": "pep_flag_noted",
            "actor": "system",
            "notes": "UBO Robert Harrington III — PEP Tier 1 (Former Minister of Finance, Malta). Enhanced due diligence required.",
            "performed_at": "2026-04-10T10:00:00+00:00",
        },
        {
            "action": "document_expiry_warning",
            "actor": "system",
            "notes": "Regulatory Licence expires 2026-07-08 — within 30-day warning window.",
            "performed_at": "2026-06-08T08:00:00+00:00",
        },
        {
            "action": "reviewer_assigned",
            "actor": "compliance_manager_01",
            "notes": "HIGH tier — senior analyst assigned. Licence renewal to be tracked.",
            "performed_at": "2026-06-08T09:00:00+00:00",
        },
    ],
    # BLE 5 — Harrington x Emirates NBD
    "b0004001-b000-0000-0000-000000000005": [
        {
            "action": "pep_contact_noted",
            "actor": "analyst_jane_doe",
            "notes": "Ahmad Al-Rashidi (connected director) — PEP Tier 2, UAE MoF. Noted for EDD.",
            "performed_at": "2026-04-10T10:30:00+00:00",
        },
        {
            "action": "screening_completed",
            "actor": "system",
            "notes": "OpenSanctions: Emirates NBD clean. PEP context recorded separately.",
            "performed_at": "2026-04-10T10:01:00+00:00",
        },
        {
            "action": "risk_score_computed",
            "actor": "system",
            "notes": "BLE score 28.0 — MEDIUM tier (PEP Tier 2 contact + UAE country risk).",
            "performed_at": "2026-04-10T10:02:00+00:00",
        },
    ],
    # Fund 5 — Queensbridge Emerging Markets Fund LP
    "f0000005-f000-0000-0000-000000000005": [
        {
            "action": "onboarding_completed",
            "actor": "analyst_bob_smith",
            "notes": "Initial KYB onboarding completed. LOW tier. All documents verified.",
            "performed_at": "2026-01-20T16:00:00+00:00",
        },
        {
            "action": "next_review_scheduled",
            "actor": "system",
            "notes": "Next periodic review scheduled for 2027-01-20.",
            "performed_at": "2026-01-20T16:01:00+00:00",
        },
    ],
    # BLE 6 — Queensbridge x ICBC Mumbai
    "b0005001-b000-0000-0000-000000000006": [
        {
            "action": "screening_completed",
            "actor": "system",
            "notes": "OpenSanctions: ICBC Limited clean.",
            "performed_at": "2026-01-20T09:00:00+00:00",
        },
        {
            "action": "risk_score_computed",
            "actor": "system",
            "notes": "BLE score 6.25 — LOW tier.",
            "performed_at": "2026-01-20T09:01:00+00:00",
        },
    ],
    # BLE 7 — Queensbridge x Standard Chartered Singapore
    "b0005002-b000-0000-0000-000000000007": [
        {
            "action": "screening_completed",
            "actor": "system",
            "notes": "OpenSanctions: Standard Chartered Bank clean.",
            "performed_at": "2026-01-20T09:00:00+00:00",
        },
        {
            "action": "risk_score_computed",
            "actor": "system",
            "notes": "BLE score 2.5 — LOW tier.",
            "performed_at": "2026-01-20T09:01:00+00:00",
        },
    ],
}


# ---------------------------------------------------------------------------
# Public tool function
# ---------------------------------------------------------------------------


def get_audit_history(
    scope: str,
    scope_id: str,
    limit: int = 10,
) -> dict[str, Any]:
    """
    Return the review audit trail for (scope, scope_id) in reverse
    chronological order (most recent first), capped at limit.

    MOCK=true → synthetic records from _MOCK_HISTORY.
    MOCK=false → reads review_audit_history table (requires DATABASE_URL).

    Raises:
      ValueError — invalid scope, empty scope_id, or limit out of range.
    """
    if scope not in ("fund", "ble"):
        raise ValueError(f"scope must be 'fund' or 'ble', got {scope!r}")
    if not scope_id or not scope_id.strip():
        raise ValueError("scope_id must not be empty")
    limit = max(1, min(limit, 100))

    if MOCK:
        rows = _MOCK_HISTORY.get(scope_id, [])
        # Sort descending by performed_at so most recent is first.
        rows_sorted = sorted(rows, key=lambda r: r["performed_at"], reverse=True)
        return {
            "scope": scope,
            "scope_id": scope_id,
            "history": rows_sorted[:limit],
            "total_available": len(rows),
            "is_mock": True,
        }

    return _real_query(scope, scope_id, limit)


def _real_query(scope: str, scope_id: str, limit: int) -> dict[str, Any]:
    """Query review_audit_history table. Requires DATABASE_URL."""
    import psycopg2  # noqa: PLC0415

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL not set — required for MOCK=false mode")

    conn = psycopg2.connect(db_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT action, actor, notes, performed_at
                FROM   review_audit_history
                WHERE  scope    = %s
                  AND  scope_id = %s::uuid
                ORDER  BY performed_at DESC
                LIMIT  %s
                """,
                (scope, scope_id, limit),
            )
            rows = cur.fetchall()
        history = [
            {
                "action": r[0],
                "actor": r[1],
                "notes": r[2],
                "performed_at": r[3].isoformat() if r[3] else None,
            }
            for r in rows
        ]
        return {
            "scope": scope,
            "scope_id": scope_id,
            "history": history,
            "total_available": len(history),
            "is_mock": False,
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# MCP dispatch
# ---------------------------------------------------------------------------


def call_tool(name: str, params: dict[str, Any]) -> ToolResult:
    if name == "get_audit_history":
        try:
            result = get_audit_history(
                scope=params["scope"],
                scope_id=params["scope_id"],
                limit=int(params.get("limit", 10)),
            )
            return ToolResult(
                tool_name=name,
                params=params,
                result=result,
                is_mock=result.get("is_mock", False),
            )
        except ValueError as exc:
            return ToolResult(
                tool_name=name,
                params=params,
                result={},
                is_mock=MOCK,
                error=str(exc),
            )
    raise ValueError(f"Unknown tool: {name!r}. Available: {[t['name'] for t in TOOLS]}")
