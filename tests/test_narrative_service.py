"""
Tests for NarrativeService (services/narrative/service.py).

All tests run in MOCK mode — no LLM call, no real API cost.
Real-path tests monkeypatch call_llm to verify the prompt shape and response
parsing without touching any external API.
"""

from __future__ import annotations

import json
import os
import pytest

os.environ.setdefault("MOCK", "true")

from services.narrative.service import (
    MOCK,
    Citation,
    DocumentInput,
    JudgeResult,
    NarrativeResult,
    NarrativeService,
    _build_judge_prompt,
    _build_narrative_prompt,
    _mock_generate,
    _mock_judge,
    _parse_judge_response,
    _parse_narrative_response,
    _validate_generate_inputs,
)
from services.budget import BudgetCap
from services.guards import StaticFundAIError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def svc() -> NarrativeService:
    return NarrativeService()


@pytest.fixture()
def budget() -> BudgetCap:
    return BudgetCap(limit_usd=5.0)


@pytest.fixture()
def doc1() -> DocumentInput:
    return DocumentInput(
        doc_id="doc-test-01",
        document_type="Incorporation Certificate",
        text="Registration Number:     EX-TEST-001\nDate of Incorporation:   2020-01-01",
    )


@pytest.fixture()
def doc2() -> DocumentInput:
    return DocumentInput(
        doc_id="doc-test-02",
        document_type="UBO Declaration",
        text="Name:               Alice Tester\n  Ownership Interest: 55.0%",
    )


FUND_ID = "f0000001-f000-0000-0000-000000000001"
SCOPE_ID_FUND = "f0000001-f000-0000-0000-000000000001"
SCOPE_ID_BLE = "b0001001-b000-0000-0000-000000000001"


# ===========================================================================
# Section 1 — MOCK flag
# ===========================================================================

def test_mock_flag_is_bool():
    assert isinstance(MOCK, bool)


def test_mock_flag_default_true():
    assert MOCK is True


# ===========================================================================
# Section 2 — generate() basics (MOCK mode)
# ===========================================================================

def test_generate_returns_narrative_result(svc, budget, doc1):
    result = svc.generate(
        scope="fund", scope_id=SCOPE_ID_FUND, fund_id=FUND_ID,
        synthetic_static=False, documents=[doc1], risk_tier="low", budget=budget,
    )
    assert isinstance(result, NarrativeResult)


def test_generate_correct_scope(svc, budget, doc1):
    result = svc.generate(
        scope="fund", scope_id=SCOPE_ID_FUND, fund_id=FUND_ID,
        synthetic_static=False, documents=[doc1], risk_tier="low", budget=budget,
    )
    assert result.scope == "fund"
    assert result.scope_id == SCOPE_ID_FUND


def test_generate_narrative_nonempty(svc, budget, doc1):
    result = svc.generate(
        scope="fund", scope_id=SCOPE_ID_FUND, fund_id=FUND_ID,
        synthetic_static=False, documents=[doc1], risk_tier="low", budget=budget,
    )
    assert len(result.narrative) > 0


def test_generate_is_mock_true(svc, budget, doc1):
    result = svc.generate(
        scope="fund", scope_id=SCOPE_ID_FUND, fund_id=FUND_ID,
        synthetic_static=False, documents=[doc1], risk_tier="low", budget=budget,
    )
    assert result.is_mock is True


def test_generate_run_at_nonempty(svc, budget, doc1):
    result = svc.generate(
        scope="fund", scope_id=SCOPE_ID_FUND, fund_id=FUND_ID,
        synthetic_static=False, documents=[doc1], risk_tier="low", budget=budget,
    )
    assert result.run_at != ""


# ===========================================================================
# Section 3 — MOCK narrative content
# ===========================================================================

def test_mock_narrative_contains_doc1_text(svc, budget, doc1):
    result = svc.generate(
        scope="fund", scope_id=SCOPE_ID_FUND, fund_id=FUND_ID,
        synthetic_static=False, documents=[doc1], risk_tier="low", budget=budget,
    )
    assert "EX-TEST-001" in result.narrative


