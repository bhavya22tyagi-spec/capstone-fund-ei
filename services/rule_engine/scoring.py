"""
PRD Section 9 — Deterministic risk scoring for BLE and Fund levels.
No LLM calls. No randomness. Output is fully reproducible from inputs + ruleset version.

Tier thresholds (0–100 scale):
  Critical : score >= 76
  High     : score >= 51
  Medium   : score >= 26
  Low      : score <  26
"""
from .models import (
    RiskTier,
    ScreeningHitSeverity,
    PEPTier,
    RulesetWeights,
    BLEScoringFactors,
    FundScoringFactors,
    ScoringResult,
)

# BLE default weights — UBO excluded (PRD §9.2), remaining factors re-normalised to 1.0
# Original ratios: Country 20, Screening 30, PEP 20, Docs 10 (80 total without UBO)
DEFAULT_BLE_WEIGHTS = RulesetWeights(
    country=0.25,
    screening=0.375,
    pep=0.25,
    documents=0.125,
    ubo=0.0,
)

# Fund default weights — all five factors (PRD §9.2)
DEFAULT_FUND_WEIGHTS = RulesetWeights(
    country=0.20,
    screening=0.30,
    pep=0.20,
    ubo=0.20,
    documents=0.10,
)

# Tier thresholds evaluated highest-first
_TIER_THRESHOLDS: list[tuple[float, RiskTier]] = [
    (76.0, RiskTier.CRITICAL),
    (51.0, RiskTier.HIGH),
    (26.0, RiskTier.MEDIUM),
    (0.0,  RiskTier.LOW),
]

_SCREENING_SUB_SCORES: dict[ScreeningHitSeverity, float] = {
    ScreeningHitSeverity.NONE:      0.0,
    ScreeningHitSeverity.LOW:      25.0,
    ScreeningHitSeverity.MEDIUM:   50.0,
    ScreeningHitSeverity.HIGH:     75.0,
    ScreeningHitSeverity.CONFIRMED: 100.0,
}

_PEP_SUB_SCORES: dict[PEPTier, float] = {
    PEPTier.NONE:   0.0,
    PEPTier.TIER_3: 33.0,
    PEPTier.TIER_2: 67.0,
    PEPTier.TIER_1: 100.0,
}


def _score_to_tier(score: float) -> RiskTier:
    for threshold, tier in _TIER_THRESHOLDS:
        if score >= threshold:
            return tier
    return RiskTier.LOW


def compute_ble_score(
    factors: BLEScoringFactors,
    weights: RulesetWeights = DEFAULT_BLE_WEIGHTS,
) -> ScoringResult:
    """
    Deterministic BLE-level risk score (PRD §9.1).
    A confirmed sanctions hit triggers the hard-stop override → Critical regardless
    of weighted total (PRD §9.3).
    """
    screening_sub = _SCREENING_SUB_SCORES[factors.screening_severity]
    pep_sub = _PEP_SUB_SCORES[factors.pep_tier]

    factor_scores = {
        "country":   factors.counterparty_country_risk,
        "screening": screening_sub,
        "pep":       pep_sub,
        "documents": factors.document_completeness,
    }

    if factors.screening_severity == ScreeningHitSeverity.CONFIRMED:
        return ScoringResult(
            direct_score=100.0,
            direct_tier=RiskTier.CRITICAL,
            hard_stop=True,
            factor_scores=factor_scores,
        )

    weighted = (
        factors.counterparty_country_risk * weights.country
        + screening_sub * weights.screening
        + pep_sub * weights.pep
        + factors.document_completeness * weights.documents
    )

    return ScoringResult(
        direct_score=round(weighted, 2),
        direct_tier=_score_to_tier(weighted),
        hard_stop=False,
        factor_scores=factor_scores,
    )


def compute_fund_direct_score(
    factors: FundScoringFactors,
    weights: RulesetWeights = DEFAULT_FUND_WEIGHTS,
) -> ScoringResult:
    """
    Deterministic Fund-level direct score — own factors only, no escalation (PRD §9.1).
    Call apply_escalation() afterwards to fold in BLE→Fund escalation (PRD §9.3).
    A confirmed sanctions hit on a Fund UBO triggers the hard-stop override (PRD §9.3).
    """
    screening_sub = _SCREENING_SUB_SCORES[factors.screening_severity]
    pep_sub = _PEP_SUB_SCORES[factors.pep_tier]

    factor_scores = {
        "country":   factors.incorporation_country_risk,
        "screening": screening_sub,
        "pep":       pep_sub,
        "ubo":       factors.ubo_risk,
        "documents": factors.document_completeness,
    }

    if factors.screening_severity == ScreeningHitSeverity.CONFIRMED:
        return ScoringResult(
            direct_score=100.0,
            direct_tier=RiskTier.CRITICAL,
            hard_stop=True,
            factor_scores=factor_scores,
        )

    weighted = (
        factors.incorporation_country_risk * weights.country
        + screening_sub * weights.screening
        + pep_sub * weights.pep
        + factors.ubo_risk * weights.ubo
        + factors.document_completeness * weights.documents
    )

    return ScoringResult(
        direct_score=round(weighted, 2),
        direct_tier=_score_to_tier(weighted),
        hard_stop=False,
        factor_scores=factor_scores,
    )
