"""Unit tests — Fund-level deterministic risk scoring (PRD §9.1)."""
import pytest

from services.rule_engine.models import (
    FundScoringFactors,
    PEPTier,
    RiskTier,
    ScreeningHitSeverity,
)
from services.rule_engine.scoring import compute_fund_direct_score


# ---------------------------------------------------------------------------
# Tier boundary tests
# ---------------------------------------------------------------------------

def test_clean_low_risk_fund_is_low_tier():
    factors = FundScoringFactors(
        incorporation_country_risk=10.0,
        screening_severity=ScreeningHitSeverity.NONE,
        pep_tier=PEPTier.NONE,
        ubo_risk=5.0,
        document_completeness=5.0,
    )
    result = compute_fund_direct_score(factors)
    assert result.direct_tier == RiskTier.LOW
    assert result.hard_stop is False
    assert result.direct_score < 26.0


def test_medium_tier_fund():
    # country:40*0.2=8  screening:25*0.3=7.5  pep:33*0.2=6.6  ubo:30*0.2=6  docs:20*0.1=2 → 30.1
    factors = FundScoringFactors(
        incorporation_country_risk=40.0,
        screening_severity=ScreeningHitSeverity.LOW,
        pep_tier=PEPTier.TIER_3,
        ubo_risk=30.0,
        document_completeness=20.0,
    )
    result = compute_fund_direct_score(factors)
    assert result.direct_tier == RiskTier.MEDIUM
    assert abs(result.direct_score - 30.1) < 0.01


def test_high_tier_fund():
    # country:70*0.2=14  screening:50*0.3=15  pep:67*0.2=13.4  ubo:60*0.2=12  docs:50*0.1=5 → 59.4
    factors = FundScoringFactors(
        incorporation_country_risk=70.0,
        screening_severity=ScreeningHitSeverity.MEDIUM,
        pep_tier=PEPTier.TIER_2,
        ubo_risk=60.0,
        document_completeness=50.0,
    )
    result = compute_fund_direct_score(factors)
    assert result.direct_tier == RiskTier.HIGH
    assert 51.0 <= result.direct_score < 76.0


def test_critical_tier_fund_from_weighted_score():
    # country:90*0.2=18  screening:75*0.3=22.5  pep:100*0.2=20  ubo:85*0.2=17  docs:70*0.1=7 → 84.5
    factors = FundScoringFactors(
        incorporation_country_risk=90.0,
        screening_severity=ScreeningHitSeverity.HIGH,
        pep_tier=PEPTier.TIER_1,
        ubo_risk=85.0,
        document_completeness=70.0,
    )
    result = compute_fund_direct_score(factors)
    assert result.direct_tier == RiskTier.CRITICAL
    assert result.hard_stop is False
    assert abs(result.direct_score - 84.5) < 0.01


# ---------------------------------------------------------------------------
# Hard-stop override (PRD §9.3) — Fund UBO confirmed sanctions hit
# ---------------------------------------------------------------------------

def test_fund_confirmed_sanctions_hard_stop():
    factors = FundScoringFactors(
        incorporation_country_risk=0.0,
        screening_severity=ScreeningHitSeverity.CONFIRMED,
        pep_tier=PEPTier.NONE,
        ubo_risk=0.0,
        document_completeness=0.0,
    )
    result = compute_fund_direct_score(factors)
    assert result.direct_tier == RiskTier.CRITICAL
    assert result.hard_stop is True
    assert result.direct_score == 100.0


def test_fund_hard_stop_even_with_otherwise_low_factors():
    """Hard stop fires even when every other factor would have been Low."""
    factors = FundScoringFactors(
        incorporation_country_risk=5.0,
        screening_severity=ScreeningHitSeverity.CONFIRMED,
        pep_tier=PEPTier.NONE,
        ubo_risk=5.0,
        document_completeness=0.0,
    )
    result = compute_fund_direct_score(factors)
    assert result.hard_stop is True
    assert result.direct_tier == RiskTier.CRITICAL


# ---------------------------------------------------------------------------
# UBO factor is present (Fund-only — PRD §9.2)
# ---------------------------------------------------------------------------

def test_ubo_factor_included_in_fund_factor_scores():
    factors = FundScoringFactors(
        incorporation_country_risk=20.0,
        screening_severity=ScreeningHitSeverity.NONE,
        pep_tier=PEPTier.NONE,
        ubo_risk=0.0,
        document_completeness=0.0,
    )
    result = compute_fund_direct_score(factors)
    assert set(result.factor_scores.keys()) == {"country", "screening", "pep", "ubo", "documents"}


def test_ubo_factor_score_reflects_input():
    factors = FundScoringFactors(
        incorporation_country_risk=0.0,
        screening_severity=ScreeningHitSeverity.NONE,
        pep_tier=PEPTier.NONE,
        ubo_risk=75.0,
        document_completeness=0.0,
    )
    result = compute_fund_direct_score(factors)
    assert result.factor_scores["ubo"] == 75.0
    # ubo: 75*0.2=15.0; all others 0 → direct_score=15.0 (LOW)
    assert result.direct_tier == RiskTier.LOW
    assert abs(result.direct_score - 15.0) < 0.01


# ---------------------------------------------------------------------------
# Factor score values are pre-weight sub-scores
# ---------------------------------------------------------------------------

def test_factor_scores_are_pre_weight_values():
    factors = FundScoringFactors(
        incorporation_country_risk=50.0,
        screening_severity=ScreeningHitSeverity.MEDIUM,
        pep_tier=PEPTier.TIER_2,
        ubo_risk=40.0,
        document_completeness=30.0,
    )
    result = compute_fund_direct_score(factors)
    assert result.factor_scores["country"] == 50.0
    assert result.factor_scores["screening"] == 50.0   # MEDIUM maps to 50
    assert result.factor_scores["pep"] == 67.0         # TIER_2 maps to 67
    assert result.factor_scores["ubo"] == 40.0
    assert result.factor_scores["documents"] == 30.0


# ---------------------------------------------------------------------------
# Escalated tier not set by scoring itself
# ---------------------------------------------------------------------------

def test_fund_scoring_never_sets_escalated_tier():
    factors = FundScoringFactors(
        incorporation_country_risk=100.0,
        screening_severity=ScreeningHitSeverity.HIGH,
        pep_tier=PEPTier.TIER_1,
        ubo_risk=100.0,
        document_completeness=100.0,
    )
    result = compute_fund_direct_score(factors)
    assert result.escalated_tier is None
    assert result.escalation_reason is None
