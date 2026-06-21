"""
Tests for AgentOrchestrationService (services/agent/service.py).

All tests run in MOCK mode — no LLM call, no external API, no DB required.
The MCP servers run in MOCK mode and return canned results.
"""

from __future__ import annotations

import os
import pytest

os.environ.setdefault("MOCK", "true")

from services.agent.service import (
    MOCK,
    AgentOrchestrationService,
    SuggestionCard,
    _TOOL_POLICY,
    _WORKFLOW_TEMPLATES,
    _is_ble_critical,
)
from services.budget import BudgetCap
from services.guards import StaticFundAIError
from services.trigger_engine.models import ReviewTrigger, TriggerScope, TriggerType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def svc() -> AgentOrchestrationService:
    return AgentOrchestrationService()


@pytest.fixture()
def budget() -> BudgetCap:
    return BudgetCap(limit_usd=5.0)


F1_FUND_ID = "f0000001-f000-0000-0000-000000000001"
F2_FUND_ID = "f0000002-f000-0000-0000-000000000002"
F4_FUND_ID = "f0000004-f000-0000-0000-000000000004"
B11_BLE_ID = "b0001001-b000-0000-0000-000000000001"
B21_BLE_ID = "b0002001-b000-0000-0000-000000000002"
B51_BLE_ID = "b0005001-b000-0000-0000-000000000006"


def _make_trigger(
    trigger_type: str,
    scope: str,
    fund_id: str,
    ble_id: str | None = None,
    detail: dict | None = None,
) -> ReviewTrigger:
    return ReviewTrigger(
        trigger_type=TriggerType(trigger_type),
        scope=TriggerScope(scope),
        fund_id=fund_id,
        ble_id=ble_id,
        detail=detail or {},
    )


# ===========================================================================
# Section 1 — MOCK flag
# ===========================================================================

def test_mock_flag_is_bool():
    assert isinstance(MOCK, bool)


def test_mock_flag_default_true():
    assert MOCK is True


# ===========================================================================
# Section 2 — _TOOL_POLICY completeness
# ===========================================================================

def test_tool_policy_has_all_9_trigger_types():
    expected_keys = {
        "risk_tier_change", "new_sanctions_pep_hit", "adverse_media_change",
        "ubo_structure_change", "document_expiry", "country_risk_reclassification",
        "shared_counterparty_contagion", "ble_critical_cascade", "sla_breach",
    }
    assert set(_TOOL_POLICY.keys()) == expected_keys


def test_tool_policy_no_empty_lists():
    for trigger_type, tools in _TOOL_POLICY.items():
        assert len(tools) > 0, f"{trigger_type!r} maps to empty tool list"


def test_tool_policy_all_values_are_lists_of_strings():
    for trigger_type, tools in _TOOL_POLICY.items():
        assert isinstance(tools, list)
        for t in tools:
            assert isinstance(t, str)


def test_tool_policy_sla_breach_only_audit_history():
    assert _TOOL_POLICY["sla_breach"] == ["get_audit_history"]


# ===========================================================================
# Section 3 — process_trigger() basics
# ===========================================================================

def test_process_trigger_returns_list(svc):
    trigger = _make_trigger("document_expiry", "fund", F2_FUND_ID)
    result = svc.process_trigger(trigger=trigger, fund_id=F2_FUND_ID, synthetic_static=False)
    assert isinstance(result, list)


def test_process_trigger_non_empty(svc):
    trigger = _make_trigger("document_expiry", "fund", F2_FUND_ID)
    result = svc.process_trigger(trigger=trigger, fund_id=F2_FUND_ID, synthetic_static=False)
    assert len(result) >= 1


def test_process_trigger_all_suggestion_cards(svc):
    trigger = _make_trigger("document_expiry", "fund", F2_FUND_ID)
    result = svc.process_trigger(trigger=trigger, fund_id=F2_FUND_ID, synthetic_static=False)
    for card in result:
        assert isinstance(card, SuggestionCard)


def test_process_trigger_scope_correct_fund(svc):
    trigger = _make_trigger("risk_tier_change", "fund", F4_FUND_ID)
    cards = svc.process_trigger(trigger=trigger, fund_id=F4_FUND_ID, synthetic_static=False)
    assert cards[0].scope == "fund"
    assert cards[0].scope_id == F4_FUND_ID


def test_process_trigger_scope_correct_ble(svc):
    trigger = _make_trigger("sla_breach", "ble", F1_FUND_ID, ble_id=B11_BLE_ID,
                             detail={"ble_risk_tier": "medium"})
    cards = svc.process_trigger(trigger=trigger, fund_id=F1_FUND_ID, synthetic_static=False)
    assert cards[0].scope == "ble"
    assert cards[0].scope_id == B11_BLE_ID