def test_mock_narrative_contains_doc2_text_when_two_docs(svc, budget, doc1, doc2):
    result = svc.generate(
        scope="fund", scope_id=SCOPE_ID_FUND, fund_id=FUND_ID,
        synthetic_static=False, documents=[doc1, doc2], risk_tier="medium", budget=budget,
    )
    assert "Alice Tester" in result.narrative
    assert "EX-TEST-001" in result.narrative


def test_mock_narrative_contains_golden_citation_substring(svc, budget):
    # Use the actual qa-f1-01 citation_substring from golden_qa.jsonl
    citation_substring = "Registration Number:     EX-CYM-2019-08742"
    doc = DocumentInput(
        doc_id="doc-f1-incorp-cert",
        document_type="Incorporation Certificate",
        text=f"Some header\n{citation_substring}\nSome footer",
    )
    result = svc.generate(
        scope="fund", scope_id=SCOPE_ID_FUND, fund_id=FUND_ID,
        synthetic_static=False, documents=[doc], risk_tier="low", budget=budget,
    )
    assert citation_substring in result.narrative


# ===========================================================================
# Section 4 — Citation structure
# ===========================================================================

def test_citations_list_nonempty(svc, budget, doc1):
    result = svc.generate(
        scope="fund", scope_id=SCOPE_ID_FUND, fund_id=FUND_ID,
        synthetic_static=False, documents=[doc1], risk_tier="low", budget=budget,
    )
    assert len(result.citations) > 0


def test_citations_have_required_fields(svc, budget, doc1):
    result = svc.generate(
        scope="fund", scope_id=SCOPE_ID_FUND, fund_id=FUND_ID,
        synthetic_static=False, documents=[doc1], risk_tier="low", budget=budget,
    )
    for c in result.citations:
        assert isinstance(c, Citation)
        assert c.claim != ""
        assert c.doc_id != ""
        assert c.citation_text != ""


def test_citation_doc_id_matches_input(svc, budget, doc1):
    result = svc.generate(
        scope="fund", scope_id=SCOPE_ID_FUND, fund_id=FUND_ID,
        synthetic_static=False, documents=[doc1], risk_tier="low", budget=budget,
    )
    doc_ids_in_citations = {c.doc_id for c in result.citations}
    assert "doc-test-01" in doc_ids_in_citations


# ===========================================================================
# Section 5 — Escalation context (fund scope)
# ===========================================================================

def test_ble_scope_generate_does_not_require_escalation_args(svc, budget, doc1):
    # BLE-scope narrative — escalation args are all optional and default to None
    result = svc.generate(
        scope="ble", scope_id=SCOPE_ID_BLE, fund_id=FUND_ID,
        synthetic_static=False, documents=[doc1], risk_tier="critical", budget=budget,
    )
    assert isinstance(result, NarrativeResult)
    assert result.scope == "ble"


def test_escalation_args_accepted_for_fund_scope(svc, budget, doc1):
    # Fund-scope with escalation context — should not raise
    result = svc.generate(
        scope="fund", scope_id=SCOPE_ID_FUND, fund_id=FUND_ID,
        synthetic_static=False, documents=[doc1], risk_tier="critical",
        direct_tier="low",
        escalation_reason="Escalated to Critical due to BLE(s): Bank Rossiya (Moscow, Russia)",
        escalated_ble_names=["Bank Rossiya (Moscow, Russia)"],
        budget=budget,
    )
    assert result.scope == "fund"


# ===========================================================================
# Section 6 — Validation errors
# ===========================================================================

def test_empty_documents_raises_value_error(svc, budget):
    with pytest.raises(ValueError, match="documents must contain at least one"):
        svc.generate(
            scope="fund", scope_id=SCOPE_ID_FUND, fund_id=FUND_ID,
            synthetic_static=False, documents=[], risk_tier="low", budget=budget,
        )


def test_bad_scope_raises_value_error(svc, budget, doc1):
    with pytest.raises(ValueError, match="scope must be"):
        svc.generate(
            scope="both", scope_id=SCOPE_ID_FUND, fund_id=FUND_ID,
            synthetic_static=False, documents=[doc1], risk_tier="low", budget=budget,
        )


