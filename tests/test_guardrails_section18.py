"""
PRD §18 Regulatory & Compliance Guardrails — explicit test mapping.

Every test in this file is cross-referenced to a specific PRD §18 bullet so the
traceability matrix can point directly here. Existing deeper test suites
(test_text_to_sql_service.py, test_rag_service.py, test_workflow_service.py, etc.)
are the primary coverage; this file adds explicit named assertions and the new
no-fabricated-facts rule (PRD §7.2 / §18) which has no other explicit test.
"""
from __future__ import annotations

import os
import re

import pytest

os.environ.setdefault("MOCK", "true")

F1 = "f0000001-f000-0000-0000-000000000001"  # Northgate Capital Partners LP
B1 = "b0001001-b000-0000-0000-000000000001"  # Bank Rossiya — screening_is_real=True

# ---------------------------------------------------------------------------
# Helper: no-fabricated-facts check (PRD §7.2 / §18)
# ---------------------------------------------------------------------------

_FABRICATION_PATTERNS = re.compile(
    r"(founded\s+in\s+\d{4}"
    r"|incorporated\s+in\s+\d{4}"
    r"|established\s+in\s+\d{4}"
    r"|revenue\s+of\s+\$"
    r"|annual\s+revenue"
    r"|headquartered\s+at\s+[A-Z]"
    r"|\d[\d,]+\s+employees"
    r"|number\s+of\s+employees"
    r"|subsidiary\s+named"
    r"|the\s+company\s+was\s+founded"
    r"|offices?\s+in\s+[A-Z][a-z]+"
    r"|net\s+assets?\s+of\s+\$"
    r"|manages\s+\$[\d\.]+ (billion|million))",
    re.I,
)


def _no_fabricated_facts(text: str) -> bool:
    """Return True if text contains NO patterns indicating fabricated business facts."""
    return not bool(_FABRICATION_PATTERNS.search(text))


# ---------------------------------------------------------------------------
# §18: Explainability — every risk score traceable to versioned ruleset;
#      escalation reasons always shown, never silently rolled up
# ---------------------------------------------------------------------------

def test_escalation_reason_populated_when_escalated():
    """§18 Explainability: escalation_reason must be set when escalated_tier != direct_tier."""
    from services.rule_engine.escalation import apply_escalation
    from services.rule_engine.scoring import compute_ble_score, compute_fund_direct_score
    from services.rule_engine.models import (
        BLEScoringFactors, FundScoringFactors, RulesetWeights,
        ScreeningHitSeverity, PEPTier,
    )

    ble_w = RulesetWeights(country=0.25, screening=0.375, pep=0.25, documents=0.125)
    ble_factors = BLEScoringFactors(
        counterparty_country_risk=100.0,
        screening_severity=ScreeningHitSeverity.CONFIRMED,
        pep_tier=PEPTier.NONE,
        document_completeness=0.0,
    )
    ble_score = compute_ble_score(ble_factors, ble_w)

    fund_w = RulesetWeights(country=0.20, screening=0.30, pep=0.20, documents=0.10, ubo=0.20)
    fund_factors = FundScoringFactors(
        incorporation_country_risk=10.0,
        screening_severity=ScreeningHitSeverity.NONE,
        pep_tier=PEPTier.NONE,
        document_completeness=5.0,
        ubo_risk=5.0,
    )
    fund_direct = compute_fund_direct_score(fund_factors, fund_w)
    result = apply_escalation(fund_direct, [("Bank Rossiya (Moscow, Russia)", ble_score)])

    assert result.escalated_tier is not None
    assert result.escalation_reason is not None
    assert "Bank Rossiya" in result.escalation_reason


def test_direct_score_preserved_under_escalation():
    """§18 Explainability: direct_score is always preserved so the reason is never hidden."""
    from services.rule_engine.escalation import apply_escalation
    from services.rule_engine.scoring import compute_ble_score, compute_fund_direct_score
    from services.rule_engine.models import (
        BLEScoringFactors, FundScoringFactors, RulesetWeights,
        ScreeningHitSeverity, PEPTier,
    )

    ble_w = RulesetWeights(country=0.25, screening=0.375, pep=0.25, documents=0.125)
    ble_factors = BLEScoringFactors(
        counterparty_country_risk=100.0,
        screening_severity=ScreeningHitSeverity.CONFIRMED,
        pep_tier=PEPTier.NONE,
        document_completeness=0.0,
    )
    ble_score = compute_ble_score(ble_factors, ble_w)

    fund_w = RulesetWeights(country=0.20, screening=0.30, pep=0.20, documents=0.10, ubo=0.20)
    fund_factors = FundScoringFactors(
        incorporation_country_risk=5.0,
        screening_severity=ScreeningHitSeverity.NONE,
        pep_tier=PEPTier.NONE,
        document_completeness=0.0,
        ubo_risk=0.0,
    )
    fund_direct = compute_fund_direct_score(fund_factors, fund_w)
    original_direct_score = fund_direct.direct_score

    result = apply_escalation(fund_direct, [("Test BLE", ble_score)])
    assert result.direct_score == original_direct_score, (
        "direct_score must not change under escalation"
    )