def test_process_trigger_trigger_type_on_card(svc):
    trigger = _make_trigger("sla_breach", "ble", F1_FUND_ID, ble_id=B51_BLE_ID)
    cards = svc.process_trigger(trigger=trigger, fund_id=F1_FUND_ID, synthetic_static=False)
    assert cards[0].trigger_type == "sla_breach"


# ===========================================================================
# Section 4 — Tool policy correctness per trigger type
# ===========================================================================

def test_risk_tier_change_includes_screen_entity(svc):
    trigger = _make_trigger("risk_tier_change", "fund", F4_FUND_ID,
                             detail={"fund_name": "Harrington Private Capital"})
    cards = svc.process_trigger(trigger=trigger, fund_id=F4_FUND_ID, synthetic_static=False)
    assert "screen_entity" in cards[0].tools_called


def test_risk_tier_change_includes_rag_retrieve(svc):
    trigger = _make_trigger("risk_tier_change", "fund", F4_FUND_ID)
    cards = svc.process_trigger(trigger=trigger, fund_id=F4_FUND_ID, synthetic_static=False)
    assert "rag_retrieve" in cards[0].tools_called


def test_ubo_structure_change_includes_get_ubo_chain(svc):
    trigger = _make_trigger("ubo_structure_change", "fund", F2_FUND_ID)
    cards = svc.process_trigger(trigger=trigger, fund_id=F2_FUND_ID, synthetic_static=False)
    assert "get_ubo_chain" in cards[0].tools_called


def test_document_expiry_does_not_include_screen_entity(svc):
    trigger = _make_trigger("document_expiry", "fund", F2_FUND_ID)
    cards = svc.process_trigger(trigger=trigger, fund_id=F2_FUND_ID, synthetic_static=False)
    assert "screen_entity" not in cards[0].tools_called


def test_sla_breach_exactly_one_tool(svc):
    trigger = _make_trigger("sla_breach", "ble", F1_FUND_ID, ble_id=B51_BLE_ID)
    cards = svc.process_trigger(trigger=trigger, fund_id=F1_FUND_ID, synthetic_static=False)
    assert len(cards[0].tools_called) == 1
    assert cards[0].tools_called == ["get_audit_history"]


# ===========================================================================
# Section 5 — Escalation cascade (PRD §9.3)
# ===========================================================================

def test_critical_ble_trigger_returns_two_cards(svc):
    trigger = _make_trigger("new_sanctions_pep_hit", "ble", F1_FUND_ID, ble_id=B11_BLE_ID,
                             detail={"hit_type": "sanctions", "hit_severity": "confirmed",
                                     "counterparty_name": "Bank Rossiya",
                                     "ble_risk_tier": "critical"})
    cards = svc.process_trigger(trigger=trigger, fund_id=F1_FUND_ID, synthetic_static=False)
    assert len(cards) == 2


def test_cascade_card_scope_is_fund(svc):
    trigger = _make_trigger("new_sanctions_pep_hit", "ble", F1_FUND_ID, ble_id=B11_BLE_ID,
                             detail={"hit_type": "sanctions", "hit_severity": "confirmed",
                                     "counterparty_name": "Bank Rossiya",
                                     "ble_risk_tier": "critical"})
    cards = svc.process_trigger(trigger=trigger, fund_id=F1_FUND_ID, synthetic_static=False)
    assert cards[1].scope == "fund"
    assert cards[1].scope_id == F1_FUND_ID


def test_cascade_card_trigger_type_is_ble_critical_cascade(svc):
    trigger = _make_trigger("new_sanctions_pep_hit", "ble", F1_FUND_ID, ble_id=B11_BLE_ID,
                             detail={"hit_type": "sanctions", "hit_severity": "confirmed",
                                     "ble_risk_tier": "critical"})
    cards = svc.process_trigger(trigger=trigger, fund_id=F1_FUND_ID, synthetic_static=False)
    assert cards[1].trigger_type == "ble_critical_cascade"


def test_cascade_card_has_cascaded_from_ble_id(svc):
    trigger = _make_trigger("new_sanctions_pep_hit", "ble", F1_FUND_ID, ble_id=B11_BLE_ID,
                             detail={"hit_type": "sanctions", "hit_severity": "confirmed",
                                     "counterparty_name": "Bank Rossiya",
                                     "ble_risk_tier": "critical"})
    cards = svc.process_trigger(trigger=trigger, fund_id=F1_FUND_ID, synthetic_static=False)
    assert cards[1].cascaded_from_ble_id == B11_BLE_ID


def test_non_critical_ble_trigger_returns_one_card(svc):
    trigger = _make_trigger("sla_breach", "ble", F1_FUND_ID, ble_id=B51_BLE_ID,
                             detail={"ble_risk_tier": "low"})
    cards = svc.process_trigger(trigger=trigger, fund_id=F1_FUND_ID, synthetic_static=False)
    assert len(cards) == 1


