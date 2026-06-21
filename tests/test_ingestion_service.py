"""
Tests for services/ingestion/service.py (PRD §8.2).

All tests run in MOCK=true mode (in-memory store, no DB required).
Covers: ingest_document, get_document, update_extraction_status,
update_embedding_status, list_documents, clear_store, idempotency, and the
MOCK=false NotImplementedError guard.
"""
from __future__ import annotations

import pytest

import services.ingestion.service as service
from services.ingestion.service import (
    clear_store,
    get_document,
    ingest_document,
    list_documents,
    update_embedding_status,
    update_extraction_status,
)

# Stable IDs matching seed_truth.json
_F1 = "f0000001-f000-0000-0000-000000000001"
_F2 = "f0000002-f000-0000-0000-000000000002"
_B11 = "b0001001-b000-0000-0000-000000000001"
_B21 = "b0002001-b000-0000-0000-000000000002"


@pytest.fixture(autouse=True)
def _reset_store(monkeypatch):
    monkeypatch.setattr(service, "MOCK", True)
    clear_store()
    yield
    clear_store()


# ---------------------------------------------------------------------------
# 1. Basic ingestion
# ---------------------------------------------------------------------------

def test_ingest_returns_string():
    doc_id = ingest_document("fund", _F1, _F1, "Incorporation Certificate", "cert.txt")
    assert isinstance(doc_id, str)


def test_ingest_returns_uuid_format():
    doc_id = ingest_document("fund", _F1, _F1, "Incorporation Certificate", "cert.txt")
    parts = doc_id.split("-")
    assert len(parts) == 5


def test_ingest_fund_scope():
    doc_id = ingest_document("fund", _F1, _F1, "UBO Declaration", "ubo.txt")
    doc = get_document(doc_id)
    assert doc.scope == "fund"
    assert doc.scope_id == _F1


def test_ingest_ble_scope():
    doc_id = ingest_document("ble", _B11, _F1, "Counterparty Agreement", "cpty.txt")
    doc = get_document(doc_id)
    assert doc.scope == "ble"
    assert doc.scope_id == _B11
    assert doc.fund_id == _F1


def test_document_type_stored():
    doc_id = ingest_document("fund", _F1, _F1, "Regulatory Licence", "lic.txt")
    assert get_document(doc_id).document_type == "Regulatory Licence"


def test_filename_extracted_from_path():
    doc_id = ingest_document("fund", _F1, _F1, "Incorporation Certificate", "/full/path/cert.txt")
    assert get_document(doc_id).filename == "cert.txt"


def test_default_status_is_pending():
    doc_id = ingest_document("fund", _F1, _F1, "Incorporation Certificate", "cert.txt")
    assert get_document(doc_id).status == "pending"


def test_explicit_status_stored():
    doc_id = ingest_document("fund", _F1, _F1, "Incorporation Certificate", "cert.txt", status="verified")
    assert get_document(doc_id).status == "verified"


def test_extraction_status_starts_pending():
    doc_id = ingest_document("fund", _F1, _F1, "Incorporation Certificate", "cert.txt")
    assert get_document(doc_id).extraction_status == "pending"


def test_embedding_status_starts_pending():
    doc_id = ingest_document("fund", _F1, _F1, "Incorporation Certificate", "cert.txt")
    assert get_document(doc_id).embedding_status == "pending"


def test_expiry_date_stored():
    doc_id = ingest_document("fund", _F1, _F1, "Regulatory Licence", "lic.txt", expiry_date="2026-07-08")
    assert get_document(doc_id).expiry_date == "2026-07-08"


def test_none_expiry_date():
    doc_id = ingest_document("fund", _F1, _F1, "Incorporation Certificate", "cert.txt")
    assert get_document(doc_id).expiry_date is None


def test_synthetic_profile_default_true():
    doc_id = ingest_document("fund", _F1, _F1, "Incorporation Certificate", "cert.txt")
    assert get_document(doc_id).synthetic_profile is True


