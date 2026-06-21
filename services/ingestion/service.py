"""
Ingestion Service (PRD §8.2) — document upload, storage, metadata, per-doc status.

Scope is always mandatory (fund | ble) and must be accompanied by the matching
scope_id (fund_id or ble_id) plus the parent fund_id at all times.

Per-doc status lifecycle (PRD §17):
  ingest -> extraction_status: pending -> extracted | failed
          -> embedding_status:  pending -> embedded  | failed

MOCK=true (default): records stored in a process-local dict; no DB required.
MOCK=false: writes to fund_documents / ble_documents via psycopg2 (requires
            running PostgreSQL and DATABASE_URL env var).

Idempotency: same (scope, scope_id, document_type, filename) returns the same
document_id within a process — re-ingesting the same file is a no-op.
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

MOCK: bool = os.getenv("MOCK", "true").lower() == "true"

VALID_SCOPES: frozenset[str] = frozenset({"fund", "ble"})
VALID_DOC_STATUSES: frozenset[str] = frozenset({"pending", "verified", "expired", "rejected"})
VALID_PROC_STATUSES: frozenset[str] = frozenset({"pending", "extracted", "failed"})
VALID_EMBED_STATUSES: frozenset[str] = frozenset({"pending", "embedded", "failed"})


@dataclass
class IngestedDocument:
    document_id: str
    scope: str            # 'fund' | 'ble'
    scope_id: str         # fund_id or ble_id — matches scope
    fund_id: str          # always the parent fund_id
    document_type: str
    filename: str
    file_path: str
    status: str           # 'pending' | 'verified' | 'expired' | 'rejected'
    expiry_date: str | None
    extraction_status: str    # 'pending' | 'extracted' | 'failed'
    embedding_status: str     # 'pending' | 'embedded' | 'failed'
    synthetic_profile: bool
    created_at: str


# ---------------------------------------------------------------------------
# Process-local store (MOCK=true only)
# ---------------------------------------------------------------------------

_store: dict[str, IngestedDocument] = {}
# (scope, scope_id, document_type, filename) -> document_id
_idempotency_index: dict[tuple[str, str, str, str], str] = {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ingest_document(
    scope: str,
    scope_id: str,
    fund_id: str,
    document_type: str,
    file_path: str | Path,
    status: str = "pending",
    expiry_date: str | None = None,
    synthetic_profile: bool = True,
) -> str:
    """
    Register a document in the ingestion store.

    Returns document_id (UUID string).
    Idempotent: same (scope, scope_id, document_type, filename) in the same
    process returns the same document_id without creating a new record.
    """
    if scope not in VALID_SCOPES:
        raise ValueError(f"scope must be one of {VALID_SCOPES!r}, got {scope!r}")
    if not scope_id:
        raise ValueError("scope_id is required and cannot be empty")
    if not fund_id:
        raise ValueError("fund_id is required and cannot be empty")
    if status not in VALID_DOC_STATUSES:
        raise ValueError(f"status must be one of {VALID_DOC_STATUSES!r}, got {status!r}")

    filename = Path(file_path).name
    idem_key = (scope, scope_id, document_type, filename)

    if MOCK:
        if idem_key in _idempotency_index:
            return _idempotency_index[idem_key]

        doc_id = str(uuid.uuid4())
        doc = IngestedDocument(
            document_id=doc_id,
            scope=scope,
            scope_id=scope_id,
            fund_id=fund_id,
            document_type=document_type,
            filename=filename,
            file_path=str(file_path),
            status=status,
            expiry_date=expiry_date,
            extraction_status="pending",
            embedding_status="pending",
            synthetic_profile=synthetic_profile,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        _store[doc_id] = doc
        _idempotency_index[idem_key] = doc_id
        return doc_id

    return _db_ingest(scope, scope_id, fund_id, document_type, file_path,
                      status, expiry_date, synthetic_profile)


def get_document(document_id: str) -> IngestedDocument | None:
    """Return the IngestedDocument for document_id, or None if not found."""
    if MOCK:
        return _store.get(document_id)
    return _db_get(document_id)


def update_extraction_status(document_id: str, status: str) -> None:
    """Update extraction pipeline status for a document."""
    if status not in VALID_PROC_STATUSES:
        raise ValueError(
            f"extraction_status must be one of {VALID_PROC_STATUSES!r}, got {status!r}"
        )
    if MOCK:
        doc = _store.get(document_id)
        if doc is None:
            raise KeyError(f"document_id {document_id!r} not found in ingestion store")
        doc.extraction_status = status
    else:
        _db_update_status(document_id, "extraction_status", status)


def update_embedding_status(document_id: str, status: str) -> None:
    """Update embedding pipeline status for a document."""
    if status not in VALID_EMBED_STATUSES:
        raise ValueError(
            f"embedding_status must be one of {VALID_EMBED_STATUSES!r}, got {status!r}"
        )
    if MOCK:
        doc = _store.get(document_id)
        if doc is None:
            raise KeyError(f"document_id {document_id!r} not found in ingestion store")
        doc.embedding_status = status
    else:
        _db_update_status(document_id, "embedding_status", status)


def list_documents(scope: str, scope_id: str) -> list[IngestedDocument]:
    """Return all ingested documents matching scope + scope_id."""
    if scope not in VALID_SCOPES:
        raise ValueError(f"scope must be one of {VALID_SCOPES!r}, got {scope!r}")
    if MOCK:
        return [
            d for d in _store.values()
            if d.scope == scope and d.scope_id == scope_id
        ]
    return _db_list(scope, scope_id)


def clear_store() -> None:
    """Reset the process-local store. For use in tests only."""
    _store.clear()
    _idempotency_index.clear()


# ---------------------------------------------------------------------------
# Real DB path (MOCK=false) — wired when PostgreSQL is available
# ---------------------------------------------------------------------------

_ALLOWED_STATUS_FIELDS: frozenset[str] = frozenset({"extraction_status", "embedding_status"})


def _db_connect():
    import psycopg2  # noqa: PLC0415
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL is not set — cannot use real DB path")
    return psycopg2.connect(db_url)


def _row_to_fund_doc(row: tuple) -> IngestedDocument:
    doc_id, fund_id, doc_type, filename, status, expiry, extr, emb, synth, created = row
    return IngestedDocument(
        document_id=str(doc_id),
        scope="fund",
        scope_id=str(fund_id),
        fund_id=str(fund_id),
        document_type=doc_type,
        filename=filename or "",
        file_path=filename or "",
        status=status or "pending",
        expiry_date=str(expiry) if expiry else None,
        extraction_status=extr or "pending",
        embedding_status=emb or "pending",
        synthetic_profile=synth,
        created_at=str(created),
    )


def _row_to_ble_doc(row: tuple) -> IngestedDocument:
    doc_id, ble_id, fund_id, doc_type, filename, status, expiry, extr, emb, synth, created = row
    return IngestedDocument(
        document_id=str(doc_id),
        scope="ble",
        scope_id=str(ble_id),
        fund_id=str(fund_id),
        document_type=doc_type,
        filename=filename or "",
        file_path=filename or "",
        status=status or "pending",
        expiry_date=str(expiry) if expiry else None,
        extraction_status=extr or "pending",
        embedding_status=emb or "pending",
        synthetic_profile=synth,
        created_at=str(created),
    )


def _db_ingest(
    scope: str, scope_id: str, fund_id: str, document_type: str,
    file_path: str | Path, status: str, expiry_date: str | None,
    synthetic_profile: bool,
) -> str:
    filename = Path(file_path).name
    with _db_connect() as conn:
        with conn.cursor() as cur:
            if scope == "fund":
                cur.execute(
                    "SELECT document_id FROM fund_documents "
                    "WHERE fund_id=%s AND document_type=%s AND filename=%s",
                    (scope_id, document_type, filename),
                )
                row = cur.fetchone()
                if row:
                    return str(row[0])
                doc_id = str(uuid.uuid4())
                cur.execute(
                    """INSERT INTO fund_documents
                           (document_id, fund_id, document_type, filename, status,
                            expiry_date, extraction_status, embedding_status, synthetic_profile)
                       VALUES (%s, %s, %s, %s, %s, %s, 'pending', 'pending', %s)""",
                    (doc_id, scope_id, document_type, filename,
                     status, expiry_date, synthetic_profile),
                )
            else:
                cur.execute(
                    "SELECT document_id FROM ble_documents "
                    "WHERE ble_id=%s AND document_type=%s AND filename=%s",
                    (scope_id, document_type, filename),
                )
                row = cur.fetchone()
                if row:
                    return str(row[0])
                doc_id = str(uuid.uuid4())
                cur.execute(
                    """INSERT INTO ble_documents
                           (document_id, ble_id, document_type, filename, status,
                            expiry_date, extraction_status, embedding_status, synthetic_profile)
                       VALUES (%s, %s, %s, %s, %s, %s, 'pending', 'pending', %s)""",
                    (doc_id, scope_id, document_type, filename,
                     status, expiry_date, synthetic_profile),
                )
        conn.commit()
    return doc_id


def _db_get(document_id: str) -> IngestedDocument | None:
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT document_id, fund_id, document_type, filename, status,
                          expiry_date, extraction_status, embedding_status,
                          synthetic_profile, created_at
                   FROM fund_documents WHERE document_id=%s""",
                (document_id,),
            )
            row = cur.fetchone()
            if row:
                return _row_to_fund_doc(row)

            cur.execute(
                """SELECT d.document_id, d.ble_id, b.parent_fund_id, d.document_type,
                          d.filename, d.status, d.expiry_date, d.extraction_status,
                          d.embedding_status, d.synthetic_profile, d.created_at
                   FROM ble_documents d
                   JOIN bles b ON b.ble_id = d.ble_id
                   WHERE d.document_id=%s""",
                (document_id,),
            )
            row = cur.fetchone()
            if row:
                return _row_to_ble_doc(row)
    return None


