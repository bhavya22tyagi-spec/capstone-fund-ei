"""
Tests for WorkflowService (services/workflow/service.py).

All tests run in MOCK mode. Each test creates a fresh WorkflowService instance
(instance-scoped state — no module-level dict to leak between tests).
"""

from __future__ import annotations

import os
import pytest

os.environ.setdefault("MOCK", "true")

from services.workflow.service import (
    MOCK,
    AuditLogEntry,
    WorkflowService,
    WorkflowSuggestion,
)
from services.agent.service import (
    AgentOrchestrationService,
    SuggestionCard,
    _TOOL_POLICY,
)
from services.trigger_engine.models import ReviewTrigger, TriggerScope, TriggerType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

F1_FUND_ID = "f0000001-f000-0000-0000-000000000001"
B11_BLE_ID = "b0001001-b000-0000-0000-000000000001"


def _make_card(
    scope: str = "fund",
    scope_id: str = F1_FUND_ID,
    fund_id: str = F1_FUND_ID,
    trigger_type: str = "document_expiry",
) -> SuggestionCard:
    """Build a minimal SuggestionCard via the agent service."""
    svc = AgentOrchestrationService()
    trigger = ReviewTrigger(
        trigger_type=TriggerType(trigger_type),
        scope=TriggerScope(scope),
        fund_id=fund_id,
        ble_id=scope_id if scope == "ble" else None,
        detail={},
    )
    cards = svc.process_trigger(trigger=trigger, fund_id=fund_id, synthetic_static=False)
    return cards[0]


@pytest.fixture()
def wf() -> WorkflowService:
    return WorkflowService()


@pytest.fixture()
def pending_card() -> SuggestionCard:
    return _make_card()


@pytest.fixture()
def pending_suggestion(wf, pending_card) -> WorkflowSuggestion:
    return wf.create_suggestion(pending_card)


# ===========================================================================
# Section 1 — create_suggestion
# ===========================================================================

def test_create_suggestion_returns_workflow_suggestion(wf, pending_card):
    result = wf.create_suggestion(pending_card)
    assert isinstance(result, WorkflowSuggestion)


def test_create_suggestion_status_pending(wf, pending_card):
    result = wf.create_suggestion(pending_card)
    assert result.status == "pending"


def test_create_suggestion_scope_matches_card(wf, pending_card):
    result = wf.create_suggestion(pending_card)
    assert result.scope == pending_card.scope
    assert result.scope_id == pending_card.scope_id


def test_create_suggestion_appears_in_pending_list(wf, pending_card):
    s = wf.create_suggestion(pending_card)
    pending = wf.get_pending_suggestions()
    ids = {p.suggestion_id for p in pending}
    assert s.suggestion_id in ids


# ===========================================================================
# Section 2 — accept_suggestion
# ===========================================================================

def test_accept_suggestion_returns_audit_log_entry(wf, pending_suggestion):
    entry = wf.accept_suggestion(pending_suggestion.suggestion_id, actor="analyst@example.com")
    assert isinstance(entry, AuditLogEntry)


def test_accept_suggestion_action_is_accept(wf, pending_suggestion):
    entry = wf.accept_suggestion(pending_suggestion.suggestion_id, actor="analyst@example.com")
    assert entry.action == "accept_suggestion"


def test_accept_suggestion_status_changes_to_accepted(wf, pending_suggestion):
    wf.accept_suggestion(pending_suggestion.suggestion_id, actor="analyst@example.com")
    assert pending_suggestion.status == "accepted"


def test_accept_suggestion_actor_recorded(wf, pending_suggestion):
    entry = wf.accept_suggestion(pending_suggestion.suggestion_id, actor="analyst@example.com")
    assert entry.actor == "analyst@example.com"


def test_accept_suggestion_resolved_by_set(wf, pending_suggestion):
    wf.accept_suggestion(pending_suggestion.suggestion_id, actor="analyst@example.com")
    assert pending_suggestion.resolved_by == "analyst@example.com"


# ===========================================================================
# Section 3 — decline_suggestion
# ===========================================================================

def test_decline_suggestion_returns_audit_log_entry(wf, pending_suggestion):
    entry = wf.decline_suggestion(pending_suggestion.suggestion_id, actor="analyst@example.com")
    assert isinstance(entry, AuditLogEntry)


