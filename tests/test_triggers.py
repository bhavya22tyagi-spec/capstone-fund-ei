"""Unit tests — Trigger & Scoping Engine (PRD §10)."""
from datetime import date, timedelta

import pytest

from services.rule_engine.models import RiskTier
from services.trigger_engine.models import TriggerScope, TriggerType
from services.trigger_engine.triggers import (
    detect_adverse_media_change,
    detect_ble_critical_cascade,
    detect_country_risk_reclassification,
    detect_document_expiry,
    detect_risk_tier_change,
    detect_sanctions_pep_hit,
    detect_shared_counterparty_contagion,
    detect_sla_breach,
    detect_ubo_structure_change,
)

FUND_ID = "fund-001"
BLE_ID  = "ble-001"

# ---------------------------------------------------------------------------
# Risk tier change
# ---------------------------------------------------------------------------

def test_risk_tier_change_fund_scope():
    t = detect_risk_tier_change("fund", FUND_ID, FUND_ID, None, RiskTier.MEDIUM, RiskTier.HIGH)
    assert t is not None
    assert t.trigger_type == TriggerType.RISK_TIER_CHANGE
    assert t.scope == TriggerScope.FUND
    assert t.fund_id == FUND_ID
    assert t.ble_id is None


def test_risk_tier_change_ble_scope():
    t = detect_risk_tier_change("ble", BLE_ID, FUND_ID, BLE_ID, RiskTier.LOW, RiskTier.CRITICAL)
    assert t is not None
    assert t.scope == TriggerScope.BLE
    assert t.ble_id == BLE_ID
    assert t.detail["previous_tier"] == "low"
    assert t.detail["current_tier"] == "critical"


def test_no_trigger_when_tier_unchanged():
    t = detect_risk_tier_change("fund", FUND_ID, FUND_ID, None, RiskTier.HIGH, RiskTier.HIGH)
    assert t is None


def test_risk_tier_change_detail_contains_scope_info():
    t = detect_risk_tier_change("ble", BLE_ID, FUND_ID, BLE_ID, RiskTier.MEDIUM, RiskTier.LOW)
    assert t.detail["scope"] == "ble"
    assert t.detail["scope_id"] == BLE_ID


# ---------------------------------------------------------------------------
# Sanctions / PEP hit
# ---------------------------------------------------------------------------

def test_sanctions_hit_fund_scope():
    t = detect_sanctions_pep_hit("fund", FUND_ID, None, "sanctions", "UBO matched OFAC")
    assert t.trigger_type == TriggerType.NEW_SANCTIONS_PEP_HIT
    assert t.scope == TriggerScope.FUND
    assert t.ble_id is None


def test_sanctions_hit_ble_scope():
    t = detect_sanctions_pep_hit("ble", FUND_ID, BLE_ID, "sanctions", "Counterparty on EU list")
    assert t.scope == TriggerScope.BLE
    assert t.ble_id == BLE_ID


def test_pep_hit_ble_scope():
    t = detect_sanctions_pep_hit("ble", FUND_ID, BLE_ID, "pep", "Director is PEP tier 1")
    assert t.detail["hit_type"] == "pep"


# ---------------------------------------------------------------------------
# Adverse media change
# ---------------------------------------------------------------------------

def test_adverse_media_triggers_on_severity_change():
    t = detect_adverse_media_change("ble", FUND_ID, BLE_ID, "low", "high")
    assert t is not None
    assert t.trigger_type == TriggerType.ADVERSE_MEDIA_CHANGE
    assert t.scope == TriggerScope.BLE


def test_adverse_media_no_trigger_when_unchanged():
    t = detect_adverse_media_change("fund", FUND_ID, None, "medium", "medium")
    assert t is None


def test_adverse_media_fund_scope():
    t = detect_adverse_media_change("fund", FUND_ID, None, "none", "medium")
    assert t.scope == TriggerScope.FUND
    assert t.ble_id is None


# ---------------------------------------------------------------------------
# UBO structure change
# ---------------------------------------------------------------------------

def test_ubo_change_fires_when_threshold_crossed():
    t = detect_ubo_structure_change(FUND_ID, "Controlling owner changed", threshold_crossed=True)
    assert t is not None
    assert t.trigger_type == TriggerType.UBO_STRUCTURE_CHANGE
    assert t.scope == TriggerScope.FUND
    assert t.ble_id is None


def test_ubo_change_no_trigger_when_threshold_not_crossed():
    t = detect_ubo_structure_change(FUND_ID, "Minor address update", threshold_crossed=False)
    assert t is None


def test_ubo_change_is_always_fund_scoped():
    t = detect_ubo_structure_change(FUND_ID, "New layer added", threshold_crossed=True)
    assert t.scope == TriggerScope.FUND


# ---------------------------------------------------------------------------
# Document expiry
# ---------------------------------------------------------------------------

def test_document_expiry_triggers_when_expired():
    expired = date.today() - timedelta(days=1)
    t = detect_document_expiry("fund", FUND_ID, None, "doc-001", "Incorporation Cert", expired)
    assert t is not None
    assert t.trigger_type == TriggerType.DOCUMENT_EXPIRY
    assert t.scope == TriggerScope.FUND


def test_document_expiry_triggers_on_exactly_today():
    today = date.today()
    t = detect_document_expiry("ble", FUND_ID, BLE_ID, "doc-002", "Counterparty Agreement", today)
    assert t is not None
    assert t.scope == TriggerScope.BLE


def test_document_expiry_no_trigger_when_future():
    future = date.today() + timedelta(days=30)
    t = detect_document_expiry("ble", FUND_ID, BLE_ID, "doc-003", "Agreement", future)
    assert t is None


