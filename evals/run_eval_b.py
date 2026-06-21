"""
Eval B — RAG Retrieval Quality (PRD §15.2, §8.2, §18).

Metrics:
  precision@3   — expected_chunk_substring appears in ANY of the top-3 retrieved chunks.
  leakage       — forbidden_substrings must NEVER appear in results from the wrong scope.

Pass bar: precision@3 >= 0.95 AND leakage_detected == 0.

Run with MOCK=true (default) to verify plumbing without model downloads.
Run with MOCK=false + PYTHONPATH=<project_root> to verify real bge-base-en-v1.5 retrieval.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

MOCK: bool = os.getenv("MOCK", "true").lower() == "true"

PASS_BAR: float = 0.95
TOP_K: int = 3

_PROJECT_ROOT = Path(__file__).parent.parent
_GOLDEN_SET_PATH = _PROJECT_ROOT / "evals" / "golden_retrieval.jsonl"
_LOG_PATH = _PROJECT_ROOT / "evals" / "eval_b_runs.jsonl"

# Paths to all 12 indexed documents.  Keyed by (scope, scope_id, doc_id).
_DOC_MANIFEST: list[dict] = [
    # Fund F1
    {"scope": "fund", "scope_id": "f0000001-f000-0000-0000-000000000001",
     "fund_id": "f0000001-f000-0000-0000-000000000001", "doc_id": "doc-f1-incorp-cert",
     "file_path": "documents/fund/f0000001-f000-0000-0000-000000000001/doc-f1-incorp-cert.txt"},
    {"scope": "fund", "scope_id": "f0000001-f000-0000-0000-000000000001",
     "fund_id": "f0000001-f000-0000-0000-000000000001", "doc_id": "doc-f1-ubo-decl",
     "file_path": "documents/fund/f0000001-f000-0000-0000-000000000001/doc-f1-ubo-decl.txt"},
    # BLE B11
    {"scope": "ble", "scope_id": "b0001001-b000-0000-0000-000000000001",
     "fund_id": "f0000001-f000-0000-0000-000000000001", "doc_id": "doc-f1-b1-cpty-agmt",
     "file_path": "documents/ble/b0001001-b000-0000-0000-000000000001/doc-f1-b1-cpty-agmt.txt"},
    # Fund F2
    {"scope": "fund", "scope_id": "f0000002-f000-0000-0000-000000000002",
     "fund_id": "f0000002-f000-0000-0000-000000000002", "doc_id": "doc-f2-ubo-decl",
     "file_path": "documents/fund/f0000002-f000-0000-0000-000000000002/doc-f2-ubo-decl.txt"},
    {"scope": "fund", "scope_id": "f0000002-f000-0000-0000-000000000002",
     "fund_id": "f0000002-f000-0000-0000-000000000002", "doc_id": "doc-f2-annual-report",
     "file_path": "documents/fund/f0000002-f000-0000-0000-000000000002/doc-f2-annual-report.txt"},
    # BLE B21
    {"scope": "ble", "scope_id": "b0002001-b000-0000-0000-000000000002",
     "fund_id": "f0000002-f000-0000-0000-000000000002", "doc_id": "doc-f2-b1-framework-agmt",
     "file_path": "documents/ble/b0002001-b000-0000-0000-000000000002/doc-f2-b1-framework-agmt.txt"},
    # Fund F3
    {"scope": "fund", "scope_id": "f0000003-f000-0000-0000-000000000003",
     "fund_id": "f0000003-f000-0000-0000-000000000003", "doc_id": "doc-f3-incorp-cert",
     "file_path": "documents/fund/f0000003-f000-0000-0000-000000000003/doc-f3-incorp-cert.txt"},
    # Fund F4
    {"scope": "fund", "scope_id": "f0000004-f000-0000-0000-000000000004",
     "fund_id": "f0000004-f000-0000-0000-000000000004", "doc_id": "doc-f4-reg-licence",
     "file_path": "documents/fund/f0000004-f000-0000-0000-000000000004/doc-f4-reg-licence.txt"},
    {"scope": "fund", "scope_id": "f0000004-f000-0000-0000-000000000004",
     "fund_id": "f0000004-f000-0000-0000-000000000004", "doc_id": "doc-f4-incorp-cert",
     "file_path": "documents/fund/f0000004-f000-0000-0000-000000000004/doc-f4-incorp-cert.txt"},
    # BLE B41
    {"scope": "ble", "scope_id": "b0004001-b000-0000-0000-000000000005",
     "fund_id": "f0000004-f000-0000-0000-000000000004", "doc_id": "doc-f4-b1-cpty-agmt",
     "file_path": "documents/ble/b0004001-b000-0000-0000-000000000005/doc-f4-b1-cpty-agmt.txt"},
    # Fund F5
    {"scope": "fund", "scope_id": "f0000005-f000-0000-0000-000000000005",
     "fund_id": "f0000005-f000-0000-0000-000000000005", "doc_id": "doc-f5-invest-mgr-agmt",
     "file_path": "documents/fund/f0000005-f000-0000-0000-000000000005/doc-f5-invest-mgr-agmt.txt"},
    # BLE B51
    {"scope": "ble", "scope_id": "b0005001-b000-0000-0000-000000000006",
     "fund_id": "f0000005-f000-0000-0000-000000000005", "doc_id": "doc-f5-b1-cpty-agmt",
     "file_path": "documents/ble/b0005001-b000-0000-0000-000000000006/doc-f5-b1-cpty-agmt.txt"},
]

_cache: dict[str, "EvalBResult"] = {}


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class QueryResult:
    query_id: str
    question: str
    scope: str
    scope_id: str
    is_leakage_test: bool
    hit: bool
    expected_chunk_substring: Optional[str]
    found_in_rank: Optional[int]
    leakage_content: Optional[str]


@dataclass
class EvalBResult:
    total_retrieval_queries: int
    retrieval_hits: int
    hit_rate: float
    total_leakage_tests: int
    leakage_detected: int
    passed: bool
    query_results: list[QueryResult]
    run_at: str
    is_mock: bool
    latency_ms: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def load_golden_set(path: "Path | str | None" = None) -> list[dict]:
    p = Path(path) if path else _GOLDEN_SET_PATH
    entries = []
    with open(p, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def _check_hit(expected_substring: str, chunks: list) -> Optional[int]:
    """Return 1-based rank of first chunk containing expected_substring, or None."""
    for rank, chunk in enumerate(chunks, start=1):
        if expected_substring in chunk.chunk_text:
            return rank
    return None


def _check_leakage_in_chunks(forbidden_substrings: list[str], chunks: list) -> Optional[str]:
    """Return first forbidden substring found in any chunk, or None if clean."""
    for chunk in chunks:
        for forbidden in forbidden_substrings:
            if forbidden in chunk.chunk_text:
                return forbidden
    return None


def _build_rag_service() -> "RAGService":  # type: ignore[name-defined]
    from services.budget import BudgetCap
    from services.embedding_service import InMemoryVectorStore
    from services.rag import RAGService

    return RAGService(
        store=InMemoryVectorStore(),
        budget=BudgetCap(limit_usd=5.0),
        ruleset_version="rag-v1",
    )


def _index_all_documents(rag: "RAGService") -> None:  # type: ignore[name-defined]
    for doc in _DOC_MANIFEST:
        file_path = _PROJECT_ROOT / doc["file_path"]
        text = file_path.read_text(encoding="utf-8")
        rag.index_document(
            doc_id=doc["doc_id"],
            text=text,
            scope=doc["scope"],
            scope_id=doc["scope_id"],
            fund_id=doc["fund_id"],
            synthetic_static=False,
        )


# ---------------------------------------------------------------------------
# Core evaluation
# ---------------------------------------------------------------------------


def run_eval_b(
    golden_set_path: "Path | str | None" = None,
    mock: "bool | None" = None,
    log_path: "Path | str | None" = None,
) -> EvalBResult:
    """
    Run Eval B against the golden retrieval set.

    Args:
        golden_set_path: Override the default golden_retrieval.jsonl path.
        mock:            Override the MOCK env-var setting for this run.
        log_path:        Override the default eval_b_runs.jsonl log path.

    Returns:
        EvalBResult with precision@3, leakage counts, and per-query details.
    """
    is_mock = MOCK if mock is None else mock
    cache_key = f"{golden_set_path or 'default'}-{is_mock}"
    if cache_key in _cache:
        return _cache[cache_key]

    t0 = time.monotonic()
    entries = load_golden_set(golden_set_path)

    rag = _build_rag_service()
    _index_all_documents(rag)

    query_results: list[QueryResult] = []
    leakage_detected = 0

    for entry in entries:
        chunks = rag.retrieve(
            query=entry["question"],
            scope=entry["scope"],
            scope_id=entry["scope_id"],
            fund_id=entry["fund_id"],
            synthetic_static=False,
            top_k=TOP_K,
        )

        if entry.get("is_cross_scope_leakage_test"):
            forbidden = entry.get("forbidden_substrings", [])
            found = _check_leakage_in_chunks(forbidden, chunks)
            if found is not None:
                leakage_detected += 1

            query_results.append(QueryResult(
                query_id=entry["query_id"],
                question=entry["question"],
                scope=entry["scope"],
                scope_id=entry["scope_id"],
                is_leakage_test=True,
                hit=found is None,
                expected_chunk_substring=None,
                found_in_rank=None,
                leakage_content=found,
            ))
        else:
            expected = entry["expected_chunk_substring"]
            rank = _check_hit(expected, chunks)
            query_results.append(QueryResult(
                query_id=entry["query_id"],
                question=entry["question"],
                scope=entry["scope"],
                scope_id=entry["scope_id"],
                is_leakage_test=False,
                hit=rank is not None,
                expected_chunk_substring=expected,
                found_in_rank=rank,
                leakage_content=None,
            ))

    retrieval_results = [r for r in query_results if not r.is_leakage_test]
    retrieval_hits = sum(1 for r in retrieval_results if r.hit)
    hit_rate = retrieval_hits / len(retrieval_results) if retrieval_results else 0.0

    leakage_tests = [r for r in query_results if r.is_leakage_test]

    result = EvalBResult(
        total_retrieval_queries=len(retrieval_results),
        retrieval_hits=retrieval_hits,
        hit_rate=hit_rate,
        total_leakage_tests=len(leakage_tests),
        leakage_detected=leakage_detected,
        passed=hit_rate >= PASS_BAR and leakage_detected == 0,
        query_results=query_results,
        run_at=datetime.now(timezone.utc).isoformat(),
        is_mock=is_mock,
        latency_ms=int((time.monotonic() - t0) * 1000),
    )

    _write_log(result, log_path)
    _cache[cache_key] = result
    return result


def _write_log(result: EvalBResult, log_path: "Path | str | None" = None) -> None:
    p = Path(log_path) if log_path else _LOG_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "run_at": result.run_at,
        "is_mock": result.is_mock,
        "total_retrieval_queries": result.total_retrieval_queries,
        "retrieval_hits": result.retrieval_hits,
        "hit_rate": result.hit_rate,
        "total_leakage_tests": result.total_leakage_tests,
        "leakage_detected": result.leakage_detected,
        "passed": result.passed,
        "latency_ms": result.latency_ms,
    }
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def _print_report(result: EvalBResult) -> None:
    print(f"\n{'='*60}")
    print(f"Eval B — RAG Retrieval Quality")
    print(f"{'='*60}")
    print(f"Mode:               {'MOCK' if result.is_mock else 'REAL (bge-base-en-v1.5)'}")
    print(f"Retrieval queries:  {result.retrieval_hits}/{result.total_retrieval_queries} hit")
    print(f"Precision@3:        {result.hit_rate:.1%}")
    print(f"Leakage detected:   {result.leakage_detected}/{result.total_leakage_tests} tests")
    print(f"Latency:            {result.latency_ms} ms")
    print(f"PASSED:             {result.passed}")
    print(f"{'='*60}")

    misses = [r for r in result.query_results if not r.is_leakage_test and not r.hit]
    if misses:
        print("\nRetrieval MISSES:")
        for r in misses:
            print(f"  [{r.query_id}] {r.question[:60]!r}")
            print(f"          expected: {r.expected_chunk_substring!r}")

    leakage_failures = [r for r in result.query_results if r.is_leakage_test and not r.hit]
    if leakage_failures:
        print("\nLeakage FAILURES:")
        for r in leakage_failures:
            print(f"  [{r.query_id}] {r.question[:60]!r}")
            print(f"          forbidden found: {r.leakage_content!r}")


if __name__ == "__main__":
    result = run_eval_b()
    _print_report(result)
    raise SystemExit(0 if result.passed else 1)
