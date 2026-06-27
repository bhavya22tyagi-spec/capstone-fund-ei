import json
import time
from datetime import date
from pathlib import Path

from fastapi import APIRouter, HTTPException
from api.deps import ACTIVE_RULESET, _ruleset_version, get_workflow, set_screening, get_screening
from api.models import RulesetConfig
import api.data_loader as data_loader
from mcp_servers.opensanctions import screen_entity
from services.trigger_engine.models import ReviewTrigger, TriggerType, TriggerScope
from services.agent.service import AgentOrchestrationService

router = APIRouter()

_SEED_PATH = Path(__file__).parent.parent.parent / "evals" / "seed_truth.json"
_EXPIRY_WINDOW_DAYS = 30


@router.get("/admin/ruleset", response_model=RulesetConfig)
def get_ruleset() -> RulesetConfig:
    return RulesetConfig(**ACTIVE_RULESET)


@router.post("/admin/ruleset", response_model=RulesetConfig)
def publish_ruleset(body: RulesetConfig) -> RulesetConfig:
    total = (
        body.weight_country + body.weight_screening + body.weight_pep
        + body.weight_ubo + body.weight_documents
    )
    if abs(total - 100.0) > 0.01:
        raise HTTPException(
            status_code=422,
            detail=f"Weights must sum to 100%; got {total:.1f}%",
        )

    _ruleset_version[0] += 1
    new_version = f"v{_ruleset_version[0]}"

    ACTIVE_RULESET.update({
        "version": new_version,
        "scope_level": body.scope_level,
        "weight_country": body.weight_country,
        "weight_screening": body.weight_screening,
        "weight_pep": body.weight_pep,
        "weight_ubo": body.weight_ubo,
        "weight_documents": body.weight_documents,
        "hard_stop_enabled": body.hard_stop_enabled,
        "escalation_enabled": body.escalation_enabled,
    })

    return RulesetConfig(**ACTIVE_RULESET)


@router.get("/admin/screen-ble/{ble_id}")
def get_last_screening(ble_id: str) -> dict:
    """Return the last cached screening result for a BLE, or 404 if never screened."""
    result = get_screening(ble_id)
    if result is None:
        raise HTTPException(status_code=404, detail="No screening result cached for this BLE")
    return result


@router.post("/admin/screen-ble/{ble_id}")
def screen_single_ble(ble_id: str) -> dict:
    """
    Screen a single BLE counterparty by ble_id. Uses 1 API call only.
    Returns the screening result and fires a trigger card if hit.
    """
    ble = data_loader.get_ble(ble_id)
    if not ble:
        raise HTTPException(status_code=404, detail=f"BLE {ble_id} not found")

    agent = AgentOrchestrationService()
    workflow = get_workflow()

    institution = ble["institution"]
    result = screen_entity(
        name=institution,
        scope="counterparty",
        scope_id=ble_id,
        fund_id=ble["fund_id"],
        synthetic_static=False,
    )

    cards_created: list[str] = []
    if result["result_status"] == "hit":
        trigger = ReviewTrigger(
            trigger_type=TriggerType.NEW_SANCTIONS_PEP_HIT,
            scope=TriggerScope.BLE,
            fund_id=ble["fund_id"],
            ble_id=ble_id,
            detail={
                "counterparty_name": institution,
                "ble_name": ble["name"],
                "ble_risk_tier": ble["tier"],
                "hit_type": result.get("hit_type"),
                "hit_severity": result.get("hit_severity"),
            },
        )
        cards = agent.process_trigger(trigger, fund_id=ble["fund_id"], synthetic_static=False)
        for card in cards:
            workflow.create_suggestion(card)
            cards_created.append(card.card_id)

    response = {
        "screened_entities": 1,
        "triggers_fired": 1 if result["result_status"] == "hit" else 0,
        "cards_created": len(cards_created),
        "results": [{
            "name": institution,
            "scope": "counterparty",
            "result": result["result_status"],
            "severity": result.get("hit_severity"),
            "hit_type": result.get("hit_type"),
            "datasets": result.get("datasets", []),
            "screened_at": result.get("screened_at"),
            "match_name": result.get("match_name"),
        }],
    }
    set_screening(ble_id, response)
    return response


