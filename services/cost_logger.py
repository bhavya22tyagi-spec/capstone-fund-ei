"""
PRD §17 — Per-call cost logging.

Every LLM and embedding call (real or mock) is appended to LOG_FILE as a
JSONL record. Visible same-day; no DB dependency in Phase 3.

Phase 4 will additionally persist records to the llm_call_log DB table.
"""

import json
import os
from datetime import datetime, timezone

# Resolved from project root: <project>/logs/ai_calls.jsonl
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_FILE: str = os.path.join(_PROJECT_ROOT, "logs", "ai_calls.jsonl")


def log_llm_call(
    model: str,
    prompt_version: str,
    scope: str,
    scope_id: str,
    tokens: int,
    cost_usd: float,
    latency_ms: int,
    is_mock: bool,
) -> None:
    """Append one JSONL record to LOG_FILE. Creates the logs/ dir if absent."""
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "prompt_version": prompt_version,
        "scope": scope,
        "scope_id": scope_id,
        "tokens": tokens,
        "cost_usd": round(cost_usd, 8),
        "latency_ms": latency_ms,
        "is_mock": is_mock,
    }
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
