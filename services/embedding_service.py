"""
PRD §14, §17, §18 — Embedding Service.

Chunks documents, encodes them via BAAI/bge-base-en-v1.5 (self-hosted,
sentence-transformers), and writes 768-dim vectors to pgvector with
mandatory scope + scope_id metadata on every chunk.

Retrieval is hard-scoped: both VectorStore implementations apply
scope + scope_id as a mandatory WHERE / filter clause BEFORE ranking.
There is no code path that performs an unscoped vector search.
Cross-scope access raises ValueError. (PRD §18)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from uuid import uuid4

from services.ai_client import EMBEDDING_DIM, call_embedding
from services.budget import BudgetCap
from services.idempotency import is_already_processed, mark_processed

# ---------------------------------------------------------------------------
# sentence-transformers — optional at import time; required only when MOCK=false
# ---------------------------------------------------------------------------
try:
    from sentence_transformers import SentenceTransformer as _ST

    _ST_AVAILABLE = True
except ImportError:
    _ST_AVAILABLE = False

_model_cache: dict[str, "_ST"] = {}  # type: ignore[type-arg]

DEFAULT_MODEL = "BAAI/bge-base-en-v1.5"
DEFAULT_CHUNK_CHARS = 2000
DEFAULT_OVERLAP_CHARS = 200


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class ChunkRecord:
    chunk_id: str
    document_id: str
    scope: str       # 'fund' | 'ble'
    scope_id: str    # fund_id or ble_id — mandatory (PRD §18)
    chunk_index: int
    chunk_text: str
    embedding: list[float]


# ---------------------------------------------------------------------------
# Text chunking
# ---------------------------------------------------------------------------


def chunk_text(
    text: str,
    max_chars: int = DEFAULT_CHUNK_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> list[str]:
    """
    Split text into overlapping character-bounded chunks, preferring to
    break at sentence boundaries (.  !  ?  \\n).

    Returns an empty list for blank input and exactly one chunk when
    len(text) <= max_chars.
    """
    if not text or not text.strip():
        return []

    text = text.strip()
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    start = 0

    while start < len(text):
        end = min(start + max_chars, len(text))

        if end < len(text):
            # Walk backwards from end to find a sentence boundary.
            boundary = end
            search_floor = max(start + max_chars // 2, start + 1)
            for i in range(end, search_floor, -1):
                if text[i] in ".!?\n":
                    boundary = i + 1
                    break
            end = boundary

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        next_start = end - overlap_chars
        # Guarantee forward progress — prevents infinite loop when overlap >= step.
        if next_start <= start:
            next_start = start + 1
        start = next_start

    return chunks


# ---------------------------------------------------------------------------
# Model encoding (called by services.ai_client._real_embedding_call)
# ---------------------------------------------------------------------------


def encode_text(text: str, model_name: str = DEFAULT_MODEL) -> list[float]:
    """
    Encode text with the specified sentence-transformers model.
    Raises ImportError if sentence-transformers is not installed — callers
    should use MOCK=true (the default) during dev and testing.
    """
    if not _ST_AVAILABLE:
        raise ImportError(
            "sentence-transformers is not installed. "
            "Install it with:  pip install sentence-transformers\n"
            "Or set MOCK=true (the default) for dev/test work."
        )
    return _load_model(model_name).encode(text, normalize_embeddings=True).tolist()


def _load_model(model_name: str) -> "_ST":  # type: ignore[name-defined]
    if model_name not in _model_cache:
        _model_cache[model_name] = _ST(model_name)  # type: ignore[name-defined]
    return _model_cache[model_name]


# ---------------------------------------------------------------------------
# Vector stores
# ---------------------------------------------------------------------------


@runtime_checkable
class VectorStore(Protocol):
    def add(self, record: ChunkRecord) -> None: ...

    def search(
        self,
        query_vec: list[float],
        scope: str,
        scope_id: str,
        top_k: int = 5,
    ) -> list[ChunkRecord]: ...


class InMemoryVectorStore:
    """
    In-process vector store for dev and testing.

    The scope + scope_id filter is applied before cosine ranking — structurally
    identical to the pgvector WHERE clause. This makes cross-scope isolation
    testable without a real database.
    """

    def __init__(self) -> None:
        self._records: list[ChunkRecord] = []

    def add(self, record: ChunkRecord) -> None:
        self._records.append(record)

    def search(
        self,
        query_vec: list[float],
        scope: str,
        scope_id: str,
        top_k: int = 5,
    ) -> list[ChunkRecord]:
        # ── Scope filter MUST come first ──────────────────────────────────────
        # This mirrors:  WHERE scope = %s AND scope_id = %s::uuid
        # in the pgvector query.  Results from other scopes are structurally
        # unreachable — there is no fallback to an unscoped search.
        candidates = [
            r for r in self._records
            if r.scope == scope and r.scope_id == scope_id
        ]
        ranked = sorted(
            candidates,
            key=lambda r: _cosine_sim(query_vec, r.embedding),
            reverse=True,
        )
        return ranked[:top_k]

    def clear(self) -> None:
        self._records.clear()

    def __len__(self) -> int:
        return len(self._records)


class PgVectorStore:
    """
    pgvector-backed store. Requires DATABASE_URL and Phase 1 migration.

    Every INSERT and SELECT includes scope + scope_id — no unscoped operation
    is ever issued. The <=> operator (cosine distance) is used for ranking.
    """

    def __init__(self, conn) -> None:
        self._conn = conn

    def add(self, record: ChunkRecord) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO document_embeddings
                    (embedding_id, scope, scope_id, document_id,
                     chunk_index, chunk_text, embedding)
                VALUES (%s, %s, %s::uuid, %s::uuid, %s, %s, %s::vector)
                ON CONFLICT (document_id, chunk_index) DO NOTHING
                """,
                (
                    str(uuid4()),
                    record.scope,
                    record.scope_id,
                    record.document_id,
                    record.chunk_index,
                    record.chunk_text,
                    # pgvector accepts '[0.1, 0.2, ...]' as a text cast to vector
                    "[" + ",".join(str(v) for v in record.embedding) + "]",
                ),
            )
        self._conn.commit()

    def search(
        self,
        query_vec: list[float],
        scope: str,
        scope_id: str,
        top_k: int = 5,
    ) -> list[ChunkRecord]:
        vec_literal = "[" + ",".join(str(v) for v in query_vec) + "]"
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT embedding_id, scope, scope_id, document_id,
                       chunk_index, chunk_text
                FROM   document_embeddings
                WHERE  scope     = %s
                  AND  scope_id  = %s::uuid
                ORDER  BY embedding <=> %s::vector
                LIMIT  %s
                """,
                (scope, scope_id, vec_literal, top_k),
            )
            rows = cur.fetchall()
        return [
            ChunkRecord(
                chunk_id=str(row[0]),
                document_id=str(row[3]),
                scope=row[1],
                scope_id=str(row[2]),
                chunk_index=row[4],
                chunk_text=row[5],
                embedding=[],  # not fetched back; callers receive text, not vectors
            )
            for row in rows
        ]


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class EmbeddingService:
    """
    Orchestrates:  chunk_text → call_embedding → store.add   (embed_document)
                   call_embedding(query) → store.search        (retrieve)

    All embedding calls go through services.ai_client.call_embedding(), which
    enforces MOCK routing, the synthetic-static guard, budget cap, retry, and
    per-call logging.

    Retrieval is unconditionally scoped: both scope and scope_id are required
    parameters. There is no method signature that accepts open-ended queries.
    (PRD §18 — cross-scope leakage is a hard failure)
    """

    def __init__(
        self,
        store: VectorStore,
        budget: BudgetCap,
        ruleset_version: str = "v1",
    ) -> None:
        self._store = store
        self._budget = budget
        self._version = ruleset_version

    def embed_document(
        self,
        document_id: str,
        text: str,
        scope: str,
        scope_id: str,
        fund_id: str,
        synthetic_static: bool,
    ) -> list[ChunkRecord]:
        """
        Chunk, embed, and store one document.

        Idempotent: calling again for an already-embedded document_id returns []
        and makes no API call.  Returns the ChunkRecords written.
        """
        if scope not in ("fund", "ble"):
            raise ValueError(f"scope must be 'fund' or 'ble', got {scope!r}")

        stage_key = f"embedded:{document_id}"
        if is_already_processed(scope, scope_id, stage_key, self._version):
            return []

        chunks = chunk_text(text)
        if not chunks:
            return []

        records: list[ChunkRecord] = []
        for idx, chunk in enumerate(chunks):
            vec = call_embedding(
                text=chunk,
                fund_id=fund_id,
                synthetic_static=synthetic_static,
                scope=scope,
                scope_id=scope_id,
                budget=self._budget,
            )
            record = ChunkRecord(
                chunk_id=str(uuid4()),
                document_id=document_id,
                scope=scope,
                scope_id=scope_id,
                chunk_index=idx,
                chunk_text=chunk,
                embedding=vec,
            )
            self._store.add(record)
            records.append(record)

        mark_processed(scope, scope_id, stage_key, self._version)
        return records

    def retrieve(
        self,
        query_text: str,
        scope: str,
        scope_id: str,
        fund_id: str,
        synthetic_static: bool,
        top_k: int = 5,
    ) -> list[ChunkRecord]:
        """
        Return the top-k chunks most similar to query_text, restricted to
        (scope, scope_id).  Raises ValueError rather than falling back to an
        unscoped search.  (PRD §18)
        """
        if not query_text or not query_text.strip():
            raise ValueError("query_text must not be empty")
        if scope not in ("fund", "ble"):
            raise ValueError(f"scope must be 'fund' or 'ble', got {scope!r}")

        query_vec = call_embedding(
            text=query_text,
            fund_id=fund_id,
            synthetic_static=synthetic_static,
            scope=scope,
            scope_id=scope_id,
            budget=self._budget,
        )
        return self._store.search(query_vec, scope, scope_id, top_k)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cosine_sim(a: list[float], b: list[float]) -> float:
    """Cosine similarity in [−1, 1]. Returns 0.0 for zero vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x ** 2 for x in a) ** 0.5
    nb = sum(x ** 2 for x in b) ** 0.5
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)
