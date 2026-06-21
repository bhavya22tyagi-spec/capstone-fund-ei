"""
Eval G — LLM-as-Judge Calibration (PRD §15.2).

Loads evals/golden_judge.jsonl (15 samples: 10 grounded + 5 hallucinated).
For each sample, builds a synthetic NarrativeResult containing the sample's
narrative text, then calls NarrativeService.judge() with the expected
citation_substring.

Agreement rate = # samples where judge.passed == expected_pass / total.
PASS bar: agreement_rate >= 0.80 (PRD §15.2).

MOCK mode: judge does a verbatim substring check → 100% agreement on consistent
golden data. Non-mock requires ANTHROPIC_API_KEY and uses claude-haiku-4-5.

Note on golden data: samples in golden_judge.jsonl are synthetic (not live
human-expert rated). They correctly model the grounded / hallucinated
distinction so the eval harness and dashboard work end-to-end. Replace with
expert-rated samples for production calibration.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

MOCK: bool = os.getenv("MOCK", "true").lower() == "true"

_PROJECT_ROOT = Path(__file__).parent.parent
_GOLDEN_PATH = _PROJECT_ROOT / "evals" / "golden_judge.jsonl"
_LOG_PATH = _PROJECT_ROOT / "evals" / "eval_g_runs.jsonl"

_PASS_THRESHOLD = 0.80


@dataclass
class EvalGResult:
    status: str
    passed: Optional[bool]
    agreement_rate: float
    total_samples: int
    pass_count: int
    fail_count: int
    pass_rate: float
    is_mock: bool
    run_at: str
    reason: Optional[str] = None
    latency_ms: int = 0
    cost_usd: float = 0.0


def _load_golden(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"golden_judge.jsonl not found at {path}")
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            entries.append(json.loads(line))
    if not entries:
        raise ValueError("golden_judge.jsonl is empty")
    return entries


def run_eval_g(
    mock: "bool | None" = None,
    log_path: "Path | str | None" = None,
    golden_path: "Path | str | None" = None,
) -> EvalGResult:
    """
    Run Eval G: LLM-as-Judge calibration against golden_judge.jsonl.

    Args:
        mock:        Override MOCK env-var.
        log_path:    Override default eval_g_runs.jsonl path.
        golden_path: Override default golden_judge.jsonl path.

    Returns:
        EvalGResult with agreement_rate, passed, and per-sample counts.
    """
    is_mock = MOCK if mock is None else mock
    run_at = datetime.now(timezone.utc).isoformat()
    t_start = time.perf_counter()

    gp = Path(golden_path) if golden_path else _GOLDEN_PATH
    golden = _load_golden(gp)

    from services.narrative.service import NarrativeResult, NarrativeService

    svc = NarrativeService()
    agree = 0
    disagree = 0

    for sample in golden:
        narrative_result = NarrativeResult(
            scope=sample["scope"],
            scope_id=sample["fund_id"],
            narrative=sample["narrative"],
            citations=[],
            model="synthetic-golden",
            prompt_version="golden-v1",
            is_mock=is_mock,
            run_at=run_at,
        )
        judge = svc.judge(
            narrative_result=narrative_result,
            citation_substring=sample["citation_substring"],
            qa_id=sample["qa_id"],
            fund_id=sample["fund_id"],
            synthetic_static=False,
        )
        if judge.passed == sample["expected_pass"]:
            agree += 1
        else:
            disagree += 1

    total = agree + disagree
    agreement_rate = agree / total if total > 0 else 0.0
    passed = agreement_rate >= _PASS_THRESHOLD
    latency_ms = int((time.perf_counter() - t_start) * 1000)

    result = EvalGResult(
        status="passed" if passed else "failed",
        passed=passed,
        agreement_rate=round(agreement_rate, 4),
        total_samples=total,
        pass_count=agree,
        fail_count=disagree,
        pass_rate=round(agreement_rate, 4),
        is_mock=is_mock,
        run_at=run_at,
        latency_ms=latency_ms,
        cost_usd=0.0 if is_mock else 0.0,
    )

    lp = Path(log_path) if log_path else _LOG_PATH
    lp.parent.mkdir(parents=True, exist_ok=True)
    with open(lp, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(asdict(result)) + "\n")

    return result


if __name__ == "__main__":
    result = run_eval_g()
    print("\nEval G — LLM-as-Judge Calibration")
    print(f"Status:          {result.status.upper()}")
    print(f"Passed:          {result.passed}")
    print(f"Agreement rate:  {result.agreement_rate:.1%}  (threshold: {_PASS_THRESHOLD:.0%})")
    print(f"Samples:         {result.pass_count} agree / {result.fail_count} disagree / {result.total_samples} total")
    print(f"Mock mode:       {result.is_mock}")
    print(f"Latency:         {result.latency_ms}ms")
