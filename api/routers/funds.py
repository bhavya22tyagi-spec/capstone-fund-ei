from fastapi import APIRouter, HTTPException
from api.data_loader import ALL_FUNDS_LIST, get_fund
from api.models import FundDetail, FundSummary, RiskScore, BLESummary, DocumentInfo

router = APIRouter()


def _to_summary(f: dict) -> FundSummary:
    return FundSummary(
        fund_id=f["fund_id"],
        name=f["name"],
        incorporation_country=f["incorporation_country"],
        direct_tier=f["direct_tier"],
        direct_score=f["direct_score"],
        escalated_tier=f.get("escalated_tier"),
        escalation_reason=f.get("escalation_reason"),
        synthetic_static=f["synthetic_static"],
        synthetic_profile=f["synthetic_profile"],
        bles=[BLESummary(**b) for b in f.get("bles", [])],
    )


def _to_detail(f: dict) -> FundDetail:
    return FundDetail(
        fund_id=f["fund_id"],
        name=f["name"],
        incorporation_country=f["incorporation_country"],
        direct_tier=f["direct_tier"],
        direct_score=f["direct_score"],
        escalated_tier=f.get("escalated_tier"),
        escalation_reason=f.get("escalation_reason"),
        synthetic_static=f["synthetic_static"],
        synthetic_profile=f["synthetic_profile"],
        bles=[BLESummary(**b) for b in f.get("bles", [])],
        ubo_chain_layers=f.get("ubo_chain_layers", 1),
        ubo_chain_resolved=f.get("ubo_chain_resolved", True),
        documents=[DocumentInfo(**d) for d in f.get("documents", [])],
        ruleset_version=f.get("ruleset_version", "v1"),
        factor_scores=f.get("factor_scores", {}),
    )


@router.get("/funds", response_model=list[FundSummary])
def list_funds() -> list[FundSummary]:
    return [_to_summary(f) for f in ALL_FUNDS_LIST]


@router.get("/funds/{fund_id}", response_model=FundDetail)
def get_fund_detail(fund_id: str) -> FundDetail:
    f = get_fund(fund_id)
    if f is None:
        raise HTTPException(status_code=404, detail=f"Fund {fund_id!r} not found")
    return _to_detail(f)


@router.get("/funds/{fund_id}/risk-score", response_model=RiskScore)
def get_fund_risk_score(fund_id: str) -> RiskScore:
    f = get_fund(fund_id)
    if f is None:
        raise HTTPException(status_code=404, detail=f"Fund {fund_id!r} not found")
    return RiskScore(
        direct_score=f["direct_score"],
        direct_tier=f["direct_tier"],
        escalated_tier=f.get("escalated_tier"),
        escalation_reason=f.get("escalation_reason"),
        hard_stop=False,
        factor_scores=f.get("factor_scores", {}),
    )
