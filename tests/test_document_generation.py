"""
Tests for scripts/generate_documents.py (PRD §7.2, §7.4, Phase 6).

These tests call generate_all_documents() directly (session-scoped fixture)
so the test suite is self-contained -- no manual pre-step required.

Covers:
  - All 12 documents exist after generation
  - Key extractable fields appear in each document
  - Three deliberate imperfections:
      doc-f2-ubo-decl        Werner Mueller shows 25.0% (planted), not 40.0%
      doc-f4-reg-licence     expiry_date shows 2025-07-08, not 2026-07-08
      doc-f5-invest-mgr-agmt agreement_date is absent (2020-07-01 not present)
  - SYNTHETIC tag present in all documents
  - Generation is idempotent (running twice produces same file content)
"""
from __future__ import annotations

from pathlib import Path

import pytest

# Import the module so generate_all_documents() can be called
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.generate_documents import DOCUMENTS_DIR, generate_all_documents

# Stable IDs
_F1 = "f0000001-f000-0000-0000-000000000001"
_F2 = "f0000002-f000-0000-0000-000000000002"
_F3 = "f0000003-f000-0000-0000-000000000003"
_F4 = "f0000004-f000-0000-0000-000000000004"
_F5 = "f0000005-f000-0000-0000-000000000005"
_B11 = "b0001001-b000-0000-0000-000000000001"
_B21 = "b0002001-b000-0000-0000-000000000002"
_B41 = "b0004001-b000-0000-0000-000000000005"
_B51 = "b0005001-b000-0000-0000-000000000006"


@pytest.fixture(scope="session", autouse=True)
def _generate_docs():
    """Generate all documents once for the test session."""
    generate_all_documents(force=True)


def _read(scope: str, scope_id: str, doc_id: str) -> str:
    path = DOCUMENTS_DIR / scope / scope_id / f"{doc_id}.txt"
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Directory structure
# ---------------------------------------------------------------------------

def test_fund_directory_exists():
    assert (DOCUMENTS_DIR / "fund").is_dir()


def test_ble_directory_exists():
    assert (DOCUMENTS_DIR / "ble").is_dir()


# ---------------------------------------------------------------------------
# 2. All 12 files exist
# ---------------------------------------------------------------------------

def test_f1_incorp_cert_exists():
    assert (DOCUMENTS_DIR / "fund" / _F1 / "doc-f1-incorp-cert.txt").exists()


def test_f1_ubo_decl_exists():
    assert (DOCUMENTS_DIR / "fund" / _F1 / "doc-f1-ubo-decl.txt").exists()


def test_f1_b1_cpty_agmt_exists():
    assert (DOCUMENTS_DIR / "ble" / _B11 / "doc-f1-b1-cpty-agmt.txt").exists()


def test_f2_ubo_decl_exists():
    assert (DOCUMENTS_DIR / "fund" / _F2 / "doc-f2-ubo-decl.txt").exists()


def test_f2_annual_report_exists():
    assert (DOCUMENTS_DIR / "fund" / _F2 / "doc-f2-annual-report.txt").exists()


def test_f2_b1_framework_agmt_exists():
    assert (DOCUMENTS_DIR / "ble" / _B21 / "doc-f2-b1-framework-agmt.txt").exists()


def test_f3_incorp_cert_exists():
    assert (DOCUMENTS_DIR / "fund" / _F3 / "doc-f3-incorp-cert.txt").exists()


def test_f4_reg_licence_exists():
    assert (DOCUMENTS_DIR / "fund" / _F4 / "doc-f4-reg-licence.txt").exists()


def test_f4_incorp_cert_exists():
    assert (DOCUMENTS_DIR / "fund" / _F4 / "doc-f4-incorp-cert.txt").exists()


def test_f4_b1_cpty_agmt_exists():
    assert (DOCUMENTS_DIR / "ble" / _B41 / "doc-f4-b1-cpty-agmt.txt").exists()


def test_f5_invest_mgr_agmt_exists():
    assert (DOCUMENTS_DIR / "fund" / _F5 / "doc-f5-invest-mgr-agmt.txt").exists()


