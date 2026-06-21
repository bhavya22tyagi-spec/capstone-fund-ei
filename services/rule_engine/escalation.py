"""
PRD Section 9.3 — BLE→Fund escalation rule.
Deterministic. No LLM calls.

Rule: if any BLE under a Fund is Critical (by effective_tier), the Fund surfaces
as Critical regardless of its own direct-factor score. The Fund's direct score
is always preserved and returned separately so the reason is never obscured.
"""
from typing import List, Tuple

from .models import RiskTier, ScoringResult


def apply_escalation(
    fund_direct: ScoringResult,
    ble_scores: List[Tuple[str, ScoringResult]],
) -> ScoringResult:
    """
    Apply BLE→Fund escalation (PRD §9.3).

    Args:
        fund_direct:  The Fund's own scoring result (direct factors only).
        ble_scores:   List of (ble_display_name, ScoringResult) for every BLE
                      under this Fund.

    Returns:
        A new ScoringResult with:
        - direct_score / direct_tier unchanged (Fund's own factors).
        - escalated_tier = CRITICAL and escalation_reason set if any BLE is Critical.
        - Otherwise identical to fund_direct (no escalation applied).
    """
    critical_bles = [
        name
        for name, score in ble_scores
        if score.effective_tier == RiskTier.CRITICAL
    ]

    if not critical_bles:
        return fund_direct

    names = ", ".join(critical_bles)
    return ScoringResult(
        direct_score=fund_direct.direct_score,
        direct_tier=fund_direct.direct_tier,
        hard_stop=fund_direct.hard_stop,
        factor_scores=fund_direct.factor_scores,
        escalated_tier=RiskTier.CRITICAL,
        escalation_reason=f"Escalated to Critical due to BLE(s): {names}",
    )
