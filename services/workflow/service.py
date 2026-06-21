"""
PRD §11 — Suggested Reviews Workflow: human Accept/Decline + audit logging.

Receives SuggestionCards from AgentOrchestrationService, manages the queue,
and logs every analyst decision (accepted, declined, expired) for audit.

PRD §18 invariants:
  - No AI output auto-publishes: all cards start as "pending" and require
    an explicit human Accept or Decline before any workflow action fires.
  - Every decision is logged (accept, decline, expire) with actor + timestamp.
  - Scope is always explicit on suggestions and audit entries — never ambiguous.
  - Decline patterns are preserved for future threshold tuning (PRD §11 step 6).

MOCK=true (default):
  - All state held in instance-level dicts/lists (no DB required).
  - WorkflowSuggestion and AuditLogEntry returned immediately.

MOCK=false:
  - create_suggestion → INSERT into workflow_suggestions (psycopg2)
  - accept/decline → UPDATE workflow_suggestions + INSERT INTO review_audit_history
  Requires DATABASE_URL env var.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.agent.service import SuggestionCard

MOCK: bool = os.getenv("MOCK", "true").lower() == "true"

_VALID_STATUSES = frozenset({"pending", "accepted", "declined", "expired"})


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class WorkflowSuggestion:
    suggestion_id: str
    scope: str
    scope_id: str
    fund_id: str
    trigger_type: str
    trigger_detail: dict
    suggested_workflow_template: str
    status: str                     # "pending" | "accepted" | "declined" | "expired"
    what_changed_summary: str
    screening_summary: dict | None
    created_at: str
    resolved_at: str | None
    resolved_by: str | None
    cascade_info: dict | None       # {"from_ble_id": ..., "from_ble_name": ...} or None


@dataclass
class AuditLogEntry:
    audit_id: str
    scope: str
    scope_id: str
    action: str                     # "accept_suggestion" | "decline_suggestion" | "expire_suggestion"
    actor: str
    notes: str | None
    performed_at: str


# ---------------------------------------------------------------------------
# Public service
# ---------------------------------------------------------------------------

class WorkflowService:
    """
    Manages the compliance review suggestion queue and human workflow decisions.

    All state is instance-scoped in MOCK mode — create a fresh WorkflowService
    per test to avoid cross-test contamination.

    PRD §18: no suggestion auto-publishes; every action requires an actor.
    """

    def __init__(self) -> None:
        self._suggestions: dict[str, WorkflowSuggestion] = {}
        self._audit_log: list[AuditLogEntry] = []

    # ------------------------------------------------------------------
    # Suggestion lifecycle
    # ------------------------------------------------------------------

    def create_suggestion(self, card: "SuggestionCard") -> WorkflowSuggestion:
        """
        Enqueue a SuggestionCard as a pending WorkflowSuggestion.

        Does NOT auto-publish (PRD §18). Status starts as "pending".
        """
        cascade_info = None
        if card.cascaded_from_ble_id is not None:
            cascade_info = {
                "from_ble_id": card.cascaded_from_ble_id,
                "from_ble_name": card.cascaded_from_ble_name,
            }

        suggestion = WorkflowSuggestion(
            suggestion_id=card.card_id,
            scope=card.scope,
            scope_id=card.scope_id,
            fund_id=card.fund_id,
            trigger_type=card.trigger_type,
            trigger_detail=card.trigger_detail,
            suggested_workflow_template=card.suggested_workflow_template,
            status="pending",
            what_changed_summary=card.what_changed_summary,
            screening_summary=card.screening_summary,
            created_at=card.created_at,
            resolved_at=None,
            resolved_by=None,
            cascade_info=cascade_info,
        )

        if MOCK:
            self._suggestions[suggestion.suggestion_id] = suggestion
        else:
            self._db_insert_suggestion(suggestion)

        return suggestion

    def accept_suggestion(
        self,
        suggestion_id: str,
        actor: str,
        notes: str | None = None,
    ) -> AuditLogEntry:
        """
        Accept a pending suggestion.

        Raises:
            ValueError: suggestion not found or not in "pending" status.
        """
        return self._resolve(suggestion_id, "accepted", "accept_suggestion", actor, notes)

    def decline_suggestion(
        self,
        suggestion_id: str,
        actor: str,
        notes: str | None = None,
    ) -> AuditLogEntry:
        """
        Decline a pending suggestion.

        Decline notes are preserved for future threshold tuning (PRD §11 step 6).

        Raises:
            ValueError: suggestion not found or not in "pending" status.
        """
        return self._resolve(suggestion_id, "declined", "decline_suggestion", actor, notes)

    def bulk_accept(
        self,
        suggestion_ids: list[str],
        actor: str,
    ) -> list[AuditLogEntry]:
        """Accept multiple pending suggestions. Stops on first error."""
        return [self.accept_suggestion(sid, actor) for sid in suggestion_ids]

    def bulk_decline(
        self,
        suggestion_ids: list[str],
        actor: str,
        notes: str | None = None,
    ) -> list[AuditLogEntry]:
        """Decline multiple pending suggestions. Stops on first error."""
        return [self.decline_suggestion(sid, actor, notes) for sid in suggestion_ids]

    def expire_suggestion(self, suggestion_id: str) -> WorkflowSuggestion:
        """
        Mark a suggestion as expired (SLA lapsed before analyst acted).

        Unlike accept/decline, expiry is system-initiated — no actor required.
        Logs an audit entry with actor="system".
        """
        suggestion = self._get_pending(suggestion_id)
        now = datetime.now(timezone.utc).isoformat()
        suggestion.status = "expired"
        suggestion.resolved_at = now
        suggestion.resolved_by = "system"

        entry = AuditLogEntry(
            audit_id=str(uuid.uuid4()),
            scope=suggestion.scope,
            scope_id=suggestion.scope_id,
            action="expire_suggestion",
            actor="system",
            notes=None,
            performed_at=now,
        )
        if MOCK:
            self._audit_log.append(entry)
        else:
            self._db_insert_audit(entry)

        return suggestion

    def get_pending_suggestions(self) -> list[WorkflowSuggestion]:
        """Return all suggestions with status "pending", oldest first."""
        if MOCK:
            return [s for s in self._suggestions.values() if s.status == "pending"]
        return self._db_get_pending()

    def get_audit_log(self) -> list[AuditLogEntry]:
        """Return all logged audit entries (MOCK introspection; real mode queries DB)."""
        if MOCK:
            return list(self._audit_log)
        return self._db_get_audit_log()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve(
        self,
        suggestion_id: str,
        new_status: str,
        action: str,
        actor: str,
        notes: str | None,
    ) -> AuditLogEntry:
        suggestion = self._get_pending(suggestion_id)
        now = datetime.now(timezone.utc).isoformat()
        suggestion.status = new_status
        suggestion.resolved_at = now
        suggestion.resolved_by = actor

        entry = AuditLogEntry(
            audit_id=str(uuid.uuid4()),
            scope=suggestion.scope,
            scope_id=suggestion.scope_id,
            action=action,
            actor=actor,
            notes=notes,
            performed_at=now,
        )
        if MOCK:
            self._audit_log.append(entry)
        else:
            self._db_update_suggestion(suggestion)
            self._db_insert_audit(entry)

        return entry

    def _get_pending(self, suggestion_id: str) -> WorkflowSuggestion:
        if MOCK:
            suggestion = self._suggestions.get(suggestion_id)
        else:
            suggestion = self._db_get_suggestion(suggestion_id)

        if suggestion is None:
            raise ValueError(f"Suggestion {suggestion_id!r} not found")
        if suggestion.status != "pending":
            raise ValueError(
                f"Suggestion {suggestion_id!r} is {suggestion.status!r}, "
                "not 'pending' — cannot be resolved again"
            )
        return suggestion

    # ------------------------------------------------------------------
    # Real-mode DB stubs (psycopg2, requires DATABASE_URL)
    # ------------------------------------------------------------------

    def _db_insert_suggestion(self, suggestion: WorkflowSuggestion) -> None:
        import json
        import psycopg2
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO workflow_suggestions
                  (suggestion_id, scope, scope_id, trigger_type, trigger_detail,
                   suggested_workflow_template, status, ai_narrative, created_at)
                VALUES (%s, %s, %s::uuid, %s, %s, %s, %s, %s, %s)
                """,
                (
                    suggestion.suggestion_id,
                    suggestion.scope,
                    suggestion.scope_id,
                    suggestion.trigger_type,
                    json.dumps(suggestion.trigger_detail),
                    suggestion.suggested_workflow_template,
                    suggestion.status,
                    suggestion.what_changed_summary or None,
                    suggestion.created_at,
                ),
            )
        conn.close()

    def _db_update_suggestion(self, suggestion: WorkflowSuggestion) -> None:
        import psycopg2
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE workflow_suggestions
                SET status = %s, resolved_at = %s, resolved_by = %s
                WHERE suggestion_id = %s
                """,
                (suggestion.status, suggestion.resolved_at,
                 suggestion.resolved_by, suggestion.suggestion_id),
            )
        conn.close()

    def _db_insert_audit(self, entry: AuditLogEntry) -> None:
        import psycopg2
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO review_audit_history
                  (audit_id, scope, scope_id, action, actor, notes, performed_at)
                VALUES (%s, %s, %s::uuid, %s, %s, %s, %s)
                """,
                (
                    entry.audit_id, entry.scope, entry.scope_id,
                    entry.action, entry.actor, entry.notes, entry.performed_at,
                ),
            )
        conn.close()

    def _db_get_suggestion(self, suggestion_id: str) -> WorkflowSuggestion | None:
        import json
        import psycopg2
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        with conn, conn.cursor() as cur:
            cur.execute(
                "SELECT suggestion_id, scope, scope_id::text, trigger_type, "
                "trigger_detail, suggested_workflow_template, status, "
                "ai_narrative, created_at, resolved_at, resolved_by "
                "FROM workflow_suggestions WHERE suggestion_id = %s",
                (suggestion_id,),
            )
            row = cur.fetchone()
        conn.close()
        if row is None:
            return None
        return WorkflowSuggestion(
            suggestion_id=str(row[0]),
            scope=row[1], scope_id=str(row[2]),
            fund_id=str(row[2]),  # approximate — real schema doesn't store fund_id
            trigger_type=row[3],
            trigger_detail=json.loads(row[4]) if row[4] else {},
            suggested_workflow_template=row[5] or "",
            status=row[6],
            what_changed_summary=row[7] or "",
            screening_summary=None,
            created_at=str(row[8]),
            resolved_at=str(row[9]) if row[9] else None,
            resolved_by=row[10],
            cascade_info=None,
        )

    def _db_get_pending(self) -> list[WorkflowSuggestion]:
        import json
        import psycopg2
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        with conn, conn.cursor() as cur:
            cur.execute(
                "SELECT suggestion_id, scope, scope_id::text, trigger_type, "
                "trigger_detail, suggested_workflow_template, status, "
                "ai_narrative, created_at, resolved_at, resolved_by "
                "FROM workflow_suggestions WHERE status = 'pending' ORDER BY created_at"
            )
            rows = cur.fetchall()
        conn.close()
        return [
            WorkflowSuggestion(
                suggestion_id=str(r[0]), scope=r[1], scope_id=str(r[2]),
                fund_id=str(r[2]), trigger_type=r[3],
                trigger_detail=json.loads(r[4]) if r[4] else {},
                suggested_workflow_template=r[5] or "",
                status=r[6], what_changed_summary=r[7] or "",
                screening_summary=None, created_at=str(r[8]),
                resolved_at=str(r[9]) if r[9] else None,
                resolved_by=r[10], cascade_info=None,
            )
            for r in rows
        ]

    def _db_get_audit_log(self) -> list[AuditLogEntry]:
        import psycopg2
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        with conn, conn.cursor() as cur:
            cur.execute(
                "SELECT audit_id, scope, scope_id::text, action, actor, notes, performed_at "
                "FROM review_audit_history ORDER BY performed_at"
            )
            rows = cur.fetchall()
        conn.close()
        return [
            AuditLogEntry(
                audit_id=str(r[0]), scope=r[1], scope_id=str(r[2]),
                action=r[3], actor=r[4], notes=r[5], performed_at=str(r[6]),
            )
            for r in rows
        ]
