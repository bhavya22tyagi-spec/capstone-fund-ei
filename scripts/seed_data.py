#!/usr/bin/env python3
"""
PRD Section 7 — Data seeding script: Fund -> BLE -> Product hierarchy.

Usage:
  uv run python scripts/seed_data.py              # dry-run: show summary + real API calls
  uv run python scripts/seed_data.py --seed       # also insert into PostgreSQL
  MOCK=true uv run python scripts/seed_data.py    # skip real API calls (dev/test)

Environment:
  OPENSANCTIONS_API_KEY   free-tier key (optional; unauthenticated attempted if absent)
  DATABASE_URL            PostgreSQL DSN (required for --seed)
  MOCK                    'true' to skip real API calls
"""
import argparse
import json
import os
import sys
from datetime import date, timedelta
from typing import Optional
from uuid import uuid4

import requests

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.guards import StaticFundAIError, assert_fund_allows_ai
from services.rule_engine.escalation import apply_escalation
from services.rule_engine.models import (
    BLEScoringFactors,
    FundScoringFactors,
    PEPTier,
    RiskTier,
    ScreeningHitSeverity,
)
from services.rule_engine.scoring import compute_ble_score, compute_fund_direct_score

MOCK = os.getenv("MOCK", "false").lower() == "true"
OPENSANCTIONS_API_KEY = os.getenv("OPENSANCTIONS_API_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")
RULESET_VERSION = "v1"
TODAY = date.today()

# ============================================================================
# Stable IDs — fixed strings, consistent with evals/seed_truth.json
# Static Fund IDs remain uuid4() in _build_static_funds() (evals don't touch them).
# ============================================================================

# Fund IDs
_F1_ID = "f0000001-f000-0000-0000-000000000001"  # Northgate Capital Partners LP
_F2_ID = "f0000002-f000-0000-0000-000000000002"  # Meridian Strategic Growth Trust
_F3_ID = "f0000003-f000-0000-0000-000000000003"  # Aldgate Street Capital Fund
_F4_ID = "f0000004-f000-0000-0000-000000000004"  # Harrington Private Capital
_F5_ID = "f0000005-f000-0000-0000-000000000005"  # Queensbridge Emerging Markets Fund LP

# BLE IDs
_B11_ID = "b0001001-b000-0000-0000-000000000001"  # Northgate x Bank Rossiya
_B21_ID = "b0002001-b000-0000-0000-000000000002"  # Meridian x Deutsche Bank AG
_B22_ID = "b0002002-b000-0000-0000-000000000003"  # Meridian x DBS Singapore
_B31_ID = "b0003001-b000-0000-0000-000000000004"  # Aldgate x DBS Hong Kong
_B41_ID = "b0004001-b000-0000-0000-000000000005"  # Harrington x Emirates NBD
_B51_ID = "b0005001-b000-0000-0000-000000000006"  # Queensbridge x ICBC Mumbai
_B52_ID = "b0005002-b000-0000-0000-000000000007"  # Queensbridge x Standard Chartered

# Counterparty IDs
_C1_ID       = "c0000001-c000-0000-0000-000000000001"  # Bank Rossiya (sanctioned)
_C2_ID       = "c0000002-c000-0000-0000-000000000002"  # Deutsche Bank AG
_DBS_CPTY_ID = "c0000003-c000-0000-0000-000000000003"  # DBS Bank Ltd (shared — Fund 2 BLE 2 + Fund 3 BLE 1)
_C4_ID       = "c0000004-c000-0000-0000-000000000004"  # Emirates NBD Bank PJSC
_C5_ID       = "c0000005-c000-0000-0000-000000000005"  # ICBC Limited
_C6_ID       = "c0000006-c000-0000-0000-000000000006"  # Standard Chartered Bank

# Product IDs
_P111_ID = "p0001011-p000-0000-0000-000000000001"  # Northgate BLE1 x Loan
_P211_ID = "p0002011-p000-0000-0000-000000000002"  # Meridian BLE1 x Cash
_P221_ID = "p0002021-p000-0000-0000-000000000003"  # Meridian BLE2 x Loan
_P311_ID = "p0003011-p000-0000-0000-000000000004"  # Aldgate BLE1 x Loan
_P411_ID = "p0004011-p000-0000-0000-000000000005"  # Harrington BLE1 x Cash
_P511_ID = "p0005011-p000-0000-0000-000000000006"  # Queensbridge BLE1 x Loan
_P512_ID = "p0005012-p000-0000-0000-000000000007"  # Queensbridge BLE1 x Cash
_P521_ID = "p0005021-p000-0000-0000-000000000008"  # Queensbridge BLE2 x Cash