@router.post("/admin/run-screening")
def run_screening() -> dict:
    """
    Screen all live-fund entities and fire triggers for any hits or document expiries.
    Counterparty reuse: each institution is screened once regardless of how many BLEs
    reference it (PRD §17). Returns a summary; cards appear in Suggested Reviews queue.
    """
    with open(_SEED_PATH, encoding="utf-8") as fh:
        seed = json.load(fh)

    agent = AgentOrchestrationService()
    workflow = get_workflow()

    screened: list[dict] = []
    cards_created: list[str] = []
    triggers_fired = 0

    # ------------------------------------------------------------------
    # 1. BLE counterparty screening — screen each institution ONCE
    # ------------------------------------------------------------------
    seen_institutions: set[str] = set()
    for ble_id, ble in data_loader.LIVE_BLES.items():
        institution = ble["institution"]
        if institution in seen_institutions:
            continue
        seen_institutions.add(institution)

        result = screen_entity(
            name=institution,
            scope="counterparty",
            scope_id=ble_id,
            fund_id=ble["fund_id"],
            synthetic_static=False,
        )
        screened.append({
            "name": institution,
            "scope": "counterparty",
            "result": result["result_status"],
            "severity": result.get("hit_severity"),
        })
        time.sleep(0.5)

        if result["result_status"] == "hit":
            trigger = ReviewTrigger(
                trigger_type=TriggerType.NEW_SANCTIONS_PEP_HIT,
                scope=TriggerScope.BLE,
                fund_id=ble["fund_id"],
                ble_id=ble_id,
                detail={
                    "counterparty_name": institution,
                    "ble_name": ble["name"],
                    "ble_risk_tier": ble["tier"],
                    "hit_type": result.get("hit_type"),
                    "hit_severity": result.get("hit_severity"),
                },
            )
            triggers_fired += 1
            cards = agent.process_trigger(trigger, fund_id=ble["fund_id"], synthetic_static=False)
            for card in cards:
                workflow.create_suggestion(card)
                cards_created.append(card.card_id)

    # ------------------------------------------------------------------
    # 2. Fund UBO screening
    # ------------------------------------------------------------------
    for fund_raw in seed.get("live_funds", []):
        fund_id = fund_raw["fund_id"]
        fund_name = fund_raw["name"]
        seen_ubo_names: set[str] = set()

        for ubo in fund_raw.get("ubos", []):
            ubo_name = ubo.get("name", "")
            if not ubo_name or ubo_name.startswith("[") or ubo_name in seen_ubo_names:
                continue
            seen_ubo_names.add(ubo_name)

            result = screen_entity(
                name=ubo_name,
                scope="fund",
                scope_id=fund_id,
                fund_id=fund_id,
                synthetic_static=False,
            )
            screened.append({
                "name": ubo_name,
                "scope": "fund_ubo",
                "result": result["result_status"],
                "severity": result.get("hit_severity"),
            })
            time.sleep(0.5)

            if result["result_status"] == "hit":
                trigger = ReviewTrigger(
                    trigger_type=TriggerType.NEW_SANCTIONS_PEP_HIT,
                    scope=TriggerScope.FUND,
                    fund_id=fund_id,
                    ble_id=None,
                    detail={
                        "ubo_name": ubo_name,
                        "entity_name": ubo_name,
                        "fund_name": fund_name,
                        "hit_type": result.get("hit_type"),
                        "hit_severity": result.get("hit_severity"),
                    },
                )
                triggers_fired += 1
                cards = agent.process_trigger(trigger, fund_id=fund_id, synthetic_static=False)
                for card in cards:
                    workflow.create_suggestion(card)
                    cards_created.append(card.card_id)

    # ------------------------------------------------------------------
    # 3. Document expiry — fund-level documents within 30-day window
    # ------------------------------------------------------------------
    today = date.today()
    for fund_id, fund in data_loader.LIVE_FUNDS.items():
        for doc in fund.get("documents", []):
            expiry_str = doc.get("expiry_date")
            if not expiry_str:
                continue
            try:
                expiry = date.fromisoformat(str(expiry_str))
            except (ValueError, TypeError):
                continue
            days_until = (expiry - today).days
            if days_until > _EXPIRY_WINDOW_DAYS:
                continue

            trigger = ReviewTrigger(
                trigger_type=TriggerType.DOCUMENT_EXPIRY,
                scope=TriggerScope.FUND,
                fund_id=fund_id,
                ble_id=None,
                detail={
                    "doc_type": doc["document_type"],
                    "fund_name": fund["name"],
                    "expiry_date": expiry_str,
                    "days_until_expiry": days_until,
                    "status": "expired" if days_until < 0 else "expiring_soon",
                },
            )
            triggers_fired += 1
            cards = agent.process_trigger(trigger, fund_id=fund_id, synthetic_static=False)
            for card in cards:
                workflow.create_suggestion(card)
                cards_created.append(card.card_id)

    return {
        "screened_entities": len(screened),
        "triggers_fired": triggers_fired,
        "cards_created": len(cards_created),
        "results": screened,
    }
