"""
PRD §8.2, §18 — Narrative Generation Service.

Drafts analyst-grade compliance narratives from KYB documents using
claude-sonnet-4-6 (stronger tier), then gates every factual claim through an
LLM-as-judge step using claude-haiku-4-5-20251001 (cost-efficient).

MOCK=true (default):
  generate() → concatenates all supplied document texts; zero LLM call.
  judge()    → checks citation_substring in narrative.narrative; zero LLM call.
  Both paths guarantee 100% Eval C pass rate — tests plumbing, not LLM quality.

MOCK=false:
  generate() → claude-sonnet-4-6 drafts structured JSON with narrative + citations.
  judge()    → claude-haiku-4-5-20251001 verifies each citation is grounded.

Security invariants (PRD §17, §18):
  - assert_fund_allows_ai() fires in generate() before any LLM call.
  - Scope is always explicit; no cross-scope retrieval path exists.
  - Every LLM call is logged via call_llm() → cost_logger.
  - No AI output auto-publishes; human Accept/Decline required (PRD §18).
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from services.ai_client import call_llm
from services.budget import BudgetCap
from services.guards import assert_fund_allows_ai

MOCK: bool = os.getenv("MOCK", "true").lower() == "true"

_NARRATIVE_MODEL = "claude-sonnet-4-6"
_JUDGE_MODEL = "claude-haiku-4-5-20251001"
_NARRATIVE_PROMPT_VERSION = "narrative-v1"
_JUDGE_PROMPT_VERSION = "judge-v1"

_DEFAULT_BUDGET_USD = 2.00


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class DocumentInput:
    doc_id: str
    document_type: str
    text: str


@dataclass
class Citation:
    claim: str
    doc_id: str
    citation_text: str  # verbatim text excerpted from the source document


@dataclass
class NarrativeResult:
    scope: str
    scope_id: str
    narrative: str
    citations: list[Citation]
    model: str
    prompt_version: str
    is_mock: bool
    run_at: str


@dataclass
class JudgeResult:
    qa_id: str
    passed: bool
    is_hallucination: bool
    reason: str | None
    is_mock: bool


# ---------------------------------------------------------------------------
# Public service
# ---------------------------------------------------------------------------

class NarrativeService:
    """
    Generates scope-bound compliance narratives and judges their groundedness.

    generate() — draft a narrative for a Fund or BLE given its documents.
    judge()    — verify that a specific citation substring is present and
                 accurately reflected in the narrative (LLM-as-judge or MOCK).

    Both methods must be called with explicit scope/scope_id — there is no
    cross-scope or unscoped path. (PRD §18)
    """

    # ------------------------------------------------------------------
    # Narrative generation
    # ------------------------------------------------------------------

    def generate(
        self,
        scope: str,
        scope_id: str,
        fund_id: str,
        synthetic_static: bool,
        documents: list[DocumentInput],
        risk_tier: str,
        direct_tier: str | None = None,
        escalation_reason: str | None = None,
        escalated_ble_names: list[str] | None = None,
        entity_name: str = "",
        screening_result: dict | None = None,
        budget: BudgetCap | None = None,
    ) -> NarrativeResult:
        """
        Draft a compliance narrative for the given scope.

        Args:
            scope:               "fund" or "ble"
            scope_id:            fund_id or ble_id
            fund_id:             parent fund ID (for static guard + cost log)
            synthetic_static:    True → StaticFundAIError raised before any work
            documents:           All documents for this scope (at least one required)
            risk_tier:           Effective risk tier (low/medium/high/critical)
            direct_tier:         Fund's direct tier before escalation (fund-scope only)
            escalation_reason:   Text explaining why Fund was escalated (fund-scope only)
            escalated_ble_names: BLE names that caused escalation (fund-scope only)
            budget:              Per-run cap; $2.00 default

        Returns:
            NarrativeResult with narrative text, citations, and metadata.

        Raises:
            ValueError:         bad scope, empty scope_id, or empty documents list
            StaticFundAIError:  fund is tagged synthetic_static
            BudgetExceededError: cost would breach cap
        """
        _validate_generate_inputs(scope, scope_id, documents)
        assert_fund_allows_ai(fund_id, synthetic_static)

        _budget = budget if budget is not None else BudgetCap(limit_usd=_DEFAULT_BUDGET_USD)

        if MOCK:
            return _mock_generate(scope, scope_id, documents)

        return _real_generate(
            scope=scope,
            scope_id=scope_id,
            fund_id=fund_id,
            synthetic_static=synthetic_static,
            documents=documents,
            risk_tier=risk_tier,
            direct_tier=direct_tier,
            escalation_reason=escalation_reason,
            escalated_ble_names=escalated_ble_names,
            entity_name=entity_name,
            screening_result=screening_result,
            budget=_budget,
        )

    # ------------------------------------------------------------------
    # LLM-as-judge
    # ------------------------------------------------------------------

    def judge(
        self,
        narrative_result: NarrativeResult,
        citation_substring: str,
        qa_id: str,
        fund_id: str,
        synthetic_static: bool,
        budget: BudgetCap | None = None,
    ) -> JudgeResult:
        """
        Verify that citation_substring is accurately reflected in the narrative.

        The static fund guard is NOT applied to judge() — judging reads an
        already-generated narrative string and does not access Fund documents
        directly. The fund_id/synthetic_static args are used only for cost logging.

        Args:
            narrative_result:   Output of generate() for this scope.
            citation_substring: Verbatim text expected to appear in the narrative
                                (taken from golden_qa.jsonl citation_substring field).
            qa_id:              Golden QA entry ID (for logging).
            fund_id:            Parent fund ID (for cost logging only).
            synthetic_static:   Not checked — judge reads a string, not a Fund doc.
            budget:             Per-run cap; $2.00 default.

        Returns:
            JudgeResult — passed=True means grounded; is_hallucination=True means
            the narrative made a claim unsupported by the cited document.
        """
        if not citation_substring or not citation_substring.strip():
            raise ValueError("citation_substring must not be empty")

        _budget = budget if budget is not None else BudgetCap(limit_usd=_DEFAULT_BUDGET_USD)

        if MOCK:
            return _mock_judge(narrative_result, citation_substring, qa_id)

        return _real_judge(
            narrative_result=narrative_result,
            citation_substring=citation_substring,
            qa_id=qa_id,
            fund_id=fund_id,
            synthetic_static=synthetic_static,
            budget=_budget,
        )


# ---------------------------------------------------------------------------
# Private — validation
# ---------------------------------------------------------------------------

def _validate_generate_inputs(
    scope: str, scope_id: str, documents: list[DocumentInput]
) -> None:
    if scope not in ("fund", "ble"):
        raise ValueError(f"scope must be 'fund' or 'ble', got {scope!r}")
    if not scope_id or not scope_id.strip():
        raise ValueError("scope_id must not be empty")
    if not documents:
        raise ValueError("documents must contain at least one DocumentInput")


# ---------------------------------------------------------------------------
# Private — MOCK paths
# ---------------------------------------------------------------------------

def _mock_generate(
    scope: str,
    scope_id: str,
    documents: list[DocumentInput],
) -> NarrativeResult:
    """
    Concatenate all document texts.

    This guarantees that every verbatim citation_substring from the 55
    golden_qa.jsonl entries is present in the narrative — Eval C MOCK
    judge can then confirm groundedness with a simple substring check.
    """
    narrative_text = "\n\n".join(doc.text for doc in documents)
    citations = [
        Citation(
            claim="[MOCK CLAIM]",
            doc_id=doc.doc_id,
            citation_text=doc.text[:200],
        )
        for doc in documents
    ]
    return NarrativeResult(
        scope=scope,
        scope_id=scope_id,
        narrative=narrative_text,
        citations=citations,
        model=_NARRATIVE_MODEL,
        prompt_version=_NARRATIVE_PROMPT_VERSION,
        is_mock=True,
        run_at=datetime.now(timezone.utc).isoformat(),
    )


def _mock_judge(
    narrative_result: NarrativeResult,
    citation_substring: str,
    qa_id: str,
) -> JudgeResult:
    """
    Substring check: citation_substring must appear verbatim in the narrative.

    For planted imperfection entries (qa-f2-07: 25.0%, qa-f4-06: 2025-07-08)
    the citation_substring IS the planted document value, which IS in the
    MOCK narrative (concatenated doc texts) → correctly passes.
    """
    passed = citation_substring in narrative_result.narrative
    return JudgeResult(
        qa_id=qa_id,
        passed=passed,
        is_hallucination=not passed,
        reason=None if passed else "citation_substring not found in narrative",
        is_mock=True,
    )


# ---------------------------------------------------------------------------
# Private — real LLM paths
# ---------------------------------------------------------------------------

def _real_generate(
    scope: str,
    scope_id: str,
    fund_id: str,
    synthetic_static: bool,
    documents: list[DocumentInput],
    risk_tier: str,
    direct_tier: str | None,
    escalation_reason: str | None,
    escalated_ble_names: list[str] | None,
    entity_name: str = "",
    screening_result: dict | None = None,
    budget: BudgetCap | None = None,
) -> NarrativeResult:
    prompt = _build_narrative_prompt(
        scope=scope,
        documents=documents,
        risk_tier=risk_tier,
        direct_tier=direct_tier,
        escalation_reason=escalation_reason,
        escalated_ble_names=escalated_ble_names,
        entity_name=entity_name,
        screening_result=screening_result,
    )
    raw = call_llm(
        prompt=prompt,
        model=_NARRATIVE_MODEL,
        prompt_version=_NARRATIVE_PROMPT_VERSION,
        fund_id=fund_id,
        synthetic_static=synthetic_static,
        scope=scope,
        scope_id=scope_id,
        budget=budget,
        estimated_cost_usd=0.15,
    )
    parsed = _parse_narrative_response(raw["content"])
    citations = [
        Citation(
            claim=c.get("claim", ""),
            doc_id=c.get("doc_id", ""),
            citation_text=c.get("citation_text", ""),
        )
        for c in parsed.get("citations", [])
    ]
    return NarrativeResult(
        scope=scope,
        scope_id=scope_id,
        narrative=parsed.get("narrative", ""),
        citations=citations,
        model=_NARRATIVE_MODEL,
        prompt_version=_NARRATIVE_PROMPT_VERSION,
        is_mock=False,
        run_at=datetime.now(timezone.utc).isoformat(),
    )


def _real_judge(
    narrative_result: NarrativeResult,
    citation_substring: str,
    qa_id: str,
    fund_id: str,
    synthetic_static: bool,
    budget: BudgetCap,
) -> JudgeResult:
    prompt = _build_judge_prompt(narrative_result.narrative, citation_substring)
    raw = call_llm(
        prompt=prompt,
        model=_JUDGE_MODEL,
        prompt_version=_JUDGE_PROMPT_VERSION,
        fund_id=fund_id,
        synthetic_static=synthetic_static,
        scope=narrative_result.scope,
        scope_id=narrative_result.scope_id,
        budget=budget,
        estimated_cost_usd=0.002,
    )
    parsed = _parse_judge_response(raw["content"])
    passed = bool(parsed.get("passes", False))
    is_hallucination = bool(parsed.get("is_hallucination", not passed))
    return JudgeResult(
        qa_id=qa_id,
        passed=passed,
        is_hallucination=is_hallucination,
        reason=parsed.get("reason"),
        is_mock=False,
    )


# ---------------------------------------------------------------------------
# Private — prompt builders
# ---------------------------------------------------------------------------

def _format_screening_block(sr: dict) -> str:
    """Format a live OpenSanctions result entry into a narrative prompt instruction."""
    result = sr.get("result", "unknown")
    if result == "hit":
        severity = sr.get("severity") or "unknown"
        hit_type = sr.get("hit_type") or "unknown"
        datasets = ", ".join(sr.get("datasets", [])) or "unknown"
        match_name = sr.get("match_name") or "unknown"
        return (
            f"\nLIVE SCREENING RESULT (OpenSanctions — authoritative):\n"
            f"  Status:    HIT\n"
            f"  Severity:  {severity}\n"
            f"  Hit type:  {hit_type}\n"
            f"  Datasets:  {datasets}\n"
            f"  Match:     {match_name}\n"
            f"You MUST mention this sanctions/PEP hit in the narrative. "
            f"This is externally verified data — not from the documents.\n"
        )
    if result == "clean":
        return (
            "\nLIVE SCREENING RESULT (OpenSanctions — authoritative):\n"
            "  Status:    CLEAN — no sanctions or PEP hits found\n"
            "You SHOULD note the clean screening result in the narrative.\n"
        )
    return (
        f"\nLIVE SCREENING RESULT:\n"
        f"  Status:    {result} (screening unavailable or error)\n"
    )


def _build_narrative_prompt(
    scope: str,
    documents: list[DocumentInput],
    risk_tier: str,
    direct_tier: str | None,
    escalation_reason: str | None,
    escalated_ble_names: list[str] | None,
    entity_name: str = "",
    screening_result: dict | None = None,
) -> str:
    doc_sections = "\n\n".join(
        f"--- Document: {doc.doc_id} ({doc.document_type}) ---\n{doc.text}"
        for doc in documents
    )

    escalation_block = ""
    if scope == "fund" and escalation_reason:
        ble_list = ", ".join(escalated_ble_names or [])
        escalation_block = (
            f"\nESCALATION CONTEXT:\n"
            f"  Direct fund tier: {direct_tier}\n"
            f"  Effective tier:   {risk_tier} (escalated)\n"
            f"  Reason:           {escalation_reason}\n"
            f"  Escalating BLEs:  {ble_list}\n"
        )

    screening_block = ""
    if screening_result is not None:
        screening_block = _format_screening_block(screening_result)

    return (
        "You are a KYB compliance analyst drafting a structured review narrative.\n"
        "Use ONLY the documents provided below for document-based facts. "
        "Externally verified data (e.g. live screening results) may also be cited.\n"
        "Every factual claim drawn from documents must be supported by verbatim text "
        "from one of the documents.\n\n"
        f"Scope:      {scope}\n"
        + (f"Entity:     {entity_name}\n" if entity_name else "")
        + f"Risk tier:  {risk_tier}\n"
        f"{escalation_block}"
        f"{screening_block}\n"
        "Return a JSON object with exactly two keys:\n"
        '  "narrative": string — the analyst narrative (2-4 paragraphs)\n'
        '  "citations": array of objects, each with:\n'
        '      "claim":         the sentence in the narrative containing the claim\n'
        '      "doc_id":        the document ID the claim is drawn from\n'
        '      "citation_text": the verbatim text from the document supporting the claim\n\n'
        "Return ONLY valid JSON — no markdown, no code fences, no explanation.\n\n"
        f"Documents:\n{doc_sections}\n\n"
        "JSON:"
    )


def _build_judge_prompt(narrative: str, citation_substring: str) -> str:
    return (
        "You are a KYB compliance audit judge.\n"
        "Your task: verify that the following citation text is accurately reflected "
        "in the narrative below.\n\n"
        f"Citation text to verify:\n{citation_substring}\n\n"
        f"Narrative:\n{narrative}\n\n"
        "Return a JSON object with exactly three keys:\n"
        '  "passes":          true if the narrative accurately reflects the citation, '
        "false otherwise\n"
        '  "is_hallucination": true if the narrative makes a claim CONTRADICTING or '
        "UNSUPPORTED BY the citation\n"
        '  "reason":          one sentence explaining your verdict (or null if passes=true)\n\n'
        "Return ONLY valid JSON — no markdown, no code fences.\n\n"
        "JSON:"
    )


# ---------------------------------------------------------------------------
# Private — response parsers
# ---------------------------------------------------------------------------

def _parse_narrative_response(content: str) -> dict[str, Any]:
    content = content.strip()
    content = re.sub(r"^```[a-z]*\s*", "", content, flags=re.IGNORECASE)
    content = re.sub(r"\s*```\s*$", "", content)
    return json.loads(content.strip())


def _parse_judge_response(content: str) -> dict[str, Any]:
    content = content.strip()
    content = re.sub(r"^```[a-z]*\s*", "", content, flags=re.IGNORECASE)
    content = re.sub(r"\s*```\s*$", "", content)
    return json.loads(content.strip())