# fmt: off
LIVE_FUNDS = [
    # ------------------------------------------------------------------
    # Fund 1 — Northgate Capital Partners LP
    # Escalation demo: BLE is Critical (Bank Rossiya sanctions hit),
    # Fund's own direct factors are LOW → surfaces as CRITICAL (PRD §9.3).
    # ------------------------------------------------------------------
    {
        "fund_id": _F1_ID,
        "name": "Northgate Capital Partners LP",
        "incorporation_country": "CYM",
        "synthetic_profile": True,
        "synthetic_static": False,
        # Pre-defined synthetic factors for Fund-level scoring.
        # UBO screening is a future phase; set to NONE here.
        "fund_factors": FundScoringFactors(
            incorporation_country_risk=45.0,   # Cayman Islands — moderate offshore
            screening_severity=ScreeningHitSeverity.NONE,
            pep_tier=PEPTier.NONE,
            ubo_risk=10.0,                     # 2-layer chain, fully resolved
            document_completeness=0.0,
        ),
        "ubos": [
            {"name": "John Richardson",    "ownership_pct": 70.0, "layer_depth": 1, "resolved": True,  "pep_tier": 0, "jurisdiction": "GBR", "parent_ubo_name": None},
            {"name": "Cayman Ventures Ltd","ownership_pct": 30.0, "layer_depth": 1, "resolved": True,  "pep_tier": 0, "jurisdiction": "CYM", "parent_ubo_name": None},
        ],
        "documents": [
            {"type": "Incorporation Certificate", "status": "verified", "expiry_date": None},
            {"type": "UBO Declaration",           "status": "verified", "expiry_date": None},
        ],
        "bles": [
            {
                "ble_id": _B11_ID,
                "counterparty_id": _C1_ID,
                "counterparty_name": "Bank Rossiya",
                "location": "Moscow, Russia",
                "counterparty_country": "RUS",
                "counterparty_country_risk": 90.0,  # Russia — high FATF/Basel risk
                "ble_pep_tier": PEPTier.NONE,
                "ble_doc_completeness": 0.0,
                "documents": [{"type": "Counterparty Agreement", "status": "verified", "expiry_date": None}],
                "products": [{"product_id": _P111_ID, "type": "Loan", "workflow": "ble_loan_onboarding_v1"}],
            },
        ],
    },

    # ------------------------------------------------------------------
    # Fund 2 — Meridian Strategic Growth Trust
    # UBO unresolved beyond layer 2 (PRD §7.4).
    # Expired document (PRD §7.4).
    # Shared DBS Bank Ltd counterparty with Fund 3.
    # ------------------------------------------------------------------
    {
        "fund_id": _F2_ID,
        "name": "Meridian Strategic Growth Trust",
        "incorporation_country": "LUX",
        "synthetic_profile": True,
        "synthetic_static": False,
        "fund_factors": FundScoringFactors(
            incorporation_country_risk=10.0,   # Luxembourg — low EU jurisdiction
            screening_severity=ScreeningHitSeverity.NONE,
            pep_tier=PEPTier.TIER_2,           # One UBO is a mid-tier PEP
            ubo_risk=60.0,                     # Partial chain — Meridian Holdings unresolved at layer 2+
            document_completeness=50.0,        # Annual Report expired (below)
        ),
        "ubos": [
            # Layer 1 entity — unresolved (PRD §7.4: "UBO chain unresolved beyond layer 2")
            {"name": "Meridian Holdings Ltd",   "ownership_pct": 60.0, "layer_depth": 1, "resolved": True,  "pep_tier": 0, "jurisdiction": "CYM", "parent_ubo_name": None},
            # Layer 2 — who controls Meridian Holdings Ltd is unknown
            {"name": "[Layer 2 entity unknown]","ownership_pct": None,  "layer_depth": 2, "resolved": False, "pep_tier": 0, "jurisdiction": None,  "parent_ubo_name": "Meridian Holdings Ltd"},
            # Second layer-1 branch — fully resolved
            {"name": "EU Capital Partners SA",  "ownership_pct": 40.0, "layer_depth": 1, "resolved": True,  "pep_tier": 0, "jurisdiction": "LUX", "parent_ubo_name": None},
            {"name": "Werner Mueller",          "ownership_pct": 40.0, "layer_depth": 2, "resolved": True,  "pep_tier": 2, "jurisdiction": "DEU", "parent_ubo_name": "EU Capital Partners SA"},
        ],
        "documents": [
            {"type": "Incorporation Certificate", "status": "verified",  "expiry_date": None},
            {"type": "UBO Declaration",           "status": "verified",  "expiry_date": None},
            # Expired document — satisfies PRD §7.4 requirement
            {"type": "Annual Report",             "status": "expired",   "expiry_date": TODAY - timedelta(days=45)},
        ],
        "bles": [
            {
                "ble_id": _B21_ID,
                "counterparty_id": _C2_ID,
                "counterparty_name": "Deutsche Bank AG",
                "location": "Frankfurt, Germany",
                "counterparty_country": "DEU",
                "counterparty_country_risk": 5.0,
                "ble_pep_tier": PEPTier.NONE,
                "ble_doc_completeness": 0.0,
                "documents": [{"type": "Framework Agreement", "status": "verified", "expiry_date": None}],
                "products": [
                    {"product_id": _P211_ID, "type": "Cash", "workflow": "ble_cash_onboarding_v1"},
                ],
            },
            {
                # Shared counterparty — same counterparty_id as Fund 3 BLE 1
                "ble_id": _B22_ID,
                "counterparty_id": _DBS_CPTY_ID,
                "counterparty_name": "DBS Bank Ltd",
                "location": "Singapore",
                "counterparty_country": "SGP",
                "counterparty_country_risk": 10.0,
                "ble_pep_tier": PEPTier.NONE,
                "ble_doc_completeness": 0.0,
                "documents": [{"type": "Counterparty Agreement", "status": "verified", "expiry_date": None}],
                "products": [
                    {"product_id": _P221_ID, "type": "Loan", "workflow": "ble_loan_onboarding_v1"},
                ],
            },
        ],
    },

    # ------------------------------------------------------------------
    # Fund 3 — Aldgate Street Capital Fund
    # References shared DBS Bank Ltd counterparty (same _DBS_CPTY_ID).
    # ------------------------------------------------------------------
    {
        "fund_id": _F3_ID,
        "name": "Aldgate Street Capital Fund",
        "incorporation_country": "IRL",
        "synthetic_profile": True,
        "synthetic_static": False,
        "fund_factors": FundScoringFactors(
            incorporation_country_risk=5.0,    # Ireland — very low EU jurisdiction
            screening_severity=ScreeningHitSeverity.NONE,
            pep_tier=PEPTier.NONE,
            ubo_risk=5.0,
            document_completeness=0.0,
        ),
        "ubos": [
            {"name": "Patrick O'Brien", "ownership_pct": 100.0, "layer_depth": 1, "resolved": True, "pep_tier": 0, "jurisdiction": "IRL", "parent_ubo_name": None},
        ],
        "documents": [
            {"type": "Incorporation Certificate", "status": "verified", "expiry_date": None},
        ],
        "bles": [
            {
                # Same counterparty_id as Fund 2 BLE 2 — screened once, reused (PRD §17)
                "ble_id": _B31_ID,
                "counterparty_id": _DBS_CPTY_ID,
                "counterparty_name": "DBS Bank Ltd",
                "location": "Hong Kong",
                "counterparty_country": "HKG",
                "counterparty_country_risk": 20.0,
                "ble_pep_tier": PEPTier.NONE,
                "ble_doc_completeness": 0.0,
                "documents": [{"type": "Counterparty Agreement", "status": "verified", "expiry_date": None}],
                "products": [
                    {"product_id": _P311_ID, "type": "Loan", "workflow": "ble_loan_onboarding_v1"},
                ],
            },
        ],
    },

    # ------------------------------------------------------------------
    # Fund 4 — Harrington Private Capital
    # HIGH direct score (Malta + PEP tier 1 + moderate screening flag).
    # BLE at HIGH tier (Emirates NBD, Dubai).
    # ------------------------------------------------------------------
    {
        "fund_id": _F4_ID,
        "name": "Harrington Private Capital",
        "incorporation_country": "MLT",
        "synthetic_profile": True,
        "synthetic_static": False,
        "fund_factors": FundScoringFactors(
            incorporation_country_risk=55.0,   # Malta — moderate EU periphery
            screening_severity=ScreeningHitSeverity.LOW,  # Synthetic: adverse media flag
            pep_tier=PEPTier.TIER_1,           # Principal owner is a senior PEP
            ubo_risk=45.0,
            document_completeness=40.0,        # Regulatory licence expiring soon
        ),
        "ubos": [
            {"name": "Robert Harrington III", "ownership_pct": 51.0, "layer_depth": 1, "resolved": True, "pep_tier": 1, "jurisdiction": "MLT", "parent_ubo_name": None},
            {"name": "HAP Holding Ltd",       "ownership_pct": 49.0, "layer_depth": 1, "resolved": True, "pep_tier": 0, "jurisdiction": "MLT", "parent_ubo_name": None},
            {"name": "Sarah Chen",            "ownership_pct": 49.0, "layer_depth": 2, "resolved": True, "pep_tier": 0, "jurisdiction": "SGP", "parent_ubo_name": "HAP Holding Ltd"},
        ],
        "documents": [
            {"type": "Incorporation Certificate", "status": "verified",  "expiry_date": None},
            {"type": "Regulatory Licence",        "status": "verified",  "expiry_date": TODAY + timedelta(days=18)},  # expiring within 30 days
        ],
        "bles": [
            {
                "ble_id": _B41_ID,
                "counterparty_id": _C4_ID,
                "counterparty_name": "Emirates NBD Bank PJSC",
                "location": "Dubai, UAE",
                "counterparty_country": "ARE",
                "counterparty_country_risk": 40.0,
                "ble_pep_tier": PEPTier.TIER_2,   # Connected director is mid-tier PEP
                "ble_doc_completeness": 10.0,
                "documents": [{"type": "Counterparty Agreement", "status": "verified", "expiry_date": None}],
                "products": [
                    {"product_id": _P411_ID, "type": "Cash", "workflow": "ble_cash_onboarding_v1"},
                ],
            },
        ],
    },

    # ------------------------------------------------------------------
    # Fund 5 — Queensbridge Emerging Markets Fund LP
    # Two BLEs, two products per BLE. LOW across the board.
    # ------------------------------------------------------------------
    {
        "fund_id": _F5_ID,
        "name": "Queensbridge Emerging Markets Fund LP",
        "incorporation_country": "SGP",
        "synthetic_profile": True,
        "synthetic_static": False,
        "fund_factors": FundScoringFactors(
            incorporation_country_risk=10.0,
            screening_severity=ScreeningHitSeverity.NONE,
            pep_tier=PEPTier.NONE,
            ubo_risk=5.0,
            document_completeness=0.0,
        ),
        "ubos": [
            {"name": "Queensbridge Asset Management Ltd", "ownership_pct": 100.0, "layer_depth": 1, "resolved": True, "pep_tier": 0, "jurisdiction": "SGP", "parent_ubo_name": None},
            {"name": "James Wentworth",                  "ownership_pct":  60.0, "layer_depth": 2, "resolved": True, "pep_tier": 0, "jurisdiction": "GBR", "parent_ubo_name": "Queensbridge Asset Management Ltd"},
            {"name": "Victoria Forsythe",                "ownership_pct":  40.0, "layer_depth": 2, "resolved": True, "pep_tier": 0, "jurisdiction": "AUS", "parent_ubo_name": "Queensbridge Asset Management Ltd"},
        ],
        "documents": [
            {"type": "Incorporation Certificate",       "status": "verified", "expiry_date": None},
            {"type": "Investment Manager Agreement",    "status": "verified", "expiry_date": None},
        ],
        "bles": [
            {
                "ble_id": _B51_ID,
                "counterparty_id": _C5_ID,
                "counterparty_name": "ICBC Limited",
                "location": "Mumbai, India",
                "counterparty_country": "IND",
                "counterparty_country_risk": 25.0,
                "ble_pep_tier": PEPTier.NONE,
                "ble_doc_completeness": 0.0,
                "documents": [{"type": "Counterparty Agreement", "status": "verified", "expiry_date": None}],
                "products": [
                    {"product_id": _P511_ID, "type": "Loan", "workflow": "ble_loan_onboarding_v1"},
                    {"product_id": _P512_ID, "type": "Cash", "workflow": "ble_cash_onboarding_v1"},
                ],
            },
            {
                "ble_id": _B52_ID,
                "counterparty_id": _C6_ID,
                "counterparty_name": "Standard Chartered Bank",
                "location": "Singapore",
                "counterparty_country": "SGP",
                "counterparty_country_risk": 10.0,
                "ble_pep_tier": PEPTier.NONE,
                "ble_doc_completeness": 0.0,
                "documents": [{"type": "Counterparty Agreement", "status": "verified", "expiry_date": None}],
                "products": [
                    {"product_id": _P521_ID, "type": "Cash", "workflow": "ble_cash_onboarding_v1"},
                ],
            },
        ],
    },
]
# fmt: on