def test_static_fund_guard_fires(svc, budget, doc1):
    with pytest.raises(StaticFundAIError):
        svc.generate(
            scope="fund", scope_id="static-001", fund_id="static-001",
            synthetic_static=True, documents=[doc1], risk_tier="low", budget=budget,
        )


def test_empty_scope_id_raises_value_error(svc, budget, doc1):
    with pytest.raises(ValueError, match="scope_id must not be empty"):
        svc.generate(
            scope="fund", scope_id="   ", fund_id=FUND_ID,
            synthetic_static=False, documents=[doc1], risk_tier="low", budget=budget,
        )


# ===========================================================================
# Section 7 — judge() MOCK mode
# ===========================================================================

def _make_narrative(text: str) -> NarrativeResult:
    return NarrativeResult(
        scope="fund", scope_id=SCOPE_ID_FUND, narrative=text,
        citations=[], model="claude-sonnet-4-6", prompt_version="narrative-v1",
        is_mock=True, run_at="2026-06-20T00:00:00+00:00",
    )


def test_judge_returns_judge_result(svc, budget):
    nr = _make_narrative("The registration number is EX-CYM-2019-08742.")
    result = svc.judge(
        narrative_result=nr, citation_substring="EX-CYM-2019-08742",
        qa_id="qa-test-01", fund_id=FUND_ID, synthetic_static=False, budget=budget,
    )
    assert isinstance(result, JudgeResult)


def test_judge_passes_when_substring_in_narrative(svc, budget):
    nr = _make_narrative("The registration number is EX-CYM-2019-08742.")
    result = svc.judge(
        narrative_result=nr, citation_substring="EX-CYM-2019-08742",
        qa_id="qa-test-01", fund_id=FUND_ID, synthetic_static=False, budget=budget,
    )
    assert result.passed is True
    assert result.is_hallucination is False


def test_judge_fails_when_substring_not_in_narrative(svc, budget):
    nr = _make_narrative("The registration number is EX-CYM-2019-08742.")
    result = svc.judge(
        narrative_result=nr, citation_substring="COMPLETELY MISSING TEXT",
        qa_id="qa-test-02", fund_id=FUND_ID, synthetic_static=False, budget=budget,
    )
    assert result.passed is False
    assert result.is_hallucination is True


def test_judge_is_hallucination_on_failure(svc, budget):
    nr = _make_narrative("Short narrative with no relevant data.")
    result = svc.judge(
        narrative_result=nr, citation_substring="Name:               Werner Mueller",
        qa_id="qa-test-03", fund_id=FUND_ID, synthetic_static=False, budget=budget,
    )
    assert result.is_hallucination is True
    assert result.passed is False


def test_judge_empty_citation_substring_raises(svc, budget):
    nr = _make_narrative("Some narrative text.")
    with pytest.raises(ValueError, match="citation_substring must not be empty"):
        svc.judge(
            narrative_result=nr, citation_substring="  ",
            qa_id="qa-test-04", fund_id=FUND_ID, synthetic_static=False, budget=budget,
        )


def test_judge_is_mock_true(svc, budget):
    nr = _make_narrative("Some narrative text with the target.")
    result = svc.judge(
        narrative_result=nr, citation_substring="the target",
        qa_id="qa-test-05", fund_id=FUND_ID, synthetic_static=False, budget=budget,
    )
    assert result.is_mock is True


# ===========================================================================
# Section 8 — Planted imperfection entries pass MOCK judge
# ===========================================================================

def test_planted_f2_07_mock_judge_passes(svc, budget):
    # qa-f2-07: citation_substring contains "25.0%" (planted) which IS in the doc
    planted_text = "Name:               Werner Mueller\n  Ownership Interest: 25.0%"
    nr = _make_narrative(f"Some header\n{planted_text}\nSome footer")
    result = svc.judge(
        narrative_result=nr, citation_substring=planted_text,
        qa_id="qa-f2-07", fund_id=FUND_ID, synthetic_static=False, budget=budget,
    )
    assert result.passed is True


