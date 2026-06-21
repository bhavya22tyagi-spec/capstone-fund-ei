"""
Tests for PRD §17 idempotency checks — no AI job may run twice for the same
(scope, scope_id, stage, version) tuple.
"""
import pytest

import services.idempotency as idm


@pytest.fixture(autouse=True)
def _clear():
    """Reset in-memory store before every test."""
    idm.reset()
    yield
    idm.reset()


def test_not_processed_initially():
    assert idm.is_already_processed("fund", "f-001", "extracted", "v1") is False


def test_mark_then_check_returns_true():
    idm.mark_processed("fund", "f-001", "extracted", "v1")
    assert idm.is_already_processed("fund", "f-001", "extracted", "v1") is True


def test_different_version_is_independent():
    idm.mark_processed("fund", "f-001", "extracted", "v1")
    assert idm.is_already_processed("fund", "f-001", "extracted", "v2") is False


def test_different_scope_is_independent():
    idm.mark_processed("fund", "f-001", "extracted", "v1")
    assert idm.is_already_processed("ble", "f-001", "extracted", "v1") is False


def test_different_scope_id_is_independent():
    idm.mark_processed("fund", "f-001", "extracted", "v1")
    assert idm.is_already_processed("fund", "f-002", "extracted", "v1") is False


def test_different_stage_is_independent():
    idm.mark_processed("fund", "f-001", "extracted", "v1")
    assert idm.is_already_processed("fund", "f-001", "embedded", "v1") is False


def test_reset_clears_all_entries():
    idm.mark_processed("fund", "f-001", "extracted", "v1")
    idm.mark_processed("ble",  "b-001", "embedded",  "v1")
    idm.reset()
    assert idm.is_already_processed("fund", "f-001", "extracted", "v1") is False
    assert idm.is_already_processed("ble",  "b-001", "embedded",  "v1") is False


def test_marking_twice_is_idempotent():
    idm.mark_processed("fund", "f-001", "extracted", "v1")
    idm.mark_processed("fund", "f-001", "extracted", "v1")  # must not raise
    assert idm.is_already_processed("fund", "f-001", "extracted", "v1") is True


def test_ble_scope_works_independently():
    idm.mark_processed("ble", "b-001", "summarized", "v2")
    assert idm.is_already_processed("ble", "b-001", "summarized", "v2") is True
    assert idm.is_already_processed("ble", "b-001", "summarized", "v1") is False


def test_multiple_funds_tracked_independently():
    idm.mark_processed("fund", "f-001", "extracted", "v1")
    idm.mark_processed("fund", "f-002", "extracted", "v1")
    assert idm.is_already_processed("fund", "f-001", "extracted", "v1") is True
    assert idm.is_already_processed("fund", "f-002", "extracted", "v1") is True
    assert idm.is_already_processed("fund", "f-003", "extracted", "v1") is False
