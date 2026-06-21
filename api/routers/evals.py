"""
Eval dashboard router.

Reads the last line of each eval_*_runs.jsonl log file for current status.
Returns 7 rows (A–G); G is always PENDING (eval not yet implemented).
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter

from api.models import EvalRunSummary

router = APIRouter()

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_EVALS_DIR = _PROJECT_ROOT / "evals"

_EVAL_META = [
    ("A", "eval_a_runs.jsonl", "Extraction Accuracy",      "≥95% field match"),
    ("B", "eval_b_runs.jsonl", "Retrieval Quality",        "Precision@3, zero leakage"),
    ("C", "eval_c_runs.jsonl", "RAG Groundedness",         "≥80% judge pass, 0 hallucinations"),
    ("D", "eval_d_runs.jsonl", "Text-to-SQL Correctness",  "100% result match"),
    ("E", "eval_e_runs.jsonl", "Trigger Detection",        "100% no flakiness"),
    ("F", "eval_f_runs.jsonl", "MCP Tool Selection",       "100% exact match"),
    ("G", "eval_g_runs.jsonl", "Judge Calibration",        "Human/judge agreement ≥80%"),
]


def _read_last_run(log_file: str | None) -> dict | None:
    if log_file is None:
        return None
    p = _EVALS_DIR / log_file
    if not p.exists():
        return None
    lines = [ln.strip() for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines:
        return None
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError:
        return None


@router.get("/evals", response_model=list[EvalRunSummary])
def list_evals() -> list[EvalRunSummary]:
    result = []
    for category, log_file, label, _ in _EVAL_META:
        run = _read_last_run(log_file)
        if run is None:
            result.append(EvalRunSummary(
                eval_category=category,
                label=label,
                last_run_at=None,
                pass_count=0,
                fail_count=0,
                pass_rate=0.0,
                latency_ms=0,
                cost_usd=0.0,
                status="pending",
                is_mock=True,
            ))
            continue

        passed = run.get("passed", False)
        pass_rate = run.get("pass_rate") or run.get("judge_pass_rate") or run.get("tool_match_rate") or 0.0
        pass_count = run.get("pass_count") or run.get("scenarios_passed") or run.get("qa_entries_evaluated") or 0
        fail_count = run.get("fail_count", 0)
        result.append(EvalRunSummary(
            eval_category=category,
            label=label,
            last_run_at=run.get("run_at"),
            pass_count=int(pass_count),
            fail_count=int(fail_count),
            pass_rate=float(pass_rate),
            latency_ms=int(run.get("latency_ms", 0)),
            cost_usd=float(run.get("cost_usd", 0.0)),
            status="pass" if passed else "fail",
            is_mock=bool(run.get("is_mock", True)),
        ))
    return result
