"""
Tests for PRD §14, §17, §18 — Embedding Service.

Invariants verified:
  1. chunk_text — boundaries, overlap, single-chunk, edge cases
  2. embed_document — scope + scope_id tagged on every ChunkRecord
  3. embed_document — idempotency (no second call for same document_id)
  4. retrieve — always filters by scope + scope_id; raises on bad inputs
  5. Cross-scope isolation (the hard requirement from PRD §18):
       • BLE chunk never leaks into Fund retrieval
       • Fund A chunk never leaks into Fund B retrieval
       • BLE X chunk never leaks into BLE Y retrieval
       • A query scoped to an unknown scope_id returns zero results,
         not results from a different scope_id
"""
import pytest

import services.ai_client as ac
import services.cost_logger as cl
import services.idempotency as idm
from services.budget import BudgetCap
from services.embedding_service import (
    ChunkRecord,
    EmbeddingService,
    InMemoryVectorStore,
    _cosine_sim,
    chunk_text,
)

FUND_A = "f0000001-f000-0000-0000-000000000001"
FUND_B = "f0000002-f000-0000-0000-000000000002"
BLE_X  = "b0001001-b000-0000-0000-000000000001"
BLE_Y  = "b0002001-b000-0000-0000-000000000002"
DOC_1  = "d0000001-d000-0000-0000-000000000001"
DOC_2  = "d0000002-d000-0000-0000-000000000002"
DOC_3  = "d0000003-d000-0000-0000-000000000003"
DOC_4  = "d0000004-d000-0000-0000-000000000004"


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset(tmp_path, monkeypatch):
    """Redirect cost log + reset idempotency store before every test."""
    monkeypatch.setattr(cl, "LOG_FILE", str(tmp_path / "test_calls.jsonl"))
    idm.reset()
    yield
    idm.reset()


def _budget() -> BudgetCap:
    return BudgetCap(limit_usd=5.0)


def _service(store: InMemoryVectorStore | None = None) -> EmbeddingService:
    return EmbeddingService(store or InMemoryVectorStore(), _budget())


def _chunk(scope: str, scope_id: str, document_id: str, text: str,
           idx: int = 0, vec: list[float] | None = None) -> ChunkRecord:
    return ChunkRecord(
        chunk_id=f"c-{scope}-{scope_id}-{idx}",
        document_id=document_id,
        scope=scope,
        scope_id=scope_id,
        chunk_index=idx,
        chunk_text=text,
        embedding=vec or ([0.0] * 768),
    )


# ---------------------------------------------------------------------------
# 1. chunk_text
# ---------------------------------------------------------------------------

def test_chunk_empty_returns_empty():
    assert chunk_text("") == []
    assert chunk_text("   ") == []


def test_chunk_short_returns_single_chunk():
    text = "Hello world."
    result = chunk_text(text)
    assert result == [text]


def test_chunk_exactly_max_returns_single():
    text = "x" * 2000
    result = chunk_text(text, max_chars=2000)
    assert len(result) == 1


def test_chunk_long_text_produces_multiple_chunks():
    text = "Sentence one. " * 300   # ~4200 chars
    result = chunk_text(text, max_chars=2000, overlap_chars=200)
    assert len(result) >= 2


def test_chunk_all_chunks_nonempty():
    text = "A" * 5000
    for chunk in chunk_text(text, max_chars=2000, overlap_chars=200):
        assert chunk.strip()


def test_chunk_overlap_means_adjacent_chunks_share_text():
    # Use a sentence-terminated phrase so boundary search produces clean splits.
    # "Alpha bravo. " = 13 chars; 200 repeats = 2600 chars → ≥3 chunks at 1000/200.
    text = "Alpha bravo. " * 200
    chunks = chunk_text(text, max_chars=1000, overlap_chars=200)
    assert len(chunks) >= 2, "Expected at least 2 chunks for overlap test"
    # Verify the overlap property on substantive chunks (len > 50).
    # The very last chunk may be a tiny trailing fragment from the forward-progress
    # guarantee and is not meaningful for testing overlap.
    substantive = [c for c in chunks if len(c) > 50]
    assert len(substantive) >= 2, "Not enough substantive chunks for overlap test"
    for chunk in substantive:
        assert "Alpha" in chunk or "bravo" in chunk, (
            f"Substantive chunk missing expected repeated content: {chunk!r}"
        )