def test_f5_b1_cpty_agmt_exists():
    assert (DOCUMENTS_DIR / "ble" / _B51 / "doc-f5-b1-cpty-agmt.txt").exists()


# ---------------------------------------------------------------------------
# 3. SYNTHETIC tag present everywhere
# ---------------------------------------------------------------------------

def test_f1_incorp_cert_has_synthetic_tag():
    assert "SYNTHETIC" in _read("fund", _F1, "doc-f1-incorp-cert").upper()


def test_f1_b1_cpty_agmt_has_synthetic_tag():
    assert "SYNTHETIC" in _read("ble", _B11, "doc-f1-b1-cpty-agmt").upper()


def test_f4_reg_licence_has_synthetic_tag():
    assert "SYNTHETIC" in _read("fund", _F4, "doc-f4-reg-licence").upper()


# ---------------------------------------------------------------------------
# 4. doc-f1-incorp-cert key fields
# ---------------------------------------------------------------------------

def test_f1_incorp_cert_entity_name():
    assert "Northgate Capital Partners LP" in _read("fund", _F1, "doc-f1-incorp-cert")


def test_f1_incorp_cert_registration_number():
    assert "EX-CYM-2019-08742" in _read("fund", _F1, "doc-f1-incorp-cert")


def test_f1_incorp_cert_rep_name():
    assert "James H. Northgate" in _read("fund", _F1, "doc-f1-incorp-cert")


def test_f1_incorp_cert_jurisdiction():
    assert "CYM" in _read("fund", _F1, "doc-f1-incorp-cert")


# ---------------------------------------------------------------------------
# 5. doc-f1-ubo-decl key fields
# ---------------------------------------------------------------------------

def test_f1_ubo_decl_entity_name():
    assert "Northgate Capital Partners LP" in _read("fund", _F1, "doc-f1-ubo-decl")


def test_f1_ubo_decl_john_richardson():
    assert "John Richardson" in _read("fund", _F1, "doc-f1-ubo-decl")


def test_f1_ubo_decl_70_pct():
    assert "70.0" in _read("fund", _F1, "doc-f1-ubo-decl")


def test_f1_ubo_decl_cayman_ventures():
    assert "Cayman Ventures Ltd" in _read("fund", _F1, "doc-f1-ubo-decl")


# ---------------------------------------------------------------------------
# 6. doc-f1-b1-cpty-agmt key fields
# ---------------------------------------------------------------------------

def test_f1_cpty_agmt_fund_name():
    assert "Northgate Capital Partners LP" in _read("ble", _B11, "doc-f1-b1-cpty-agmt")


def test_f1_cpty_agmt_counterparty():
    assert "Bank Rossiya" in _read("ble", _B11, "doc-f1-b1-cpty-agmt")


def test_f1_cpty_agmt_amount():
    content = _read("ble", _B11, "doc-f1-b1-cpty-agmt")
    assert "5000000" in content or "5,000,000" in content


def test_f1_cpty_agmt_ref():
    assert "NCP-BR-2022-001" in _read("ble", _B11, "doc-f1-b1-cpty-agmt")


# ---------------------------------------------------------------------------
# 7. doc-f2-ubo-decl — IMPERFECTION: Werner Mueller 25.0% (not 40.0%)
# ---------------------------------------------------------------------------

def test_f2_ubo_decl_has_werner_mueller():
    assert "Werner Mueller" in _read("fund", _F2, "doc-f2-ubo-decl")


def test_f2_ubo_decl_planted_pct_25():
    assert "25.0" in _read("fund", _F2, "doc-f2-ubo-decl")


def test_f2_ubo_decl_eu_capital_has_40():
    content = _read("fund", _F2, "doc-f2-ubo-decl")
    assert "EU Capital Partners SA" in content
    assert "40.0" in content  # EU Capital Partners SA correctly has 40.0%


# ---------------------------------------------------------------------------
# 8. doc-f2-annual-report key fields
# ---------------------------------------------------------------------------

def test_f2_annual_report_entity_name():
    assert "Meridian Strategic Growth Trust" in _read("fund", _F2, "doc-f2-annual-report")


def test_f2_annual_report_expiry_date():
    assert "2026-05-06" in _read("fund", _F2, "doc-f2-annual-report")


