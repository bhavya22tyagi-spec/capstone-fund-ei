"""
Eval G harness tests — LLM-as-Judge Calibration (PRD §15.2).

Runs against golden_judge.jsonl (15 samples: 10 grounded, 5 hallucinated).
In MOCK mode, NarrativeService.judge() does a verbatim substring check —
agreement should be 100% (15/15) because golden data is internally consistent.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("MOCK", "true")

from evals.run_eval_g import EvalGResult, _PASS_THRESHOLD, _GOLDEN_PATH, run_eval_g

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def result(tmp_path_factory) -> EvalGResult:
    log = tmp_path_factory.mktemp("logs") / "eval_g_test.jsonl"
    return run_eval_g(mock=True, log_path=log)


@pytest.fixture(scope="module")
def golden_entries() -> list[dict]:
    return [json.loads(l) for l in _GOLDEN_PATH.read_text().splitlines() if l.strip()]


# ---------------------------------------------------------------------------
# Top-level result shape
# ---------------------------------------------------------------------------

def test_eval_g_status_passed(result: EvalGResult):
    assert result.status == "passed"


def test_eval_g_passed_true(result: EvalGResult):
    assert result.passed is True


def test_eval_g_agreement_rate_meets_threshold(result: EvalGResult):
    assert result.agreement_rate >= _PASS_THRESHOLD


def test_eval_g_agreement_rate_perfect_in_mock(result: EvalGResult):
    assert result.agreement_rate == 1.0, "MOCK substring check should give 100% agreement"


def test_eval_g_total_samples(result: EvalGResult):
    assert result.total_samples == 15


def test_eval_g_fail_count_zero_in_mock(result: EvalGResult):
    assert result.fail_count == 0


def test_eval_g_pass_count_15(result: EvalGResult):
    assert result.pass_count == 15


def test_eval_g_is_mock_true(result: EvalGResult):
    assert result.is_mock is True


def test_eval_g_run_at_non_empty(result: EvalGResult):
    assert result.run_at.strip()


def test_eval_g_pass_rate_1_0(result: EvalGResult):
    assert result.pass_rate == 1.0


# ---------------------------------------------------------------------------
# Golden dataset integrity
# ---------------------------------------------------------------------------

def test_golden_file_exists():
    assert _GOLDEN_PATH.exists(), f"golden_judge.jsonl missing at {_GOLDEN_PATH}"


def test_golden_file_has_15_entries(golden_entries: list[dict]):
    assert len(golden_entries) == 15


def test_golden_file_10_grounded(golden_entries: list[dict]):
    grounded = [e for e in golden_entries if e["expected_pass"] is True]
    assert len(grounded) == 10


def test_golden_file_5_hallucinated(golden_entries: list[dict]):
    hallucinated = [e for e in golden_entries if e["expected_pass"] is False]
    assert len(hallucinated) == 5


def test_golden_grounded_citation_in_narrative(golden_entries: list[dict]):
    for entry in golden_entries:
        if entry["expected_pass"]:
            assert entry["citation_substring"] in entry["narrative"], (
                f"{entry['qa_id']}: citation '{entry['citation_substring']}' "
                f"not found in narrative (would break MOCK agreement)"
            )


def test_golden_hallucinated_citation_not_in_narrative(golden_entries: list[dict]):
    for entry in golden_entries:
        if not entry["expected_pass"]:
            assert entry["citation_substring"] not in entry["narrative"], (
                f"{entry['qa_id']}: citation '{entry['citation_substring']}' "
                f"unexpectedly found in narrative (would break MOCK agreement)"
            )


def test_golden_all_required_fields(golden_entries: list[dict]):
    required = {"qa_id", "fund_id", "scope", "citation_substring", "narrative", "expected_pass"}
    for entry in golden_entries:
        missing = required - set(entry.keys())
        assert not missing, f"{entry.get('qa_id')} missing fields: {missing}"


# ---------------------------------------------------------------------------
# Log file format (must match what evals router expects)
# ---------------------------------------------------------------------------

def test_eval_g_logs_jsonl(tmp_path: Path):
    log = tmp_path / "eval_g.jsonl"
    run_eval_g(mock=True, log_path=log)
    lines = [l for l in log.read_text().splitlines() if l.strip()]
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["passed"] is True
    assert record["pass_rate"] == 1.0
    assert record["total_samples"] == 15
    assert record["status"] == "passed"
    assert "run_at" in record
    assert "is_mock" in record
