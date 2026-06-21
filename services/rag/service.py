"""
PRD §8.2, §18 — RAG Retrieval Service.

Indexes documents and retrieves relevant chunks, scoped strictly to a Fund or BLE.
MOCK=true uses keyword-overlap scoring over an in-memory dict — zero embedding cost,
safe for all dev/test runs. MOCK=false delegates to EmbeddingService (bge-base-en-v1.5).

Cross-scope isolation is structural: the scope/scope_id filter is applied before any
ranking. There is no code path that performs an unscoped search. (PRD §18)
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING
from uuid import uuid4

from services.guards import assert_fund_allows_ai

if TYPE_CHECKING:
    from services.budget import BudgetCap
    from services.embedding_service import ChunkRecord, EmbeddingService, VectorStore

MOCK: bool = os.getenv("MOCK", "true").lower() == "true"


def _keyword_score(query: str, text: str) -> int:
    """Count word-level overlap between query and chunk text (case-insensitive)."""
    q_words = set(query.lower().split())
    t_words = set(text.lower().split())
    return len(q_words & t_words)


class RAGService:
    """
    Scope-isolated retrieval service.

    index_document() — chunk, embed (or mock), and store one document.
    retrieve()       — return top-k chunks for a scoped query.

    Both methods call assert_fund_allows_ai() before doing any work, enforcing
    the hard prohibition on static demo funds triggering AI operations.
    (CLAUDE.md rule 10, PRD §17)
    """

    def __init__(
        self,
        store: "VectorStore | None" = None,
        budget: "BudgetCap | None" = None,
        ruleset_version: str = "rag-v1",
    ) -> None:
        self._mock_chunks: dict[tuple[str, str], list["ChunkRecord"]] = {}
        self._store = store
        self._budget = budget
        self._ruleset_version = ruleset_version
        self._embedding_service: "EmbeddingService | None" = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def index_document(
        self,
        doc_id: str,
        text: str,
        scope: str,
        scope_id: str,
        fund_id: str,
        synthetic_static: bool = False,
        budget: "BudgetCap | None" = None,
    ) -> "list[ChunkRecord]":
        """
        Index one document. Idempotent: re-indexing the same doc_id under the same
        scope is a no-op that returns the already-stored chunks.
        """
        assert_fund_allows_ai(fund_id, synthetic_static)

        if scope not in ("fund", "ble"):
            raise ValueError(f"scope must be 'fund' or 'ble', got {scope!r}")

        if MOCK:
            from services.embedding_service import ChunkRecord  # noqa: PLC0415

            key = (scope, scope_id)
            existing = self._mock_chunks.get(key, [])
            already = [c for c in existing if c.document_id == doc_id]
            if already:
                return already

            chunk = ChunkRecord(
                chunk_id=str(uuid4()),
                document_id=doc_id,
                scope=scope,
                scope_id=scope_id,
                chunk_index=0,
                chunk_text=text,
                embedding=[],
            )
            self._mock_chunks.setdefault(key, []).append(chunk)
            return [chunk]

        return self._get_embedding_service().embed_document(
            document_id=doc_id,
            text=text,
            scope=scope,
            scope_id=scope_id,
            fund_id=fund_id,
            synthetic_static=synthetic_static,
        )

    def retrieve(
        self,
        query: str,
        scope: str,
        scope_id: str,
        fund_id: str,
        synthetic_static: bool = False,
        top_k: int = 3,
    ) -> "list[ChunkRecord]":
        """
        Return top-k chunks most relevant to query, restricted to (scope, scope_id).
        Raises ValueError rather than falling back to an unscoped search. (PRD §18)
        """
        assert_fund_allows_ai(fund_id, synthetic_static)

        if not query or not query.strip():
            raise ValueError("query must not be empty")
        if scope not in ("fund", "ble"):
            raise ValueError(f"scope must be 'fund' or 'ble', got {scope!r}")

        if MOCK:
            key = (scope, scope_id)
            candidates = self._mock_chunks.get(key, [])
            scored = sorted(
                candidates,
                key=lambda c: _keyword_score(query, c.chunk_text),
                reverse=True,
            )
            return scored[:top_k]

        return self._get_embedding_service().retrieve(
            query_text=query,
            scope=scope,
            scope_id=scope_id,
            fund_id=fund_id,
            synthetic_static=synthetic_static,
            top_k=top_k,
        )

    def clear(self) -> None:
        """Reset all in-memory state. Used between tests."""
        self._mock_chunks.clear()
        if self._embedding_service is not None:
            try:
                self._embedding_service._store.clear()  # type: ignore[attr-defined]
            except AttributeError:
                pass
            from services.idempotency import reset as _idm_reset  # noqa: PLC0415

            _idm_reset()
        self._embedding_service = None

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _get_embedding_service(self) -> "EmbeddingService":
        if self._embedding_service is None:
            from services.budget import BudgetCap as _BudgetCap  # noqa: PLC0415
            from services.embedding_service import EmbeddingService, InMemoryVectorStore  # noqa: PLC0415

            _store = self._store if self._store is not None else InMemoryVectorStore()
            _budget = self._budget if self._budget is not None else _BudgetCap(limit_usd=5.0)
            self._embedding_service = EmbeddingService(
                store=_store,
                budget=_budget,
                ruleset_version=self._ruleset_version,
            )
        return self._embedding_service