def test_planted_f4_06_mock_judge_passes(svc, budget):
    # qa-f4-06: citation_substring contains "2025-07-08" (planted) which IS in the doc
    planted_text = "Expiry Date:       2025-07-08"
    nr = _make_narrative(f"Some licence details\n{planted_text}\nEnd.")
    result = svc.judge(
        narrative_result=nr, citation_substring=planted_text,
        qa_id="qa-f4-06", fund_id=FUND_ID, synthetic_static=False, budget=budget,
    )
    assert result.passed is True


# ===========================================================================
# Section 9 — Real path (monkeypatched call_llm)
# ===========================================================================

def _make_narrative_llm_response() -> dict:
    payload = {
        "narrative": "The fund was incorporated in the Cayman Islands.",
        "citations": [
            {
                "claim": "The fund was incorporated in the Cayman Islands.",
                "doc_id": "doc-test-01",
                "citation_text": "Jurisdiction: Cayman Islands",
            }
        ],
    }
    return {
        "content": json.dumps(payload),
        "model": "claude-sonnet-4-6",
        "usage": {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
        "is_mock": False,
    }


def _make_judge_llm_response(passes: bool) -> dict:
    payload = {
        "passes": passes,
        "is_hallucination": not passes,
        "reason": None if passes else "substring not found",
    }
    return {
        "content": json.dumps(payload),
        "model": "claude-haiku-4-5-20251001",
        "usage": {"input_tokens": 50, "output_tokens": 10, "total_tokens": 60},
        "is_mock": False,
    }


def test_generate_real_path_calls_call_llm(monkeypatch, doc1, budget):
    import services.narrative.service as ns_module
    calls = []

    def fake_call_llm(**kwargs):
        calls.append(kwargs)
        return _make_narrative_llm_response()

    monkeypatch.setattr(ns_module, "MOCK", False)
    monkeypatch.setattr(ns_module, "call_llm", fake_call_llm)

    svc = NarrativeService()
    result = svc.generate(
        scope="fund", scope_id=SCOPE_ID_FUND, fund_id=FUND_ID,
        synthetic_static=False, documents=[doc1], risk_tier="low", budget=budget,
    )
    assert len(calls) == 1
    assert calls[0]["model"] == "claude-sonnet-4-6"
    assert result.is_mock is False
    assert "Cayman Islands" in result.narrative


def test_judge_real_path_calls_haiku(monkeypatch, budget):
    import services.narrative.service as ns_module

    judge_calls = []

    def fake_call_llm(**kwargs):
        judge_calls.append(kwargs)
        return _make_judge_llm_response(passes=True)

    monkeypatch.setattr(ns_module, "MOCK", False)
    monkeypatch.setattr(ns_module, "call_llm", fake_call_llm)

    svc = NarrativeService()
    nr = NarrativeResult(
        scope="fund", scope_id=SCOPE_ID_FUND,
        narrative="The fund was incorporated in the Cayman Islands.",
        citations=[], model="claude-sonnet-4-6",
        prompt_version="narrative-v1", is_mock=False,
        run_at="2026-06-20T00:00:00+00:00",
    )
    result = svc.judge(
        narrative_result=nr, citation_substring="Cayman Islands",
        qa_id="qa-real-01", fund_id=FUND_ID, synthetic_static=False, budget=budget,
    )
    assert len(judge_calls) == 1
    assert judge_calls[0]["model"] == "claude-haiku-4-5-20251001"
    assert result.passed is True
    assert result.is_mock is False


# ===========================================================================
# Section 10 — Budget default
# ===========================================================================

def test_generate_uses_default_budget_when_none(svc, doc1):
    # Should not raise — default $2.00 is plenty for MOCK mode
    result = svc.generate(
        scope="fund", scope_id=SCOPE_ID_FUND, fund_id=FUND_ID,
        synthetic_static=False, documents=[doc1], risk_tier="low",
        budget=None,
    )
    assert isinstance(result, NarrativeResult)


def test_judge_uses_default_budget_when_none(svc):
    nr = _make_narrative("Test narrative with target text.")
    result = svc.judge(
        narrative_result=nr, citation_substring="target text",
        qa_id="qa-budget-01", fund_id=FUND_ID, synthetic_static=False,
        budget=None,
    )
    assert result.passed is True