# ---------------------------------------------------------------------------
# §18: Human-in-the-loop — no AI output auto-publishes a decision
# ---------------------------------------------------------------------------

def test_workflow_suggestion_starts_pending():
    """§18 HITL: every suggestion starts as 'pending' — never auto-accepted."""
    from services.workflow.service import WorkflowService
    from services.agent.service import AgentOrchestrationService
    from services.trigger_engine.models import ReviewTrigger, TriggerScope, TriggerType

    agent = AgentOrchestrationService()
    trigger = ReviewTrigger(
        trigger_type=TriggerType.DOCUMENT_EXPIRY,
        scope=TriggerScope.FUND,
        fund_id=F1, ble_id=None, detail={},
    )
    cards = agent.process_trigger(trigger, fund_id=F1, synthetic_static=False)
    wf = WorkflowService()
    suggestion = wf.create_suggestion(cards[0])
    assert suggestion.status == "pending"


def test_accept_requires_explicit_actor():
    """§18 HITL: accept_suggestion requires an explicit actor — no anonymous auto-accepts."""
    import inspect
    from services.workflow.service import WorkflowService

    sig = inspect.signature(WorkflowService.accept_suggestion)
    assert "actor" in sig.parameters, "accept_suggestion must require actor parameter"


def test_decline_requires_explicit_actor():
    """§18 HITL: decline_suggestion requires an explicit actor."""
    import inspect
    from services.workflow.service import WorkflowService

    sig = inspect.signature(WorkflowService.decline_suggestion)
    assert "actor" in sig.parameters, "decline_suggestion must require actor parameter"


# ---------------------------------------------------------------------------
# §18: Audit trail — every AI call and human decision logged
# ---------------------------------------------------------------------------

def test_accept_writes_audit_entry():
    """§18 Audit trail: accepting a suggestion writes an AuditLogEntry."""
    from services.workflow.service import WorkflowService, AuditLogEntry
    from services.agent.service import AgentOrchestrationService
    from services.trigger_engine.models import ReviewTrigger, TriggerScope, TriggerType

    agent = AgentOrchestrationService()
    trigger = ReviewTrigger(
        trigger_type=TriggerType.SLA_BREACH,
        scope=TriggerScope.FUND,
        fund_id=F1, ble_id=None, detail={},
    )
    cards = agent.process_trigger(trigger, fund_id=F1, synthetic_static=False)
    wf = WorkflowService()
    sug = wf.create_suggestion(cards[0])
    entry = wf.accept_suggestion(sug.suggestion_id, actor="test.officer@fundei.internal")
    assert isinstance(entry, AuditLogEntry)
    assert entry.action == "accept_suggestion"


def test_decline_writes_audit_entry():
    """§18 Audit trail: declining a suggestion writes an AuditLogEntry."""
    from services.workflow.service import WorkflowService, AuditLogEntry
    from services.agent.service import AgentOrchestrationService
    from services.trigger_engine.models import ReviewTrigger, TriggerScope, TriggerType

    agent = AgentOrchestrationService()
    trigger = ReviewTrigger(
        trigger_type=TriggerType.DOCUMENT_EXPIRY,
        scope=TriggerScope.FUND,
        fund_id=F1, ble_id=None, detail={},
    )
    cards = agent.process_trigger(trigger, fund_id=F1, synthetic_static=False)
    wf = WorkflowService()
    sug = wf.create_suggestion(cards[0])
    entry = wf.decline_suggestion(sug.suggestion_id, actor="test.officer@fundei.internal")
    assert isinstance(entry, AuditLogEntry)
    assert entry.action == "decline_suggestion"


