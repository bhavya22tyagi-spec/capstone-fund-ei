"""Tests for services.rag.service — RAGService (PRD §8.2, §18)."""

from __future__ import annotations

import pytest

import services.cost_logger as cl
import services.idempotency as idm
import services.rag.service as svc_module
from services.embedding_service import ChunkRecord, InMemoryVectorStore
from services.guards import StaticFundAIError
from services.rag import MOCK, RAGService

# ---------------------------------------------------------------------------
# IDs
# ---------------------------------------------------------------------------

_F1 = "f0000001-f000-0000-0000-000000000001"
_F4 = "f0000004-f000-0000-0000-000000000004"
_F5 = "f0000005-f000-0000-0000-000000000005"
_B11 = "b0001001-b000-0000-0000-000000000001"
_B41 = "b0004001-b000-0000-0000-000000000005"
_B51 = "b0005001-b000-0000-0000-000000000006"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset(tmp_path, monkeypatch):
    monkeypatch.setattr(svc_module, "MOCK", True)
    monkeypatch.setattr(cl, "LOG_FILE", str(tmp_path / "calls.jsonl"))
    idm.reset()
    yield
    idm.reset()


def _make_svc() -> RAGService:
    return RAGService()


# ---------------------------------------------------------------------------
# 1. Module-level flag reflects env var default
# ---------------------------------------------------------------------------


def test_mock_flag_is_bool():
    assert isinstance(MOCK, bool)


def test_mock_defaults_true():
    assert MOCK is True


# ---------------------------------------------------------------------------
# 2. MOCK=true — index_document
# ---------------------------------------------------------------------------


def test_index_returns_one_chunk():
    svc = _make_svc()
    chunks = svc.index_document("doc-001", "Some text about EX-CYM-2019-08742", "fund", _F1, _F1)
    assert len(chunks) == 1


def test_indexed_chunk_stores_text():
    svc = _make_svc()
    text = "NCP-BR-2022-001 Bank Rossiya Moscow Loan"
    chunks = svc.index_document("doc-ble-001", text, "ble", _B11, _F1)
    assert chunks[0].chunk_text == text


def test_indexed_chunk_has_correct_scope():
    svc = _make_svc()
    chunks = svc.index_document("doc-001", "text", "fund", _F1, _F1)
    assert chunks[0].scope == "fund"
    assert chunks[0].scope_id == _F1


def test_index_is_idempotent():
    svc = _make_svc()
    r1 = svc.index_document("doc-001", "some text", "fund", _F1, _F1)
    r2 = svc.index_document("doc-001", "some text", "fund", _F1, _F1)
    assert r1[0].chunk_id == r2[0].chunk_id


def test_index_idempotent_does_not_duplicate():
    svc = _make_svc()
    svc.index_document("doc-001", "text A", "fund", _F1, _F1)
    svc.index_document("doc-001", "text B", "fund", _F1, _F1)  # same doc_id — should skip
    results = svc.retrieve("text", "fund", _F1, _F1, top_k=10)
    assert len(results) == 1


def test_index_invalid_scope_raises():
    svc = _make_svc()
    with pytest.raises(ValueError, match="scope must be"):
        svc.index_document("doc-001", "text", "invalid", _F1, _F1)


# ---------------------------------------------------------------------------
# 3. MOCK=true — retrieve
# ---------------------------------------------------------------------------


def test_retrieve_empty_when_nothing_indexed():
    svc = _make_svc()
    results = svc.retrieve("any query", "fund", _F1, _F1, top_k=3)
    assert results == []


def test_retrieve_returns_indexed_chunk():
    svc = _make_svc()
    svc.index_document("doc-001", "NCP-BR-2022-001 Bank Rossiya Loan 5000000", "ble", _B11, _F1)
    results = svc.retrieve("NCP-BR-2022-001 agreement reference", "ble", _B11, _F1, top_k=3)
    assert len(results) == 1
    assert "NCP-BR-2022-001" in results[0].chunk_text


def test_retrieve_empty_query_raises():
    svc = _make_svc()
    with pytest.raises(ValueError, match="must not be empty"):
        svc.retrieve("", "fund", _F1, _F1)


def test_retrieve_invalid_scope_raises():
    svc = _make_svc()
    with pytest.raises(ValueError, match="scope must be"):
        svc.retrieve("query", "bad_scope", _F1, _F1)


def test_retrieve_top_k_respected():
    svc = _make_svc()
    for i in range(5):
        svc.index_document(f"doc-{i}", f"document {i} content keyword", "fund", _F1, _F1)
    results = svc.retrieve("document content keyword", "fund", _F1, _F1, top_k=3)
    assert len(results) <= 3


def test_retrieve_keyword_ranking():
    svc = _make_svc()
    svc.index_document("doc-a", "registration number EX-CYM-2019-08742 cayman exempted", "fund", _F1, _F1)
    svc.index_document("doc-b", "John Richardson ownership percentage 70", "fund", _F1, _F1)

    results = svc.retrieve("EX-CYM-2019-08742 registration cayman", "fund", _F1, _F1, top_k=3)
    # doc-a has more keyword overlap → should rank first
    assert "EX-CYM-2019-08742" in results[0].chunk_text


# ---------------------------------------------------------------------------
# 4. Cross-scope isolation (PRD §18)
# ---------------------------------------------------------------------------


