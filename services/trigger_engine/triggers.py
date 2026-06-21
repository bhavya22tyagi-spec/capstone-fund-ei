"""
PRD Section 10 — Deterministic trigger detection with explicit scoping.
Every function returns None (or an empty list) when the trigger condition is
not met, so callers can safely filter. No LLM calls anywhere in this module.

Trigger → scope mapping (PRD §10 table):
  risk_tier_change                → Fund or BLE (whichever changed)
  new_sanctions_pep_hit           → Fund (on UBO) or BLE (on counterparty)
  adverse_media_change            → Fund or BLE
  ubo_structure_change            → Fund only
  document_expiry                 → Fund or BLE (whichever document)
  country_risk_reclassification   → Fund or BLE
  shared_counterparty_contagion   → BOTH (every Fund+BLE pair referencing the counterparty)
  ble_critical_cascade            → BLE trigger + cascaded Fund trigger (two triggers)
  sla_breach                      → Fund or BLE (whichever review was due)
"""
from datetime import date
from typing import List, Optional

from ..rule_engine.models import RiskTier
from .models import ReviewTrigger, TriggerScope, TriggerType


def detect_risk_tier_change(
    scope: str,
    scope_id: str,
    fund_id: str,
    ble_id: Optional[str],
    previous_tier: RiskTier,
    current_tier: RiskTier,
) -> Optional[ReviewTrigger]:
    """Fires when a Fund's or BLE's risk tier changes in either direction."""
    if previous_tier == current_tier:
        return None
    return ReviewTrigger(
        trigger_type=TriggerType.RISK_TIER_CHANGE,
        scope=TriggerScope.FUND if scope == "fund" else TriggerScope.BLE,
        fund_id=fund_id,
        ble_id=ble_id,
        detail={
            "scope": scope,
            "scope_id": scope_id,
            "previous_tier": previous_tier.value,
            "current_tier": current_tier.value,
        },
    )


def detect_sanctions_pep_hit(
    scope: str,
    fund_id: str,
    ble_id: Optional[str],
    hit_type: str,
    hit_detail: str,
) -> ReviewTrigger:
    """
    Fires on a new sanctions or PEP hit.
    scope='fund' → triggered by a Fund UBO hit.
    scope='ble'  → triggered by a BLE counterparty hit.
    Always fires (caller is responsible for only calling on genuinely new hits).
    """
    return ReviewTrigger(
        trigger_type=TriggerType.NEW_SANCTIONS_PEP_HIT,
        scope=TriggerScope.FUND if scope == "fund" else TriggerScope.BLE,
        fund_id=fund_id,
        ble_id=ble_id,
        detail={"hit_type": hit_type, "hit_detail": hit_detail},
    )


def detect_adverse_media_change(
    scope: str,
    fund_id: str,
    ble_id: Optional[str],
    previous_severity: str,
    current_severity: str,
) -> Optional[ReviewTrigger]:
    """Fires when adverse media severity/volume changes at Fund or BLE scope."""
    if previous_severity == current_severity:
        return None
    return ReviewTrigger(
        trigger_type=TriggerType.ADVERSE_MEDIA_CHANGE,
        scope=TriggerScope.FUND if scope == "fund" else TriggerScope.BLE,
        fund_id=fund_id,
        ble_id=ble_id,
        detail={
            "previous_severity": previous_severity,
            "current_severity": current_severity,
        },
    )


def detect_ubo_structure_change(
    fund_id: str,
    change_detail: str,
    threshold_crossed: bool,
) -> Optional[ReviewTrigger]:
    """
    Fires when a UBO/ownership structure change crosses a configured threshold.
    Scoped to Fund only (PRD §10).
    Returns None if the change did not cross the threshold.
    """
    if not threshold_crossed:
        return None
    return ReviewTrigger(
        trigger_type=TriggerType.UBO_STRUCTURE_CHANGE,
        scope=TriggerScope.FUND,
        fund_id=fund_id,
        ble_id=None,
        detail={"change_detail": change_detail},
    )