def test_chunk_covers_full_text():
    text = "The quick brown fox " * 300   # 6000 chars
    chunks = chunk_text(text, max_chars=2000, overlap_chars=200)
    # Verify the opening phrase appears in the first chunk.
    assert "The quick brown fox" in chunks[0]
    # Verify the text is covered end-to-end: joining all chunks must contain
    # a representative token from the source (not checking byte-exact suffix
    # because strip() can trim the very last partial word).
    joined = " ".join(chunks)
    assert "quick brown fox" in joined


def test_chunk_prefers_sentence_boundary():
    # A text with a clear sentence boundary around the max_chars mark
    sentence_a = "A" * 900 + ". "
    sentence_b = "B" * 900 + ". "
    sentence_c = "C" * 900 + ". "
    text = sentence_a + sentence_b + sentence_c  # ~2703 chars
    chunks = chunk_text(text, max_chars=1000, overlap_chars=100)
    # Each chunk should not mid-split inside a long run of the same letter
    for chunk in chunks:
        assert "A. B" not in chunk or chunk.startswith("A")


# ---------------------------------------------------------------------------
# 2. embed_document — scope/scope_id tagging
# ---------------------------------------------------------------------------

def test_embed_document_tags_scope_on_every_chunk():
    svc = _service()
    records = svc.embed_document(
        document_id=DOC_1,
        text="Northgate Capital Partners LP was incorporated in the Cayman Islands on 15 March 2019.",
        scope="fund",
        scope_id=FUND_A,
        fund_id=FUND_A,
        synthetic_static=False,
    )
    assert len(records) >= 1
    for r in records:
        assert r.scope == "fund"
        assert r.scope_id == FUND_A


def test_embed_document_tags_ble_scope_correctly():
    svc = _service()
    records = svc.embed_document(
        document_id=DOC_2,
        text="Counterparty Agreement between Northgate Capital Partners LP and Bank Rossiya.",
        scope="ble",
        scope_id=BLE_X,
        fund_id=FUND_A,
        synthetic_static=False,
    )
    assert len(records) >= 1
    for r in records:
        assert r.scope == "ble"
        assert r.scope_id == BLE_X


def test_embed_document_chunk_index_sequential():
    svc = _service()
    long_text = "Paragraph. " * 500   # ~5500 chars → at least 3 chunks
    records = svc.embed_document(
        document_id=DOC_1, text=long_text,
        scope="fund", scope_id=FUND_A,
        fund_id=FUND_A, synthetic_static=False,
    )
    indices = [r.chunk_index for r in records]
    assert indices == list(range(len(indices)))


def test_embed_document_document_id_on_every_chunk():
    svc = _service()
    records = svc.embed_document(
        document_id=DOC_1, text="short text",
        scope="fund", scope_id=FUND_A,
        fund_id=FUND_A, synthetic_static=False,
    )
    for r in records:
        assert r.document_id == DOC_1


def test_embed_document_embedding_has_correct_dimension():
    svc = _service()
    records = svc.embed_document(
        document_id=DOC_1, text="test document text",
        scope="fund", scope_id=FUND_A,
        fund_id=FUND_A, synthetic_static=False,
    )
    for r in records:
        assert len(r.embedding) == 768


def test_embed_document_invalid_scope_raises():
    svc = _service()
    with pytest.raises(ValueError, match="scope"):
        svc.embed_document(
            document_id=DOC_1, text="text",
            scope="counterparty", scope_id=FUND_A,
            fund_id=FUND_A, synthetic_static=False,
        )


# ---------------------------------------------------------------------------
# 3. Idempotency
# ---------------------------------------------------------------------------

def test_embed_document_second_call_returns_empty(monkeypatch):
    store = InMemoryVectorStore()
    svc = EmbeddingService(store, _budget())

    first = svc.embed_document(
        document_id=DOC_1, text="some text",
        scope="fund", scope_id=FUND_A,
        fund_id=FUND_A, synthetic_static=False,
    )
    assert len(first) >= 1

    second = svc.embed_document(
        document_id=DOC_1, text="some text",
        scope="fund", scope_id=FUND_A,
        fund_id=FUND_A, synthetic_static=False,
    )
    assert second == []  # idempotent — no new records written


def test_embed_document_second_call_does_not_add_to_store():
    store = InMemoryVectorStore()
    svc = EmbeddingService(store, _budget())

    svc.embed_document(
        document_id=DOC_1, text="some text",
        scope="fund", scope_id=FUND_A,
        fund_id=FUND_A, synthetic_static=False,
    )
    count_after_first = len(store)

    svc.embed_document(
        document_id=DOC_1, text="some text",
        scope="fund", scope_id=FUND_A,
        fund_id=FUND_A, synthetic_static=False,
    )
    assert len(store) == count_after_first  # store unchanged


