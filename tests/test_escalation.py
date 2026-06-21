"""
Unit tests — BLE→Fund escalation rule (PRD §9.3).
Covers the key scenario: BLE is Critical while Fund's own direct factors are Low.
"""
import pytest

from services.rule_engine.escalation import apply_escalation
from services.rule_engine.models import (
    BLEScoringFactors,
    FundScoringFactors,
    PEPTier,
    RiskTier,
    ScoringResult,
    ScreeningHitSeverity,
)
from services.rule_engine.scoring import compute_ble_score, compute_fund_direct_score


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _result(tier: RiskTier, score: float = 50.0, hard_stop: bool = False) -> ScoringResult:
    return ScoringResult(
        direct_score=score,
        direct_tier=tier,
        hard_stop=hard_stop,
        factor_scores={},
    )


# ---------------------------------------------------------------------------
# No escalation cases
# ---------------------------------------------------------------------------

def test_no_escalation_when_no_critical_bles():
    fund = _result(RiskTier.MEDIUM, 40.0)
    bles = [
        ("ICBC, Noida",   _result(RiskTier.HIGH,   65.0)),
        ("ICBC, Gurgaon", _result(RiskTier.LOW,    15.0)),
    ]
    result = apply_escalation(fund, bles)
    assert result.escalated_tier is None
    assert result.effective_tier == RiskTier.MEDIUM
    assert result.direct_score == 40.0


def test_no_escalation_with_empty_ble_list():
    fund = _result(RiskTier.HIGH, 60.0)
    result = apply_escalation(fund, [])
    assert result.escalated_tier is None
    assert result.effective_tier == RiskTier.HIGH


# ---------------------------------------------------------------------------
# Escalation fires — PRD §9.3 core rule
# ---------------------------------------------------------------------------

def test_escalation_when_one_ble_is_critical():
    fund = _result(RiskTier.MEDIUM, 40.0)
    bles = [
        ("ICBC, Noida",   _result(RiskTier.CRITICAL, 91.0)),
        ("ICBC, Gurgaon", _result(RiskTier.LOW,      15.0)),
    ]
    result = apply_escalation(fund, bles)
    assert result.escalated_tier == RiskTier.CRITICAL
    assert result.effective_tier == RiskTier.CRITICAL
    assert "ICBC, Noida" in result.escalation_reason


def test_key_scenario_ble_critical_fund_direct_low(  ):
    """
    PRD §9.3 — the scenario that must be tested: BLE is Critical, Fund's own
    direct-factor score is Low. The Fund must surface as Critical, but its
    direct score must remain visible and unchanged.
    """
    fund = _result(RiskTier.LOW, 18.0)
    bles = [("Suspicious BLE", _result(RiskTier.CRITICAL, 88.0))]

    result = apply_escalation(fund, bles)

    # Direct score/tier are preserved unchanged
    assert result.direct_score == 18.0
    assert result.direct_tier == RiskTier.LOW

    # Effective tier is Critical
    assert result.escalated_tier == RiskTier.CRITICAL
    assert result.effective_tier == RiskTier.CRITICAL

    # Reason is non-empty
    assert result.escalation_reason is not None
    assert "Suspicious BLE" in result.escalation_reason


def test_direct_score_preserved_under_escalation():
    """Escalation must never modify direct_score — it is the Fund's own audit record."""
    fund = _result(RiskTier.LOW, 12.0)
    bles = [("Bad BLE", _result(RiskTier.CRITICAL, 95.0))]
    result = apply_escalation(fund, bles)
    assert result.direct_score == 12.0
    assert result.direct_tier == RiskTier.LOW
    assert result.escalated_tier == RiskTier.CRITICAL


def test_multiple_critical_bles_all_named_in_reason():
    fund = _result(RiskTier.HIGH, 70.0)
    bles = [
        ("BLE Alpha", _result(RiskTier.CRITICAL, 80.0)),
        ("BLE Beta",  _result(RiskTier.CRITICAL, 90.0)),
        ("BLE Gamma", _result(RiskTier.MEDIUM,   45.0)),
    ]
    result = apply_escalation(fund, bles)
    assert result.escalated_tier == RiskTier.CRITICAL
    assert "BLE Alpha" in result.escalation_reason
    assert "BLE Beta" in result.escalation_reason
    assert "BLE Gamma" not in result.escalation_reason


def test_escalation_reason_absent_when_no_escalation():
    fund = _result(RiskTier.HIGH, 70.0)
    bles = [("Normal BLE", _result(RiskTier.HIGH, 65.0))]
    result = apply_escalation(fund, bles)
    assert result.escalation_reason is None


# ---------------------------------------------------------------------------
# Hard-stop BLE propagates through escalation
# ---------------------------------------------------------------------------

def test_ble_hard_stop_produces_critical_and_escalates_fund():
    """
    End-to-end: BLE counterparty has a confirmed sanctions hit → BLE is Critical
    via hard-stop. Fund's own factors are Low. After escalation Fund is Critical.
    """
    ble_factors = BLEScoringFactors(
        counterparty_country_risk=0.0,
        screening_severity=ScreeningHitSeverity.CONFIRMED,
        pep_tier=PEPTier.NONE,
        document_completeness=0.0,
    )
    ble_result = compute_ble_score(ble_factors)
    assert ble_result.hard_stop is True
    assert ble_result.effective_tier == RiskTier.CRITICAL

    fund_factors = FundScoringFactors(
        incorporation_country_risk=5.0,
        screening_severity=ScreeningHitSeverity.NONE,
        pep_tier=PEPTier.NONE,
        ubo_risk=5.0,
        document_completeness=0.0,
    )
    fund_direct = compute_fund_direct_score(fund_factors)
    assert fund_direct.direct_tier == RiskTier.LOW

    final = apply_escalation(fund_direct, [("Sanctioned BLE", ble_result)])
    assert final.effective_tier == RiskTier.CRITICAL
    assert final.direct_tier == RiskTier.LOW
    assert "Sanctioned BLE" in final.escalation_reason


# ---------------------------------------------------------------------------
# effective_tier property consistency
# ---------------------------------------------------------------------------

def test_effective_tier_returns_direct_tier_when_no_escalation():
    result = _result(RiskTier.HIGH, 60.0)
    assert result.effective_tier == RiskTier.HIGH


def test_effective_tier_returns_escalated_tier_when_set():
    result = ScoringResult(
        direct_score=20.0,
        direct_tier=RiskTier.LOW,
        hard_stop=False,
        factor_scores={},
        escalated_tier=RiskTier.CRITICAL,
        escalation_reason="Test",
    )
    assert result.effective_tier == RiskTier.CRITICAL
