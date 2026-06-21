"""Document upload + extraction endpoints (PRD §13.2, §17).

POST /api/funds/{fund_id}/documents          — upload a fund-scope document
POST /api/bles/{ble_id}/documents            — upload a BLE-scope document
GET  /api/funds/{fund_id}/documents          — list pipeline docs for a fund
GET  /api/bles/{ble_id}/documents            — list pipeline docs for a BLE
POST /api/documents/{document_id}/extract    — manual extraction trigger (Option C)

Document types are the 7 types the extraction service understands exactly —
imported from services.extraction.service.KNOWN_DOCUMENT_TYPES so there is
one source of truth and no mapping needed at extraction time.

Static-demo funds (synthetic_static=True) are blocked at upload and extraction.
MOCK=true: extraction returns canned type-specific responses (zero cost, no file read).
MOCK=false: extraction reads the .txt file and calls Claude Haiku (~$0.01/doc).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from api import data_loader
from api.models import DocumentInfo
from services.extraction.service import (
    KNOWN_DOCUMENT_TYPES,
    extract_document_fields,
)
from services.ingestion import service as ingestion_svc

router = APIRouter()

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

# Single source of truth — extraction service defines the valid types
VALID_DOC_TYPES: frozenset[str] = KNOWN_DOCUMENT_TYPES


def _to_doc_info(doc) -> DocumentInfo:
    return DocumentInfo(
        doc_id=doc.document_id,
        document_type=doc.document_type,
        status=doc.status,
        expiry_date=doc.expiry_date,
        extraction_status=doc.extraction_status,
        embedding_status=doc.embedding_status,
    )


def _resolve_file_path(doc) -> Path:
    """Return the upload file path, handling both MOCK (full path) and DB (filename only) modes."""
    full = Path(doc.file_path)
    if full.exists():
        return full
    # DB mode stores only the filename; reconstruct from uploads dir
    return UPLOAD_DIR / (doc.filename or "upload.txt")


# ---------------------------------------------------------------------------
# Fund document endpoints
# ---------------------------------------------------------------------------

@router.post("/funds/{fund_id}/documents")
async def upload_fund_document(
    fund_id: str,
    document_type: str = Form(...),
    expiry_date: str | None = Form(None),
    file: UploadFile = File(...),
):
    fund = data_loader.get_fund(fund_id)
    if fund is None:
        raise HTTPException(status_code=404, detail="Fund not found")
    if fund.get("synthetic_static"):
        raise HTTPException(
            status_code=403,
            detail="Document upload is disabled for static demo funds",
        )
    if document_type not in VALID_DOC_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"document_type must be one of {sorted(VALID_DOC_TYPES)}",
        )

    content = await file.read()
    safe_name = f"{fund_id}_{file.filename or 'upload.txt'}"
    save_path = UPLOAD_DIR / safe_name
    save_path.write_bytes(content)

    doc_id = ingestion_svc.ingest_document(
        scope="fund",
        scope_id=fund_id,
        fund_id=fund_id,
        document_type=document_type,
        file_path=save_path,
        status="pending",
        expiry_date=expiry_date or None,
        synthetic_profile=fund.get("synthetic_profile", True),
    )

    return {
        "document_id": doc_id,
        "filename": file.filename,
        "document_type": document_type,
        "status": "pending",
        "extraction_status": "pending",
        "embedding_status": "pending",
    }


@router.get("/funds/{fund_id}/documents")
def list_fund_documents(fund_id: str) -> list[dict]:
    fund = data_loader.get_fund(fund_id)
    if fund is None:
        raise HTTPException(status_code=404, detail="Fund not found")
    docs = ingestion_svc.list_documents("fund", fund_id)
    return [
        {
            "document_id": d.document_id,
            "filename": d.filename,
            "document_type": d.document_type,
            "status": d.status,
            "expiry_date": d.expiry_date,
            "extraction_status": d.extraction_status,
            "embedding_status": d.embedding_status,
        }
        for d in docs
    ]


# ---------------------------------------------------------------------------
# BLE document endpoints
# ---------------------------------------------------------------------------

@router.post("/bles/{ble_id}/documents")
async def upload_ble_document(
    ble_id: str,
    document_type: str = Form(...),
    expiry_date: str | None = Form(None),
    file: UploadFile = File(...),
):
    ble = data_loader.get_ble(ble_id)
    if ble is None:
        raise HTTPException(status_code=404, detail="BLE not found")

    fund_id: str = ble.get("fund_id") or ""
    if fund_id:
        parent_fund = data_loader.get_fund(fund_id)
        if parent_fund and parent_fund.get("synthetic_static"):
            raise HTTPException(
                status_code=403,
                detail="Document upload is disabled for BLEs of static demo funds",
            )

    if document_type not in VALID_DOC_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"document_type must be one of {sorted(VALID_DOC_TYPES)}",
        )

    content = await file.read()
    safe_name = f"{ble_id}_{file.filename or 'upload.txt'}"
    save_path = UPLOAD_DIR / safe_name
    save_path.write_bytes(content)

    doc_id = ingestion_svc.ingest_document(
        scope="ble",
        scope_id=ble_id,
        fund_id=fund_id,
        document_type=document_type,
        file_path=save_path,
        status="pending",
        expiry_date=expiry_date or None,
        synthetic_profile=True,
    )

    return {
        "document_id": doc_id,
        "filename": file.filename,
        "document_type": document_type,
        "status": "pending",
        "extraction_status": "pending",
        "embedding_status": "pending",
    }


@router.get("/bles/{ble_id}/documents")
def list_ble_documents(ble_id: str) -> list[dict]:
    ble = data_loader.get_ble(ble_id)
    if ble is None:
        raise HTTPException(status_code=404, detail="BLE not found")
    docs = ingestion_svc.list_documents("ble", ble_id)
    return [
        {
            "document_id": d.document_id,
            "filename": d.filename,
            "document_type": d.document_type,
            "status": d.status,
            "expiry_date": d.expiry_date,
            "extraction_status": d.extraction_status,
            "embedding_status": d.embedding_status,
        }
        for d in docs
    ]


# ---------------------------------------------------------------------------
# Manual extraction trigger — Option C (PRD §17)
# ---------------------------------------------------------------------------

@router.post("/documents/{document_id}/extract")
def trigger_extraction(document_id: str) -> dict[str, Any]:
    """
    Human-initiated extraction trigger (PRD §17, CLAUDE.md rule 5).

    Calls ExtractionService.extract_document_fields() for the given document.
    Idempotent: already-extracted docs return cached fields without re-calling the LLM.
    MOCK=true: returns canned type-specific structured fields, zero cost.
    MOCK=false: reads the uploaded .txt file and calls Claude Haiku (~$0.01).
    """
    doc = ingestion_svc.get_document(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    # Look up fund for synthetic_static guard
    fund = data_loader.get_fund(doc.fund_id) if doc.fund_id else None
    synthetic_static: bool = bool(fund.get("synthetic_static")) if fund else False

    if synthetic_static:
        raise HTTPException(
            status_code=403,
            detail="Extraction is disabled for static demo funds",
        )

    file_path = _resolve_file_path(doc)

    try:
        fields = extract_document_fields(
            scope=doc.scope,
            scope_id=doc.scope_id,
            fund_id=doc.fund_id,
            document_type=doc.document_type,
            file_path=file_path,
            doc_id=doc.document_id,
            synthetic_static=synthetic_static,
        )
        ingestion_svc.update_extraction_status(document_id, "extracted")
        return {
            "document_id": document_id,
            "extraction_status": "extracted",
            "extracted_fields": fields,
        }
    except Exception as exc:
        ingestion_svc.update_extraction_status(document_id, "failed")
        raise HTTPException(
            status_code=500,
            detail=f"Extraction failed: {exc}",
        )