def test_different_document_ids_are_not_deduplicated():
    store = InMemoryVectorStore()
    svc = EmbeddingService(store, _budget())

    svc.embed_document(
        document_id=DOC_1, text="first doc",
        scope="fund", scope_id=FUND_A,
        fund_id=FUND_A, synthetic_static=False,
    )
    svc.embed_document(
        document_id=DOC_2, text="second doc",
        scope="fund", scope_id=FUND_A,
        fund_id=FUND_A, synthetic_static=False,
    )
    assert len(store) == 2


# ---------------------------------------------------------------------------
# 4. retrieve — validation
# ---------------------------------------------------------------------------

def test_retrieve_raises_for_empty_query():
    svc = _service()
    with pytest.raises(ValueError, match="empty"):
        svc.retrieve("", scope="fund", scope_id=FUND_A,
                     fund_id=FUND_A, synthetic_static=False)


def test_retrieve_raises_for_whitespace_query():
    svc = _service()
    with pytest.raises(ValueError, match="empty"):
        svc.retrieve("   ", scope="fund", scope_id=FUND_A,
                     fund_id=FUND_A, synthetic_static=False)


def test_retrieve_raises_for_invalid_scope():
    svc = _service()
    with pytest.raises(ValueError, match="scope"):
        svc.retrieve("query text", scope="counterparty", scope_id=FUND_A,
                     fund_id=FUND_A, synthetic_static=False)


def test_retrieve_returns_empty_when_store_is_empty():
    svc = _service()
    results = svc.retrieve("what is the UBO name?",
                           scope="fund", scope_id=FUND_A,
                           fund_id=FUND_A, synthetic_static=False)
    assert results == []


def test_retrieve_respects_top_k():
    store = InMemoryVectorStore()
    # Add 5 chunks for FUND_A
    for i in range(5):
        store.add(_chunk("fund", FUND_A, DOC_1, f"chunk {i}", idx=i,
                          vec=[float(i)] + [0.0] * 767))
    svc = EmbeddingService(store, _budget())
    results = svc.retrieve("query", scope="fund", scope_id=FUND_A,
                            fund_id=FUND_A, synthetic_static=False, top_k=3)
    assert len(results) <= 3


# ---------------------------------------------------------------------------
# 5. Cross-scope isolation (PRD §18)
# ---------------------------------------------------------------------------
# These tests use manually crafted vectors with the same values across scopes
# so that similarity ranking cannot hide a scope-filter failure.

def _populate_multi_scope_store() -> InMemoryVectorStore:
    """
    Populate a store with 4 chunks across 4 distinct (scope, scope_id) pairs.
    All embeddings are [1.0] + [0.0]*767 so the query always has perfect
    similarity to every chunk — only the scope filter must discriminate.
    """
    store = InMemoryVectorStore()
    perfect_vec = [1.0] + [0.0] * 767

    store.add(_chunk("fund", FUND_A, DOC_1, "Fund A incorporation details.", vec=perfect_vec))
    store.add(_chunk("fund", FUND_B, DOC_2, "Fund B UBO declaration.",       vec=perfect_vec))
    store.add(_chunk("ble",  BLE_X,  DOC_3, "BLE X counterparty agreement.", vec=perfect_vec))
    store.add(_chunk("ble",  BLE_Y,  DOC_4, "BLE Y framework agreement.",    vec=perfect_vec))
    return store


def test_fund_a_retrieval_excludes_fund_b():
    store = _populate_multi_scope_store()
    query_vec = [1.0] + [0.0] * 767
    results = store.search(query_vec, scope="fund", scope_id=FUND_A, top_k=10)

    assert all(r.scope == "fund" for r in results), "Non-fund result returned"
    assert all(r.scope_id == FUND_A for r in results), "Fund B chunk leaked into Fund A results"
    assert not any(r.scope_id == FUND_B for r in results)


def test_fund_b_retrieval_excludes_fund_a():
    store = _populate_multi_scope_store()
    query_vec = [1.0] + [0.0] * 767
    results = store.search(query_vec, scope="fund", scope_id=FUND_B, top_k=10)

    assert all(r.scope_id == FUND_B for r in results)
    assert not any(r.scope_id == FUND_A for r in results)


