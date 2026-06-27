"""
Singleton service instances for dependency injection.
"""
from __future__ import annotations

import os

MOCK: bool = os.getenv("MOCK", "true").lower() == "true"

# ---------------------------------------------------------------------------
# WorkflowService — single instance shared across all requests
# ---------------------------------------------------------------------------
from services.workflow.service import WorkflowService
from services.text_to_sql.service import TextToSQLService
from services.rag.service import RAGService
from services.narrative.service import NarrativeService

_workflow: WorkflowService | None = None
_text_to_sql: TextToSQLService | None = None
_rag: RAGService | None = None
_narrative: NarrativeService | None = None

# Active ruleset config (in-memory, mutable via POST /api/admin/ruleset)
_ruleset_version = [1]   # mutable via list to allow mutation from module

ACTIVE_RULESET: dict = {
    "version": "v1",
    "scope_level": "both",
    "weight_country": 20.0,
    "weight_screening": 30.0,
    "weight_pep": 20.0,
    "weight_ubo": 20.0,
    "weight_documents": 10.0,
    "hard_stop_enabled": True,
    "escalation_enabled": True,
}


def get_workflow() -> WorkflowService:
    global _workflow
    if _workflow is None:
        _workflow = WorkflowService()
    return _workflow


def get_text_to_sql() -> TextToSQLService:
    global _text_to_sql
    if _text_to_sql is None:
        _text_to_sql = TextToSQLService()
    return _text_to_sql


def get_rag() -> RAGService:
    global _rag
    if _rag is None:
        _rag = RAGService()
    return _rag


def get_narrative() -> NarrativeService:
    global _narrative
    if _narrative is None:
        _narrative = NarrativeService()
    return _narrative


# ---------------------------------------------------------------------------
# Decision store — HITL audit trail (PRD §18)
# Writes to review_audit_history in DB if DATABASE_URL is set; falls back
# to in-memory list so the app works offline too.
# ---------------------------------------------------------------------------

_decision_log: list[dict] = []

_DB_URL: str | None = os.getenv("DATABASE_URL")


def get_decision_log() -> list[dict]:
    return _decision_log


def append_decision(record: dict) -> None:
    _decision_log.append(record)
    if _DB_URL:
        try:
            import psycopg2  # noqa: PLC0415
            with psycopg2.connect(_DB_URL) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO review_audit_history
                            (scope, scope_id, action, actor, notes, performed_at)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            record.get("scope"),
                            record.get("scope_id"),
                            record.get("decision"),
                            record.get("actor"),
                            record.get("notes"),
                            record.get("decided_at"),
                        ),
                    )
                conn.commit()
        except Exception:
            pass  # DB write failure never breaks the API response


# ---------------------------------------------------------------------------
# Screening cache — live OpenSanctions results per BLE (PRD §8.3, §17)
# In-memory: survives requests within a Railway instance, cleared on restart.
# ---------------------------------------------------------------------------

_screening_cache: dict[str, dict] = {}


def set_screening(ble_id: str, payload: dict) -> None:
    _screening_cache[ble_id] = payload


def get_screening(ble_id: str) -> dict | None:
    return _screening_cache.get(ble_id)


def get_screening_result(ble_id: str) -> dict | None:
    """Return the first result entry from the cached payload, or None if not screened."""
    payload = _screening_cache.get(ble_id)
    if not payload:
        return None
    results = payload.get("results", [])
    return results[0] if results else None