# ===========================================================================
# Section 6 — Validation
# ===========================================================================

def test_static_fund_guard_fires(svc):
    trigger = _make_trigger("sla_breach", "fund", "static-fund-001")
    with pytest.raises(StaticFundAIError):
        svc.process_trigger(trigger=trigger, fund_id="static-fund-001", synthetic_static=True)


def test_unknown_trigger_type_raises(svc):
    # Construct a ReviewTrigger with an invalid trigger_type string
    trigger = ReviewTrigger(
        trigger_type="nonexistent_trigger_type",
        scope=TriggerScope.FUND,
        fund_id=F1_FUND_ID,
        ble_id=None,
        detail={},
    )
    with pytest.raises((ValueError, KeyError)):
        svc.process_trigger(trigger=trigger, fund_id=F1_FUND_ID, synthetic_static=False)


def test_empty_fund_id_raises(svc):
    trigger = _make_trigger("sla_breach", "fund", F1_FUND_ID)
    with pytest.raises(ValueError, match="fund_id must not be empty"):
        svc.process_trigger(trigger=trigger, fund_id="  ", synthetic_static=False)


# ===========================================================================
# Section 7 — SuggestionCard structure
# ===========================================================================

def test_card_id_nonempty(svc):
    trigger = _make_trigger("sla_breach", "ble", F1_FUND_ID, ble_id=B51_BLE_ID)
    cards = svc.process_trigger(trigger=trigger, fund_id=F1_FUND_ID, synthetic_static=False)
    assert cards[0].card_id != ""


def test_card_created_at_nonempty(svc):
    trigger = _make_trigger("sla_breach", "ble", F1_FUND_ID, ble_id=B51_BLE_ID)
    cards = svc.process_trigger(trigger=trigger, fund_id=F1_FUND_ID, synthetic_static=False)
    assert cards[0].created_at != ""


def test_card_is_mock_true(svc):
    trigger = _make_trigger("document_expiry", "fund", F2_FUND_ID)
    cards = svc.process_trigger(trigger=trigger, fund_id=F2_FUND_ID, synthetic_static=False)
    assert cards[0].is_mock is True


def test_card_suggested_workflow_template_nonempty(svc):
    trigger = _make_trigger("document_expiry", "fund", F2_FUND_ID)
    cards = svc.process_trigger(trigger=trigger, fund_id=F2_FUND_ID, synthetic_static=False)
    assert cards[0].suggested_workflow_template != ""


# ===========================================================================
# Section 8 — Workflow template mapping
# ===========================================================================

def test_cascade_card_template_is_fund_critical_escalation(svc):
    trigger = _make_trigger("new_sanctions_pep_hit", "ble", F1_FUND_ID, ble_id=B11_BLE_ID,
                             detail={"hit_type": "sanctions", "hit_severity": "confirmed",
                                     "ble_risk_tier": "critical"})
    cards = svc.process_trigger(trigger=trigger, fund_id=F1_FUND_ID, synthetic_static=False)
    assert cards[1].suggested_workflow_template == "fund_critical_escalation_v1"


def test_sla_breach_ble_template_correct(svc):
    trigger = _make_trigger("sla_breach", "ble", F1_FUND_ID, ble_id=B51_BLE_ID)
    cards = svc.process_trigger(trigger=trigger, fund_id=F1_FUND_ID, synthetic_static=False)
    assert cards[0].suggested_workflow_template == "ble_sla_review_v1"


# ===========================================================================
# Section 9 — _is_ble_critical helper
# ===========================================================================

def test_is_ble_critical_by_ble_risk_tier():
    trigger = _make_trigger("sla_breach", "ble", F1_FUND_ID, ble_id=B11_BLE_ID,
                             detail={"ble_risk_tier": "critical"})
    assert _is_ble_critical(trigger) is True


def test_is_ble_critical_by_effective_tier():
    trigger = _make_trigger("sla_breach", "ble", F1_FUND_ID, ble_id=B11_BLE_ID,
                             detail={"effective_tier": "critical"})
    assert _is_ble_critical(trigger) is True


def test_is_ble_critical_by_confirmed_sanctions():
    trigger = _make_trigger("new_sanctions_pep_hit", "ble", F1_FUND_ID, ble_id=B11_BLE_ID,
                             detail={"hit_type": "sanctions", "hit_severity": "confirmed"})
    assert _is_ble_critical(trigger) is True


def test_is_ble_critical_low_tier_returns_false():
    trigger = _make_trigger("sla_breach", "ble", F1_FUND_ID, ble_id=B51_BLE_ID,
                             detail={"ble_risk_tier": "low"})
    assert _is_ble_critical(trigger) is False