def test_decline_suggestion_action_is_decline(wf, pending_suggestion):
    entry = wf.decline_suggestion(pending_suggestion.suggestion_id, actor="analyst@example.com")
    assert entry.action == "decline_suggestion"


def test_decline_suggestion_status_changes_to_declined(wf, pending_suggestion):
    wf.decline_suggestion(pending_suggestion.suggestion_id, actor="analyst@example.com",
                          notes="Out of scope for current review cycle")
    assert pending_suggestion.status == "declined"


def test_decline_suggestion_notes_preserved(wf, pending_suggestion):
    entry = wf.decline_suggestion(pending_suggestion.suggestion_id, actor="analyst@example.com",
                                  notes="Threshold not met")
    assert entry.notes == "Threshold not met"


# ===========================================================================
# Section 4 — bulk operations
# ===========================================================================

def test_bulk_accept_returns_n_entries(wf):
    cards = [_make_card() for _ in range(3)]
    suggestions = [wf.create_suggestion(c) for c in cards]
    ids = [s.suggestion_id for s in suggestions]
    entries = wf.bulk_accept(ids, actor="bulk-analyst@example.com")
    assert len(entries) == 3


def test_bulk_accept_all_accepted(wf):
    cards = [_make_card() for _ in range(2)]
    suggestions = [wf.create_suggestion(c) for c in cards]
    ids = [s.suggestion_id for s in suggestions]
    wf.bulk_accept(ids, actor="analyst@example.com")
    for s in suggestions:
        assert s.status == "accepted"


def test_bulk_decline_all_declined(wf):
    cards = [_make_card() for _ in range(2)]
    suggestions = [wf.create_suggestion(c) for c in cards]
    ids = [s.suggestion_id for s in suggestions]
    wf.bulk_decline(ids, actor="analyst@example.com")
    for s in suggestions:
        assert s.status == "declined"


# ===========================================================================
# Section 5 — audit invariants (PRD §18)
# ===========================================================================

def test_accept_non_pending_raises_value_error(wf, pending_suggestion):
    wf.accept_suggestion(pending_suggestion.suggestion_id, actor="a@b.com")
    with pytest.raises(ValueError, match="not 'pending'"):
        wf.accept_suggestion(pending_suggestion.suggestion_id, actor="a@b.com")


def test_decline_non_pending_raises_value_error(wf, pending_suggestion):
    wf.decline_suggestion(pending_suggestion.suggestion_id, actor="a@b.com")
    with pytest.raises(ValueError, match="not 'pending'"):
        wf.decline_suggestion(pending_suggestion.suggestion_id, actor="a@b.com")


def test_all_decisions_appear_in_audit_log(wf):
    card1 = _make_card()
    card2 = _make_card()
    s1 = wf.create_suggestion(card1)
    s2 = wf.create_suggestion(card2)
    wf.accept_suggestion(s1.suggestion_id, actor="a@b.com")
    wf.decline_suggestion(s2.suggestion_id, actor="b@c.com", notes="Not applicable")
    log = wf.get_audit_log()
    actions = {e.action for e in log}
    assert "accept_suggestion" in actions
    assert "decline_suggestion" in actions
    assert len(log) == 2


def test_not_found_suggestion_raises_value_error(wf):
    with pytest.raises(ValueError, match="not found"):
        wf.accept_suggestion("00000000-0000-0000-0000-000000000000", actor="a@b.com")


# ===========================================================================
# Section 6 — cascade suggestion
# ===========================================================================

def test_cascade_card_creates_suggestion_with_cascade_info(wf):
    agent = AgentOrchestrationService()
    trigger = ReviewTrigger(
        trigger_type=TriggerType.NEW_SANCTIONS_PEP_HIT,
        scope=TriggerScope.BLE,
        fund_id=F1_FUND_ID,
        ble_id=B11_BLE_ID,
        detail={
            "hit_type": "sanctions",
            "hit_severity": "confirmed",
            "counterparty_name": "Bank Rossiya",
            "ble_risk_tier": "critical",
        },
    )
    cards = agent.process_trigger(trigger=trigger, fund_id=F1_FUND_ID, synthetic_static=False)
    cascade_card = cards[1]
    cascade_suggestion = wf.create_suggestion(cascade_card)
    assert cascade_suggestion.cascade_info is not None
    assert cascade_suggestion.cascade_info["from_ble_id"] == B11_BLE_ID
