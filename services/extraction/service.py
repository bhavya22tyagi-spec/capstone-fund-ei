"""
Extraction Service — PRD §8.2.

Structured field extraction from compliance documents using
claude-haiku-4-5-20251001 (cheapest viable tier, CLAUDE.md locked).

All LLM calls route through services.ai_client.call_llm(), which enforces:
  - synthetic_static fund guard
  - per-run budget cap
  - cost logging
  - bounded retry with exponential backoff

MOCK=true (default): returns canned type-specific responses; no file I/O, no
  LLM call, zero cost. Used for all tests and dev runs.
MOCK=false: reads the document file, builds an extraction prompt, calls the
  LLM, and parses the JSON response.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from services.ai_client import call_llm
from services.budget import BudgetCap
from services.guards import assert_fund_allows_ai
from services.idempotency import is_already_processed, mark_processed

MOCK: bool = os.getenv("MOCK", "true").lower() == "true"

_MODEL = "claude-haiku-4-5-20251001"
_PROMPT_VERSION = "extraction-v1"

# In-process result cache: "{doc_id}:{prompt_version}" -> extracted dict
_result_cache: dict[str, dict] = {}

# ---------------------------------------------------------------------------
# Per-document-type field schemas (used in the extraction prompt)
# ---------------------------------------------------------------------------

_SCHEMAS: dict[str, str] = {
    "Incorporation Certificate": """{
  "entity_name": "string — legal entity name",
  "incorporation_date": "string — YYYY-MM-DD",
  "registration_number": "string — registration reference number",
  "legal_form": "string — e.g. Exempted Limited Partnership, QIAIF, Private Limited Company",
  "jurisdiction_country_code": "string — ISO 3-letter code e.g. CYM, IRL, MLT",
  "registered_address": "string — full registered address as a single string",
  "authorized_representative_name": "string — name of authorized representative",
  "authorized_representative_title": "string — title of authorized representative"
}""",

    "UBO Declaration": """{
  "entity_name": "string — legal entity name",
  "ubos": [
    {
      "name": "string — UBO or holding entity name",
      "ownership_pct": "number or null — direct ownership percentage (null if unknown)",
      "layer_depth": "integer — 1=direct owner, 2=indirect via a layer-1 entity, etc.",
      "resolved": "boolean — true if beneficial owner is fully identified",
      "pep_tier": "integer 0-3 — PEP risk tier (0=none, 1=highest risk PEP, 3=lowest risk PEP)",
      "jurisdiction": "string or null — ISO 3-letter country code, null if unknown"
    }
  ]
}""",

    "Counterparty Agreement": """{
  "fund_name": "string — name of the fund party",
  "counterparty_name": "string — name of the counterparty institution",
  "counterparty_location": "string — city, country",
  "agreement_date": "string — YYYY-MM-DD",
  "agreement_ref": "string — agreement reference code",
  "facility_type": "string — e.g. Loan, Cash Management, Loan and Cash Management",
  "credit_facility_currency": "string or null — ISO currency code e.g. USD, null if not a credit facility",
  "credit_facility_amount": "number or null — credit limit as a plain number, null if not applicable"
}""",

    "Framework Agreement": """{
  "fund_name": "string — name of the fund party",
  "counterparty_name": "string — name of the counterparty institution",
  "counterparty_location": "string — city, country",
  "agreement_date": "string — YYYY-MM-DD",
  "agreement_ref": "string — agreement reference code",
  "facility_type": "string — e.g. Cash Management"
}""",

    "Annual Report": """{
  "entity_name": "string — legal entity name",
  "period": "string — e.g. FY 2024 (2024-01-01 to 2024-12-31)",
  "period_start": "string — YYYY-MM-DD",
  "period_end": "string — YYYY-MM-DD",
  "expiry_date": "string — KYB review expiry date YYYY-MM-DD",
  "status": "string — e.g. expired, verified"
}""",

    "Regulatory Licence": """{
  "entity_name": "string — entity the licence was issued to",
  "expiry_date": "string — licence expiry date YYYY-MM-DD",
  "status": "string — e.g. verified, expired"
}""",

    "Investment Manager Agreement": """{
  "entity_name": "string — name of the fund",
  "authorized_representative_name": "string — name of the authorized representative or managing partner",
  "authorized_representative_title": "string — title of the representative",
  "agreement_date": "string or null — agreement execution date YYYY-MM-DD, null if not stated in the document"
}""",
}

KNOWN_DOCUMENT_TYPES: frozenset[str] = frozenset(_SCHEMAS)

# ---------------------------------------------------------------------------
# Canned MOCK responses — returned in MOCK=true mode (no file I/O, no LLM)
# ---------------------------------------------------------------------------

_MOCK_EXTRACTIONS: dict[str, dict] = {
    "Incorporation Certificate": {
        "entity_name": "[MOCK] Sample Entity LP",
        "incorporation_date": "2020-01-15",
        "registration_number": "MOCK-REG-001",
        "legal_form": "Exempted Limited Partnership",
        "jurisdiction_country_code": "CYM",
        "registered_address": "1 Mock Street, George Town, Cayman Islands",
        "authorized_representative_name": "Mock Representative",
        "authorized_representative_title": "General Partner",
    },
    "UBO Declaration": {
        "entity_name": "[MOCK] Sample Entity LP",
        "ubos": [
            {
                "name": "Mock UBO Person",
                "ownership_pct": 100.0,
                "layer_depth": 1,
                "resolved": True,
                "pep_tier": 0,
                "jurisdiction": "GBR",
            }
        ],
    },
    "Counterparty Agreement": {
        "fund_name": "[MOCK] Sample Fund LP",
        "counterparty_name": "[MOCK] Sample Bank Ltd",
        "counterparty_location": "London, United Kingdom",
        "agreement_date": "2022-01-01",
        "agreement_ref": "MOCK-AGMT-001",
        "facility_type": "Loan",
        "credit_facility_currency": "USD",
        "credit_facility_amount": 1000000,
    },
    "Framework Agreement": {
        "fund_name": "[MOCK] Sample Fund LP",
        "counterparty_name": "[MOCK] Sample Bank Ltd",
        "counterparty_location": "Frankfurt, Germany",
        "agreement_date": "2021-01-01",
        "agreement_ref": "MOCK-FWK-001",
        "facility_type": "Cash Management",
    },
    "Annual Report": {
        "entity_name": "[MOCK] Sample Entity LP",
        "period": "FY 2024 (2024-01-01 to 2024-12-31)",
        "period_start": "2024-01-01",
        "period_end": "2024-12-31",
        "expiry_date": "2026-05-06",
        "status": "expired",
    },
    "Regulatory Licence": {
        "entity_name": "[MOCK] Sample Entity Ltd",
        "expiry_date": "2026-07-08",
        "status": "verified",
    },
    "Investment Manager Agreement": {
        "entity_name": "[MOCK] Sample Fund LP",
        "authorized_representative_name": "Mock Managing Partner",
        "authorized_representative_title": "Managing Partner",
        "agreement_date": "2020-06-01",
    },
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_document_fields(
    scope: str,
    scope_id: str,
    fund_id: str,
    document_type: str,
    file_path: "str | Path",
    doc_id: str,
    synthetic_static: bool = False,
    budget: "BudgetCap | None" = None,
) -> dict[str, Any]:
    """
    Extract structured fields from a compliance document.

    The static-fund guard (CLAUDE.md rule 10) runs in both MOCK and real modes
    — synthetic_static funds can never trigger this service.

    Args:
        scope:            "fund" or "ble"
        scope_id:         fund_id for fund-scope docs; ble_id for ble-scope docs
        fund_id:          parent fund's ID (always required for guard + logging)
        document_type:    one of KNOWN_DOCUMENT_TYPES
        file_path:        path to the .txt compliance document (real mode only)
        doc_id:           stable document identifier used for idempotency keying
        synthetic_static: if True, raises StaticFundAIError before any work
        budget:           per-run BudgetCap; a default $0.50 cap is used if None

    Returns:
        dict of extracted field values; fields absent from the document are null

    Raises:
        StaticFundAIError:  fund is tagged synthetic_static
        ValueError:         invalid scope or unknown document_type
        FileNotFoundError:  file_path does not exist (real mode only)
        json.JSONDecodeError: LLM returned non-parseable content (real mode only)
    """
    # Guard runs in both MOCK and real modes (CLAUDE.md rule 10)
    assert_fund_allows_ai(fund_id, synthetic_static)

    if scope not in ("fund", "ble"):
        raise ValueError(f"scope must be 'fund' or 'ble', got {scope!r}")
    if not scope_id:
        raise ValueError("scope_id must not be empty")
    if not fund_id:
        raise ValueError("fund_id must not be empty")
    if document_type not in _SCHEMAS:
        raise ValueError(
            f"Unknown document_type: {document_type!r}. "
            f"Known types: {sorted(_SCHEMAS)}"
        )

    if MOCK:
        return _mock_extract(document_type, doc_id)

    return _real_extract(
        scope=scope,
        scope_id=scope_id,
        fund_id=fund_id,
        document_type=document_type,
        file_path=Path(file_path),
        doc_id=doc_id,
        synthetic_static=synthetic_static,
        budget=budget if budget is not None else BudgetCap(limit_usd=0.50),
    )


def reset_cache() -> None:
    """Clear in-process result cache and idempotency state. Use between test cases."""
    _result_cache.clear()
    from services.idempotency import reset
    reset()


# ---------------------------------------------------------------------------
# Private — MOCK path
# ---------------------------------------------------------------------------

def _mock_extract(document_type: str, doc_id: str) -> dict[str, Any]:
    cache_key = f"{doc_id}:{_PROMPT_VERSION}"
    if cache_key in _result_cache:
        return _result_cache[cache_key]
    result: dict[str, Any] = json.loads(json.dumps(_MOCK_EXTRACTIONS[document_type]))
    _result_cache[cache_key] = result
    return result


# ---------------------------------------------------------------------------
# Private — real LLM path
# ---------------------------------------------------------------------------

def _real_extract(
    scope: str,
    scope_id: str,
    fund_id: str,
    document_type: str,
    file_path: Path,
    doc_id: str,
    synthetic_static: bool,
    budget: BudgetCap,
) -> dict[str, Any]:
    cache_key = f"{doc_id}:{_PROMPT_VERSION}"

    # Return cached result if already processed this session
    if is_already_processed(scope, doc_id, "extracted", _PROMPT_VERSION):
        if cache_key in _result_cache:
            return _result_cache[cache_key]

    if not file_path.exists():
        raise FileNotFoundError(f"Document not found: {file_path}")

    content = file_path.read_text(encoding="utf-8")
    prompt = _build_extraction_prompt(document_type, content)

    raw = call_llm(
        prompt=prompt,
        model=_MODEL,
        prompt_version=_PROMPT_VERSION,
        fund_id=fund_id,
        synthetic_static=synthetic_static,
        scope=scope,
        scope_id=scope_id,
        budget=budget,
        estimated_cost_usd=0.01,
    )

    extracted = _parse_json_response(raw["content"])

    _result_cache[cache_key] = extracted
    mark_processed(scope, doc_id, "extracted", _PROMPT_VERSION)

    return extracted


def _build_extraction_prompt(document_type: str, content: str) -> str:
    schema = _SCHEMAS[document_type]
    return (
        "You are a KYB compliance document field extractor.\n"
        "Extract the fields listed below from the provided document.\n"
        "Return ONLY a valid JSON object — no explanation, no markdown, no code blocks.\n"
        "Set any field not found in the document to null.\n\n"
        f"Document type: {document_type}\n\n"
        f"Fields to extract:\n{schema}\n\n"
        f"Document:\n---\n{content}\n---\n\n"
        "Return the JSON object now:"
    )


def _parse_json_response(content: str) -> dict[str, Any]:
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```[a-z]*\n?", "", content)
        content = re.sub(r"\n?```\s*$", "", content)
    return json.loads(content.strip())