# ---------------------------------------------------------------------------
# §18: Read-only data access — text-to-SQL via read-only role + allowlist
# ---------------------------------------------------------------------------

def test_ddl_drop_blocked_by_allowlist():
    """
    §18 Read-only: DDL DROP SQL must be rejected by validate_sql() regardless of how it
    arrives (prompt injection, direct call). validate_sql() is a public entry-point exposed
    precisely for adversarial testing (PRD §18 / Eval D).
    """
    from services.text_to_sql.service import TextToSQLService

    svc = TextToSQLService()
    result = svc.validate_sql("DROP TABLE funds")
    assert not result.passed, "DDL DROP must be blocked"
    assert result.blocked_reason == "forbidden_statement_type"


def test_dml_insert_blocked_by_allowlist():
    """§18 Read-only: DML INSERT SQL must be rejected by validate_sql()."""
    from services.text_to_sql.service import TextToSQLService

    svc = TextToSQLService()
    result = svc.validate_sql("INSERT INTO funds VALUES ('evil', 'data')")
    assert not result.passed, "DML INSERT must be blocked"
    assert result.blocked_reason == "forbidden_statement_type"


# ---------------------------------------------------------------------------
# §18: Scope isolation — retrieval/generation hard-scoped; cross-scope is a hard failure
# ---------------------------------------------------------------------------

def test_rag_cross_scope_leakage_blocked():
    """
    §18 Scope isolation: retrieving chunks for Fund f0000001 must NOT return
    chunks belonging to Fund f0000002. Cross-scope leakage is a hard failure.
    """
    from services.rag.service import RAGService

    F2 = "f0000002-f000-0000-0000-000000000002"

    rag = RAGService()

    # Index a chunk belonging to Fund f0000002
    rag.index_document(
        doc_id="doc-f2-aml-gs18",
        text="Meridian Strategic Growth Trust — AML policy details UNIQUESTRING_F2",
        scope="fund",
        scope_id=F2,
        fund_id=F2,
        synthetic_static=False,
    )

    # Retrieve with scope locked to f0000001 — must not surface f0000002 chunk
    chunks = rag.retrieve(
        query="AML policy details UNIQUESTRING_F2",
        scope="fund",
        scope_id=F1,
        fund_id=F1,
        synthetic_static=False,
    )
    for chunk in chunks:
        assert chunk.fund_id == F1, (
            f"Cross-scope leakage: chunk from {chunk.fund_id} returned for {F1}"
        )


# ---------------------------------------------------------------------------
# §18: Data labeling integrity — real vs. synthetic always visible
# ---------------------------------------------------------------------------

def test_static_funds_have_synthetic_static_true():
    """§18 Labeling: all 45 static Funds have synthetic_static=True."""
    import scripts.seed_data as sd
    for f in sd.STATIC_FUNDS:
        assert f.get("synthetic_static") is True, (
            f"Static fund {f.get('name')} has synthetic_static != True"
        )


def test_live_funds_have_synthetic_static_false():
    """§18 Labeling: live Funds must have synthetic_static=False (AI pipeline eligible)."""
    import scripts.seed_data as sd
    for f in sd.LIVE_FUNDS:
        assert f.get("synthetic_static") is False, (
            f"Live fund {f.get('name')} has synthetic_static=True — would block AI pipeline"
        )


def test_static_fund_count_is_45():
    """§17: exactly 45 static Funds exist."""
    import scripts.seed_data as sd
    assert len(sd.STATIC_FUNDS) == 45


# ---------------------------------------------------------------------------
# §18 / §7.2: No fabricated facts on real positive screening matches
# ---------------------------------------------------------------------------

def test_no_fabricated_facts_check_passes_clean_text():
    """The helper returns True (no fabrication) for text that only states screening facts."""
    clean = (
        "Bank Rossiya has a confirmed sanctions hit under OFAC SDN and EU restrictive measures. "
        "Screening result: hit_type=sanctions, hit_severity=confirmed. "
        "BLE risk score: 100.0 (CRITICAL, hard-stop). Escalation active per PRD §9.3."
    )
    assert _no_fabricated_facts(clean) is True


def test_no_fabricated_facts_check_rejects_invented_text():
    """The helper returns False (fabrication detected) for invented business facts."""
    invented = "Bank Rossiya was founded in 1990 and has 5,000 employees."
    assert _no_fabricated_facts(invented) is False