def test_document_expiry_detail_contains_expiry_date():
    expired = date.today() - timedelta(days=5)
    t = detect_document_expiry("fund", FUND_ID, None, "doc-004", "UBO Declaration", expired)
    assert t.detail["expiry_date"] == expired.isoformat()
    assert t.detail["document_type"] == "UBO Declaration"


# ---------------------------------------------------------------------------
# Country risk reclassification
# ---------------------------------------------------------------------------

def test_country_reclassification_fund_scope():
    t = detect_country_risk_reclassification("fund", FUND_ID, None, "IRN", "high", "critical")
    assert t is not None
    assert t.trigger_type == TriggerType.COUNTRY_RISK_RECLASSIFICATION
    assert t.scope == TriggerScope.FUND
    assert t.detail["country_code"] == "IRN"


def test_country_reclassification_ble_scope():
    t = detect_country_risk_reclassification("ble", FUND_ID, BLE_ID, "CHN", "medium", "high")
    assert t.scope == TriggerScope.BLE
    assert t.ble_id == BLE_ID


def test_country_reclassification_no_trigger_when_unchanged():
    t = detect_country_risk_reclassification("fund", FUND_ID, None, "USA", "low", "low")
    assert t is None


# ---------------------------------------------------------------------------
# Shared counterparty contagion
# ---------------------------------------------------------------------------

def test_contagion_fires_for_every_affected_pair():
    pairs = [
        {"fund_id": "fund-001", "ble_id": "ble-001"},
        {"fund_id": "fund-002", "ble_id": "ble-003"},
        {"fund_id": "fund-003", "ble_id": "ble-007"},
    ]
    triggers = detect_shared_counterparty_contagion("cpty-icbc", pairs, "ICBC sanctions hit")
    assert len(triggers) == 3
    for t in triggers:
        assert t.trigger_type == TriggerType.SHARED_COUNTERPARTY_CONTAGION
        assert t.scope == TriggerScope.BOTH
        assert t.detail["counterparty_profile_id"] == "cpty-icbc"


def test_contagion_empty_pairs_returns_empty():
    triggers = detect_shared_counterparty_contagion("cpty-xyz", [], "some reason")
    assert triggers == []


def test_contagion_each_trigger_has_correct_fund_and_ble_ids():
    pairs = [
        {"fund_id": "fund-A", "ble_id": "ble-A"},
        {"fund_id": "fund-B", "ble_id": "ble-B"},
    ]
    triggers = detect_shared_counterparty_contagion("cpty-icbc", pairs, "reason")
    fund_ids = {t.fund_id for t in triggers}
    ble_ids  = {t.ble_id  for t in triggers}
    assert fund_ids == {"fund-A", "fund-B"}
    assert ble_ids  == {"ble-A",  "ble-B"}


# ---------------------------------------------------------------------------
# BLE critical cascade — PRD §10 (two triggers must fire)
# ---------------------------------------------------------------------------

def test_ble_critical_cascade_fires_two_triggers():
    triggers = detect_ble_critical_cascade(FUND_ID, BLE_ID, "ICBC, Noida")
    assert len(triggers) == 2


def test_ble_critical_cascade_has_ble_scoped_trigger():
    triggers = detect_ble_critical_cascade(FUND_ID, BLE_ID, "ICBC, Noida")
    ble_t = next(t for t in triggers if t.scope == TriggerScope.BLE)
    assert ble_t.trigger_type == TriggerType.BLE_CRITICAL_CASCADE
    assert ble_t.ble_id == BLE_ID
    assert ble_t.fund_id == FUND_ID


def test_ble_critical_cascade_has_fund_scoped_trigger():
    triggers = detect_ble_critical_cascade(FUND_ID, BLE_ID, "ICBC, Noida")
    fund_t = next(t for t in triggers if t.scope == TriggerScope.FUND)
    assert fund_t.trigger_type == TriggerType.BLE_CRITICAL_CASCADE
    assert fund_t.fund_id == FUND_ID
    assert "ICBC, Noida" in fund_t.detail["cascade_reason"]


def test_ble_critical_cascade_fund_trigger_names_the_ble():
    triggers = detect_ble_critical_cascade("fund-99", "ble-99", "Deutsche Bank, Mumbai")
    fund_t = next(t for t in triggers if t.scope == TriggerScope.FUND)
    assert "Deutsche Bank, Mumbai" in fund_t.detail["cascade_reason"]


# ---------------------------------------------------------------------------
# SLA breach
# ---------------------------------------------------------------------------

def test_sla_breach_when_overdue():
    past = date.today() - timedelta(days=5)
    t = detect_sla_breach("ble", FUND_ID, BLE_ID, past, date.today() - timedelta(days=200))
    assert t is not None
    assert t.trigger_type == TriggerType.SLA_BREACH
    assert t.scope == TriggerScope.BLE
    assert t.detail["days_overdue"] == 5


def test_sla_no_breach_when_due_date_in_future():
    future = date.today() + timedelta(days=1)
    t = detect_sla_breach("fund", FUND_ID, None, future, None)
    assert t is None


def test_sla_breach_fund_scope():
    past = date.today() - timedelta(days=10)
    t = detect_sla_breach("fund", FUND_ID, None, past, None)
    assert t.scope == TriggerScope.FUND
    assert t.ble_id is None


def test_sla_breach_last_review_date_can_be_none():
    past = date.today() - timedelta(days=3)
    t = detect_sla_breach("ble", FUND_ID, BLE_ID, past, None)
    assert t is not None
    assert t.detail["last_review_date"] is None
