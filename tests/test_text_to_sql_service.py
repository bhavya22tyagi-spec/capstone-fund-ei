"""
Tests for TextToSQLService — unit tests and full adversarial suite.

All tests run with MOCK=true (the default), so no LLM call or DB connection
is required. The validation layer runs identically in MOCK and real modes —
the adversarial tests therefore confirm real-mode blocking as well.
"""

from __future__ import annotations

import os
import pytest

os.environ.setdefault("MOCK", "true")

from services.text_to_sql.service import (
    TextToSQLService,
    ValidationResult,
    _extract_cte_names,
    _extract_table_names,
    _get_first_keyword,
    _strip_comments,
)
from services.budget import BudgetCap
from services.guards import StaticFundAIError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def svc() -> TextToSQLService:
    return TextToSQLService()


@pytest.fixture()
def budget() -> BudgetCap:
    return BudgetCap(limit_usd=5.0)


FUND_ID = "f0000001-f000-0000-0000-000000000001"


# ---------------------------------------------------------------------------
# Helper assertions
# ---------------------------------------------------------------------------

def assert_blocked(vr: ValidationResult, reason: str) -> None:
    assert not vr.passed, f"Expected blocked ({reason}) but passed: {vr.error}"
    assert vr.blocked_reason == reason, (
        f"Wrong blocked_reason: expected {reason!r}, got {vr.blocked_reason!r}"
    )


def assert_valid(vr: ValidationResult) -> None:
    assert vr.passed, f"Expected valid but blocked: {vr.error}"
    assert vr.blocked_reason is None


# ===========================================================================
# Section 1 — _strip_comments
# ===========================================================================

def test_strip_line_comment():
    result = _strip_comments("SELECT 1 -- dangerous stuff DROP TABLE x")
    assert "DROP" not in result
    assert "SELECT" in result


def test_strip_block_comment():
    result = _strip_comments("SELECT /* DROP TABLE funds */ 1")
    assert "DROP" not in result


def test_strip_multiline_block_comment():
    result = _strip_comments("SELECT *\n/* DROP TABLE funds\n   DELETE FROM bles */\nFROM funds")
    assert "DROP" not in result
    assert "funds" in result


# ===========================================================================
# Section 2 — _get_first_keyword
# ===========================================================================

def test_first_keyword_select():
    assert _get_first_keyword("SELECT * FROM funds") == "SELECT"


def test_first_keyword_with():
    assert _get_first_keyword("WITH cte AS (SELECT 1) SELECT * FROM cte") == "WITH"


def test_first_keyword_drop_uppercase():
    assert _get_first_keyword("DROP TABLE funds") == "DROP"


def test_first_keyword_drop_mixed_case():
    assert _get_first_keyword("DrOp TaBlE funds") == "DROP"


def test_first_keyword_leading_whitespace():
    assert _get_first_keyword("   \n  SELECT 1") == "SELECT"


# ===========================================================================
# Section 3 — _extract_table_names and _extract_cte_names
# ===========================================================================

def test_extract_table_names_simple():
    tables = _extract_table_names("SELECT * FROM funds")
    assert "funds" in tables


def test_extract_table_names_join():
    tables = _extract_table_names(
        "SELECT f.name FROM funds f JOIN bles b ON b.parent_fund_id = f.fund_id"
    )
    assert "funds" in tables
    assert "bles" in tables


def test_extract_table_names_case_insensitive():
    tables = _extract_table_names("SELECT * FROM FUNDS")
    assert "funds" in tables


def test_extract_cte_names():
    sql = "WITH critical_bles AS (SELECT * FROM bles) SELECT * FROM critical_bles"
    ctes = _extract_cte_names(sql)
    assert "critical_bles" in ctes


# ===========================================================================
# Section 4 — validate_sql: valid queries
# ===========================================================================

def test_valid_simple_select(svc):
    assert_valid(svc.validate_sql("SELECT name FROM funds"))


def test_valid_join(svc):
    assert_valid(svc.validate_sql(
        "SELECT f.name, b.location FROM funds f "
        "JOIN bles b ON b.parent_fund_id = f.fund_id"
    ))


def test_valid_three_table_join(svc):
    assert_valid(svc.validate_sql(
        "SELECT f.name, cp.institution_name, bp.product_type "
        "FROM funds f "
        "JOIN bles b ON b.parent_fund_id = f.fund_id "
        "JOIN counterparty_profiles cp ON cp.counterparty_id = b.counterparty_profile_id "
        "JOIN ble_products bp ON bp.ble_id = b.ble_id"
    ))