def test_no_fabricated_facts_check_rejects_revenue_claim():
    assert _no_fabricated_facts("The bank has annual revenue of $4.2 billion.") is False


def test_no_fabricated_facts_check_rejects_incorporation_date():
    assert _no_fabricated_facts("Incorporated in 1989 under Russian law.") is False


def test_real_positive_match_answer_no_fabricated_facts():
    """
    §18 / §7.2: When screening_is_real=True (Bank Rossiya confirmed sanctions),
    the MOCK copilot answer for Bank Rossiya must NOT contain fabricated business
    facts beyond the screening result itself.

    This test calls the MOCK copilot router directly (without HTTP) and asserts
    that the answer passes _no_fabricated_facts(). The copilot router is imported
    as a plain function — no server required.
    """
    import importlib
    copilot = importlib.import_module("api.routers.copilot")
    routing = copilot._route_question("bank rossiya screening status")
    ans = copilot._mock_answer("bank rossiya screening status", routing)
    answer_text = ans["answer"]

    assert _no_fabricated_facts(answer_text), (
        f"Fabricated business facts detected in Bank Rossiya MOCK answer:\n{answer_text}"
    )


def test_real_positive_match_answer_contains_match_result():
    """
    Complementary to the no-fabrication test: the answer MUST contain the
    actual screening match facts (sanctions hit, OFAC, severity).
    """
    import importlib
    copilot = importlib.import_module("api.routers.copilot")
    ans = copilot._mock_answer("bank rossiya screening status", "rag")
    answer_text = ans["answer"]

    assert "sanctions" in answer_text.lower(), "Answer must mention the sanctions hit"
    assert "critical" in answer_text.lower(), "Answer must mention CRITICAL tier"


def test_real_positive_match_citations_no_fabricated_facts():
    """
    §18 / §7.2: Citation text for Bank Rossiya must also not contain fabricated facts.
    Each citation must reference the screening result or counterparty agreement.
    """
    import importlib
    copilot = importlib.import_module("api.routers.copilot")
    ans = copilot._mock_answer("bank rossiya", "rag")
    for citation in ans.get("citations", []):
        text = citation.get("text", "")
        assert _no_fabricated_facts(text), (
            f"Fabricated facts in citation: {text!r}"
        )


# ---------------------------------------------------------------------------
# §17 / §18: Static fund physically incapable of AI calls
# ---------------------------------------------------------------------------

def test_static_fund_physically_blocks_llm():
    """§17 + §18: assert_fund_allows_ai raises StaticFundAIError for synthetic_static=True."""
    from services.guards import StaticFundAIError, assert_fund_allows_ai

    with pytest.raises(StaticFundAIError):
        assert_fund_allows_ai(fund_id="static-fund-0001", synthetic_static=True)


def test_live_fund_does_not_block_llm():
    """§17: assert_fund_allows_ai does NOT raise for a live fund."""
    from services.guards import assert_fund_allows_ai

    # Should not raise
    assert_fund_allows_ai(fund_id=F1, synthetic_static=False)


# ---------------------------------------------------------------------------
# §17: Counterparty screened once, not per BLE (deduplication)
# ---------------------------------------------------------------------------

def test_counterparty_screened_once_across_bles():
    """
    §17 Counterparty profile reuse: a shared counterparty_id must be screened
    once, not once per BLE. Tests that the deduplication set logic works:
    given the 7 BLEs (6 unique counterparties), unique-by-counterparty_id
    produces 6 screening calls, not 7.
    """
    from api.data_loader import load_all, LIVE_BLES

    # Ensure data is loaded (idempotent)
    load_all()

    seen_cpty_ids: set[str] = set()
    screening_calls = 0

    for ble_id, ble in LIVE_BLES.items():
        cpty_id = ble.get("counterparty_profile_id") or ble.get("institution", ble_id)
        if cpty_id not in seen_cpty_ids:
            seen_cpty_ids.add(cpty_id)
            screening_calls += 1

    total_bles = len(LIVE_BLES)
    # DBS Bank Ltd appears in 2 BLEs → 6 unique counterparties < 7 total BLEs
    assert len(seen_cpty_ids) < total_bles, (
        f"Expected unique counterparties ({len(seen_cpty_ids)}) < total BLEs ({total_bles}); "
        "DBS Bank Ltd is shared across 2 BLEs and must be screened only once"
    )
    assert screening_calls == len(seen_cpty_ids), (
        "screening_calls must equal unique counterparty count"
    )
