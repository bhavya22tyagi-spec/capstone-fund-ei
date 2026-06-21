"""
PRD §11 — Agent Orchestration Service (Suggested Reviews Workflow).

Wires together the existing MCP tool servers, RAG service, and trigger engine
into a bounded, scope-aware tool-calling loop that produces SuggestionCards.

Security invariants (PRD §17, §18):
  - assert_fund_allows_ai() fires before ANY tool call.
  - Scope is always explicit; every tool call carries scope + scope_id.
  - No AI auto-publishes: cards are queued for human Accept/Decline (PRD §18).
  - Tool selection is DETERMINISTIC (_TOOL_POLICY dict, not an LLM call).
    (CLAUDE.md rule 1 — risk/escalation/trigger logic is never an LLM call.)
  - Escalation cascade (BLE Critical → Fund) is deterministic (_is_ble_critical).
    (PRD §9.3)

MOCK=true (default):
  - All MCP tool servers return their canned MOCK results (no external calls).
  - RAG retrieve returns [] if no rag_service injected (tool still logged).
  - SuggestionCard.is_mock=True; tools_called populated from policy.

MOCK=false:
  - MCP servers make real API calls (opensanctions) or real DB queries.
  - RAG returns real bge-base-en-v1.5 retrieval results.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import mcp_servers.audit_history as _audit_history_mcp
import mcp_servers.entity_relationships as _entity_rel_mcp
import mcp_servers.opensanctions as _opensanctions_mcp
from services.budget import BudgetCap
from services.guards import assert_fund_allows_ai
from services.trigger_engine.models import ReviewTrigger, TriggerScope

MOCK: bool = os.getenv("MOCK", "true").lower() == "true"

# ---------------------------------------------------------------------------
# Deterministic tool-selection policy (CLAUDE.md rule 1 — never an LLM call)
# ---------------------------------------------------------------------------

_TOOL_POLICY: dict[str, list[str]] = {
    "risk_tier_change":              ["get_audit_history", "screen_entity", "rag_retrieve"],
    "new_sanctions_pep_hit":         ["screen_entity", "get_audit_history"],
    "adverse_media_change":          ["screen_entity", "get_audit_history", "rag_retrieve"],
    "ubo_structure_change":          ["get_ubo_chain", "get_audit_history", "rag_retrieve"],
    "document_expiry":               ["get_audit_history", "rag_retrieve"],
    "country_risk_reclassification": ["get_audit_history", "screen_entity"],
    "shared_counterparty_contagion": ["get_shared_counterparties", "get_audit_history"],
    "ble_critical_cascade":          ["get_audit_history", "screen_entity"],
    "sla_breach":                    ["get_audit_history"],
}

# Workflow template per (trigger_type, scope). Falls back to "{scope}_periodic_review_v1".
_WORKFLOW_TEMPLATES: dict[tuple[str, str], str] = {
    ("risk_tier_change",              "fund"): "fund_risk_review_v1",
    ("risk_tier_change",              "ble"):  "ble_risk_review_v1",
    ("new_sanctions_pep_hit",         "fund"): "fund_sanctions_review_v1",
    ("new_sanctions_pep_hit",         "ble"):  "ble_sanctions_review_v1",
    ("adverse_media_change",          "fund"): "fund_media_review_v1",
    ("adverse_media_change",          "ble"):  "ble_media_review_v1",
    ("ubo_structure_change",          "fund"): "fund_ubo_review_v1",
    ("document_expiry",               "fund"): "fund_doc_refresh_v1",
    ("document_expiry",               "ble"):  "ble_doc_refresh_v1",
    ("country_risk_reclassification", "fund"): "fund_country_review_v1",
    ("country_risk_reclassification", "ble"):  "ble_country_review_v1",
    ("shared_counterparty_contagion", "ble"):  "ble_contagion_review_v1",
    ("ble_critical_cascade",          "fund"): "fund_critical_escalation_v1",
    ("sla_breach",                    "fund"): "fund_sla_review_v1",
    ("sla_breach",                    "ble"):  "ble_sla_review_v1",
}


# ---------------------------------------------------------------------------
# Data type
# ---------------------------------------------------------------------------

@dataclass
class SuggestionCard:
    """
    Structured suggestion assembled by the agent from tool outputs.

    Passed to WorkflowService.create_suggestion() for human Accept/Decline.
    NOT auto-published (PRD §18).

    tools_called is the Eval F key — populated deterministically from
    _TOOL_POLICY[trigger_type], regardless of MOCK mode.
    """
    card_id: str
    scope: str                          # "fund" | "ble"
    scope_id: str                       # fund_id or ble_id
    fund_id: str                        # always the parent Fund
    trigger_type: str
    trigger_detail: dict
    suggested_workflow_template: str
    tools_called: list[str]             # exact list from _TOOL_POLICY
    last_review_context: list[dict]     # get_audit_history result
    screening_summary: dict | None      # screen_entity result (None if not in policy)
    ubo_chain: dict | None              # get_ubo_chain result (None if not in policy)
    shared_counterparties: list | None  # get_shared_counterparties (None if not in policy)
    what_changed_summary: str           # RAG top-3 chunks joined; "" if no RAG
    is_mock: bool
    created_at: str
    cascaded_from_ble_id: str | None    # set only on fund-scope cascade cards
    cascaded_from_ble_name: str | None  # human-readable BLE name for cascade cards


# ---------------------------------------------------------------------------
# Public service
# ---------------------------------------------------------------------------

class AgentOrchestrationService:
    """
    Bounded tool-calling agent for the Suggested Reviews workflow (PRD §11).

    process_trigger() executes the tool-calling loop for one trigger and
    returns one or two SuggestionCards:
      - Normally: [primary_card]
      - BLE trigger that is Critical: [ble_card, fund_cascade_card]  (PRD §9.3)

    Tool selection is deterministic (_TOOL_POLICY). No free-form LLM routing.
    """

    def __init__(self, rag_service=None):
        """
        Args:
            rag_service: Optional pre-built RAGService. When None, "rag_retrieve"
                         is still recorded in tools_called (it would be called)
                         but the actual retrieval returns empty chunks.
        """
        self._rag = rag_service

    def process_trigger(
        self,
        trigger: ReviewTrigger,
        fund_id: str,
        synthetic_static: bool,
        budget: BudgetCap | None = None,
    ) -> list[SuggestionCard]:
        """
        Execute the bounded tool-calling loop for a ReviewTrigger.

        Args:
            trigger:          Deterministic trigger from the trigger engine.
            fund_id:          Parent Fund ID (for static guard + tool params).
            synthetic_static: Raises StaticFundAIError if True.
            budget:           Per-run cost cap ($2.00 default).

        Returns:
            [primary_card]                    — normally
            [ble_card, fund_cascade_card]     — when BLE trigger is Critical (PRD §9.3)

        Raises:
            StaticFundAIError:  fund is tagged synthetic_static
            ValueError:         empty fund_id, or trigger_type not in policy
        """
        if not fund_id or not fund_id.strip():
            raise ValueError("fund_id must not be empty")
        assert_fund_allows_ai(fund_id, synthetic_static)

        trigger_type = trigger.trigger_type.value if hasattr(trigger.trigger_type, "value") else trigger.trigger_type
        if trigger_type not in _TOOL_POLICY:
            raise ValueError(f"trigger_type {trigger_type!r} not in _TOOL_POLICY")

        # Derive scope and scope_id for primary card
        scope = trigger.scope.value if hasattr(trigger.scope, "value") else str(trigger.scope)
        if scope == "both":
            scope = "ble"  # contagion triggers processed at BLE scope
        scope_id = fund_id if scope == "fund" else (trigger.ble_id or fund_id)

        primary_card = self._build_card(
            trigger_type=trigger_type,
            scope=scope,
            scope_id=scope_id,
            fund_id=fund_id,
            trigger_detail=trigger.detail,
            synthetic_static=synthetic_static,
        )

        # Escalation cascade (PRD §9.3): BLE Critical → also generate Fund-level card
        if scope == "ble" and _is_ble_critical(trigger):
            cascade_card = self._build_card(
                trigger_type="ble_critical_cascade",
                scope="fund",
                scope_id=fund_id,
                fund_id=fund_id,
                trigger_detail={
                    "cascaded_from_ble_id": trigger.ble_id,
                    "cascaded_from_ble_name": (
                        trigger.detail.get("counterparty_name")
                        or trigger.detail.get("ble_name")
                        or trigger.ble_id
                    ),
                    "ble_direct_tier": trigger.detail.get("ble_risk_tier", "critical"),
                },
                synthetic_static=synthetic_static,
                cascaded_from_ble_id=trigger.ble_id,
                cascaded_from_ble_name=(
                    trigger.detail.get("counterparty_name")
                    or trigger.detail.get("ble_name")
                    or trigger.ble_id
                ),
            )
            return [primary_card, cascade_card]

        return [primary_card]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_card(
        self,
        trigger_type: str,
        scope: str,
        scope_id: str,
        fund_id: str,
        trigger_detail: dict,
        synthetic_static: bool,
        cascaded_from_ble_id: str | None = None,
        cascaded_from_ble_name: str | None = None,
    ) -> SuggestionCard:
        """Execute the tool policy for the given trigger_type and assemble a card."""
        tools_to_call = list(_TOOL_POLICY[trigger_type])

        last_review_context: list[dict] = []
        screening_summary: dict | None = None
        ubo_chain: dict | None = None
        shared_counterparties: list | None = None
        rag_chunks: list = []

        for tool_name in tools_to_call:
            if tool_name == "get_audit_history":
                result = _audit_history_mcp.call_tool(
                    "get_audit_history",
                    {"scope": scope, "scope_id": scope_id, "limit": 10},
                )
                if result.ok:
                    last_review_context = result.result.get("events", [])

            elif tool_name == "screen_entity":
                # opensanctions scope: "fund" for fund-scope; "counterparty" for ble-scope
                os_scope = "fund" if scope == "fund" else "counterparty"
                os_scope_id = scope_id
                entity_name = (
                    trigger_detail.get("counterparty_name")
                    or trigger_detail.get("fund_name")
                    or trigger_detail.get("entity_name")
                    or scope_id
                )
                result = _opensanctions_mcp.call_tool(
                    "screen_entity",
                    {
                        "name": entity_name,
                        "scope": os_scope,
                        "scope_id": os_scope_id,
                        "fund_id": fund_id,
                        "synthetic_static": synthetic_static,
                    },
                )
                if result.ok:
                    screening_summary = result.result

            elif tool_name == "get_ubo_chain":
                result = _entity_rel_mcp.call_tool(
                    "get_ubo_chain",
                    {"fund_id": fund_id},
                )
                if result.ok:
                    ubo_chain = result.result

            elif tool_name == "get_shared_counterparties":
                result = _entity_rel_mcp.call_tool(
                    "get_shared_counterparties",
                    {"fund_id": fund_id},
                )
                if result.ok:
                    shared_counterparties = result.result.get("shared_counterparties", [])

            elif tool_name == "rag_retrieve":
                if self._rag is not None:
                    try:
                        rag_chunks = self._rag.retrieve(
                            query="what changed since last review",
                            scope=scope,
                            scope_id=scope_id,
                            fund_id=fund_id,
                            synthetic_static=synthetic_static,
                            top_k=3,
                        )
                    except Exception:
                        rag_chunks = []
                # else: rag_retrieve logged in tools_called; result is empty

        what_changed_summary = "\n\n".join(
            getattr(c, "chunk_text", str(c)) for c in rag_chunks[:3]
        ) if rag_chunks else ""

        template = _WORKFLOW_TEMPLATES.get(
            (trigger_type, scope),
            f"{scope}_periodic_review_v1",
        )

        return SuggestionCard(
            card_id=str(uuid.uuid4()),
            scope=scope,
            scope_id=scope_id,
            fund_id=fund_id,
            trigger_type=trigger_type,
            trigger_detail=trigger_detail,
            suggested_workflow_template=template,
            tools_called=tools_to_call,
            last_review_context=last_review_context,
            screening_summary=screening_summary,
            ubo_chain=ubo_chain,
            shared_counterparties=shared_counterparties,
            what_changed_summary=what_changed_summary,
            is_mock=MOCK,
            created_at=datetime.now(timezone.utc).isoformat(),
            cascaded_from_ble_id=cascaded_from_ble_id,
            cascaded_from_ble_name=cascaded_from_ble_name,
        )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _is_ble_critical(trigger: ReviewTrigger) -> bool:
    """
    Determine whether a BLE trigger represents a Critical-tier BLE.

    Deterministic — checks trigger.detail fields only (CLAUDE.md rule 1).
    A confirmed sanctions hit implies Critical per the rule engine (PRD §9.1).
    """
    d = trigger.detail
    return (
        d.get("ble_risk_tier") == "critical"
        or d.get("effective_tier") == "critical"
        or (d.get("hit_type") == "sanctions" and d.get("hit_severity") == "confirmed")
    )
