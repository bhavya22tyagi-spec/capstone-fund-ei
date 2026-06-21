"""
Tests for services/extraction/service.py (PRD §8.2).

All tests run in MOCK=true mode unless explicitly testing the real LLM path
via monkeypatching. Covers: field extraction per document type, static fund
guard (runs in both MOCK and real modes), idempotency, validation errors,
and the real-path JSON parsing.
"""
from __future__ import annotations

import json

import pytest

import services.extraction.service as ext_svc
from services.extraction.service import (
    KNOWN_DOCUMENT_TYPES,
    extract_document_fields,
    reset_cache,
)
from services.guards import StaticFundAIError

# Stable IDs matching seed_truth.json
_F1 = "f0000001-f000-0000-0000-000000000001"
_F2 = "f0000002-f000-0000-0000-000000000002"
_F4 = "f0000004-f000-0000-0000-000000000004"
_B11 = "b0001001-b000-0000-0000-000000000001"


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr(ext_svc, "MOCK", True)
    reset_cache()
    yield
    reset_cache()


def _extract(
    document_type: str,
    doc_id: str = "doc-test-001",
    scope: str = "fund",
) -> dict:
    scope_id = _F1 if scope == "fund" else _B11
    return extract_document_fields(
        scope=scope,
        scope_id=scope_id,
        fund_id=_F1,
        document_type=document_type,
        file_path="ignored_in_mock.txt",
        doc_id=doc_id,
    )


# ---------------------------------------------------------------------------
# 1. Known document types
# ---------------------------------------------------------------------------

def test_seven_known_document_types():
    assert len(KNOWN_DOCUMENT_TYPES) == 7


def test_all_expected_types_present():
    expected = {
        "Incorporation Certificate",
        "UBO Declaration",
        "Counterparty Agreement",
        "Framework Agreement",
        "Annual Report",
        "Regulatory Licence",
        "Investment Manager Agreement",
    }
    assert KNOWN_DOCUMENT_TYPES == expected


# ---------------------------------------------------------------------------
# 2. MOCK extraction returns correct structure per document type
# ---------------------------------------------------------------------------

def test_incorp_cert_returns_dict():
    assert isinstance(_extract("Incorporation Certificate"), dict)


def test_incorp_cert_has_required_keys():
    result = _extract("Incorporation Certificate")
    for key in (
        "entity_name", "incorporation_date", "registration_number",
        "legal_form", "jurisdiction_country_code", "registered_address",
        "authorized_representative_name", "authorized_representative_title",
    ):
        assert key in result, f"Missing key: {key}"


def test_ubo_decl_returns_dict():
    assert isinstance(_extract("UBO Declaration", doc_id="doc-test-ubo"), dict)


def test_ubo_decl_ubos_is_list():
    result = _extract("UBO Declaration", doc_id="doc-test-ubo")
    assert isinstance(result["ubos"], list)


def test_ubo_decl_ubo_has_required_fields():
    ubo = _extract("UBO Declaration", doc_id="doc-test-ubo")["ubos"][0]
    for field in ("name", "ownership_pct", "layer_depth", "resolved", "pep_tier", "jurisdiction"):
        assert field in ubo, f"Missing UBO field: {field}"


def test_counterparty_agmt_returns_dict():
    assert isinstance(
        _extract("Counterparty Agreement", doc_id="doc-test-cpty", scope="ble"), dict
    )


def test_counterparty_agmt_has_required_keys():
    result = _extract("Counterparty Agreement", doc_id="doc-test-cpty", scope="ble")
    for key in ("fund_name", "counterparty_name", "counterparty_location",
                "agreement_date", "agreement_ref", "facility_type"):
        assert key in result, f"Missing key: {key}"


def test_framework_agmt_returns_dict():
    assert isinstance(
        _extract("Framework Agreement", doc_id="doc-test-fwk", scope="ble"), dict
    )


def test_annual_report_returns_dict():
    assert isinstance(_extract("Annual Report", doc_id="doc-test-ar"), dict)


def test_annual_report_has_required_keys():
    result = _extract("Annual Report", doc_id="doc-test-ar")
    for key in ("entity_name", "period", "period_start", "period_end", "expiry_date", "status"):
        assert key in result, f"Missing key: {key}"


def test_regulatory_licence_returns_dict():
    assert isinstance(_extract("Regulatory Licence", doc_id="doc-test-rl"), dict)


def test_investment_mgr_agmt_returns_dict():
    assert isinstance(_extract("Investment Manager Agreement", doc_id="doc-test-ima"), dict)


