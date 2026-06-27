from fastapi import APIRouter, HTTPException, Query
from api.deps import get_workflow
from api.data_loader import get_fund, get_ble
from api.models import SuggestionItem, AcceptDeclineRequest, BulkRequest

router = APIRouter()


def _resolve_fund_id(ws) -> str:
    """Return the real fund_id — in real DB mode scope_id is stored instead."""
    if get_fund(ws.fund_id):
        return ws.fund_id
    if ws.scope == "ble":
        ble = get_ble(ws.scope_id)
        if ble:
            return ble["fund_id"]
    return ws.fund_id


def _fund_name(fund_id: str) -> str:
    f = get_fund(fund_id)
    return f["name"] if f else fund_id


def _ble_name(scope: str, scope_id: str, cascade_info: dict | None) -> str | None:
    if cascade_info and cascade_info.get("from_ble_name"):
        return cascade_info["from_ble_name"]
    if scope == "ble":
        b = get_ble(scope_id)
        return b["name"] if b else None
    return None


def _derive_summary(trigger_type: str, trigger_detail: dict | None) -> str:
    """Generate a human-readable summary from trigger_detail when RAG is unavailable."""
    d = trigger_detail or {}
    if trigger_type == "new_sanctions_pep_hit":
        name = d.get("counterparty_name") or d.get("ubo_name") or "entity"
        sev = d.get("hit_severity", "")
        hit = d.get("hit_type", "sanctions")
        return f"{hit.capitalize()} hit on {name}" + (f" — severity: {sev}" if sev else "")
    if trigger_type == "ble_critical_cascade":
        ble = d.get("ble_name") or d.get("from_ble_name") or "BLE"
        return f"BLE escalation: {ble} reached Critical tier"
    if trigger_type == "document_expiry":
        doc = d.get("doc_type", "document")
        days = d.get("days_until_expiry")
        if days is not None and days < 0:
            return f"{doc} expired {abs(int(days))} days ago"
        return f"{doc} expiring in {int(days)} days" if days is not None else f"{doc} expiry alert"
    if trigger_type == "risk_tier_change":
        old = d.get("old_tier", "")
        new = d.get("new_tier", "")
        return f"Risk tier changed{f': {old} → {new}' if old and new else ''}"
    return trigger_type.replace("_", " ").capitalize()


def _to_item(ws) -> SuggestionItem:
    real_fund_id = _resolve_fund_id(ws)
    summary = ws.what_changed_summary or _derive_summary(ws.trigger_type, ws.trigger_detail)
    return SuggestionItem(
        suggestion_id=ws.suggestion_id,
        scope=ws.scope,
        scope_id=ws.scope_id,
        fund_id=real_fund_id,
        fund_name=_fund_name(real_fund_id),
        ble_name=_ble_name(ws.scope, ws.scope_id, ws.cascade_info),
        trigger_type=ws.trigger_type,
        what_changed_summary=summary,
        status=ws.status,
        created_at=ws.created_at,
        cascade_info=ws.cascade_info,
    )


@router.get("/suggestions", response_model=list[SuggestionItem])
def list_suggestions(status: str = Query("pending")) -> list[SuggestionItem]:
    wf = get_workflow()
    if status == "pending":
        suggestions = wf.get_pending_suggestions()
    else:
        # Return all by status filter
        all_s = list(wf._suggestions.values())
        suggestions = [s for s in all_s if s.status == status]
    return [_to_item(s) for s in suggestions]


@router.post("/suggestions/{suggestion_id}/accept")
def accept_suggestion(suggestion_id: str, body: AcceptDeclineRequest) -> dict:
    wf = get_workflow()
    try:
        entry = wf.accept_suggestion(suggestion_id, actor=body.actor, notes=body.notes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "audit_id": entry.audit_id,
        "action": entry.action,
        "actor": entry.actor,
        "performed_at": entry.performed_at,
    }


@router.post("/suggestions/{suggestion_id}/decline")
def decline_suggestion(suggestion_id: str, body: AcceptDeclineRequest) -> dict:
    wf = get_workflow()
    try:
        entry = wf.decline_suggestion(suggestion_id, actor=body.actor, notes=body.notes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "audit_id": entry.audit_id,
        "action": entry.action,
        "actor": entry.actor,
        "performed_at": entry.performed_at,
    }


@router.post("/suggestions/bulk-accept")
def bulk_accept(body: BulkRequest) -> list[dict]:
    wf = get_workflow()
    entries = wf.bulk_accept(body.ids, actor=body.actor)
    return [{"audit_id": e.audit_id, "action": e.action, "performed_at": e.performed_at} for e in entries]


@router.post("/suggestions/bulk-decline")
def bulk_decline(body: BulkRequest) -> list[dict]:
    wf = get_workflow()
    entries = wf.bulk_decline(body.ids, actor=body.actor, notes=body.notes)
    return [{"audit_id": e.audit_id, "action": e.action, "performed_at": e.performed_at} for e in entries]