def test_valid_cte(svc):
    assert_valid(svc.validate_sql(
        "WITH crit AS (SELECT scope_id FROM risk_scores WHERE COALESCE(escalated_tier, direct_tier) = 'critical') "
        "SELECT f.name FROM funds f JOIN crit c ON c.scope_id = f.fund_id"
    ))


def test_valid_trailing_semicolon(svc):
    assert_valid(svc.validate_sql("SELECT COUNT(*) FROM funds;"))


def test_valid_coalesce_effective_tier(svc):
    assert_valid(svc.validate_sql(
        "SELECT f.name, COALESCE(rs.escalated_tier, rs.direct_tier) AS effective_tier "
        "FROM funds f JOIN risk_scores rs ON rs.scope_id = f.fund_id "
        "WHERE rs.scope = 'fund'"
    ))


def test_valid_aggregate(svc):
    assert_valid(svc.validate_sql(
        "SELECT COUNT(*) FROM ubo_records WHERE pep_tier >= 1"
    ))


def test_valid_all_allowed_tables(svc):
    tables = [
        "funds", "bles", "ble_products", "counterparty_profiles",
        "fund_documents", "ble_documents", "ubo_records",
        "screening_results", "risk_scores", "review_triggers",
        "workflow_suggestions", "review_audit_history", "ruleset_config",
    ]
    for t in tables:
        assert_valid(svc.validate_sql(f"SELECT * FROM {t} LIMIT 1"))


# ===========================================================================
# Section 5 — Adversarial: DDL attacks
# ===========================================================================

def test_adv_drop_table(svc):
    assert_blocked(svc.validate_sql("DROP TABLE funds"), "forbidden_statement_type")


def test_adv_create_table(svc):
    assert_blocked(svc.validate_sql("CREATE TABLE evil (id INT)"), "forbidden_statement_type")


def test_adv_alter_table(svc):
    assert_blocked(svc.validate_sql("ALTER TABLE funds ADD COLUMN backdoor TEXT"), "forbidden_statement_type")


def test_adv_truncate(svc):
    assert_blocked(svc.validate_sql("TRUNCATE TABLE risk_scores"), "forbidden_statement_type")


def test_adv_mixed_case_drop(svc):
    assert_blocked(svc.validate_sql("DrOp TaBlE funds"), "forbidden_statement_type")


# ===========================================================================
# Section 6 — Adversarial: DML attacks
# ===========================================================================

def test_adv_delete(svc):
    assert_blocked(svc.validate_sql("DELETE FROM funds WHERE 1=1"), "forbidden_statement_type")


def test_adv_insert(svc):
    assert_blocked(svc.validate_sql("INSERT INTO funds(name) VALUES('hacked')"), "forbidden_statement_type")


def test_adv_update(svc):
    assert_blocked(svc.validate_sql("UPDATE funds SET name = 'pwned'"), "forbidden_statement_type")


def test_adv_merge(svc):
    assert_blocked(svc.validate_sql("MERGE INTO funds USING (SELECT 1) s ON true WHEN MATCHED THEN DELETE"), "forbidden_statement_type")


# ===========================================================================
# Section 7 — Adversarial: Statement stacking
# ===========================================================================

def test_adv_semicolon_stacking(svc):
    assert_blocked(svc.validate_sql("SELECT * FROM funds; DROP TABLE funds"), "statement_stacking")


def test_adv_comment_obfuscated_stacking(svc):
    assert_blocked(svc.validate_sql("SELECT * FROM funds /* legit */ ; DROP TABLE funds"), "statement_stacking")


def test_adv_newline_stacking(svc):
    assert_blocked(svc.validate_sql("SELECT * FROM funds\n;\nDELETE FROM bles"), "statement_stacking")


# ===========================================================================
# Section 8 — Adversarial: System schema / catalog
# ===========================================================================

def test_adv_information_schema(svc):
    assert_blocked(
        svc.validate_sql("SELECT table_name FROM information_schema.tables"),
        "blocklist_match",
    )


def test_adv_pg_catalog(svc):
    assert_blocked(
        svc.validate_sql("SELECT relname FROM pg_catalog.pg_class"),
        "blocklist_match",
    )


def test_adv_union_into_information_schema(svc):
    assert_blocked(
        svc.validate_sql(
            "SELECT name FROM funds UNION SELECT table_name FROM information_schema.tables"
        ),
        "blocklist_match",
    )