def test_investment_mgr_agmt_has_required_keys():
    result = _extract("Investment Manager Agreement", doc_id="doc-test-ima")
    for key in (
        "entity_name", "authorized_representative_name",
        "authorized_representative_title", "agreement_date",
    ):
        assert key in result, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# 3. Static fund guard — runs in both MOCK and real modes
# ---------------------------------------------------------------------------

def test_static_fund_guard_raises_in_mock():
    with pytest.raises(StaticFundAIError):
        extract_document_fields(
            scope="fund",
            scope_id="static-001",
            fund_id="static-001",
            document_type="Incorporation Certificate",
            file_path="cert.txt",
            doc_id="doc-static",
            synthetic_static=True,
        )


def test_static_fund_guard_runs_before_any_extraction():
    """Guard must fire before returning any result, even in MOCK=true."""
    with pytest.raises(StaticFundAIError):
        extract_document_fields(
            scope="fund",
            scope_id="static-001",
            fund_id="static-001",
            document_type="UBO Declaration",
            file_path="ubo.txt",
            doc_id="doc-static-ubo",
            synthetic_static=True,
        )


# ---------------------------------------------------------------------------
# 4. Validation errors
# ---------------------------------------------------------------------------

def test_invalid_scope_raises():
    with pytest.raises(ValueError, match="scope"):
        extract_document_fields(
            scope="company",
            scope_id=_F1,
            fund_id=_F1,
            document_type="Incorporation Certificate",
            file_path="cert.txt",
            doc_id="doc-bad-scope",
        )


def test_unknown_document_type_raises():
    with pytest.raises(ValueError, match="document_type"):
        extract_document_fields(
            scope="fund",
            scope_id=_F1,
            fund_id=_F1,
            document_type="Board Resolution",
            file_path="br.txt",
            doc_id="doc-bad-type",
        )


def test_empty_scope_id_raises():
    with pytest.raises(ValueError, match="scope_id"):
        extract_document_fields(
            scope="fund",
            scope_id="",
            fund_id=_F1,
            document_type="Incorporation Certificate",
            file_path="cert.txt",
            doc_id="doc-bad-sid",
        )


def test_empty_fund_id_raises():
    with pytest.raises(ValueError, match="fund_id"):
        extract_document_fields(
            scope="fund",
            scope_id=_F1,
            fund_id="",
            document_type="Incorporation Certificate",
            file_path="cert.txt",
            doc_id="doc-bad-fid",
        )


# ---------------------------------------------------------------------------
# 5. Idempotency — MOCK=true
# ---------------------------------------------------------------------------

def test_second_call_same_doc_id_returns_equal_result():
    r1 = _extract("Incorporation Certificate", doc_id="doc-idem-001")
    r2 = _extract("Incorporation Certificate", doc_id="doc-idem-001")
    assert r1 == r2


def test_second_call_returns_cached_object():
    r1 = _extract("Incorporation Certificate", doc_id="doc-idem-002")
    r2 = _extract("Incorporation Certificate", doc_id="doc-idem-002")
    assert r1 is r2


def test_reset_cache_allows_fresh_extraction():
    r1 = _extract("Regulatory Licence", doc_id="doc-idem-003")
    reset_cache()
    r2 = _extract("Regulatory Licence", doc_id="doc-idem-003")
    assert r1 == r2
    assert r1 is not r2  # different object after cache reset


def test_different_doc_ids_are_cached_independently():
    r1 = _extract("Annual Report", doc_id="doc-ar-001")
    r2 = _extract("Annual Report", doc_id="doc-ar-002")
    assert isinstance(r1, dict)
    assert isinstance(r2, dict)
    # Verify both are in cache independently
    reset_cache()
    r1_fresh = _extract("Annual Report", doc_id="doc-ar-001")
    assert r1_fresh is not r2  # separate cache entries


# ---------------------------------------------------------------------------
# 6. Real path — monkeypatched LLM for isolation
# ---------------------------------------------------------------------------

_INCORP_JSON = json.dumps({
    "entity_name": "Test Entity LP",
    "incorporation_date": "2021-01-15",
    "registration_number": "TEST-REG-001",
    "legal_form": "Exempted Limited Partnership",
    "jurisdiction_country_code": "CYM",
    "registered_address": "1 Test Road, George Town, Cayman Islands",
    "authorized_representative_name": "Test Rep",
    "authorized_representative_title": "General Partner",
})


