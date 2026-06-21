"""
PRD §17 — Central LLM and embedding call router.

ALL LLM and embedding calls in this project must go through call_llm() and
call_embedding() respectively. No other module may call an Anthropic API or
sentence-transformer model directly.

Enforcement order on every call:
  1. Fail-fast input validation  (ValueError — never retried)
  2. Synthetic-static Fund guard (StaticFundAIError — never retried)
  3. Per-run budget cap check    (BudgetExceededError — never retried)
  4. MOCK branch → canned response + zero-cost log entry (default)
  5. Real call with bounded retry (max 2 retries, exponential backoff)
  6. Cost log + budget accumulation on success

Real Anthropic API and bge-base-en-v1.5 integration are wired in Phase 4.
Until then MOCK=true (the default) is the only operational path.
"""

import os
import time
from typing import Any

from services.budget import BudgetCap, BudgetExceededError
from services.cost_logger import log_llm_call
from services.guards import StaticFundAIError, assert_fund_allows_ai

# MOCK defaults to true — real API calls require an explicit opt-in.
MOCK: bool = os.getenv("MOCK", "true").lower() == "true"

MAX_RETRIES: int = 2
_BACKOFF_BASE_S: float = 0.5

# Dimension of BAAI/bge-base-en-v1.5 (locked in CLAUDE.md).
EMBEDDING_DIM: int = 768

# Exceptions that represent deterministic failures — retrying will not help.
_NO_RETRY = (StaticFundAIError, ValueError, BudgetExceededError, NotImplementedError)

# Canned mock payloads.
_MOCK_LLM_CONTENT = "[MOCK LLM RESPONSE — set MOCK=false for real API calls]"
_MOCK_EMBEDDING: list[float] = [0.0] * EMBEDDING_DIM

# Rough per-1k-token pricing (input+output blended) for cost estimation.
_COST_PER_1K: dict[str, float] = {
    "claude-haiku-4-5-20251001": 0.00125,
    "claude-sonnet-4-6":         0.00900,
    "claude-opus-4-8":           0.04500,
    "BAAI/bge-base-en-v1.5":     0.00000,  # self-hosted, zero per-call cost
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def call_llm(
    prompt: str,
    model: str,
    prompt_version: str,
    fund_id: str,
    synthetic_static: bool,
    scope: str,
    scope_id: str,
    budget: BudgetCap,
    estimated_cost_usd: float = 0.001,
) -> dict[str, Any]:
    """
    Call an LLM. Returns a dict with at minimum:
      {"content": str, "model": str, "usage": {...}, "is_mock": bool}

    Raises:
      ValueError          — invalid inputs (empty prompt, bad scope)
      StaticFundAIError   — fund is synthetic_static
      BudgetExceededError — would breach the per-run cap
      RuntimeError        — transient failure persisted beyond MAX_RETRIES
    """
    _validate_llm_inputs(prompt, scope)
    assert_fund_allows_ai(fund_id, synthetic_static)
    budget.check(estimated_cost_usd)

    if MOCK:
        log_llm_call(
            model=model, prompt_version=prompt_version,
            scope=scope, scope_id=scope_id,
            tokens=0, cost_usd=0.0, latency_ms=0, is_mock=True,
        )
        budget.record(0.0)
        return {
            "content": _MOCK_LLM_CONTENT,
            "model": model,
            "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            "is_mock": True,
        }

    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            t0 = time.monotonic()
            raw = _real_llm_call(prompt, model)
            latency_ms = int((time.monotonic() - t0) * 1000)
            tokens = raw.get("usage", {}).get("total_tokens", 0)
            cost_usd = _estimate_cost(model, tokens)
            log_llm_call(
                model=model, prompt_version=prompt_version,
                scope=scope, scope_id=scope_id,
                tokens=tokens, cost_usd=cost_usd, latency_ms=latency_ms, is_mock=False,
            )
            budget.record(cost_usd)
            return raw
        except _NO_RETRY:
            raise
        except Exception as exc:
            last_exc = exc
            if attempt < MAX_RETRIES:
                time.sleep(_BACKOFF_BASE_S * (2 ** attempt))

    raise RuntimeError(
        f"LLM call failed after {MAX_RETRIES + 1} attempt(s): {last_exc}"
    ) from last_exc


def call_embedding(
    text: str,
    fund_id: str,
    synthetic_static: bool,
    scope: str,
    scope_id: str,
    budget: BudgetCap,
    model: str = "BAAI/bge-base-en-v1.5",
    estimated_cost_usd: float = 0.0,
) -> list[float]:
    """
    Compute a text embedding. Returns a list of EMBEDDING_DIM floats.
    Self-hosted bge-base-en-v1.5 has zero per-call cost (CLAUDE.md).

    Raises:
      ValueError          — empty text or bad scope
      StaticFundAIError   — fund is synthetic_static
      BudgetExceededError — would breach cap (unlikely at $0, but checked)
      RuntimeError        — transient model failure beyond MAX_RETRIES
    """
    if not text or not text.strip():
        raise ValueError("text must not be empty")
    if scope not in ("fund", "ble"):
        raise ValueError(f"scope must be 'fund' or 'ble', got {scope!r}")
    assert_fund_allows_ai(fund_id, synthetic_static)
    budget.check(estimated_cost_usd)

    if MOCK:
        log_llm_call(
            model=model, prompt_version="embedding-v1",
            scope=scope, scope_id=scope_id,
            tokens=0, cost_usd=0.0, latency_ms=0, is_mock=True,
        )
        budget.record(0.0)
        return list(_MOCK_EMBEDDING)

    last_exc = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            t0 = time.monotonic()
            vec = _real_embedding_call(text, model)
            latency_ms = int((time.monotonic() - t0) * 1000)
            log_llm_call(
                model=model, prompt_version="embedding-v1",
                scope=scope, scope_id=scope_id,
                tokens=0, cost_usd=0.0, latency_ms=latency_ms, is_mock=False,
            )
            budget.record(0.0)
            return vec
        except _NO_RETRY:
            raise
        except Exception as exc:
            last_exc = exc
            if attempt < MAX_RETRIES:
                time.sleep(_BACKOFF_BASE_S * (2 ** attempt))

    raise RuntimeError(
        f"Embedding call failed after {MAX_RETRIES + 1} attempt(s): {last_exc}"
    ) from last_exc


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _validate_llm_inputs(prompt: str, scope: str) -> None:
    if not prompt or not prompt.strip():
        raise ValueError("prompt must not be empty")
    if scope not in ("fund", "ble"):
        raise ValueError(f"scope must be 'fund' or 'ble', got {scope!r}")


def _estimate_cost(model: str, total_tokens: int) -> float:
    rate = _COST_PER_1K.get(model, 0.009)
    return round((total_tokens / 1000) * rate, 8)


def _real_llm_call(prompt: str, model: str) -> dict[str, Any]:
    try:
        import anthropic as _anthropic
    except ImportError:
        raise RuntimeError(
            "anthropic package not installed. Run: uv pip install anthropic"
        ) from None
    client = _anthropic.Anthropic()
    message = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    return {
        "content": message.content[0].text,
        "model": message.model,
        "usage": {
            "input_tokens": message.usage.input_tokens,
            "output_tokens": message.usage.output_tokens,
            "total_tokens": message.usage.input_tokens + message.usage.output_tokens,
        },
        "is_mock": False,
    }


def _real_embedding_call(text: str, model: str) -> list[float]:
    # Lazy import — avoids circular dependency and allows MOCK=true without
    # requiring sentence-transformers to be installed.
    from services.embedding_service import encode_text  # noqa: PLC0415
    return encode_text(text, model)
