"""
PRD Section 9 — Risk Rule Engine data models.
All types used by scoring and escalation. Zero LLM calls in this module.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class RiskTier(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ScreeningHitSeverity(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CONFIRMED = "confirmed"  # confirmed sanctions hit → hard-stop override (PRD §9.3)


class PEPTier(int, Enum):
    NONE = 0   # not a PEP
    TIER_1 = 1  # highest risk — senior public officials
    TIER_2 = 2  # medium risk
    TIER_3 = 3  # lowest risk — family / close associates


@dataclass
class RulesetWeights:
    """
    Configurable per-level weights. Must sum to 1.0.
    ubo must be 0.0 for BLE-level configs (UBO factor is Fund-only per PRD §9.2).
    """
    country: float
    screening: float
    pep: float
    documents: float
    ubo: float = 0.0

    def __post_init__(self) -> None:
        total = self.country + self.screening + self.pep + self.documents + self.ubo
        if abs(total - 1.0) > 0.0005:
            raise ValueError(f"Weights must sum to 1.0, got {total:.6f}")


@dataclass
class BLEScoringFactors:
    """Input factors for BLE-level deterministic scoring (PRD §9.1)."""
    counterparty_country_risk: float   # 0–100
    screening_severity: ScreeningHitSeverity
    pep_tier: PEPTier
    document_completeness: float       # 0–100; higher = more incomplete/expired


@dataclass
class FundScoringFactors:
    """Input factors for Fund-level deterministic scoring (PRD §9.1)."""
    incorporation_country_risk: float  # 0–100
    screening_severity: ScreeningHitSeverity  # from Fund UBO/entity screening
    pep_tier: PEPTier                  # highest PEP tier across all UBOs
    ubo_risk: float                    # 0–100; computed from chain depth, unresolved %, jurisdictions
    document_completeness: float       # 0–100; higher = more incomplete/expired


@dataclass
class ScoringResult:
    """
    Output of a scoring function.
    direct_score and direct_tier always reflect the entity's own factors.
    escalated_tier is set only when BLE→Fund escalation applies (PRD §9.3).
    """
    direct_score: float
    direct_tier: RiskTier
    hard_stop: bool
    factor_scores: dict   # per-factor sub-scores for audit trail

    escalated_tier: Optional[RiskTier] = None
    escalation_reason: Optional[str] = None

    @property
    def effective_tier(self) -> RiskTier:
        """The tier that surfaces in the Command Centre (escalated if set)."""
        return self.escalated_tier if self.escalated_tier is not None else self.direct_tier
