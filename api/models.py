"""Pydantic response models for the FastAPI layer."""
from __future__ import annotations
from typing import Any
from pydantic import BaseModel


class DocumentInfo(BaseModel):
    doc_id: str
    document_type: str
    status: str
    expiry_date: str | None
    extraction_status: str
    embedding_status: str


class BLESummary(BaseModel):
    ble_id: str
    fund_id: str
    name: str
    tier: str
    score: float
    screening_is_real: bool
    last_trigger_type: str | None


class FundSummary(BaseModel):
    fund_id: str
    name: str
    incorporation_country: str
    direct_tier: str
    direct_score: float
    escalated_tier: str | None
    escalation_reason: str | None
    synthetic_static: bool
    synthetic_profile: bool
    bles: list[BLESummary]


class FundDetail(FundSummary):
    ubo_chain_layers: int
    ubo_chain_resolved: bool
    documents: list[DocumentInfo]
    ruleset_version: str
    factor_scores: dict[str, float]


class ProductInfo(BaseModel):
    product_id: str
    product_type: str
    workflow_template: str
    status: str


class BLEDetail(BaseModel):
    ble_id: str
    fund_id: str
    fund_name: str
    name: str
    tier: str
    score: float
    screening_is_real: bool
    institution: str
    location: str
    counterparty_country: str
    screening_status: str
    hit_type: str | None
    hit_severity: str | None
    products: list[ProductInfo]
    documents: list[DocumentInfo]
    factor_scores: dict[str, float]
    ruleset_version: str


class RiskScore(BaseModel):
    direct_score: float
    direct_tier: str
    escalated_tier: str | None
    escalation_reason: str | None
    hard_stop: bool
    factor_scores: dict[str, float]


class HighRiskEntry(BaseModel):
    fund_id: str
    fund_name: str
    synthetic_static: bool
    effective_tier: str
    direct_tier: str
    direct_score: float
    escalated_ble_name: str | None
    last_trigger_type: str | None


class DashboardResponse(BaseModel):
    total_funds: int
    live_funds: int
    high_critical_count: int
    tier_distribution: dict[str, int]
    high_risk_queue: list[HighRiskEntry]


class SuggestionItem(BaseModel):
    suggestion_id: str
    scope: str
    scope_id: str
    fund_id: str
    fund_name: str
    ble_name: str | None
    trigger_type: str
    what_changed_summary: str
    status: str
    created_at: str
    cascade_info: dict[str, Any] | None


class AcceptDeclineRequest(BaseModel):
    actor: str
    notes: str | None = None


class BulkRequest(BaseModel):
    ids: list[str]
    actor: str
    notes: str | None = None


class CopilotRequest(BaseModel):
    question: str
    fund_id: str | None = None
    scope: str | None = None
    scope_id: str | None = None


class CitationItem(BaseModel):
    text: str
    doc_id: str
    document_type: str


class CopilotAnswer(BaseModel):
    question: str
    routing: str
    answer: str
    sql: str | None
    citations: list[CitationItem]
    is_mock: bool


class RulesetConfig(BaseModel):
    version: str
    scope_level: str
    weight_country: float
    weight_screening: float
    weight_pep: float
    weight_ubo: float
    weight_documents: float
    hard_stop_enabled: bool
    escalation_enabled: bool


class EvalRunSummary(BaseModel):
    eval_category: str
    label: str
    last_run_at: str | None
    pass_count: int
    fail_count: int
    pass_rate: float
    latency_ms: int
    cost_usd: float
    status: str
    is_mock: bool


# ---------------------------------------------------------------------------
# Analyst Report — PRD §13.3
# ---------------------------------------------------------------------------

class ReportCitation(BaseModel):
    claim: str
    doc_id: str
    citation_text: str
    document_type: str


class AnalystReport(BaseModel):
    scope: str                        # "fund" | "ble"
    scope_id: str
    fund_id: str
    fund_name: str
    ble_name: str | None              # BLE scope only
    effective_tier: str               # escalated_tier ?? direct_tier
    direct_tier: str
    direct_score: float
    escalation_reason: str | None     # Fund scope only
    escalated_ble_names: list[str]    # Fund scope only
    factor_scores: dict[str, float]
    narrative: str
    citations: list[ReportCitation]
    document_status: list[DocumentInfo]
    screening_status: str | None      # BLE scope: hit_severity
    hit_type: str | None
    ruleset_version: str
    model: str
    prompt_version: str
    is_mock: bool
    generated_at: str


# ---------------------------------------------------------------------------
# HITL Decision Audit Trail — PRD §18
# ---------------------------------------------------------------------------

class DecisionRequest(BaseModel):
    decision: str                     # "accepted" | "rejected" | "edited"
    actor: str                        # analyst identifier (free-text for demo)
    notes: str | None = None
    edited_narrative: str | None = None   # populated when decision == "edited"


class DecisionRecord(DecisionRequest):
    scope: str
    scope_id: str
    fund_id: str
    decided_at: str                   # ISO timestamp (UTC)
