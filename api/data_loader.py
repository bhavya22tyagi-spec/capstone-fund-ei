"""
In-memory data store for the FastAPI layer.

Loads at startup:
  - 5 live Funds from evals/seed_truth.json
  - 45 static Funds from scripts/seed_data.py constants

All data is read-only after load_all() is called; no mutation during request handling.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
_SEED_TRUTH_PATH = _PROJECT_ROOT / "evals" / "seed_truth.json"

# ---------------------------------------------------------------------------
# Real OpenSanctions badge: only Bank Rossiya BLE gets screening_is_real=True
# (simulates a live positive match for demo; all other BLEs are MOCK-clean)
# ---------------------------------------------------------------------------
_REAL_SCREENING_BLES = {"b0001001-b000-0000-0000-000000000001"}

# ---------------------------------------------------------------------------
# In-memory stores (populated by load_all())
# ---------------------------------------------------------------------------
LIVE_FUNDS: dict[str, dict] = {}    # fund_id -> fund record
LIVE_BLES:  dict[str, dict] = {}    # ble_id  -> ble record (includes fund_id, fund_name)
STATIC_FUNDS: dict[str, dict] = {}  # fund_id -> static record
ALL_FUNDS_LIST: list[dict] = []     # all 50, live first then static

_loaded = False


def _make_static_id(i: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"static-fund-{i:04d}"))


def _doc_id(fund_alias: str, doc_type: str) -> str:
    slug = doc_type.lower().replace(" ", "-")
    return f"doc-{fund_alias}-{slug}"


def _ble_doc_id(ble_alias: str, doc_type: str) -> str:
    slug = doc_type.lower().replace(" ", "-")
    return f"doc-{ble_alias}-{slug}"


def _tier_from_score(score: float) -> str:
    if score < 26:
        return "low"
    if score < 51:
        return "medium"
    if score < 76:
        return "high"
    return "critical"


def _build_ble_record(ble_raw: dict, fund_id: str, fund_name: str, fund_idx: int, ble_idx: int) -> dict:
    fund_alias = f"f{fund_idx}"
    ble_alias  = f"f{fund_idx}-b{ble_idx}"

    screening = ble_raw.get("screening", {})
    risk = ble_raw.get("ble_risk_result", {})
    factors = ble_raw.get("ble_scoring_factors", {})
    ble_id = ble_raw["ble_id"]

    products = []
    for p in ble_raw.get("products", []):
        products.append({
            "product_id": p["product_id"],
            "product_type": p["type"],
            "workflow_template": p["workflow"],
            "status": "active",
        })

    documents = []
    for d in ble_raw.get("ble_documents", []):
        documents.append({
            "doc_id": _ble_doc_id(ble_alias, d["type"]),
            "document_type": d["type"],
            "status": d["status"],
            "expiry_date": d.get("expiry_date"),
            "extraction_status": "complete",
            "embedding_status": "complete",
        })

    return {
        "ble_id": ble_id,
        "fund_id": fund_id,
        "fund_name": fund_name,
        "name": f"{ble_raw['counterparty_name']}, {ble_raw['location']}",
        "institution": ble_raw["counterparty_name"],
        "location": ble_raw["location"],
        "counterparty_country": ble_raw.get("counterparty_country_code", ""),
        "tier": risk.get("effective_tier", risk.get("direct_tier", "low")),
        "score": float(risk.get("direct_score", 0.0)),
        "screening_is_real": ble_id in _REAL_SCREENING_BLES,
        "screening_status": screening.get("result_status", "clean"),
        "hit_type": screening.get("hit_type"),
        "hit_severity": screening.get("hit_severity", "none") if screening.get("result_status") == "hit" else None,
        "products": products,
        "documents": documents,
        "factor_scores": {
            "country":   factors.get("counterparty_country_risk", 0.0) * 0.25 / 100,
            "screening": factors.get("screening_sub_score", 0) * 0.375 / 100,
            "pep":       factors.get("pep_sub_score", 0) * 0.25 / 100,
            "documents": factors.get("document_completeness", 0.0) * 0.125 / 100,
        },
        "ruleset_version": "v1",
        # raw factor scores for ScoreBar
        "raw_factor_scores": {
            "Country Risk":  round(factors.get("counterparty_country_risk", 0.0) * 0.25 / 100, 2),
            "Screening":     round(factors.get("screening_sub_score", 0) * 0.375 / 100, 2),
            "PEP":           round(factors.get("pep_sub_score", 0) * 0.25 / 100, 2),
            "Documents":     round(factors.get("document_completeness", 0.0) * 0.125 / 100, 2),
        },
    }


def _build_live_fund(raw: dict, fund_idx: int) -> dict:
    fund_id = raw["fund_id"]
    name = raw["name"]
    incorporation = raw.get("incorporation", {})
    risk = raw.get("fund_risk_result", {})
    fund_alias = f"f{fund_idx}"

    ubos = raw.get("ubos", [])
    max_layer = max((u.get("layer_depth", 1) for u in ubos), default=1)
    all_resolved = all(u.get("resolved", True) for u in ubos)

    documents = []
    for d in raw.get("fund_documents", []):
        expiry = d.get("expiry_date")
        if expiry and not isinstance(expiry, str):
            expiry = str(expiry)
        documents.append({
            "doc_id": _doc_id(fund_alias, d["type"]),
            "document_type": d["type"],
            "status": d["status"],
            "expiry_date": expiry,
            "extraction_status": "complete",
            "embedding_status": "complete",
        })

    ble_summaries = []
    for i, ble_raw in enumerate(raw.get("bles", []), start=1):
        ble_rec = _build_ble_record(ble_raw, fund_id, name, fund_idx, i)
        LIVE_BLES[ble_rec["ble_id"]] = ble_rec
        ble_summaries.append({
            "ble_id": ble_rec["ble_id"],
            "fund_id": fund_id,
            "name": ble_rec["name"],
            "tier": ble_rec["tier"],
            "score": ble_rec["score"],
            "screening_is_real": ble_rec["screening_is_real"],
            "last_trigger_type": None,
        })

    factor_bd = risk.get("factor_breakdown", {})

    return {
        "fund_id": fund_id,
        "name": name,
        "incorporation_country": incorporation.get("country_code", incorporation.get("country_name", "")),
        "direct_tier": risk.get("direct_tier", "low"),
        "direct_score": float(risk.get("direct_score", 0.0)),
        "escalated_tier": risk.get("escalated_tier"),
        "escalation_reason": risk.get("escalation_reason"),
        "synthetic_static": raw.get("synthetic_static", False),
        "synthetic_profile": raw.get("synthetic_profile", True),
        "ubo_chain_layers": max_layer,
        "ubo_chain_resolved": all_resolved,
        "documents": documents,
        "ruleset_version": "v1",
        "factor_scores": {
            "Country":   round(factor_bd.get("country", 0.0), 2),
            "Screening": round(factor_bd.get("screening", 0.0), 2),
            "PEP":       round(factor_bd.get("pep", 0.0), 2),
            "UBO":       round(factor_bd.get("ubo", 0.0), 2),
            "Documents": round(factor_bd.get("documents", 0.0), 2),
        },
        "bles": ble_summaries,
    }


def _build_static_fund(i: int, name: str, country: str, score: float, tier: str) -> dict:
    fund_id = _make_static_id(i)
    has_ble = (i % 2 == 0)

    ble_names = [
        "Continental Bank AG", "Eastern Ventures Bank", "Northern Trust Corp",
        "Meridian Finance Ltd", "Pacific Capital Bank", "Atlantic Banking Group",
        "Southern Finance Corp", "Western Credit Bank", "Central Capital Ltd",
        "Global Banking Partners", "Vertex Finance Group", "Apex Banking Corp",
        "Summit Financial Ltd", "Horizon Capital Bank", "Crest Finance Corp",
        "Vanguard Credit Ltd", "Pinnacle Finance Corp", "Sterling Capital Bank",
        "Crown Finance Group", "Sovereign Banking Ltd",
    ]
    ble_scores = [12, 35, 55, 80, 15, 40, 62, 78, 18, 45, 58, 82, 20, 30, 68, 75, 22, 48, 51, 85]

    bles = []
    if has_ble:
        ble_idx = (i // 2) % len(ble_names)
        ble_score = float(ble_scores[ble_idx])
        bles.append({
            "ble_id": str(uuid.uuid5(uuid.NAMESPACE_DNS, f"static-ble-{i}")),
            "fund_id": fund_id,
            "name": f"{ble_names[ble_idx]}, Various",
            "tier": _tier_from_score(ble_score),
            "score": ble_score,
            "screening_is_real": False,
            "last_trigger_type": None,
        })

    return {
        "fund_id": fund_id,
        "name": name,
        "incorporation_country": country,
        "direct_tier": tier,
        "direct_score": score,
        "escalated_tier": None,
        "escalation_reason": None,
        "synthetic_static": True,
        "synthetic_profile": True,
        "ubo_chain_layers": 1,
        "ubo_chain_resolved": True,
        "documents": [],
        "ruleset_version": "v1",
        "factor_scores": {},
        "bles": bles,
    }


def load_all() -> None:
    global _loaded
    if _loaded:
        return

    # --- Live Funds ---
    with open(_SEED_TRUTH_PATH, encoding="utf-8") as fh:
        seed = json.load(fh)

    for idx, raw in enumerate(seed.get("live_funds", []), start=1):
        fund = _build_live_fund(raw, idx)
        LIVE_FUNDS[fund["fund_id"]] = fund

    # --- Static Funds ---
    _static_names = [
        "Abacus Strategic Fund LP", "Beacon Growth Trust", "Cedar Hill Capital Fund",
        "Durango Equity Partners LP", "Everest Income Fund", "Falcon Value Trust",
        "Geneva Capital Partners LP", "Huntington Growth Fund", "Ivy Lane Capital",
        "Jasper Income Trust", "Kent Street Capital LP", "Laurel Park Fund",
        "Mayfair Growth Partners", "Nordic Value Fund LP", "Oakwood Capital Trust",
        "Pacific Bridge Fund LP", "Queensway Capital Partners", "Regent Street Trust",
        "Sterling Growth Fund LP", "Thornbury Equity Partners", "Upton Capital Trust LP",
        "Vantage Growth Fund", "Westbridge Capital Partners", "Xavier Street Fund LP",
        "Yellowstone Income Trust", "Zurich Capital Partners LP", "Atlas Growth Fund",
        "Balmoral Capital Trust LP", "Cavendish Equity Fund", "Dawning Capital Partners LP",
        "Eastern Bridge Fund LP", "Frontier Capital Trust", "Global Reach Partners LP",
        "Highland Growth Fund", "Imperial Capital Trust LP", "Jade Street Partners",
        "Kensington Growth Fund LP", "Lakeview Capital Trust", "Merriweather Bridge Fund LP",
        "North Star Capital LP",
        "Offshore Ventures Trust LP", "Pinnacle Capital Partners",
        "Quantum Growth Fund LP", "Rockshore Capital Trust", "Summit Bridge Partners LP",
    ]
    _static_countries = [
        "GBR","USA","DEU","FRA","NLD","CHE","LUX","IRL","SWE","AUS",
        "CAN","JPN","NZL","DNK","NOR","SGP","HKG","ARE","MLT","CYM",
        "GBR","USA","DEU","FRA","NLD","CHE","LUX","IRL","SWE","AUS",
        "CAN","JPN","SGP","HKG","MLT","ARE","CYM","CHE","GBR","DEU",
        "NLD","FRA","ARE","MLT","CYM",
    ]
    _static_scores = (
        [15, 12, 20, 8, 18, 14, 22, 10, 16, 19, 11, 24, 13, 17, 21]
      + [28, 35, 42, 30, 47, 33, 38, 44, 29, 49, 31, 45, 36, 40, 27]
      + [53, 61, 68, 55, 72, 58, 65, 70, 52, 74]
      + [78, 85, 91, 82, 88]
    )
    _static_tiers = ["low"] * 15 + ["medium"] * 15 + ["high"] * 10 + ["critical"] * 5

    for i, (name, country, score, tier) in enumerate(
        zip(_static_names, _static_countries, _static_scores, _static_tiers)
    ):
        fund = _build_static_fund(i, name, country, float(score), tier)
        STATIC_FUNDS[fund["fund_id"]] = fund

    # --- Combined list: live first (sorted critical→low), then static same order ---
    _tier_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    live_sorted = sorted(
        LIVE_FUNDS.values(),
        key=lambda f: _tier_order.get(
            f["escalated_tier"] or f["direct_tier"], 4
        ),
    )
    ALL_FUNDS_LIST.clear()
    ALL_FUNDS_LIST.extend(live_sorted)
    ALL_FUNDS_LIST.extend(STATIC_FUNDS.values())

    _loaded = True


def get_fund(fund_id: str) -> dict | None:
    return LIVE_FUNDS.get(fund_id) or STATIC_FUNDS.get(fund_id)


def get_ble(ble_id: str) -> dict | None:
    return LIVE_BLES.get(ble_id)


def get_all_bles_for_fund(fund_id: str) -> list[dict]:
    return [b for b in LIVE_BLES.values() if b["fund_id"] == fund_id]