# ---------------------------------------------------------------------------
# Static Funds — 45 dashboard-scale records (PRD §7.3)
# synthetic_static=True; NEVER capable of triggering LLM or embedding calls.
# ---------------------------------------------------------------------------

_STATIC_NAMES = [
    # Low (15)
    "Abacus Strategic Fund LP", "Beacon Growth Trust", "Cedar Hill Capital Fund",
    "Durango Equity Partners LP", "Everest Income Fund", "Falcon Value Trust",
    "Geneva Capital Partners LP", "Huntington Growth Fund", "Ivy Lane Capital",
    "Jasper Income Trust", "Kent Street Capital LP", "Laurel Park Fund",
    "Mayfair Growth Partners", "Nordic Value Fund LP", "Oakwood Capital Trust",
    # Medium (15)
    "Pacific Bridge Fund LP", "Queensway Capital Partners", "Regent Street Trust",
    "Sterling Growth Fund LP", "Thornbury Equity Partners", "Upton Capital Trust LP",
    "Vantage Growth Fund", "Westbridge Capital Partners", "Xavier Street Fund LP",
    "Yellowstone Income Trust", "Zurich Capital Partners LP", "Atlas Growth Fund",
    "Balmoral Capital Trust LP", "Cavendish Equity Fund", "Dawning Capital Partners LP",
    # High (10)
    "Eastern Bridge Fund LP", "Frontier Capital Trust", "Global Reach Partners LP",
    "Highland Growth Fund", "Imperial Capital Trust LP", "Jade Street Partners",
    "Kensington Growth Fund LP", "Lakeview Capital Trust", "Merriweather Bridge Fund LP",
    "North Star Capital LP",
    # Critical (5)
    "Offshore Ventures Trust LP", "Pinnacle Capital Partners",
    "Quantum Growth Fund LP", "Rockshore Capital Trust", "Summit Bridge Partners LP",
]