def test_fund_id_always_stored():
    doc_id = ingest_document("ble", _B11, _F1, "Counterparty Agreement", "cpty.txt")
    assert get_document(doc_id).fund_id == _F1


# ---------------------------------------------------------------------------
# 2. Validation errors
# ---------------------------------------------------------------------------

def test_invalid_scope_raises():
    with pytest.raises(ValueError, match="scope must be one of"):
        ingest_document("company", _F1, _F1, "Incorporation Certificate", "cert.txt")


def test_empty_scope_id_raises():
    with pytest.raises(ValueError, match="scope_id"):
        ingest_document("fund", "", _F1, "Incorporation Certificate", "cert.txt")


def test_empty_fund_id_raises():
    with pytest.raises(ValueError, match="fund_id"):
        ingest_document("fund", _F1, "", "Incorporation Certificate", "cert.txt")


def test_invalid_doc_status_raises():
    with pytest.raises(ValueError, match="status"):
        ingest_document("fund", _F1, _F1, "Incorporation Certificate", "cert.txt", status="uploaded")


# ---------------------------------------------------------------------------
# 3. get_document
# ---------------------------------------------------------------------------

def test_get_document_returns_ingested_doc():
    doc_id = ingest_document("fund", _F1, _F1, "Incorporation Certificate", "cert.txt")
    doc = get_document(doc_id)
    assert doc is not None
    assert doc.document_id == doc_id


def test_get_document_unknown_returns_none():
    assert get_document("does-not-exist") is None


# ---------------------------------------------------------------------------
# 4. Idempotency
# ---------------------------------------------------------------------------

def test_same_inputs_return_same_doc_id():
    id1 = ingest_document("fund", _F1, _F1, "Incorporation Certificate", "cert.txt")
    id2 = ingest_document("fund", _F1, _F1, "Incorporation Certificate", "cert.txt")
    assert id1 == id2


def test_different_filename_different_id():
    id1 = ingest_document("fund", _F1, _F1, "Incorporation Certificate", "cert1.txt")
    id2 = ingest_document("fund", _F1, _F1, "Incorporation Certificate", "cert2.txt")
    assert id1 != id2


def test_different_scope_different_id():
    id1 = ingest_document("fund", _F1, _F1, "Incorporation Certificate", "cert.txt")
    id2 = ingest_document("ble", _B11, _F1, "Incorporation Certificate", "cert.txt")
    assert id1 != id2


def test_different_scope_id_different_id():
    id1 = ingest_document("fund", _F1, _F1, "Counterparty Agreement", "agmt.txt")
    id2 = ingest_document("fund", _F2, _F2, "Counterparty Agreement", "agmt.txt")
    assert id1 != id2


def test_different_document_type_different_id():
    id1 = ingest_document("fund", _F1, _F1, "Incorporation Certificate", "doc.txt")
    id2 = ingest_document("fund", _F1, _F1, "UBO Declaration", "doc.txt")
    assert id1 != id2


# ---------------------------------------------------------------------------
# 5. update_extraction_status
# ---------------------------------------------------------------------------

def test_update_extraction_extracted():
    doc_id = ingest_document("fund", _F1, _F1, "Incorporation Certificate", "cert.txt")
    update_extraction_status(doc_id, "extracted")
    assert get_document(doc_id).extraction_status == "extracted"


def test_update_extraction_failed():
    doc_id = ingest_document("fund", _F1, _F1, "Incorporation Certificate", "cert.txt")
    update_extraction_status(doc_id, "failed")
    assert get_document(doc_id).extraction_status == "failed"


def test_update_extraction_back_to_pending():
    doc_id = ingest_document("fund", _F1, _F1, "Incorporation Certificate", "cert.txt")
    update_extraction_status(doc_id, "extracted")
    update_extraction_status(doc_id, "pending")
    assert get_document(doc_id).extraction_status == "pending"


