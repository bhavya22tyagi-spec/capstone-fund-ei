"""
PRD §17 — Idempotency checks for extraction, embedding, and summarisation jobs.

Every AI job calls is_already_processed() before issuing a real API call.
If the result for (scope, scope_id, stage, version) is already recorded, the
job is skipped — preventing duplicate spend on re-runs.

In-memory store for Phase 3; Phase 4 will back this with the fund_documents /
ble_documents status columns in the DB.
"""

from typing import Literal

Stage = Literal["extracted", "embedded", "summarized"]
Scope = Literal["fund", "ble"]

# (scope, scope_id, stage, version) -> True
_processed: dict[tuple[str, str, str, str], bool] = {}


def is_already_processed(
    scope: Scope,
    scope_id: str,
    stage: Stage,
    version: str,
) -> bool:
    """Return True if this (scope, scope_id, stage, version) has been completed."""
    return _processed.get((scope, scope_id, stage, version), False)


def mark_processed(
    scope: Scope,
    scope_id: str,
    stage: Stage,
    version: str,
) -> None:
    """Record that this (scope, scope_id, stage, version) is now complete."""
    _processed[(scope, scope_id, stage, version)] = True


def reset() -> None:
    """Clear all in-memory state. Call between test cases for isolation."""
    _processed.clear()
