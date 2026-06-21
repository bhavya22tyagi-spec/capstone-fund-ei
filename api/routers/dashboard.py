from fastapi import APIRouter
from api.data_loader import ALL_FUNDS_LIST
from api.models import DashboardResponse, HighRiskEntry

router = APIRouter()

_TIER_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


@router.get("/dashboard", response_model=DashboardResponse)
def get_dashboard() -> DashboardResponse:
    tier_dist: dict[str, int] = {"low": 0, "medium": 0, "high": 0, "critical": 0}
    high_risk_queue: list[HighRiskEntry] = []
    live_count = 0
    high_critical_count = 0

    for f in ALL_FUNDS_LIST:
        if not f["synthetic_static"]:
            live_count += 1

        effective = f.get("escalated_tier") or f["direct_tier"]
        tier_dist[effective] = tier_dist.get(effective, 0) + 1

        if effective in ("high", "critical"):
            high_critical_count += 1
            # Only show in high-risk queue if live OR static-critical
            if not f["synthetic_static"] or effective == "critical":
                escalated_ble_name: str | None = None
                if f.get("escalated_tier") and f["escalated_tier"] != f["direct_tier"]:
                    for ble in f.get("bles", []):
                        if ble["tier"] == "critical":
                            escalated_ble_name = ble["name"]
                            break
                high_risk_queue.append(HighRiskEntry(
                    fund_id=f["fund_id"],
                    fund_name=f["name"],
                    synthetic_static=f["synthetic_static"],
                    effective_tier=effective,
                    direct_tier=f["direct_tier"],
                    direct_score=f["direct_score"],
                    escalated_ble_name=escalated_ble_name,
                    last_trigger_type=None,
                ))

    high_risk_queue.sort(key=lambda e: _TIER_ORDER.get(e.effective_tier, 4))

    return DashboardResponse(
        total_funds=len(ALL_FUNDS_LIST),
        live_funds=live_count,
        high_critical_count=high_critical_count,
        tier_distribution=tier_dist,
        high_risk_queue=high_risk_queue,
    )