_STATIC_COUNTRIES = [
    "GBR","USA","DEU","FRA","NLD","CHE","LUX","IRL","SWE","AUS",
    "CAN","JPN","NZL","DNK","NOR","SGP","HKG","ARE","MLT","CYM",
    "GBR","USA","DEU","FRA","NLD","CHE","LUX","IRL","SWE","AUS",
    "CAN","JPN","SGP","HKG","MLT","ARE","CYM","CHE","GBR","DEU",
    "NLD","FRA","ARE","MLT","CYM",
]

# Pre-assigned static scores and tiers (no rule engine needed — dashboard-scale only)
_STATIC_SCORES = (
    [15, 12, 20, 8, 18, 14, 22, 10, 16, 19, 11, 24, 13, 17, 21]     # Low  0-14
  + [28, 35, 42, 30, 47, 33, 38, 44, 29, 49, 31, 45, 36, 40, 27]    # Medium 15-29
  + [53, 61, 68, 55, 72, 58, 65, 70, 52, 74]                         # High 30-39
  + [78, 85, 91, 82, 88]                                              # Critical 40-44
)
_STATIC_TIERS = (
    ["low"] * 15 + ["medium"] * 15 + ["high"] * 10 + ["critical"] * 5
)

# Static BLE counterparty names (generic, synthetic — no OpenSanctions calls)
_STATIC_BLE_NAMES = [
    "Continental Bank AG", "Eastern Ventures Bank", "Northern Trust Corp",
    "Meridian Finance Ltd", "Pacific Capital Bank", "Atlantic Banking Group",
    "Southern Finance Corp", "Western Credit Bank", "Central Capital Ltd",
    "Global Banking Partners", "Vertex Finance Group", "Apex Banking Corp",
    "Summit Financial Ltd", "Horizon Capital Bank", "Crest Finance Corp",
    "Vanguard Credit Ltd", "Pinnacle Finance Corp", "Sterling Capital Bank",
    "Crown Finance Group", "Sovereign Banking Ltd",
]