def test_real_path_returns_dict(monkeypatch, tmp_path):
    doc_file = tmp_path / "cert.txt"
    doc_file.write_text("[SYNTHETIC COMPLIANCE DOCUMENT]\nEntity: Test Entity LP\n", encoding="utf-8")

    monkeypatch.setattr(ext_svc, "MOCK", False)
    import services.ai_client as ac
    import services.cost_logger as cl
    monkeypatch.setattr(ac, "MOCK", False)
    monkeypatch.setattr(ac, "_real_llm_call", lambda p, m: {
        "content": _INCORP_JSON, "model": m,
        "usage": {"input_tokens": 200, "output_tokens": 80, "total_tokens": 280},
        "is_mock": False,
    })
    monkeypatch.setattr(cl, "LOG_FILE", str(tmp_path / "calls.jsonl"))

    result = extract_document_fields(
        scope="fund", scope_id=_F1, fund_id=_F1,
        document_type="Incorporation Certificate",
        file_path=doc_file, doc_id="doc-real-001",
    )
    assert isinstance(result, dict)
    assert result["entity_name"] == "Test Entity LP"


def test_real_path_parses_json_in_code_block(monkeypatch, tmp_path):
    doc_file = tmp_path / "rl.txt"
    doc_file.write_text("[SYNTHETIC]\nLicence expiry: 2026-07-08\n", encoding="utf-8")

    payload = json.dumps({"entity_name": "Test Ltd", "expiry_date": "2026-07-08", "status": "verified"})

    monkeypatch.setattr(ext_svc, "MOCK", False)
    import services.ai_client as ac
    import services.cost_logger as cl
    monkeypatch.setattr(ac, "MOCK", False)
    monkeypatch.setattr(ac, "_real_llm_call", lambda p, m: {
        "content": f"```json\n{payload}\n```", "model": m,
        "usage": {"input_tokens": 100, "output_tokens": 40, "total_tokens": 140},
        "is_mock": False,
    })
    monkeypatch.setattr(cl, "LOG_FILE", str(tmp_path / "calls2.jsonl"))

    result = extract_document_fields(
        scope="fund", scope_id=_F4, fund_id=_F4,
        document_type="Regulatory Licence",
        file_path=doc_file, doc_id="doc-real-rl-001",
    )
    assert result["expiry_date"] == "2026-07-08"


def test_real_path_file_not_found(monkeypatch):
    monkeypatch.setattr(ext_svc, "MOCK", False)
    with pytest.raises(FileNotFoundError):
        extract_document_fields(
            scope="fund", scope_id=_F1, fund_id=_F1,
            document_type="Incorporation Certificate",
            file_path="/nonexistent/cert.txt", doc_id="doc-no-file",
        )


def test_real_path_static_fund_guard(monkeypatch):
    monkeypatch.setattr(ext_svc, "MOCK", False)
    with pytest.raises(StaticFundAIError):
        extract_document_fields(
            scope="fund", scope_id="static-001", fund_id="static-001",
            document_type="Incorporation Certificate",
            file_path="/nonexistent/cert.txt", doc_id="doc-static-real",
            synthetic_static=True,
        )


def test_real_path_idempotency(monkeypatch, tmp_path):
    """Second call with same doc_id returns cached result without re-calling LLM."""
    doc_file = tmp_path / "fwk.txt"
    doc_file.write_text("[SYNTHETIC] Framework Agreement\n", encoding="utf-8")

    monkeypatch.setattr(ext_svc, "MOCK", False)
    import services.ai_client as ac
    import services.cost_logger as cl
    monkeypatch.setattr(ac, "MOCK", False)
    monkeypatch.setattr(cl, "LOG_FILE", str(tmp_path / "calls3.jsonl"))

    call_count = {"n": 0}

    def _fake_llm(prompt, model):
        call_count["n"] += 1
        return {
            "content": json.dumps({
                "fund_name": "Test Fund", "counterparty_name": "Test Bank",
                "counterparty_location": "London, UK", "agreement_date": "2021-01-01",
                "agreement_ref": "TEST-001", "facility_type": "Cash Management",
            }),
            "model": model,
            "usage": {"input_tokens": 50, "output_tokens": 30, "total_tokens": 80},
            "is_mock": False,
        }

    monkeypatch.setattr(ac, "_real_llm_call", _fake_llm)

    r1 = extract_document_fields(
        scope="ble", scope_id=_B11, fund_id=_F1,
        document_type="Framework Agreement",
        file_path=doc_file, doc_id="doc-idem-real-001",
    )
    r2 = extract_document_fields(
        scope="ble", scope_id=_B11, fund_id=_F1,
        document_type="Framework Agreement",
        file_path=doc_file, doc_id="doc-idem-real-001",
    )

    assert call_count["n"] == 1  # LLM called exactly once
    assert r1 == r2
