"""
PRD Section 10 — Trigger & Scoping Engine data models.
Deterministic. No LLM calls.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class TriggerType(str, Enum):
    RISK_TIER_CHANGE                = "risk_tier_change"
    NEW_SANCTIONS_PEP_HIT           = "new_sanctions_pep_hit"
    ADVERSE_MEDIA_CHANGE            = "adverse_media_change"
    UBO_STRUCTURE_CHANGE            = "ubo_structure_change"
    DOCUMENT_EXPIRY                 = "document_expiry"
    COUNTRY_RISK_RECLASSIFICATION   = "country_risk_reclassification"
    SHARED_COUNTERPARTY_CONTAGION   = "shared_counterparty_contagion"
    BLE_CRITICAL_CASCADE            = "ble_critical_cascade"
    SLA_BREACH                      = "sla_breach"


class TriggerScope(str, Enum):
    FUND = "fund"
    BLE  = "ble"
    BOTH = "both"  # counterparty contagion — cascades to all affected Fund+BLE pairs


@dataclass
class ReviewTrigger:
    trigger_type: TriggerType
    scope: TriggerScope
    fund_id: Optional[str]
    ble_id: Optional[str]
    detail: dict = field(default_factory=dict)
    fired_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