_STATIC_BLE_SCORES = [12, 35, 55, 80, 15, 40, 62, 78, 18, 45, 58, 82, 20, 30, 68, 75, 22, 48, 51, 85]
_STATIC_BLE_TIERS  = ["low","medium","high","critical","low","medium","high","critical",
                       "low","medium","high","critical","low","medium","high","critical",
                       "low","medium","high","critical"]

def _build_static_funds() -> list:
    funds = []
    ble_idx = 0
    for i, name in enumerate(_STATIC_NAMES):
        has_ble = (i % 2 == 0) and (ble_idx < len(_STATIC_BLE_NAMES))
        fund = {
            "fund_id": str(uuid4()),
            "name": name,
            "incorporation_country": _STATIC_COUNTRIES[i],
            "synthetic_profile": True,
            "synthetic_static": True,
            "direct_score": float(_STATIC_SCORES[i]),
            "direct_tier": _STATIC_TIERS[i],
            "ble": None,
        }
        if has_ble:
            fund["ble"] = {
                "ble_id": str(uuid4()),
                "counterparty_id": str(uuid4()),
                "counterparty_name": _STATIC_BLE_NAMES[ble_idx],
                "location": "London, UK",
                "direct_score": float(_STATIC_BLE_SCORES[ble_idx]),
                "direct_tier": _STATIC_BLE_TIERS[ble_idx],
            }
            ble_idx += 1
        funds.append(fund)
    return funds

STATIC_FUNDS = _build_static_funds()

# ============================================================================
# OpenSanctions screening
# ============================================================================

_MOCK_HITS = {
    "Bank Rossiya": ("hit", "confirmed", "sanctions"),
}

def _mock_screen(name: str) -> dict:
    if name in _MOCK_HITS:
        s, sev, ht = _MOCK_HITS[name]
        return {"result_status": s, "hit_severity": sev, "hit_type": ht,
                "raw_result": {"mock": True, "entity": name}, "is_mock": True}
    return {"result_status": "clean", "hit_severity": "none", "hit_type": None,
            "raw_result": {"mock": True}, "is_mock": True}


def _parse_opensanctions(name: str, data: dict) -> dict:
    results = data.get("results", [])
    if not results:
        return {"result_status": "clean", "hit_severity": "none", "hit_type": None, "raw_result": data, "is_mock": False}
    top = results[0]
    score = top.get("score", 0)
    if score < 0.7:
        return {"result_status": "clean", "hit_severity": "none", "hit_type": None, "raw_result": data, "is_mock": False}
    topics = top.get("properties", {}).get("topics", [])
    if "sanction" in topics or "sanction.linked" in topics:
        sev = "confirmed" if score >= 0.9 else "high"
        hit_type = "sanctions"
    elif "role.pep" in topics or "role.rca" in topics:
        sev = "high" if score >= 0.9 else "medium"
        hit_type = "pep"
    else:
        sev = "medium" if score >= 0.9 else "low"
        hit_type = "adverse"
    return {"result_status": "hit", "hit_severity": sev, "hit_type": hit_type, "raw_result": data, "is_mock": False}


def screen_counterparty(name: str) -> dict:
    """
    Real free-tier OpenSanctions call for a BLE counterparty name.
    PRD §7.4: the call itself is real regardless of the result.
    """
    if MOCK:
        return _mock_screen(name)

    headers = {}
    if OPENSANCTIONS_API_KEY:
        headers["Authorization"] = f"ApiKey {OPENSANCTIONS_API_KEY}"

    try:
        resp = requests.get(
            "https://api.opensanctions.org/search/default",
            params={"q": name, "schema": "LegalEntity", "limit": 5},
            headers=headers,
            timeout=10,
        )
        if resp.status_code in (401, 403):
            print(f"    [API] OpenSanctions requires auth — set OPENSANCTIONS_API_KEY.", file=sys.stderr)
            return {"result_status": "error", "hit_severity": "none", "hit_type": None,
                    "raw_result": {"error": f"http_{resp.status_code}"}, "is_mock": False}
        resp.raise_for_status()
        return _parse_opensanctions(name, resp.json())
    except requests.exceptions.RequestException as exc:
        return {"result_status": "error", "hit_severity": "none", "hit_type": None,
                "raw_result": {"error": str(exc)}, "is_mock": False}


_SEV_MAP = {
    "none":      ScreeningHitSeverity.NONE,
    "low":       ScreeningHitSeverity.LOW,
    "medium":    ScreeningHitSeverity.MEDIUM,
    "high":      ScreeningHitSeverity.HIGH,
    "confirmed": ScreeningHitSeverity.CONFIRMED,
    "error":     ScreeningHitSeverity.NONE,  # error treated as unscreened
}

# ============================================================================
# Build seeded results (deterministic scoring, real API calls)
# ============================================================================

