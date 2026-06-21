"""
PRD §17 — Counterparty profile reuse test.

A shared BLE counterparty (same counterparty_id referenced by multiple BLEs,
possibly across different Funds) must be screened exactly ONCE, never once
per BLE. This file proves that invariant holds against the live seed data.

Seed facts being tested:
  - 7 BLEs across 5 Funds
  - 6 unique counterparty_ids (DBS Bank Ltd shared by Fund 2 BLE 2 + Fund 3 BLE 1)
  - screen_counterparty() must be called 6 times, not 7
"""
import sys
import os

import pytest

# Ensure scripts/ is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scripts.seed_data as sd
from scripts.seed_data import _DBS_CPTY_ID


# ---------------------------------------------------------------------------
# Shared fixture: replace screen_counterparty with a call-counting stub
# ---------------------------------------------------------------------------

@pytest.fixture()
def patched_screener(monkeypatch):
    """
    Replaces scripts.seed_data.screen_counterparty with a stub that:
    - records every (counterparty_name) it is called with
    - returns a clean result (no real API call)
    """
    calls: list[str] = []

    def _stub(name: str) -> dict:
        calls.append(name)
        return {
            "result_status": "clean",
            "hit_severity": "none",
            "hit_type": None,
            "raw_result": {"stub": True},
            "is_mock": True,
        }

    monkeypatch.setattr(sd, "screen_counterparty", _stub)
    monkeypatch.setattr(sd, "MOCK", True)  # prevent any real API escape hatch
    return calls


# ---------------------------------------------------------------------------
# Core reuse invariant
# ---------------------------------------------------------------------------

def test_screen_called_once_per_unique_counterparty_id(patched_screener):
    """
    7 BLEs but 6 unique counterparty_ids — screen_counterparty must be
    called exactly 6 times.
    """
    sd.process_live_funds()
    assert len(patched_screener) == 6, (
        f"Expected 6 screening calls (one per unique counterparty_id), "
        f"got {len(patched_screener)}: {patched_screener}"
    )


def test_dbs_bank_screened_exactly_once(patched_screener):
    """
    DBS Bank Ltd appears in Fund 2 BLE 2 (Singapore) and Fund 3 BLE 1
    (Hong Kong) but must be screened only once because both BLEs reference
    the same counterparty_profiles record (_DBS_CPTY_ID).
    """
    sd.process_live_funds()
    dbs_calls = [n for n in patched_screener if "DBS" in n]
    assert len(dbs_calls) == 1, (
        f"DBS Bank Ltd was screened {len(dbs_calls)} time(s); expected exactly 1. "
        f"All calls: {patched_screener}"
    )


def test_all_six_unique_counterparties_screened(patched_screener):
    """
    Every unique counterparty must be screened at least once — reuse must
    not accidentally skip a counterparty that hasn't been seen yet.
    """
    expected = {
        "Bank Rossiya",
        "Deutsche Bank AG",
        "DBS Bank Ltd",
        "Emirates NBD Bank PJSC",
        "ICBC Limited",
        "Standard Chartered Bank",
    }
    sd.process_live_funds()
    actually_screened = set(patched_screener)
    assert actually_screened == expected, (
        f"Screened: {actually_screened}\nExpected: {expected}"
    )


def test_shared_counterparty_id_is_consistent_across_bles():
    """
    Structural sanity: Fund 2 BLE 2 and Fund 3 BLE 1 must reference the
    same _DBS_CPTY_ID — if this breaks, the reuse mechanism itself is broken.
    """
    fund2 = next(f for f in sd.LIVE_FUNDS if f["name"] == "Meridian Strategic Growth Trust")
    fund3 = next(f for f in sd.LIVE_FUNDS if f["name"] == "Aldgate Street Capital Fund")

    dbs_ble_fund2 = next(b for b in fund2["bles"] if b["counterparty_name"] == "DBS Bank Ltd")
    dbs_ble_fund3 = next(b for b in fund3["bles"] if b["counterparty_name"] == "DBS Bank Ltd")

    assert dbs_ble_fund2["counterparty_id"] == dbs_ble_fund3["counterparty_id"] == _DBS_CPTY_ID