def _db_update_status(document_id: str, field: str, value: str) -> None:
    if field not in _ALLOWED_STATUS_FIELDS:
        raise ValueError(f"field must be one of {_ALLOWED_STATUS_FIELDS!r}, got {field!r}")
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE fund_documents SET {field}=%s WHERE document_id=%s",
                (value, document_id),
            )
            if cur.rowcount == 0:
                cur.execute(
                    f"UPDATE ble_documents SET {field}=%s WHERE document_id=%s",
                    (value, document_id),
                )
        conn.commit()


def _db_list(scope: str, scope_id: str) -> list[IngestedDocument]:
    results: list[IngestedDocument] = []
    with _db_connect() as conn:
        with conn.cursor() as cur:
            if scope == "fund":
                cur.execute(
                    """SELECT document_id, fund_id, document_type, filename, status,
                              expiry_date, extraction_status, embedding_status,
                              synthetic_profile, created_at
                       FROM fund_documents WHERE fund_id=%s ORDER BY created_at DESC""",
                    (scope_id,),
                )
                results = [_row_to_fund_doc(r) for r in cur.fetchall()]
            else:
                cur.execute(
                    """SELECT d.document_id, d.ble_id, b.parent_fund_id, d.document_type,
                              d.filename, d.status, d.expiry_date, d.extraction_status,
                              d.embedding_status, d.synthetic_profile, d.created_at
                       FROM ble_documents d
                       JOIN bles b ON b.ble_id = d.ble_id
                       WHERE d.ble_id=%s ORDER BY d.created_at DESC""",
                    (scope_id,),
                )
                results = [_row_to_ble_doc(r) for r in cur.fetchall()]
    return results