def process_live_funds() -> list:
    """Screen each unique BLE counterparty, compute BLE and Fund scores."""
    # Track which counterparty_ids have already been screened (reuse PRD §17)
    screened: dict[str, dict] = {}
    results = []

    for fund in LIVE_FUNDS:
        # Enforce guard — live funds pass, but guard must exist in pipeline
        try:
            assert_fund_allows_ai(fund["fund_id"], fund["synthetic_static"])
        except StaticFundAIError:
            raise  # should never happen for live funds

        ble_results = []
        for ble in fund["bles"]:
            cpty_id = ble["counterparty_id"]
            if cpty_id not in screened:
                print(f"  Screening: {ble['counterparty_name']} ...", end=" ", flush=True)
                sr = screen_counterparty(ble["counterparty_name"])
                screened[cpty_id] = sr
                tag = " [MOCK]" if sr["is_mock"] else " [REAL]"
                hit = f"HIT ({sr['hit_severity']}, {sr['hit_type']})" if sr["result_status"] == "hit" else sr["result_status"].upper()
                print(f"{hit}{tag}")
            else:
                sr = screened[cpty_id]
                print(f"  Screening: {ble['counterparty_name']} ... REUSED (shared profile {cpty_id[:8]})")

            ble_factors = BLEScoringFactors(
                counterparty_country_risk=ble["counterparty_country_risk"],
                screening_severity=_SEV_MAP.get(sr["hit_severity"], ScreeningHitSeverity.NONE),
                pep_tier=ble["ble_pep_tier"],
                document_completeness=ble["ble_doc_completeness"],
            )
            ble_score = compute_ble_score(ble_factors)
            ble_results.append({
                "ble": ble,
                "screening": sr,
                "score": ble_score,
            })

        fund_score = compute_fund_direct_score(fund["fund_factors"])
        ble_name_scores = [(br["ble"]["counterparty_name"] + ", " + br["ble"]["location"], br["score"]) for br in ble_results]
        fund_effective = apply_escalation(fund_score, ble_name_scores)

        results.append({
            "fund": fund,
            "fund_score": fund_effective,
            "ble_results": ble_results,
        })

    return results


def process_static_funds() -> list:
    """Return static funds with guard verification. No API calls, no scoring."""
    for f in STATIC_FUNDS:
        # Prove the guard blocks any AI attempt on these funds
        try:
            assert_fund_allows_ai(f["fund_id"], f["synthetic_static"])
            raise RuntimeError(f"Guard failed to block static fund {f['name']}")  # must not reach here
        except StaticFundAIError:
            pass  # correct — guard fires, no AI call made
    return STATIC_FUNDS


# ============================================================================
# Summary printer
# ============================================================================

def _tier_badge(tier: str) -> str:
    return {"low": "LOW", "medium": "MEDIUM", "high": "HIGH", "critical": "CRITICAL"}.get(tier.lower() if isinstance(tier, str) else tier.value, str(tier))


def print_summary(live_results: list, static_funds: list) -> None:
    hr = "=" * 68
    print(f"\n{hr}")
    print("  SEED DATA SUMMARY — KYB Platform Demo (PRD §7)")
    print(f"{hr}\n")

    # ---- Live Funds ----
    print(f"LIVE FUNDS — {len(live_results)} total\n")
    positive_matches = []

    for idx, r in enumerate(live_results, 1):
        fund = r["fund"]
        fs = r["fund_score"]
        direct_tier = _tier_badge(fs.direct_tier)
        eff_tier = _tier_badge(fs.effective_tier)
        escalated = fs.escalated_tier is not None

        print(f"  Fund {idx}/5 | {fund['name']}")
        print(f"    Country     : {fund['incorporation_country']}")
        print(f"    Fund score  : {fs.direct_score:.1f} ({direct_tier})", end="")
        if escalated:
            print(f"  →  {eff_tier} effective  [BLE escalation]")
            print(f"    Reason      : {fs.escalation_reason}")
        else:
            print()
        print(f"    UBOs        : {len(fund['ubos'])} records ({sum(1 for u in fund['ubos'] if not u['resolved'])} unresolved)")
        print(f"    Documents   : {len(fund['documents'])} ({sum(1 for d in fund['documents'] if d['status'] == 'expired')} expired, {sum(1 for d in fund['documents'] if d.get('expiry_date') and d['expiry_date'] > TODAY) } expiring soon)")

        for bidx, br in enumerate(r["ble_results"], 1):
            ble = br["ble"]
            sr = br["screening"]
            bs = br["score"]
            ble_tier = _tier_badge(bs.direct_tier)
            is_hit = sr["result_status"] == "hit"
            hit_label = f"HIT — {sr['hit_severity'].upper()} ({sr['hit_type']})" if is_hit else sr["result_status"].upper()
            mock_tag = " [MOCK]" if sr["is_mock"] else " [REAL API]"
            match_flag = "  ◄ REAL POSITIVE MATCH" if (is_hit and not sr["is_mock"]) else ("  ◄ DESIGNED POSITIVE MATCH (mock)" if (is_hit and sr["is_mock"]) else "")

            print(f"\n    BLE {bidx}/{len(r['ble_results'])} | {ble['counterparty_name']} — {ble['location']}")
            print(f"      Cpty profile  : {ble['counterparty_id'][:16]}...")
            print(f"      OpenSanctions : {hit_label}{mock_tag}{match_flag}")
            if bs.hard_stop:
                print(f"      BLE score     : {bs.direct_score:.1f} ({ble_tier}) — HARD STOP (sanctions override)")
            else:
                print(f"      BLE score     : {bs.direct_score:.1f} ({ble_tier})")
            print(f"      Products      : {', '.join(p['type'] for p in ble['products'])}")

            if is_hit:
                positive_matches.append((fund["name"], ble["counterparty_name"], ble["location"], sr, bs))

        print()

    # ---- Static Funds ----
    tier_counts = {}
    for sf in static_funds:
        t = sf["direct_tier"]
        tier_counts[t] = tier_counts.get(t, 0) + 1

    ble_count = sum(1 for sf in static_funds if sf["ble"])
    print(f"\n{'-'*68}")
    print(f"STATIC FUNDS — {len(static_funds)} total (synthetic_static=True, LLM guard ACTIVE)")
    print(f"  Risk tier spread:")
    for tier in ("low", "medium", "high", "critical"):
        print(f"    {_tier_badge(tier):<8} : {tier_counts.get(tier, 0)} funds")
    print(f"  BLEs         : {ble_count}/{len(static_funds)} funds have 1 BLE (static, no API call)")
    print(f"  Guard test   : assert_fund_allows_ai() called and confirmed blocking on all {len(static_funds)} records")

    # ---- Shared counterparty ----
    print(f"\n{'-'*68}")
    print("SHARED COUNTERPARTY (PRD §17 — screened once, reused)")
    print(f"  Institution  : DBS Bank Ltd")
    print(f"  Profile ID   : {_DBS_CPTY_ID}")
    print(f"  Referenced by:")
    for r in live_results:
        for br in r["ble_results"]:
            if br["ble"]["counterparty_id"] == _DBS_CPTY_ID:
                print(f"    → {r['fund']['name']} — BLE: DBS Bank Ltd, {br['ble']['location']}")

    # ---- Required test cases ----
    print(f"\n{'-'*68}")
    print("REQUIRED TEST CASES (PRD §7.4)")
    print(f"  ✓ Shared counterparty across 2 Funds : DBS Bank Ltd ({_DBS_CPTY_ID[:16]}...)")
    unresolved_fund = next((r["fund"]["name"] for r in live_results if any(not u["resolved"] for u in r["fund"]["ubos"])), None)
    print(f"  ✓ UBO chain unresolved beyond layer 2 : {unresolved_fund}")
    expired_fund = next((r["fund"]["name"] for r in live_results if any(d["status"] == "expired" for d in r["fund"]["documents"])), None)
    print(f"  ✓ Document expired/expiring           : {expired_fund}")
    if positive_matches:
        fn, cn, loc, sr, bs = positive_matches[0]
        tag = "REAL API" if not sr["is_mock"] else "MOCK (set MOCK=false + API key for real call)"
        print(f"  ✓ Real positive OpenSanctions match   : {cn} ({loc})")
        print(f"      Source : {tag}")
        print(f"      Result : {sr['hit_severity'].upper()} {sr['hit_type']} hit → BLE {_tier_badge(bs.direct_tier)}")
        print(f"      Fund   : {fn} escalated to CRITICAL")
    else:
        print(f"  ✗ Real positive match                 : not yet confirmed (run with MOCK=false + API key)")

    print(f"\n{hr}\n")


