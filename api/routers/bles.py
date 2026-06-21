from fastapi import APIRouter, HTTPException
from api.data_loader import get_ble
from api.models import BLEDetail, RiskScore, ProductInfo, DocumentInfo

router = APIRouter()


def _to_detail(b: dict) -> BLEDetail:
    return BLEDetail(
        ble_id=b["ble_id"],
        fund_id=b["fund_id"],
        fund_name=b["fund_name"],
        name=b["name"],
        tier=b["tier"],
        score=b["score"],
        screening_is_real=b["screening_is_real"],
        institution=b["institution"],
        location=b["location"],
        counterparty_country=b["counterparty_country"],
        screening_status=b["screening_status"],
        hit_type=b.get("hit_type"),
        hit_severity=b.get("hit_severity"),
        products=[ProductInfo(**p) for p in b.get("products", [])],
        documents=[DocumentInfo(**d) for d in b.get("documents", [])],
        factor_scores=b.get("raw_factor_scores", {}),
        ruleset_version=b.get("ruleset_version", "v1"),
    )


@router.get("/bles/{ble_id}", response_model=BLEDetail)
def get_ble_detail(ble_id: str) -> BLEDetail:
    b = get_ble(ble_id)
    if b is None:
        raise HTTPException(status_code=404, detail=f"BLE {ble_id!r} not found")
    return _to_detail(b)


@router.get("/bles/{ble_id}/risk-score", response_model=RiskScore)
def get_ble_risk_score(ble_id: str) -> RiskScore:
    b = get_ble(ble_id)
    if b is None:
        raise HTTPException(status_code=404, detail=f"BLE {ble_id!r} not found")
    return RiskScore(
        direct_score=b["score"],
        direct_tier=b["tier"],
        escalated_tier=None,
        escalation_reason=None,
        hard_stop=b.get("hit_severity") == "confirmed",
        factor_scores=b.get("raw_factor_scores", {}),
    )