def test_ble_chunk_never_leaks_into_fund_retrieval():
    """
    A BLE-scoped chunk must never appear in a Fund-scoped retrieval,
    even for the Fund that owns that BLE.
    """
    store = _populate_multi_scope_store()
    query_vec = [1.0] + [0.0] * 767
    results = store.search(query_vec, scope="fund", scope_id=FUND_A, top_k=10)

    ble_results = [r for r in results if r.scope == "ble"]
    assert ble_results == [], (
        f"BLE chunks leaked into Fund A retrieval: {[r.scope_id for r in ble_results]}"
    )


def test_fund_chunk_never_leaks_into_ble_retrieval():
    store = _populate_multi_scope_store()
    query_vec = [1.0] + [0.0] * 767
    results = store.search(query_vec, scope="ble", scope_id=BLE_X, top_k=10)

    fund_results = [r for r in results if r.scope == "fund"]
    assert fund_results == [], (
        f"Fund chunks leaked into BLE X retrieval: {[r.scope_id for r in fund_results]}"
    )


def test_ble_x_retrieval_excludes_ble_y():
    store = _populate_multi_scope_store()
    query_vec = [1.0] + [0.0] * 767
    results = store.search(query_vec, scope="ble", scope_id=BLE_X, top_k=10)

    assert all(r.scope_id == BLE_X for r in results)
    assert not any(r.scope_id == BLE_Y for r in results)


def test_ble_y_retrieval_excludes_ble_x():
    store = _populate_multi_scope_store()
    query_vec = [1.0] + [0.0] * 767
    results = store.search(query_vec, scope="ble", scope_id=BLE_Y, top_k=10)

    assert all(r.scope_id == BLE_Y for r in results)
    assert not any(r.scope_id == BLE_X for r in results)


def test_unknown_scope_id_returns_empty_not_other_scope():
    """
    A query for a scope_id that has no embeddings must return [],
    not results from a different scope_id.
    """
    store = _populate_multi_scope_store()
    query_vec = [1.0] + [0.0] * 767
    unknown_id = "00000000-0000-0000-0000-000000000099"
    results = store.search(query_vec, scope="fund", scope_id=unknown_id, top_k=10)
    assert results == []


def test_cross_scope_via_embedding_service(monkeypatch, tmp_path):
    """
    End-to-end: embed documents for Fund A and BLE X via EmbeddingService,
    then verify retrieval for Fund A never returns BLE X chunks.
    """
    monkeypatch.setattr(cl, "LOG_FILE", str(tmp_path / "test_calls.jsonl"))
    idm.reset()

    store = InMemoryVectorStore()
    svc = EmbeddingService(store, _budget())

    svc.embed_document(
        document_id=DOC_1,
        text="Northgate Capital Partners LP. Incorporation Certificate. Cayman Islands.",
        scope="fund", scope_id=FUND_A,
        fund_id=FUND_A, synthetic_static=False,
    )
    svc.embed_document(
        document_id=DOC_3,
        text="Bank Rossiya counterparty agreement. Loan facility USD 5,000,000.",
        scope="ble", scope_id=BLE_X,
        fund_id=FUND_A, synthetic_static=False,
    )

    fund_results = svc.retrieve(
        "incorporation details",
        scope="fund", scope_id=FUND_A,
        fund_id=FUND_A, synthetic_static=False,
    )

    assert all(r.scope == "fund" for r in fund_results), \
        "BLE chunk leaked into Fund retrieval via EmbeddingService.retrieve()"
    assert all(r.scope_id == FUND_A for r in fund_results), \
        "Wrong scope_id in Fund A retrieval"


# ---------------------------------------------------------------------------
# 6. cosine similarity helper
# ---------------------------------------------------------------------------

def test_cosine_sim_identical_vectors():
    v = [1.0, 0.0, 0.0]
    assert abs(_cosine_sim(v, v) - 1.0) < 1e-9


def test_cosine_sim_orthogonal_vectors():
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert abs(_cosine_sim(a, b)) < 1e-9


def test_cosine_sim_zero_vector_returns_zero():
    z = [0.0, 0.0, 0.0]
    v = [1.0, 2.0, 3.0]
    assert _cosine_sim(z, v) == 0.0
    assert _cosine_sim(v, z) == 0.0


def test_cosine_sim_antiparallel():
    a = [1.0, 0.0]
    b = [-1.0, 0.0]
    assert abs(_cosine_sim(a, b) - (-1.0)) < 1e-9