def test_f2_annual_report_status_expired():
    assert "expired" in _read("fund", _F2, "doc-f2-annual-report").lower()


# ---------------------------------------------------------------------------
# 9. doc-f3-incorp-cert key fields
# ---------------------------------------------------------------------------

def test_f3_incorp_cert_entity_name():
    assert "Aldgate Street Capital Fund" in _read("fund", _F3, "doc-f3-incorp-cert")


def test_f3_incorp_cert_reg_number():
    assert "IRL-673421" in _read("fund", _F3, "doc-f3-incorp-cert")


def test_f3_incorp_cert_rep_name():
    assert "Siobhan Murphy" in _read("fund", _F3, "doc-f3-incorp-cert")


# ---------------------------------------------------------------------------
# 10. doc-f4-reg-licence — IMPERFECTION: expiry_date 2025-07-08 (not 2026-07-08)
# ---------------------------------------------------------------------------

def test_f4_reg_licence_entity_name():
    assert "Harrington Private Capital" in _read("fund", _F4, "doc-f4-reg-licence")


def test_f4_reg_licence_planted_expiry():
    assert "2025-07-08" in _read("fund", _F4, "doc-f4-reg-licence")


def test_f4_reg_licence_no_correct_expiry():
    assert "2026-07-08" not in _read("fund", _F4, "doc-f4-reg-licence")


# ---------------------------------------------------------------------------
# 11. doc-f4-incorp-cert key fields
# ---------------------------------------------------------------------------

def test_f4_incorp_cert_entity_name():
    assert "Harrington Private Capital" in _read("fund", _F4, "doc-f4-incorp-cert")


def test_f4_incorp_cert_reg_number():
    assert "MLT-C-88412" in _read("fund", _F4, "doc-f4-incorp-cert")


def test_f4_incorp_cert_rep_name():
    assert "Robert Harrington III" in _read("fund", _F4, "doc-f4-incorp-cert")


# ---------------------------------------------------------------------------
# 12. doc-f5-invest-mgr-agmt — IMPERFECTION: agreement_date absent
# ---------------------------------------------------------------------------

def test_f5_invest_mgr_agmt_entity_name():
    assert "Queensbridge Emerging Markets Fund LP" in _read("fund", _F5, "doc-f5-invest-mgr-agmt")


def test_f5_invest_mgr_agmt_rep_name():
    assert "James Wentworth" in _read("fund", _F5, "doc-f5-invest-mgr-agmt")


def test_f5_invest_mgr_agmt_rep_title():
    assert "Managing Partner" in _read("fund", _F5, "doc-f5-invest-mgr-agmt")


def test_f5_invest_mgr_agmt_missing_agreement_date():
    assert "2020-07-01" not in _read("fund", _F5, "doc-f5-invest-mgr-agmt")


# ---------------------------------------------------------------------------
# 13. doc-f5-b1-cpty-agmt key fields
# ---------------------------------------------------------------------------

def test_f5_b1_cpty_agmt_fund_name():
    assert "Queensbridge Emerging Markets Fund LP" in _read("ble", _B51, "doc-f5-b1-cpty-agmt")


def test_f5_b1_cpty_agmt_counterparty():
    assert "ICBC Limited" in _read("ble", _B51, "doc-f5-b1-cpty-agmt")


def test_f5_b1_cpty_agmt_ref():
    assert "QEM-ICBC-2022-004" in _read("ble", _B51, "doc-f5-b1-cpty-agmt")


# ---------------------------------------------------------------------------
# 14. Idempotency
# ---------------------------------------------------------------------------

def test_second_run_produces_same_content():
    first = _read("fund", _F1, "doc-f1-incorp-cert")
    generate_all_documents(force=True)
    second = _read("fund", _F1, "doc-f1-incorp-cert")
    assert first == second


def test_generate_returns_12_results():
    results = generate_all_documents(force=False)
    assert len(results) == 12


def test_generate_force_writes_all():
    results = generate_all_documents(force=True)
    assert all(status == "written" for status, _ in results)


def test_generate_no_force_skips_existing():
    generate_all_documents(force=True)  # ensure files exist
    results = generate_all_documents(force=False)
    assert all(status == "skipped" for status, _ in results)