def detect_document_expiry(
    scope: str,
    fund_id: str,
    ble_id: Optional[str],
    document_id: str,
    document_type: str,
    expiry_date: date,
) -> Optional[ReviewTrigger]:
    """
    Fires when a document's expiry_date is today or in the past.
    Scoped to whichever entity owns the document (Fund or BLE).
    """
    if expiry_date > date.today():
        return None
    return ReviewTrigger(
        trigger_type=TriggerType.DOCUMENT_EXPIRY,
        scope=TriggerScope.FUND if scope == "fund" else TriggerScope.BLE,
        fund_id=fund_id,
        ble_id=ble_id,
        detail={
            "document_id": document_id,
            "document_type": document_type,
            "expiry_date": expiry_date.isoformat(),
        },
    )


def detect_country_risk_reclassification(
    scope: str,
    fund_id: str,
    ble_id: Optional[str],
    country_code: str,
    previous_risk: str,
    current_risk: str,
) -> Optional[ReviewTrigger]:
    """Fires when a country's FATF/Basel risk tier is reclassified."""
    if previous_risk == current_risk:
        return None
    return ReviewTrigger(
        trigger_type=TriggerType.COUNTRY_RISK_RECLASSIFICATION,
        scope=TriggerScope.FUND if scope == "fund" else TriggerScope.BLE,
        fund_id=fund_id,
        ble_id=ble_id,
        detail={
            "country_code": country_code,
            "previous_risk": previous_risk,
            "current_risk": current_risk,
        },
    )


def detect_shared_counterparty_contagion(
    counterparty_profile_id: str,
    affected_fund_ble_pairs: List[dict],
    contagion_reason: str,
) -> List[ReviewTrigger]:
    """
    A shared counterparty escalation cascades to every Fund+BLE that references it
    (PRD §10 — Linked-entity / shared-counterparty contagion row).
    Returns one BOTH-scoped trigger per affected Fund+BLE pair.
    affected_fund_ble_pairs: [{"fund_id": ..., "ble_id": ...}, ...]
    """
    return [
        ReviewTrigger(
            trigger_type=TriggerType.SHARED_COUNTERPARTY_CONTAGION,
            scope=TriggerScope.BOTH,
            fund_id=pair["fund_id"],
            ble_id=pair["ble_id"],
            detail={
                "counterparty_profile_id": counterparty_profile_id,
                "contagion_reason": contagion_reason,
            },
        )
        for pair in affected_fund_ble_pairs
    ]


def detect_ble_critical_cascade(
    fund_id: str,
    ble_id: str,
    ble_name: str,
) -> List[ReviewTrigger]:
    """
    When a BLE escalates to Critical, two triggers fire (PRD §10):
    1. A BLE-scoped trigger for the BLE itself.
    2. A Fund-scoped cascade trigger for the parent Fund.
    Both are returned so the queue sees each at the correct scope.
    """
    return [
        ReviewTrigger(
            trigger_type=TriggerType.BLE_CRITICAL_CASCADE,
            scope=TriggerScope.BLE,
            fund_id=fund_id,
            ble_id=ble_id,
            detail={"ble_name": ble_name, "cascade_target": "ble"},
        ),
        ReviewTrigger(
            trigger_type=TriggerType.BLE_CRITICAL_CASCADE,
            scope=TriggerScope.FUND,
            fund_id=fund_id,
            ble_id=ble_id,
            detail={
                "ble_name": ble_name,
                "cascade_target": "fund",
                "cascade_reason": f"BLE '{ble_name}' escalated to Critical",
            },
        ),
    ]


def detect_sla_breach(
    scope: str,
    fund_id: str,
    ble_id: Optional[str],
    review_due_date: date,
    last_review_date: Optional[date],
) -> Optional[ReviewTrigger]:
    """Fires when a scheduled review's due date has passed without completion."""
    today = date.today()
    if review_due_date > today:
        return None
    return ReviewTrigger(
        trigger_type=TriggerType.SLA_BREACH,
        scope=TriggerScope.FUND if scope == "fund" else TriggerScope.BLE,
        fund_id=fund_id,
        ble_id=ble_id,
        detail={
            "review_due_date": review_due_date.isoformat(),
            "last_review_date": last_review_date.isoformat() if last_review_date else None,
            "days_overdue": (today - review_due_date).days,
        },
    )