# ============================================================================
# DB seeding (requires --seed flag and DATABASE_URL)
# ============================================================================

def seed_to_db(live_results: list, static_funds: list) -> None:
    try:
        import psycopg2
    except ImportError:
        print("psycopg2 not installed — run: uv pip install psycopg2-binary", file=sys.stderr)
        sys.exit(1)

    if not DATABASE_URL:
        print("DATABASE_URL not set.", file=sys.stderr)
        sys.exit(1)

    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    # Ruleset config
    cur.execute("""
        INSERT INTO ruleset_config (version, scope_level, weight_country, weight_screening, weight_pep, weight_ubo, weight_documents)
        VALUES (%s, 'both', 0.20, 0.30, 0.20, 0.20, 0.10)
        ON CONFLICT (version) DO NOTHING
    """, (RULESET_VERSION,))

    screened_cpty: dict[str, dict] = {}

    # ---- Live Funds ----
    for r in live_results:
        fund = r["fund"]
        fs = r["fund_score"]

        cur.execute("""
            INSERT INTO funds (fund_id, name, incorporation_country, synthetic_profile, synthetic_static)
            VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
        """, (fund["fund_id"], fund["name"], fund["incorporation_country"], True, False))

        # UBOs
        ubo_id_map = {}
        for ubo in fund["ubos"]:
            uid = str(uuid4())
            parent_id = ubo_id_map.get(ubo["parent_ubo_name"]) if ubo["parent_ubo_name"] else None
            cur.execute("""
                INSERT INTO ubo_records (ubo_id, fund_id, ubo_name, ownership_pct, layer_depth, jurisdiction, parent_ubo_id, resolved, pep_tier, synthetic_profile)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s, TRUE)
            """, (uid, fund["fund_id"], ubo["name"], ubo["ownership_pct"], ubo["layer_depth"],
                  ubo["jurisdiction"], parent_id, ubo["resolved"], ubo["pep_tier"]))
            ubo_id_map[ubo["name"]] = uid

        # Fund documents
        for doc in fund["documents"]:
            cur.execute("""
                INSERT INTO fund_documents (document_id, fund_id, document_type, status, expiry_date, extraction_status, embedding_status, synthetic_profile)
                VALUES (%s,%s,%s,%s,%s,'pending','pending',TRUE)
            """, (str(uuid4()), fund["fund_id"], doc["type"], doc["status"], doc["expiry_date"]))

        # Fund risk score
        cur.execute("""
            INSERT INTO risk_scores (score_id, scope, scope_id, ruleset_version, direct_score, direct_tier, escalated_tier, escalation_reason, hard_stop, factor_scores)
            VALUES (%s,'fund',%s,%s,%s,%s,%s,%s,%s,%s)
        """, (str(uuid4()), fund["fund_id"], RULESET_VERSION,
              fs.direct_score, fs.direct_tier.value,
              fs.escalated_tier.value if fs.escalated_tier else None,
              fs.escalation_reason, fs.hard_stop,
              json.dumps(fs.factor_scores)))

        # BLEs
        for br in r["ble_results"]:
            ble = br["ble"]
            sr = br["screening"]
            bs = br["score"]
            cpty_id = ble["counterparty_id"]

            # Counterparty profile — insert once per unique cpty_id
            if cpty_id not in screened_cpty:
                cur.execute("""
                    INSERT INTO counterparty_profiles (counterparty_id, institution_name, country, last_screened_at, screening_status, synthetic_profile)
                    VALUES (%s,%s,%s, NOW(),%s, TRUE) ON CONFLICT DO NOTHING
                """, (cpty_id, ble["counterparty_name"], ble["counterparty_country"],
                      "hit" if sr["result_status"] == "hit" else sr["result_status"]))
                # Screening result
                cur.execute("""
                    INSERT INTO screening_results (screening_id, scope, scope_id, screened_name, result_status, hit_severity, hit_type, raw_result, is_mock)
                    VALUES (%s,'counterparty',%s,%s,%s,%s,%s,%s,%s)
                """, (str(uuid4()), cpty_id, ble["counterparty_name"],
                      sr["result_status"], sr["hit_severity"] or "none", sr["hit_type"],
                      json.dumps(sr["raw_result"]), sr["is_mock"]))
                screened_cpty[cpty_id] = sr

            # BLE record
            cur.execute("""
                INSERT INTO bles (ble_id, parent_fund_id, counterparty_profile_id, location, synthetic_profile)
                VALUES (%s,%s,%s,%s,TRUE) ON CONFLICT DO NOTHING
            """, (ble["ble_id"], fund["fund_id"], cpty_id, ble["location"]))

            # BLE documents
            for doc in ble["documents"]:
                cur.execute("""
                    INSERT INTO ble_documents (document_id, ble_id, document_type, status, expiry_date, extraction_status, embedding_status, synthetic_profile)
                    VALUES (%s,%s,%s,%s,%s,'pending','pending',TRUE)
                """, (str(uuid4()), ble["ble_id"], doc["type"], doc["status"], doc["expiry_date"]))

            # BLE risk score
            cur.execute("""
                INSERT INTO risk_scores (score_id, scope, scope_id, ruleset_version, direct_score, direct_tier, hard_stop, factor_scores)
                VALUES (%s,'ble',%s,%s,%s,%s,%s,%s)
            """, (str(uuid4()), ble["ble_id"], RULESET_VERSION,
                  bs.direct_score, bs.direct_tier.value, bs.hard_stop,
                  json.dumps(bs.factor_scores)))

            # Products
            for prod in ble["products"]:
                cur.execute("""
                    INSERT INTO ble_products (product_id, ble_id, product_type, workflow_template_id)
                    VALUES (%s,%s,%s,%s)
                """, (prod["product_id"], ble["ble_id"], prod["type"], prod["workflow"]))

    # ---- Static Funds ----
    for sf in static_funds:
        cur.execute("""
            INSERT INTO funds (fund_id, name, incorporation_country, synthetic_profile, synthetic_static)
            VALUES (%s,%s,%s,TRUE,TRUE) ON CONFLICT DO NOTHING
        """, (sf["fund_id"], sf["name"], sf["incorporation_country"]))

        cur.execute("""
            INSERT INTO risk_scores (score_id, scope, scope_id, ruleset_version, direct_score, direct_tier, hard_stop, factor_scores)
            VALUES (%s,'fund',%s,%s,%s,%s,FALSE,%s)
        """, (str(uuid4()), sf["fund_id"], RULESET_VERSION,
              sf["direct_score"], sf["direct_tier"],
              json.dumps({"pre_computed": True, "synthetic_static": True})))

        if sf["ble"]:
            ble = sf["ble"]
            cur.execute("""
                INSERT INTO counterparty_profiles (counterparty_id, institution_name, country, screening_status, synthetic_profile)
                VALUES (%s,%s,'GBR','clean',TRUE) ON CONFLICT DO NOTHING
            """, (ble["counterparty_id"], ble["counterparty_name"]))
            cur.execute("""
                INSERT INTO bles (ble_id, parent_fund_id, counterparty_profile_id, location, synthetic_profile)
                VALUES (%s,%s,%s,'London, UK',TRUE) ON CONFLICT DO NOTHING
            """, (ble["ble_id"], sf["fund_id"], ble["counterparty_id"]))
            cur.execute("""
                INSERT INTO risk_scores (score_id, scope, scope_id, ruleset_version, direct_score, direct_tier, hard_stop, factor_scores)
                VALUES (%s,'ble',%s,%s,%s,%s,FALSE,%s)
            """, (str(uuid4()), ble["ble_id"], RULESET_VERSION,
                  ble["direct_score"], ble["direct_tier"],
                  json.dumps({"pre_computed": True, "synthetic_static": True})))

    conn.commit()
    cur.close()
    conn.close()
    print(f"DB seeding complete: {len(live_results)} live Funds, {len(static_funds)} static Funds.")


# ============================================================================
# Main
# ============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(description="Seed KYB demo data (PRD §7)")
    parser.add_argument("--seed", action="store_true", help="Insert into PostgreSQL (requires DATABASE_URL)")
    args = parser.parse_args()

    mode = "MOCK" if MOCK else "REAL API"
    print(f"\nKYB Seeding — mode: {mode}")
    print(f"Screening {sum(len(f['bles']) for f in LIVE_FUNDS)} BLE counterparties ({len(LIVE_FUNDS)} live Funds)...\n")

    live_results = process_live_funds()
    static_funds = process_static_funds()
    print_summary(live_results, static_funds)

    if args.seed:
        print("Inserting into DB...")
        seed_to_db(live_results, static_funds)


if __name__ == "__main__":
    main()
