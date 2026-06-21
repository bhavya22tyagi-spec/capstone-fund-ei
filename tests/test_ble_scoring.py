"""Unit tests — BLE-level deterministic risk scoring (PRD §9.1)."""
import pytest

from services.rule_engine.models import (
    BLEScoringFactors,
    PEPTier,
    RiskTier,
    RulesetWeights,
    ScreeningHitSeverity,
)
from services.rule_engine.scoring import DEFAULT_BLE_WEIGHTS, compute_ble_score


# ---------------------------------------------------------------------------
# Tier boundary tests
# ---------------------------------------------------------------------------

def test_clean_low_risk_ble_is_low_tier():
    factors = BLEScoringFactors(
        counterparty_country_risk=10.0,
        screening_severity=ScreeningHitSeverity.NONE,
        pep_tier=PEPTier.NONE,
        document_completeness=5.0,
    )
    result = compute_ble_score(factors)
    assert result.direct_tier == RiskTier.LOW
    assert result.hard_stop is False
    assert result.direct_score < 26.0


def test_medium_tier_ble():
    # country:50*0.25=12.5  screening:25*0.375=9.375  pep:0  docs:10*0.125=1.25 → 23.125
    # Add screening HIGH to push into medium range
    # country:50*0.25=12.5  screening:75*0.375=28.125  pep:0  docs:10*0.125=1.25 → 41.875
    factors = BLEScoringFactors(
        counterparty_country_risk=50.0,
        screening_severity=ScreeningHitSeverity.HIGH,
        pep_tier=PEPTier.NONE,
        document_completeness=10.0,
    )
    result = compute_ble_score(factors)
    assert result.direct_tier == RiskTier.MEDIUM
    assert abs(result.direct_score - 41.875) < 0.01


def test_high_tier_ble():
    # country:80*0.25=20  screening:50*0.375=18.75  pep:67*0.25=16.75  docs:20*0.125=2.5 → 58.0
    factors = BLEScoringFactors(
        counterparty_country_risk=80.0,
        screening_severity=ScreeningHitSeverity.MEDIUM,
        pep_tier=PEPTier.TIER_2,
        document_completeness=20.0,
    )
    result = compute_ble_score(factors)
    assert result.direct_tier == RiskTier.HIGH
    assert 51.0 <= result.direct_score < 76.0


def test_critical_tier_ble_from_weighted_score():
    # country:90*0.25=22.5  screening:75*0.375=28.125  pep:100*0.25=25  docs:80*0.125=10 → 85.625
    factors = BLEScoringFactors(
        counterparty_country_risk=90.0,
        screening_severity=ScreeningHitSeverity.HIGH,
        pep_tier=PEPTier.TIER_1,
        document_completeness=80.0,
    )
    result = compute_ble_score(factors)
    assert result.direct_tier == RiskTier.CRITICAL
    assert result.hard_stop is False
    assert abs(result.direct_score - 85.625) < 0.01


# ---------------------------------------------------------------------------
# Hard-stop override (PRD §9.3)
# ---------------------------------------------------------------------------

def test_confirmed_sanctions_hard_stop_overrides_everything():
    """A confirmed sanctions hit → Critical + hard_stop=True regardless of other factors."""
    factors = BLEScoringFactors(
        counterparty_country_risk=0.0,
        screening_severity=ScreeningHitSeverity.CONFIRMED,
        pep_tier=PEPTier.NONE,
        document_completeness=0.0,
    )
    result = compute_ble_score(factors)
    assert result.direct_tier == RiskTier.CRITICAL
    assert result.hard_stop is True
    assert result.direct_score == 100.0


def test_confirmed_sanctions_hard_stop_even_if_all_other_factors_clean():
    """Hard stop fires even when every other factor would produce Low."""
    factors = BLEScoringFactors(
        counterparty_country_risk=0.0,
        screening_severity=ScreeningHitSeverity.CONFIRMED,
        pep_tier=PEPTier.NONE,
        document_completeness=0.0,
    )
    result = compute_ble_score(factors)
    assert result.hard_stop is True
    assert result.direct_tier == RiskTier.CRITICAL


# ---------------------------------------------------------------------------
# Factor scores in output
# ---------------------------------------------------------------------------

def test_factor_scores_keys_are_correct_for_ble():
    factors = BLEScoringFactors(
        counterparty_country_risk=40.0,
        screening_severity=ScreeningHitSeverity.MEDIUM,
        pep_tier=PEPTier.TIER_2,
        document_completeness=20.0,
    )
    result = compute_ble_score(factors)
    assert set(result.factor_scores.keys()) == {"country", "screening", "pep", "documents"}
    assert "ubo" not in result.factor_scores


def test_factor_scores_values_are_sub_scores_not_weighted():
    factors = BLEScoringFactors(
        counterparty_country_risk=60.0,
        screening_severity=ScreeningHitSeverity.HIGH,
        pep_tier=PEPTier.TIER_1,
        document_completeness=30.0,
    )
    result = compute_ble_score(factors)
    assert result.factor_scores["country"] == 60.0
    assert result.factor_scores["screening"] == 75.0   # HIGH maps to 75
    assert result.factor_scores["pep"] == 100.0        # TIER_1 maps to 100
    assert result.factor_scores["documents"] == 30.0


# ---------------------------------------------------------------------------
# Custom weights
# ---------------------------------------------------------------------------

def test_custom_weights_respected():
    weights = RulesetWeights(country=0.50, screening=0.30, pep=0.10, documents=0.10, ubo=0.0)
    factors = BLEScoringFactors(
        counterparty_country_risk=100.0,
        screening_severity=ScreeningHitSeverity.NONE,
        pep_tier=PEPTier.NONE,
        document_completeness=0.0,
    )
    result = compute_ble_score(factors, weights=weights)
    # Only country contributes: 100 * 0.50 = 50.0
    assert result.direct_tier == RiskTier.MEDIUM
    assert abs(result.direct_score - 50.0) < 0.01


def test_invalid_weights_raise():
    with pytest.raises(ValueError, match="sum to 1.0"):
        RulesetWeights(country=0.5, screening=0.5, pep=0.5, documents=0.5, ubo=0.0)


# ---------------------------------------------------------------------------
# Escalated tier not set by scoring (only by escalation module)
# ---------------------------------------------------------------------------

def test_scoring_never_sets_escalated_tier():
    factors = BLEScoringFactors(
        counterparty_country_risk=100.0,
        screening_severity=ScreeningHitSeverity.HIGH,
        pep_tier=PEPTier.TIER_1,
        document_completeness=100.0,
    )
    result = compute_ble_score(factors)
    assert result.escalated_tier is None
    assert result.escalation_reason is None