def test_update_extraction_invalid_status_raises():
    doc_id = ingest_document("fund", _F1, _F1, "Incorporation Certificate", "cert.txt")
    with pytest.raises(ValueError, match="extraction_status"):
        update_extraction_status(doc_id, "done")


def test_update_extraction_unknown_doc_raises():
    with pytest.raises(KeyError):
        update_extraction_status("nonexistent-doc-id", "extracted")


# ---------------------------------------------------------------------------
# 6. update_embedding_status
# ---------------------------------------------------------------------------

def test_update_embedding_embedded():
    doc_id = ingest_document("fund", _F1, _F1, "Incorporation Certificate", "cert.txt")
    update_embedding_status(doc_id, "embedded")
    assert get_document(doc_id).embedding_status == "embedded"


def test_update_embedding_failed():
    doc_id = ingest_document("fund", _F1, _F1, "Incorporation Certificate", "cert.txt")
    update_embedding_status(doc_id, "failed")
    assert get_document(doc_id).embedding_status == "failed"


def test_update_embedding_invalid_status_raises():
    doc_id = ingest_document("fund", _F1, _F1, "Incorporation Certificate", "cert.txt")
    with pytest.raises(ValueError, match="embedding_status"):
        update_embedding_status(doc_id, "complete")


def test_update_embedding_unknown_doc_raises():
    with pytest.raises(KeyError):
        update_embedding_status("nonexistent-doc-id", "embedded")


# ---------------------------------------------------------------------------
# 7. list_documents
# ---------------------------------------------------------------------------

def test_list_fund_documents():
    ingest_document("fund", _F1, _F1, "Incorporation Certificate", "cert.txt")
    ingest_document("fund", _F1, _F1, "UBO Declaration", "ubo.txt")
    ingest_document("fund", _F2, _F2, "Incorporation Certificate", "cert2.txt")
    docs = list_documents("fund", _F1)
    assert len(docs) == 2
    assert all(d.scope == "fund" and d.scope_id == _F1 for d in docs)


def test_list_ble_documents():
    ingest_document("ble", _B11, _F1, "Counterparty Agreement", "cpty.txt")
    ingest_document("ble", _B21, _F2, "Framework Agreement", "agmt.txt")
    docs = list_documents("ble", _B11)
    assert len(docs) == 1
    assert docs[0].scope_id == _B11


def test_list_empty_for_unknown_scope_id():
    ingest_document("fund", _F1, _F1, "Incorporation Certificate", "cert.txt")
    docs = list_documents("fund", "unknown-fund-id")
    assert docs == []


def test_list_invalid_scope_raises():
    with pytest.raises(ValueError):
        list_documents("organization", _F1)


# ---------------------------------------------------------------------------
# 8. clear_store
# ---------------------------------------------------------------------------

def test_clear_store_empties_records():
    doc_id = ingest_document("fund", _F1, _F1, "Incorporation Certificate", "cert.txt")
    clear_store()
    assert get_document(doc_id) is None


def test_clear_store_resets_idempotency_index():
    id1 = ingest_document("fund", _F1, _F1, "Incorporation Certificate", "cert.txt")
    clear_store()
    id2 = ingest_document("fund", _F1, _F1, "Incorporation Certificate", "cert.txt")
    assert id1 != id2  # new UUID assigned after clear


# ---------------------------------------------------------------------------
# 9. MOCK=false raises NotImplementedError
# ---------------------------------------------------------------------------

def test_mock_false_ingest_raises(monkeypatch):
    monkeypatch.setattr(service, "MOCK", False)
    with pytest.raises(NotImplementedError):
        ingest_document("fund", _F1, _F1, "Incorporation Certificate", "cert.txt")


def test_mock_false_get_raises(monkeypatch):
    monkeypatch.setattr(service, "MOCK", False)
    with pytest.raises(NotImplementedError):
        get_document("any-id")


def test_mock_false_list_raises(monkeypatch):
    monkeypatch.setattr(service, "MOCK", False)
    with pytest.raises(NotImplementedError):
        list_documents("fund", _F1)
