"""
Seed the Neon DB from the existing in-memory data.
Reads from evals/seed_truth.json (5 live funds) and data_loader constants (45 static).
Idempotent: clears and re-seeds all tables on each run (demo only).
"""
from __future__ import annotations
import json, os, sys, uuid
from pathlib import Path
from datetime import datetime, timezone

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://neondb_owner:npg_zBpEctiquW27@ep-sparkling-mud-aoq42ki0.c-2.ap-southeast-1.aws.neon.tech/neondb?sslmode=require",
)

import psycopg2
import psycopg2.extras

PROJECT_ROOT = Path(__file__).parent.parent
SEED_PATH    = PROJECT_ROOT / "evals" / "seed_truth.json"

# ── helpers ──────────────────────────────────────────────────────────────────

def _tier(score: float) -> str:
    if score < 26: return "low"
    if score < 51: return "medium"
    if score < 76: return "high"
    return "critical"

def _static_id(i: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"static-fund-{i:04d}"))

def _static_ble_id(i: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"static-ble-{i}"))

NOW = datetime.now(timezone.utc)

# ── load source data ──────────────────────────────────────────────────────────

seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
live_funds_raw = seed.get("live_funds", [])

_static_names = [
    "Abacus Strategic Fund LP","Beacon Growth Trust","Cedar Hill Capital Fund",
    "Durango Equity Partners LP","Everest Income Fund","Falcon Value Trust",
    "Geneva Capital Partners LP","Huntington Growth Fund","Ivy Lane Capital",
    "Jasper Income Trust","Kent Street Capital LP","Laurel Park Fund",
    "Mayfair Growth Partners","Nordic Value Fund LP","Oakwood Capital Trust",
    "Pacific Bridge Fund LP","Queensway Capital Partners","Regent Street Trust",
    "Sterling Growth Fund LP","Thornbury Equity Partners","Upton Capital Trust LP",
    "Vantage Growth Fund","Westbridge Capital Partners","Xavier Street Fund LP",
    "Yellowstone Income Trust","Zurich Capital Partners LP","Atlas Growth Fund",
    "Balmoral Capital Trust LP","Cavendish Equity Fund","Dawning Capital Partners LP",
    "Eastern Bridge Fund LP","Frontier Capital Trust","Global Reach Partners LP",
    "Highland Growth Fund","Imperial Capital Trust LP","Jade Street Partners",
    "Kensington Growth Fund LP","Lakeview Capital Trust","Merriweather Bridge Fund LP",
    "North Star Capital LP",
    "Offshore Ventures Trust LP","Pinnacle Capital Partners",
    "Quantum Growth Fund LP","Rockshore Capital Trust","Summit Bridge Partners LP",
]
_static_countries = [
    "GBR","USA","DEU","FRA","NLD","CHE","LUX","IRL","SWE","AUS",
    "CAN","JPN","NZL","DNK","NOR","SGP","HKG","ARE","MLT","CYM",
    "GBR","USA","DEU","FRA","NLD","CHE","LUX","IRL","SWE","AUS",
    "CAN","JPN","SGP","HKG","MLT","ARE","CYM","CHE","GBR","DEU",
    "NLD","FRA","ARE","MLT","CYM",
]
_static_scores = (
    [15,12,20,8,18,14,22,10,16,19,11,24,13,17,21]
  + [28,35,42,30,47,33,38,44,29,49,31,45,36,40,27]
  + [53,61,68,55,72,58,65,70,52,74]
  + [78,85,91,82,88]
)
_static_tiers  = ["low"]*15 + ["medium"]*15 + ["high"]*10 + ["critical"]*5

_ble_names = [
    "Continental Bank AG","Eastern Ventures Bank","Northern Trust Corp",
    "Meridian Finance Ltd","Pacific Capital Bank","Atlantic Banking Group",
    "Southern Finance Corp","Western Credit Bank","Central Capital Ltd",
    "Global Banking Partners","Vertex Finance Group","Apex Banking Corp",
    "Summit Financial Ltd","Horizon Capital Bank","Crest Finance Corp",
    "Vanguard Credit Ltd","Pinnacle Finance Corp","Sterling Capital Bank",
    "Crown Finance Group","Sovereign Banking Ltd",
]
_ble_scores = [12,35,55,80,15,40,62,78,18,45,58,82,20,30,68,75,22,48,51,85]

