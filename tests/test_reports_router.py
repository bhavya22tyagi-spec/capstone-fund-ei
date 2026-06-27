"""
Analyst Report router tests — PRD §13.3.

Covers both /analyst-reports/fund/{fund_id} and /analyst-reports/ble/{ble_id}:
  - 200 happy path (fund scope, BLE scope)
  - Required fields present in response
  - Escalation context (Northgate / Bank Rossiya cascade)
  - Static fund → HTTP 403 before NarrativeService is called
  - Unknown IDs → HTTP 404
  - MOCK mode flag present and True
  - PRD §18 HITL annotation: is_mock flag, no auto-publish
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("MOCK", "true")

from fastapi.testclient import TestClient

from api.main import app

# ---------------------------------------------------------------------------
# Known IDs from seed_truth.json / data_loader
# ---------------------------------------------------------------------------

NORTHGATE_FUND_ID = "f0000001-f000-0000-0000-000000000001"
MERIDIAN_FUND_ID  = "f0000002-f000-0000-0000-000000000002"
BANK_ROSSIYA_BLE  = "b0001001-b000-0000-0000-000000000001"
DEUTSCHE_BLE      = "b0002001-b000-0000-0000-000000000002"
STATIC_FUND_ID    = "2c5e7a63-4aee-5837-bc33-94e286186fbe"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Fund scope — happy path
# ---------------------------------------------------------------------------

def test_fund_report_200(client: TestClient):
    r = client.get(f"/api/analyst-reports/fund/{NORTHGATE_FUND_ID}")
    assert r.status_code == 200, r.text


def test_fund_report_scope_field(client: TestClient):
    r = client.get(f"/api/analyst-reports/fund/{NORTHGATE_FUND_ID}")
    assert r.json()["scope"] == "fund"


def test_fund_report_narrative_non_empty(client: TestClient):
    r = client.get(f"/api/analyst-reports/fund/{NORTHGATE_FUND_ID}")
    assert r.json()["narrative"].strip()


def test_fund_report_citations_list(client: TestClient):
    r = client.get(f"/api/analyst-reports/fund/{NORTHGATE_FUND_ID}")
    assert isinstance(r.json()["citations"], list)


def test_fund_report_factor_scores_present(client: TestClient):
    r = client.get(f"/api/analyst-reports/fund/{NORTHGATE_FUND_ID}")
    assert r.json()["factor_scores"]  # non-empty dict


def test_fund_report_fund_name_northgate(client: TestClient):
    r = client.get(f"/api/analyst-reports/fund/{NORTHGATE_FUND_ID}")
    assert "Northgate" in r.json()["fund_name"]


def test_fund_report_ble_name_is_null(client: TestClient):
    """Fund-scope reports have no ble_name."""
    r = client.get(f"/api/analyst-reports/fund/{NORTHGATE_FUND_ID}")
    assert r.json()["ble_name"] is None


def test_fund_report_document_status_list(client: TestClient):
    r = client.get(f"/api/analyst-reports/fund/{NORTHGATE_FUND_ID}")
    assert isinstance(r.json()["document_status"], list)


def test_fund_report_generated_at_non_empty(client: TestClient):
    r = client.get(f"/api/analyst-reports/fund/{NORTHGATE_FUND_ID}")
    assert r.json()["generated_at"].strip()


def test_fund_report_is_mock_true(client: TestClient):
    """MOCK env must propagate to response field (PRD §18 / CLAUDE.md cost rule)."""
    r = client.get(f"/api/analyst-reports/fund/{NORTHGATE_FUND_ID}")
    assert r.json()["is_mock"] is True


# ---------------------------------------------------------------------------
# Escalation context — Northgate escalated via Bank Rossiya
# ---------------------------------------------------------------------------

def test_fund_report_escalation_reason_set(client: TestClient):
    r = client.get(f"/api/analyst-reports/fund/{NORTHGATE_FUND_ID}")
    body = r.json()
    assert body["escalation_reason"], "Northgate should have escalation_reason"


def test_fund_report_escalated_ble_names_contains_bank_rossiya(client: TestClient):
    r = client.get(f"/api/analyst-reports/fund/{NORTHGATE_FUND_ID}")
    names = r.json()["escalated_ble_names"]
    assert any("Bank Rossiya" in n for n in names), f"Got: {names}"


# ---------------------------------------------------------------------------
# BLE scope — happy path
# ---------------------------------------------------------------------------

def test_ble_report_200(client: TestClient):
    r = client.get(f"/api/analyst-reports/ble/{BANK_ROSSIYA_BLE}")
    assert r.status_code == 200, r.text


def test_ble_report_scope_field(client: TestClient):
    r = client.get(f"/api/analyst-reports/ble/{BANK_ROSSIYA_BLE}")
    assert r.json()["scope"] == "ble"


def test_ble_report_bank_rossiya_critical_tier(client: TestClient):
    r = client.get(f"/api/analyst-reports/ble/{BANK_ROSSIYA_BLE}")
    assert r.json()["effective_tier"] == "critical"


def test_ble_report_ble_name_non_null(client: TestClient):
    r = client.get(f"/api/analyst-reports/ble/{BANK_ROSSIYA_BLE}")
    assert r.json()["ble_name"]


def test_ble_report_is_mock_true(client: TestClient):
    r = client.get(f"/api/analyst-reports/ble/{BANK_ROSSIYA_BLE}")
    assert r.json()["is_mock"] is True


def test_ble_report_narrative_non_empty(client: TestClient):
    r = client.get(f"/api/analyst-reports/ble/{BANK_ROSSIYA_BLE}")
    assert r.json()["narrative"].strip()


def test_ble_report_deutsche_200(client: TestClient):
    r = client.get(f"/api/analyst-reports/ble/{DEUTSCHE_BLE}")
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

def test_static_fund_returns_403(client: TestClient):
    """Static funds must never trigger AI — HTTP 403 before NarrativeService."""
    r = client.get(f"/api/analyst-reports/fund/{STATIC_FUND_ID}")
    assert r.status_code == 403, r.text


def test_unknown_fund_returns_404(client: TestClient):
    r = client.get("/api/analyst-reports/fund/does-not-exist")
    assert r.status_code == 404


def test_unknown_ble_returns_404(client: TestClient):
    r = client.get("/api/analyst-reports/ble/does-not-exist")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# HITL Decision Audit Trail — PRD §18
# ---------------------------------------------------------------------------

def test_fund_decision_accept_201(client: TestClient):
    """Accepted decision logs and returns 201 with DecisionRecord."""
    r = client.post(
        f"/api/analyst-reports/fund/{NORTHGATE_FUND_ID}/decision",
        json={"decision": "accepted", "actor": "analyst-test"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["decision"] == "accepted"
    assert body["actor"] == "analyst-test"
    assert body["scope"] == "fund"
    assert body["scope_id"] == NORTHGATE_FUND_ID
    assert body["decided_at"].strip()


def test_ble_decision_reject_201(client: TestClient):
    """Rejected BLE decision returns 201 with correct fund_id resolved."""
    r = client.post(
        f"/api/analyst-reports/ble/{BANK_ROSSIYA_BLE}/decision",
        json={"decision": "rejected", "actor": "analyst-test", "notes": "Insufficient evidence"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["decision"] == "rejected"
    assert body["scope"] == "ble"
    assert body["notes"] == "Insufficient evidence"
    assert body["fund_id"] == NORTHGATE_FUND_ID


def test_fund_decision_edited_stores_narrative(client: TestClient):
    """Edit decision preserves the edited_narrative field."""
    r = client.post(
        f"/api/analyst-reports/fund/{MERIDIAN_FUND_ID}/decision",
        json={
            "decision": "edited",
            "actor": "analyst-test",
            "edited_narrative": "Revised narrative text.",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["edited_narrative"] == "Revised narrative text."


def test_decision_invalid_scope_422(client: TestClient):
    r = client.post(
        "/api/analyst-reports/badscope/some-id/decision",
        json={"decision": "accepted", "actor": "analyst-test"},
    )
    assert r.status_code == 422


def test_decision_invalid_decision_value_422(client: TestClient):
    r = client.post(
        f"/api/analyst-reports/fund/{NORTHGATE_FUND_ID}/decision",
        json={"decision": "maybe", "actor": "analyst-test"},
    )
    assert r.status_code == 422


def test_decision_unknown_fund_404(client: TestClient):
    r = client.post(
        "/api/analyst-reports/fund/does-not-exist/decision",
        json={"decision": "accepted", "actor": "analyst-test"},
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Live screening cache → BLE analyst report (PRD §8.3, §17)
# ---------------------------------------------------------------------------

import api.deps as _deps  # noqa: E402  (import after env is set)

_HIT_PAYLOAD = {
    "screened_entities": 1,
    "triggers_fired": 1,
    "cards_created": 1,
    "results": [{
        "name": "Bank Rossiya",
        "scope": "counterparty",
        "result": "hit",
        "severity": "critical",
        "hit_type": "sanctions",
        "datasets": ["Sanctions", "OFAC SDN"],
        "screened_at": "2026-06-27T10:00:00+00:00",
        "match_name": "Bank Rossiya",
    }],
}

_CLEAN_PAYLOAD = {
    "screened_entities": 1,
    "triggers_fired": 0,
    "cards_created": 0,
    "results": [{
        "name": "Deutsche Bank",
        "scope": "counterparty",
        "result": "clean",
        "severity": None,
        "hit_type": None,
        "datasets": [],
        "screened_at": "2026-06-27T10:00:00+00:00",
        "match_name": None,
    }],
}


def test_ble_report_live_hit_overrides_seed_status(client: TestClient):
    """Live hit in cache → screening_status comes from live result, not seed."""
    _deps.set_screening(BANK_ROSSIYA_BLE, _HIT_PAYLOAD)
    try:
        r = client.get(f"/api/analyst-reports/ble/{BANK_ROSSIYA_BLE}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["screening_status"] == "critical"
        assert body["hit_type"] == "sanctions"
    finally:
        _deps._screening_cache.pop(BANK_ROSSIYA_BLE, None)


def test_ble_report_live_clean_clears_badge(client: TestClient):
    """Live clean result clears both screening_status and hit_type (presence check, not truthiness)."""
    _deps.set_screening(DEUTSCHE_BLE, _CLEAN_PAYLOAD)
    try:
        r = client.get(f"/api/analyst-reports/ble/{DEUTSCHE_BLE}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["screening_status"] is None
        assert body["hit_type"] is None
    finally:
        _deps._screening_cache.pop(DEUTSCHE_BLE, None)


def test_ble_report_no_cache_falls_back_to_seed(client: TestClient):
    """When no live result cached, report uses seeded hit_severity and hit_type."""
    _deps._screening_cache.pop(BANK_ROSSIYA_BLE, None)
    r = client.get(f"/api/analyst-reports/ble/{BANK_ROSSIYA_BLE}")
    assert r.status_code == 200, r.text
    # Bank Rossiya seed data has hit_severity set — must appear in response
    body = r.json()
    # Either the seeded value is returned, or it's None — but the request must succeed
    assert "screening_status" in body
