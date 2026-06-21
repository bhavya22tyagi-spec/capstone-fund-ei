"""Tests for evals.run_eval_b — Eval B harness (PRD §15.2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import evals.run_eval_b as harness
import services.idempotency as idm
import services.rag.service as rag_svc_module
from services.embedding_service import ChunkRecord

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_cache():
    harness._cache.clear()
    idm.reset()
    yield
    harness._cache.clear()
    idm.reset()


@pytest.fixture()
def log_path(tmp_path, monkeypatch):
    p = tmp_path / "eval_b_runs.jsonl"
    monkeypatch.setattr(harness, "_LOG_PATH", p)
    return p


@pytest.fixture(autouse=True)
def _force_mock(monkeypatch):
    monkeypatch.setattr(harness, "MOCK", True)
    monkeypatch.setattr(rag_svc_module, "MOCK", True)


# ---------------------------------------------------------------------------
# 1. Golden set loading
# ---------------------------------------------------------------------------


def test_golden_set_loads():
    entries = harness.load_golden_set()
    assert len(entries) == 34


def test_golden_set_has_30_retrieval_entries():
    entries = harness.load_golden_set()
    retrieval = [e for e in entries if not e.get("is_cross_scope_leakage_test")]
    assert len(retrieval) == 30


def test_golden_set_has_4_leakage_entries():
    entries = harness.load_golden_set()
    leakage = [e for e in entries if e.get("is_cross_scope_leakage_test")]
    assert len(leakage) == 4


def test_golden_set_required_fields():
    entries = harness.load_golden_set()
    for e in entries:
        assert "query_id" in e
        assert "question" in e
        assert "scope" in e
        assert "scope_id" in e
        assert "fund_id" in e


def test_retrieval_entries_have_expected_substring():
    entries = harness.load_golden_set()
    for e in entries:
        if not e.get("is_cross_scope_leakage_test"):
            assert e.get("expected_chunk_substring"), (
                f"{e['query_id']} missing expected_chunk_substring"
            )


def test_leakage_entries_have_forbidden_substrings():
    entries = harness.load_golden_set()
    for e in entries:
        if e.get("is_cross_scope_leakage_test"):
            assert e.get("forbidden_substrings"), (
                f"{e['query_id']} missing forbidden_substrings"
            )


def test_golden_set_scope_values_valid():
    entries = harness.load_golden_set()
    for e in entries:
        assert e["scope"] in ("fund", "ble"), f"{e['query_id']}: invalid scope {e['scope']!r}"


def test_golden_set_query_ids_unique():
    entries = harness.load_golden_set()
    ids = [e["query_id"] for e in entries]
    assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# 2. Helper functions
# ---------------------------------------------------------------------------


def _make_chunk(text: str) -> ChunkRecord:
    return ChunkRecord(
        chunk_id="test-id",
        document_id="doc-test",
        scope="fund",
        scope_id="f-test",
        chunk_index=0,
        chunk_text=text,
        embedding=[],
    )


def test_check_hit_found():
    chunk = _make_chunk("The registration number is EX-CYM-2019-08742 in Cayman.")
    rank = harness._check_hit("EX-CYM-2019-08742", [chunk])
    assert rank == 1


def test_check_hit_not_found():
    chunk = _make_chunk("Some other unrelated content.")
    rank = harness._check_hit("EX-CYM-2019-08742", [chunk])
    assert rank is None


def test_check_hit_correct_rank():
    c1 = _make_chunk("first chunk unrelated")
    c2 = _make_chunk("second chunk NCP-BR-2022-001 details")
    rank = harness._check_hit("NCP-BR-2022-001", [c1, c2])
    assert rank == 2


def test_check_leakage_found():
    chunk = _make_chunk("NCP-BR-2022-001 forbidden content here")
    result = harness._check_leakage_in_chunks(["NCP-BR-2022-001"], [chunk])
    assert result == "NCP-BR-2022-001"


def test_check_leakage_clean():
    chunk = _make_chunk("Clean content with no forbidden terms.")
    result = harness._check_leakage_in_chunks(["NCP-BR-2022-001"], [chunk])
    assert result is None


def test_check_leakage_multiple_forbidden_first_wins():
    chunk = _make_chunk("Content with EX-CYM-2019-08742 and NCP-BR-2022-001 both present")
    result = harness._check_leakage_in_chunks(
        ["EX-CYM-2019-08742", "NCP-BR-2022-001"], [chunk]
    )
    assert result == "EX-CYM-2019-08742"


def test_check_leakage_empty_chunks():
    result = harness._check_leakage_in_chunks(["forbidden"], [])
    assert result is None


# ---------------------------------------------------------------------------
# 3. Full MOCK run
# ---------------------------------------------------------------------------


def test_mock_run_passes(log_path):
    result = harness.run_eval_b(log_path=log_path)
    assert result.passed is True


def test_mock_run_hit_rate_perfect(log_path):
    result = harness.run_eval_b(log_path=log_path)
    assert result.hit_rate == 1.0


def test_mock_run_no_leakage(log_path):
    result = harness.run_eval_b(log_path=log_path)
    assert result.leakage_detected == 0


def test_mock_run_counts(log_path):
    result = harness.run_eval_b(log_path=log_path)
    assert result.total_retrieval_queries == 30
    assert result.total_leakage_tests == 4
    assert result.retrieval_hits == 30


def test_mock_run_result_is_mock(log_path):
    result = harness.run_eval_b(log_path=log_path)
    assert result.is_mock is True


def test_mock_run_query_results_count(log_path):
    result = harness.run_eval_b(log_path=log_path)
    assert len(result.query_results) == 34


# ---------------------------------------------------------------------------
# 4. Result structure
# ---------------------------------------------------------------------------


def test_result_has_all_fields(log_path):
    result = harness.run_eval_b(log_path=log_path)
    assert result.total_retrieval_queries >= 0
    assert result.retrieval_hits >= 0
    assert 0.0 <= result.hit_rate <= 1.0
    assert result.total_leakage_tests >= 0
    assert result.leakage_detected >= 0
    assert isinstance(result.passed, bool)
    assert isinstance(result.run_at, str)
    assert result.latency_ms >= 0


def test_query_result_leakage_flag(log_path):
    result = harness.run_eval_b(log_path=log_path)
    leakage_results = [r for r in result.query_results if r.is_leakage_test]
    assert len(leakage_results) == 4
    for r in leakage_results:
        assert r.expected_chunk_substring is None
        assert r.found_in_rank is None


def test_query_result_retrieval_flag(log_path):
    result = harness.run_eval_b(log_path=log_path)
    retrieval_results = [r for r in result.query_results if not r.is_leakage_test]
    assert len(retrieval_results) == 30
    for r in retrieval_results:
        assert r.expected_chunk_substring is not None
        assert r.leakage_content is None


# ---------------------------------------------------------------------------
# 5. Logging
# ---------------------------------------------------------------------------


def test_log_written(log_path):
    harness.run_eval_b(log_path=log_path)
    assert log_path.exists()
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert "hit_rate" in row
    assert "leakage_detected" in row
    assert "passed" in row


def test_log_accumulates(log_path):
    harness.run_eval_b(log_path=log_path)
    harness._cache.clear()
    idm.reset()
    harness.run_eval_b(log_path=log_path)
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2


# ---------------------------------------------------------------------------
# 6. Caching
# ---------------------------------------------------------------------------


def test_result_is_cached(log_path):
    r1 = harness.run_eval_b(log_path=log_path)
    r2 = harness.run_eval_b(log_path=log_path)
    assert r1 is r2


def test_cache_cleared_between_fixtures(log_path):
    r1 = harness.run_eval_b(log_path=log_path)
    harness._cache.clear()
    idm.reset()
    r2 = harness.run_eval_b(log_path=log_path)
    assert r1 is not r2


# ---------------------------------------------------------------------------
# 7. Document manifest completeness
# ---------------------------------------------------------------------------


def test_manifest_has_12_docs():
    assert len(harness._DOC_MANIFEST) == 12


def test_manifest_file_paths_exist():
    for doc in harness._DOC_MANIFEST:
        p = harness._PROJECT_ROOT / doc["file_path"]
        assert p.exists(), f"Missing document: {doc['file_path']}"


def test_manifest_scopes_valid():
    for doc in harness._DOC_MANIFEST:
        assert doc["scope"] in ("fund", "ble"), f"Invalid scope in manifest: {doc}"