# ── seed ─────────────────────────────────────────────────────────────────────

def seed_db(conn):
    cur = conn.cursor()

    # Wipe in reverse FK order
    for tbl in [
        "document_embeddings","eval_runs","llm_call_log",
        "review_audit_history","workflow_suggestions","review_triggers",
        "risk_scores","screening_results","ubo_records",
        "ble_documents","fund_documents","ble_products",
        "bles","counterparty_profiles","funds","ruleset_config",
    ]:
        cur.execute(f"TRUNCATE {tbl} CASCADE")
    print("  Cleared all tables.")

    # Ruleset
    cur.execute("""
        INSERT INTO ruleset_config
            (version, scope_level, weight_country, weight_screening,
             weight_pep, weight_ubo, weight_documents, is_active)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
    """, ("v1","both",0.20,0.30,0.20,0.20,0.10,True))
    print("  Ruleset v1 inserted.")

    # ── Live Funds ────────────────────────────────────────────────────────────
    for f_idx, raw in enumerate(live_funds_raw, start=1):
        fund_id = raw["fund_id"]
        name    = raw["name"]
        inc     = raw.get("incorporation",{})
        country = inc.get("country_code", inc.get("country_name",""))[:3]
        risk    = raw.get("fund_risk_result",{})

        cur.execute("""
            INSERT INTO funds (fund_id, name, incorporation_country,
                               synthetic_profile, synthetic_static)
            VALUES (%s,%s,%s,%s,%s)
        """, (fund_id, name, country or None, True, False))

        # Fund documents
        for doc in raw.get("fund_documents",[]):
            cur.execute("""
                INSERT INTO fund_documents
                    (fund_id, document_type, status, expiry_date,
                     extraction_status, embedding_status, synthetic_profile)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
            """, (fund_id, doc["type"], doc["status"],
                  doc.get("expiry_date"), "extracted", "embedded", True))

        # UBO records
        for ubo in raw.get("ubos",[]):
            cur.execute("""
                INSERT INTO ubo_records
                    (fund_id, ubo_name, ownership_pct, layer_depth,
                     jurisdiction, resolved, pep_tier, synthetic_profile)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """, (fund_id, ubo.get("name","Unknown"),
                  ubo.get("ownership_pct"), ubo.get("layer_depth",1),
                  ubo.get("jurisdiction"), ubo.get("resolved",False),
                  ubo.get("pep_tier",0), True))

        # Fund risk score
        fb = risk.get("factor_breakdown",{})
        cur.execute("""
            INSERT INTO risk_scores
                (scope, scope_id, ruleset_version, direct_score, direct_tier,
                 escalated_tier, escalation_reason, hard_stop, factor_scores)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, ("fund", fund_id, "v1",
              risk.get("direct_score",0), risk.get("direct_tier","low"),
              risk.get("escalated_tier"), risk.get("escalation_reason"),
              bool(risk.get("hard_stop",False)),
              psycopg2.extras.Json(fb)))

        # BLEs
        for b_idx, ble_raw in enumerate(raw.get("bles",[]), start=1):
            ble_id  = ble_raw["ble_id"]
            c_name  = ble_raw["counterparty_name"]
            c_loc   = ble_raw["location"]
            c_cntry = ble_raw.get("counterparty_country_code","")[:3]

            # Counterparty profile (one per unique institution+country)
            cp_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{c_name}:{c_cntry}"))
            cur.execute("""
                INSERT INTO counterparty_profiles
                    (counterparty_id, institution_name, country, synthetic_profile)
                VALUES (%s,%s,%s,%s)
                ON CONFLICT DO NOTHING
            """, (cp_id, c_name, c_cntry or None, True))

            cur.execute("""
                INSERT INTO bles
                    (ble_id, parent_fund_id, counterparty_profile_id,
                     location, synthetic_profile)
                VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT DO NOTHING
            """, (ble_id, fund_id, cp_id, c_loc, True))

            # BLE products
            for p in ble_raw.get("products",[]):
                prod_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, p["product_id"]))
                cur.execute("""
                    INSERT INTO ble_products
                        (product_id, ble_id, product_type,
                         workflow_template_id, status)
                    VALUES (%s,%s,%s,%s,%s)
                """, (prod_id, ble_id, p["type"], p["workflow"], "active"))

            # BLE documents
            for doc in ble_raw.get("ble_documents",[]):
                cur.execute("""
                    INSERT INTO ble_documents
                        (ble_id, document_type, status, expiry_date,
                         extraction_status, embedding_status, synthetic_profile)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                """, (ble_id, doc["type"], doc["status"],
                      doc.get("expiry_date"), "extracted", "embedded", True))

            # BLE screening result
            scr = ble_raw.get("screening",{})
            cur.execute("""
                INSERT INTO screening_results
                    (scope, scope_id, screened_name, result_status,
                     hit_severity, hit_type, is_mock)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
            """, ("counterparty", cp_id, c_name,
                  scr.get("result_status","clean"),
                  scr.get("hit_severity","none"),
                  scr.get("hit_type"), False))

            # BLE risk score
            b_risk = ble_raw.get("ble_risk_result",{})
            cur.execute("""
                INSERT INTO risk_scores
                    (scope, scope_id, ruleset_version, direct_score, direct_tier,
                     hard_stop, factor_scores)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
            """, ("ble", ble_id, "v1",
                  b_risk.get("direct_score",0),
                  b_risk.get("direct_tier","low"),
                  bool(b_risk.get("hard_stop",False)),
                  psycopg2.extras.Json(ble_raw.get("ble_scoring_factors",{}))))

        print(f"  Live fund {f_idx}: {name}")

    # ── Static Funds ──────────────────────────────────────────────────────────
    for i, (name, country, score, tier) in enumerate(
        zip(_static_names, _static_countries, _static_scores, _static_tiers)
    ):
        fund_id = _static_id(i)
        cur.execute("""
            INSERT INTO funds (fund_id, name, incorporation_country,
                               synthetic_profile, synthetic_static)
            VALUES (%s,%s,%s,%s,%s)
        """, (fund_id, name, country, True, True))

        cur.execute("""
            INSERT INTO risk_scores
                (scope, scope_id, ruleset_version, direct_score, direct_tier,
                 hard_stop, factor_scores)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
        """, ("fund", fund_id, "v1", float(score), tier, False,
              psycopg2.extras.Json({})))

        # Static BLE (every other fund)
        if i % 2 == 0:
            ble_idx   = (i // 2) % len(_ble_names)
            ble_score = float(_ble_scores[ble_idx])
            ble_id    = _static_ble_id(i)
            b_name    = _ble_names[ble_idx]
            cp_id     = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"static-cp-{ble_idx}"))

            cur.execute("""
                INSERT INTO counterparty_profiles
                    (counterparty_id, institution_name, synthetic_profile)
                VALUES (%s,%s,%s)
                ON CONFLICT DO NOTHING
            """, (cp_id, b_name, True))

            cur.execute("""
                INSERT INTO bles
                    (ble_id, parent_fund_id, counterparty_profile_id,
                     location, synthetic_profile)
                VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT DO NOTHING
            """, (ble_id, fund_id, cp_id, "Various", True))

            cur.execute("""
                INSERT INTO risk_scores
                    (scope, scope_id, ruleset_version, direct_score, direct_tier,
                     hard_stop, factor_scores)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
            """, ("ble", ble_id, "v1", ble_score, _tier(ble_score),
                  False, psycopg2.extras.Json({})))

    print(f"  45 static funds inserted.")
    conn.commit()
    print("SEED COMPLETE.")


if __name__ == "__main__":
    conn = psycopg2.connect(DB_URL)
    try:
        seed_db(conn)
    finally:
        conn.close()
