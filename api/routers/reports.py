"""
Analyst Report API — PRD §13.3.

Endpoints:
  GET  /analyst-reports/fund/{fund_id}                — Fund-scoped narrative + risk breakdown
  GET  /analyst-reports/ble/{ble_id}                  — BLE-scoped narrative + risk breakdown
  POST /analyst-reports/{scope}/{scope_id}/decision   — Log analyst Accept/Reject/Edit (PRD §18)

Both GET endpoints:
  - Enforce static fund guard (HTTP 403 before NarrativeService is called)
  - Load documents from disk (documents/fund/ or documents/ble/)
  - Call NarrativeService.generate() — MOCK mode by default, zero cost
  - Return AnalystReport with narrative, citations, factor scores, doc status
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException

from api.data_loader import get_fund, get_ble
from api.deps import append_decision
from api.models import AnalystReport, DecisionRecord, DecisionRequest, DocumentInfo, ReportCitation
from services.narrative.service import NarrativeService, DocumentInput

router = APIRouter()

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_DOCS_ROOT = _PROJECT_ROOT / "documents"

_narrative_svc = NarrativeService()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_documents(
    doc_list: list[dict],
    scope: str,
    scope_id: str,
    entity_name: str = "",
) -> list[DocumentInput]:
    """Read .txt document files for the scope; skip missing files gracefully."""
    docs: list[DocumentInput] = []
    base = _DOCS_ROOT / scope / scope_id
    for doc in doc_list:
        path = base / f"{doc['doc_id']}.txt"
        if path.exists():
            docs.append(DocumentInput(
                doc_id=doc["doc_id"],
                document_type=doc.get("document_type", "Document"),
                text=path.read_text(encoding="utf-8"),
            ))
    if not docs:
        label = entity_name or scope_id
        docs.append(DocumentInput(
            doc_id="fallback",
            document_type="Summary",
            text=f"No documents are currently available for {label}.",
        ))
    return docs


def _to_doc_info(doc: dict) -> DocumentInfo:
    return DocumentInfo(
        doc_id=doc["doc_id"],
        document_type=doc.get("document_type", "Document"),
        status=doc.get("status", "unknown"),
        expiry_date=doc.get("expiry_date"),
        extraction_status=doc.get("extraction_status", "unknown"),
        embedding_status=doc.get("embedding_status", "unknown"),
    )


def _to_report_citation(c, document_type: str = "Document") -> ReportCitation:
    return ReportCitation(
        claim=c.claim,
        doc_id=c.doc_id,
        citation_text=c.citation_text,
        document_type=document_type,
    )


# ---------------------------------------------------------------------------
# Fund analyst report
# ---------------------------------------------------------------------------

@router.get("/analyst-reports/fund/{fund_id}", response_model=AnalystReport)
def fund_analyst_report(fund_id: str) -> AnalystReport:
    f = get_fund(fund_id)
    if f is None:
        raise HTTPException(status_code=404, detail=f"Fund {fund_id!r} not found")
    if f.get("synthetic_static"):
        raise HTTPException(
            status_code=403,
            detail="Static funds cannot generate AI analyst reports",
        )

    docs = _load_documents(f.get("documents", []), scope="fund", scope_id=fund_id, entity_name=f["name"])

    effective_tier: str = f.get("escalated_tier") or f["direct_tier"]
    critical_ble_names = [
        b["name"] for b in f.get("bles", []) if b.get("tier") == "critical"
    ]

    result = _narrative_svc.generate(
        scope="fund",
        scope_id=fund_id,
        fund_id=fund_id,
        synthetic_static=False,
        documents=docs,
        risk_tier=effective_tier,
        direct_tier=f["direct_tier"],
        escalation_reason=f.get("escalation_reason"),
        escalated_ble_names=critical_ble_names or None,
        entity_name=f["name"],
    )

    doc_type_map = {d["doc_id"]: d.get("document_type", "Document") for d in f.get("documents", [])}
    citations = [_to_report_citation(c, doc_type_map.get(c.doc_id, "Document")) for c in result.citations]

    return AnalystReport(
        scope="fund",
        scope_id=fund_id,
        fund_id=fund_id,
        fund_name=f["name"],
        ble_name=None,
        effective_tier=effective_tier,
        direct_tier=f["direct_tier"],
        direct_score=f.get("direct_score", 0.0),
        escalation_reason=f.get("escalation_reason"),
        escalated_ble_names=critical_ble_names,
        factor_scores=f.get("factor_scores", {}),
        narrative=result.narrative,
        citations=citations,
        document_status=[_to_doc_info(d) for d in f.get("documents", [])],
        screening_status=None,
        hit_type=None,
        ruleset_version=f.get("ruleset_version", "v1"),
        model=result.model,
        prompt_version=result.prompt_version,
        is_mock=result.is_mock,
        generated_at=result.run_at,
    )


# ---------------------------------------------------------------------------
# BLE analyst report
# ---------------------------------------------------------------------------

@router.get("/analyst-reports/ble/{ble_id}", response_model=AnalystReport)
def ble_analyst_report(ble_id: str) -> AnalystReport:
    ble = get_ble(ble_id)
    if ble is None:
        raise HTTPException(status_code=404, detail=f"BLE {ble_id!r} not found")

    parent = get_fund(ble["fund_id"])
    if parent and parent.get("synthetic_static"):
        raise HTTPException(
            status_code=403,
            detail="Static funds cannot generate AI analyst reports",
        )

    docs = _load_documents(ble.get("documents", []), scope="ble", scope_id=ble_id, entity_name=ble["name"])

    result = _narrative_svc.generate(
        scope="ble",
        scope_id=ble_id,
        fund_id=ble["fund_id"],
        synthetic_static=False,
        documents=docs,
        risk_tier=ble["tier"],
        entity_name=ble["name"],
    )

    doc_type_map = {d["doc_id"]: d.get("document_type", "Document") for d in ble.get("documents", [])}
    citations = [_to_report_citation(c, doc_type_map.get(c.doc_id, "Document")) for c in result.citations]

    return AnalystReport(
        scope="ble",
        scope_id=ble_id,
        fund_id=ble["fund_id"],
        fund_name=ble.get("fund_name", ""),
        ble_name=ble["name"],
        effective_tier=ble["tier"],
        direct_tier=ble["tier"],
        direct_score=ble.get("score", 0.0),
        escalation_reason=None,
        escalated_ble_names=[],
        factor_scores=ble.get("factor_scores", {}),
        narrative=result.narrative,
        citations=citations,
        document_status=[_to_doc_info(d) for d in ble.get("documents", [])],
        screening_status=ble.get("hit_severity"),
        hit_type=ble.get("hit_type"),
        ruleset_version=ble.get("ruleset_version", "v1"),
        model=result.model,
        prompt_version=result.prompt_version,
        is_mock=result.is_mock,
        generated_at=result.run_at,
    )


# ---------------------------------------------------------------------------
# HITL Decision Audit Trail — PRD §18
# ---------------------------------------------------------------------------

_VALID_SCOPES = {"fund", "ble"}
_VALID_DECISIONS = {"accepted", "rejected", "edited"}


@router.post(
    "/analyst-reports/{scope}/{scope_id}/decision",
    response_model=DecisionRecord,
    status_code=201,
)
def submit_decision(scope: str, scope_id: str, body: DecisionRequest) -> DecisionRecord:
    """Log an analyst Accept / Reject / Edit decision (PRD §18: every human decision logged)."""
    if scope not in _VALID_SCOPES:
        raise HTTPException(status_code=422, detail=f"scope must be one of {_VALID_SCOPES}")
    if body.decision not in _VALID_DECISIONS:
        raise HTTPException(
            status_code=422,
            detail=f"decision must be one of {_VALID_DECISIONS}",
        )

    # Resolve fund_id from scope
    if scope == "fund":
        entity = get_fund(scope_id)
        if entity is None:
            raise HTTPException(status_code=404, detail=f"Fund {scope_id!r} not found")
        fund_id = scope_id
    else:
        entity = get_ble(scope_id)
        if entity is None:
            raise HTTPException(status_code=404, detail=f"BLE {scope_id!r} not found")
        fund_id = entity["fund_id"]

    record = DecisionRecord(
        decision=body.decision,
        actor=body.actor,
        notes=body.notes,
        edited_narrative=body.edited_narrative,
        scope=scope,
        scope_id=scope_id,
        fund_id=fund_id,
        decided_at=datetime.now(timezone.utc).isoformat(),
    )
    append_decision(record.model_dump())
    return record