def test_adv_pg_tables(svc):
    assert_blocked(
        svc.validate_sql("SELECT tablename FROM pg_tables"),
        "blocklist_match",
    )


# ===========================================================================
# Section 9 — Adversarial: Dangerous functions
# ===========================================================================

def test_adv_pg_read_file(svc):
    assert_blocked(
        svc.validate_sql("SELECT pg_read_file('/etc/passwd')"),
        "blocklist_match",
    )


def test_adv_lo_import(svc):
    assert_blocked(
        svc.validate_sql("SELECT lo_import('/etc/shadow')"),
        "blocklist_match",
    )


def test_adv_copy_statement(svc):
    assert_blocked(
        svc.validate_sql("COPY funds TO '/tmp/dump.csv' WITH CSV HEADER"),
        "forbidden_statement_type",
    )


def test_adv_do_block(svc):
    assert_blocked(
        svc.validate_sql("DO $$ BEGIN EXECUTE 'DROP TABLE funds'; END $$"),
        "forbidden_statement_type",
    )


def test_adv_grant(svc):
    assert_blocked(
        svc.validate_sql("GRANT ALL ON funds TO attacker"),
        "forbidden_statement_type",
    )


# ===========================================================================
# Section 10 — Adversarial: Non-allowlisted tables
# ===========================================================================

def test_adv_llm_call_log_blocked(svc):
    assert_blocked(
        svc.validate_sql("SELECT * FROM llm_call_log"),
        "table_not_allowed",
    )


def test_adv_document_embeddings_blocked(svc):
    assert_blocked(
        svc.validate_sql("SELECT chunk_text, embedding FROM document_embeddings"),
        "table_not_allowed",
    )


def test_adv_eval_runs_blocked(svc):
    assert_blocked(
        svc.validate_sql("SELECT * FROM eval_runs"),
        "table_not_allowed",
    )


def test_adv_nonexistent_table_blocked(svc):
    assert_blocked(
        svc.validate_sql("SELECT * FROM totally_made_up_table"),
        "table_not_allowed",
    )


# ===========================================================================
# Section 11 — Empty / degenerate inputs
# ===========================================================================

def test_empty_string_blocked(svc):
    vr = svc.validate_sql("")
    assert not vr.passed
    assert vr.blocked_reason == "empty_query"


def test_whitespace_only_blocked(svc):
    vr = svc.validate_sql("   \n  \t  ")
    assert not vr.passed
    assert vr.blocked_reason == "empty_query"


# ===========================================================================
# Section 12 — service.query() MOCK mode behaviour
# ===========================================================================

def test_query_mock_returns_result(svc, budget):
    result = svc.query(
        question="How many funds are there?",
        fund_id=FUND_ID,
        synthetic_static=False,
        scope="fund",
        scope_id=FUND_ID,
        budget=budget,
    )
    assert result.is_mock is True
    assert result.validation.passed is True
    assert result.sql_result is None  # execution skipped in MOCK


def test_query_mock_sql_passes_validation(svc, budget):
    result = svc.query(
        question="List all funds",
        fund_id=FUND_ID,
        synthetic_static=False,
        scope="fund",
        scope_id=FUND_ID,
        budget=budget,
    )
    # The canned MOCK SQL must itself be valid
    assert result.validation.passed is True


def test_query_empty_question_raises(svc, budget):
    with pytest.raises(ValueError, match="question must not be empty"):
        svc.query(
            question="",
            fund_id=FUND_ID,
            synthetic_static=False,
            scope="fund",
            scope_id=FUND_ID,
            budget=budget,
        )


def test_query_bad_scope_raises(svc, budget):
    with pytest.raises(ValueError, match="scope must be"):
        svc.query(
            question="What is the risk?",
            fund_id=FUND_ID,
            synthetic_static=False,
            scope="both",
            scope_id=FUND_ID,
            budget=budget,
        )


def test_query_static_fund_blocked(svc, budget):
    with pytest.raises(StaticFundAIError):
        svc.query(
            question="How many funds?",
            fund_id="static-fund-001",
            synthetic_static=True,
            scope="fund",
            scope_id="static-fund-001",
            budget=budget,
        )


def test_query_result_has_required_fields(svc, budget):
    result = svc.query(
        question="Show all BLEs",
        fund_id=FUND_ID,
        synthetic_static=False,
        scope="fund",
        scope_id=FUND_ID,
        budget=budget,
    )
    assert result.question == "Show all BLEs"
    assert result.generated_sql != ""
    assert result.model != ""
    assert result.prompt_version != ""
    assert result.run_at != ""