def test_ble_chunk_not_visible_in_fund_scope():
    svc = _make_svc()
    svc.index_document("doc-ble", "NCP-BR-2022-001 Bank Rossiya secret", "ble", _B11, _F1)
    results = svc.retrieve("NCP-BR-2022-001 Bank Rossiya secret", "fund", _F1, _F1, top_k=3)
    for chunk in results:
        assert "NCP-BR-2022-001" not in chunk.chunk_text


def test_fund_chunk_not_visible_in_ble_scope():
    svc = _make_svc()
    svc.index_document("doc-fund", "EX-CYM-2019-08742 registration cayman", "fund", _F1, _F1)
    results = svc.retrieve("EX-CYM-2019-08742 registration cayman", "ble", _B11, _F1, top_k=3)
    for chunk in results:
        assert "EX-CYM-2019-08742" not in chunk.chunk_text


def test_ble1_chunk_not_visible_in_ble2_scope():
    svc = _make_svc()
    svc.index_document("doc-b11", "NCP-BR-2022-001 Bank Rossiya Loan", "ble", _B11, _F1)
    svc.index_document("doc-b41", "HPC-ENBD-2023-002 Emirates NBD Cash", "ble", _B41, _F4)
    results = svc.retrieve("HPC-ENBD-2023-002 Emirates NBD", "ble", _B11, _F1, top_k=3)
    for chunk in results:
        assert "HPC-ENBD-2023-002" not in chunk.chunk_text


def test_fund1_chunk_not_visible_in_fund5_scope():
    svc = _make_svc()
    svc.index_document("doc-f1", "EX-CYM-2019-08742 Northgate Cayman", "fund", _F1, _F1)
    svc.index_document("doc-f5", "Queensbridge Laws of Singapore", "fund", _F5, _F5)
    results = svc.retrieve("EX-CYM-2019-08742 Cayman", "fund", _F5, _F5, top_k=3)
    for chunk in results:
        assert "EX-CYM-2019-08742" not in chunk.chunk_text


# ---------------------------------------------------------------------------
# 5. Static fund guard fires in MOCK mode
# ---------------------------------------------------------------------------


def test_static_guard_on_index():
    svc = _make_svc()
    with pytest.raises(StaticFundAIError):
        svc.index_document("doc-x", "text", "fund", "static-001", "static-001",
                           synthetic_static=True)


def test_static_guard_on_retrieve():
    svc = _make_svc()
    with pytest.raises(StaticFundAIError):
        svc.retrieve("query", "fund", "static-001", "static-001", synthetic_static=True)


# ---------------------------------------------------------------------------
# 6. clear()
# ---------------------------------------------------------------------------


def test_clear_removes_all_chunks():
    svc = _make_svc()
    svc.index_document("doc-001", "text content", "fund", _F1, _F1)
    svc.clear()
    results = svc.retrieve("text content", "fund", _F1, _F1, top_k=3)
    assert results == []


def test_clear_allows_reindex():
    svc = _make_svc()
    svc.index_document("doc-001", "original text", "fund", _F1, _F1)
    svc.clear()
    svc.index_document("doc-001", "new text", "fund", _F1, _F1)
    results = svc.retrieve("new text", "fund", _F1, _F1, top_k=3)
    assert len(results) == 1
    assert "new text" in results[0].chunk_text


# ---------------------------------------------------------------------------
# 7. Real path (MOCK=false, embedding monkeypatched)
# ---------------------------------------------------------------------------


def test_real_path_indexes_and_retrieves(monkeypatch, tmp_path):
    import services.ai_client as ac

    monkeypatch.setattr(svc_module, "MOCK", False)
    monkeypatch.setattr(ac, "MOCK", False)
    monkeypatch.setattr(cl, "LOG_FILE", str(tmp_path / "calls.jsonl"))

    fake_vec = [0.1] * 768
    monkeypatch.setattr(ac, "_real_embedding_call", lambda text, model: fake_vec)

    from services.budget import BudgetCap

    store = InMemoryVectorStore()
    svc = RAGService(store=store, budget=BudgetCap(limit_usd=1.0))

    svc.index_document("doc-001", "NCP-BR-2022-001 Bank Rossiya Loan Moscow", "ble", _B11, _F1)
    results = svc.retrieve("NCP-BR-2022-001 agreement Bank Rossiya", "ble", _B11, _F1, top_k=3)

    assert len(results) == 1
    assert "NCP-BR-2022-001" in results[0].chunk_text


def test_real_path_scope_isolation(monkeypatch, tmp_path):
    import services.ai_client as ac

    monkeypatch.setattr(svc_module, "MOCK", False)
    monkeypatch.setattr(ac, "MOCK", False)
    monkeypatch.setattr(cl, "LOG_FILE", str(tmp_path / "calls.jsonl"))

    fake_vec = [0.1] * 768
    monkeypatch.setattr(ac, "_real_embedding_call", lambda text, model: fake_vec)

    from services.budget import BudgetCap

    store = InMemoryVectorStore()
    svc = RAGService(store=store, budget=BudgetCap(limit_usd=1.0))

    svc.index_document("doc-ble", "NCP-BR-2022-001 Bank Rossiya", "ble", _B11, _F1)
    results = svc.retrieve("NCP-BR-2022-001 agreement", "fund", _F1, _F1, top_k=3)

    for chunk in results:
        assert "NCP-BR-2022-001" not in chunk.chunk_text
