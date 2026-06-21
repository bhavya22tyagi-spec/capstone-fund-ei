"""
PRD §8.2, §18 — Text-to-SQL Service.

SECURITY INVARIANTS (enforced in code, not convention):
  1. Only SELECT/WITH-SELECT statements. First keyword must be SELECT or WITH.
  2. No semicolons mid-query — prevents statement stacking.
  3. Blocklist of DDL/DML/dangerous functions/system schemas — raises ValidationError.
  4. Table allowlist — only approved compliance tables may appear in FROM/JOIN clauses.
  5. Every real execution runs inside SET TRANSACTION READ ONLY (DB-level belt-and-suspenders).
  6. Statement timeout hardcoded to 5 s — prevents runaway queries.
  7. Every LLM generation call is logged via services.cost_logger (PRD §17).

MOCK=true (default): canned SQL returned; DB execution skipped; validation always runs.
MOCK=false: claude-sonnet-4-6 generates SQL; validation gates execution; psycopg2 executes.

The static_fund guard (CLAUDE.md rule 10) applies to the LLM generation step.
Validation is stateless and has no fund-level guard — it is safe to call on any SQL string.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from services.ai_client import call_llm
from services.budget import BudgetCap
from services.guards import assert_fund_allows_ai

MOCK: bool = os.getenv("MOCK", "true").lower() == "true"

_MODEL = "claude-haiku-4-5-20251001"
_PROMPT_VERSION = "text_to_sql-v1"
_STATEMENT_TIMEOUT_S = 5

# Canned SQL returned in MOCK mode — passes all validation checks.
_MOCK_SQL = "SELECT name FROM funds LIMIT 0"

# ---------------------------------------------------------------------------
# Table allowlist — the ONLY tables a generated query may reference.
# Internal-audit / embedding tables are deliberately excluded.
# ---------------------------------------------------------------------------
_ALLOWED_TABLES: frozenset[str] = frozenset({
    "funds",
    "bles",
    "ble_products",
    "counterparty_profiles",
    "fund_documents",
    "ble_documents",
    "ubo_records",
    "screening_results",
    "risk_scores",
    "review_triggers",
    "workflow_suggestions",
    "review_audit_history",
    "ruleset_config",
})

# ---------------------------------------------------------------------------
# Blocklist: (regex_pattern, human_readable_error)
# Checked on comment-stripped SQL, case-insensitive.
# ---------------------------------------------------------------------------
_BLOCKLIST: list[tuple[str, str]] = [
    # DDL
    (r"\bDROP\b",              "DDL not permitted: DROP"),
    (r"\bCREATE\b",            "DDL not permitted: CREATE"),
    (r"\bALTER\b",             "DDL not permitted: ALTER"),
    (r"\bTRUNCATE\b",          "DDL not permitted: TRUNCATE"),
    # DML
    (r"\bINSERT\b",            "DML not permitted: INSERT"),
    (r"\bUPDATE\b",            "DML not permitted: UPDATE"),
    (r"\bDELETE\b",            "DML not permitted: DELETE"),
    (r"\bMERGE\b",             "DML not permitted: MERGE"),
    # Admin / control
    (r"\bCOPY\b",              "COPY not permitted"),
    (r"\bGRANT\b",             "GRANT not permitted"),
    (r"\bREVOKE\b",            "REVOKE not permitted"),
    (r"\bEXECUTE\b",           "EXECUTE not permitted"),
    (r"\bDO\b",                "DO block not permitted"),
    (r"\bSET\b",               "SET not permitted"),
    # Dangerous built-in functions
    (r"\bpg_read_file\b",      "System function not permitted: pg_read_file"),
    (r"\bpg_ls_dir\b",         "System function not permitted: pg_ls_dir"),
    (r"\bpg_stat_file\b",      "System function not permitted: pg_stat_file"),
    (r"\blo_import\b",         "System function not permitted: lo_import"),
    (r"\blo_export\b",         "System function not permitted: lo_export"),
    (r"\bpg_sleep\b",          "System function not permitted: pg_sleep"),
    # System schema / catalog access
    (r"\binformation_schema\b", "System schema not permitted: information_schema"),
    (r"\bpg_catalog\b",         "System catalog not permitted: pg_catalog"),
    (r"\bpg_class\b",           "System table not permitted: pg_class"),
    (r"\bpg_tables\b",          "System table not permitted: pg_tables"),
    (r"\bpg_user\b",            "System table not permitted: pg_user"),
    (r"\bpg_shadow\b",          "System table not permitted: pg_shadow"),
]

# ---------------------------------------------------------------------------
# Schema context injected into the generation prompt
# ---------------------------------------------------------------------------
_SCHEMA_CONTEXT = """\
Available tables (read-only, SELECT only):

  funds(fund_id UUID, name TEXT, incorporation_country CHAR(3),
        synthetic_profile BOOL, synthetic_static BOOL, created_at TIMESTAMPTZ)

  bles(ble_id UUID, parent_fund_id UUID, counterparty_profile_id UUID,
       location TEXT, synthetic_profile BOOL, created_at TIMESTAMPTZ)

  ble_products(product_id UUID, ble_id UUID, product_type TEXT,
               workflow_template_id TEXT, status TEXT, created_at TIMESTAMPTZ)

  counterparty_profiles(counterparty_id UUID, institution_name TEXT,
                        country CHAR(3), last_screened_at TIMESTAMPTZ,
                        screening_status TEXT, synthetic_profile BOOL)

  fund_documents(document_id UUID, fund_id UUID, document_type TEXT,
                 filename TEXT, status TEXT, expiry_date DATE,
                 extraction_status TEXT, embedding_status TEXT)

  ble_documents(document_id UUID, ble_id UUID, document_type TEXT,
                filename TEXT, status TEXT, expiry_date DATE,
                extraction_status TEXT, embedding_status TEXT)

  ubo_records(ubo_id UUID, fund_id UUID, ubo_name TEXT, ownership_pct NUMERIC,
              layer_depth INT, jurisdiction CHAR(3), parent_ubo_id UUID,
              resolved BOOL, pep_tier SMALLINT)

  screening_results(screening_id UUID, scope TEXT, scope_id UUID,
                    screened_name TEXT, result_status TEXT, hit_severity TEXT,
                    hit_type TEXT, screened_at TIMESTAMPTZ, is_mock BOOL)

  risk_scores(score_id UUID, scope TEXT, scope_id UUID, ruleset_version TEXT,
              direct_score NUMERIC, direct_tier TEXT, escalated_tier TEXT,
              escalation_reason TEXT, hard_stop BOOL, factor_scores JSONB,
              computed_at TIMESTAMPTZ)

  review_triggers(trigger_id UUID, scope TEXT, fund_id UUID, ble_id UUID,
                  trigger_type TEXT, trigger_detail JSONB, fired_at TIMESTAMPTZ,
                  processed BOOL)

  workflow_suggestions(suggestion_id UUID, scope TEXT, scope_id UUID,
                       trigger_type TEXT, status TEXT, ai_narrative TEXT,
                       created_at TIMESTAMPTZ, resolved_at TIMESTAMPTZ)

  review_audit_history(audit_id UUID, scope TEXT, scope_id UUID,
                       action TEXT, actor TEXT, notes TEXT, performed_at TIMESTAMPTZ)

  ruleset_config(ruleset_id UUID, version TEXT, scope_level TEXT,
                 weight_country NUMERIC, weight_screening NUMERIC,
                 weight_pep NUMERIC, weight_ubo NUMERIC, weight_documents NUMERIC,
                 is_active BOOL)

Key joins:
  bles.parent_fund_id          -> funds.fund_id
  bles.counterparty_profile_id -> counterparty_profiles.counterparty_id
  ble_products.ble_id          -> bles.ble_id
  fund_documents.fund_id       -> funds.fund_id
  ble_documents.ble_id         -> bles.ble_id
  ubo_records.fund_id          -> funds.fund_id
  risk_scores: scope='fund'          -> scope_id = fund_id
  risk_scores: scope='ble'           -> scope_id = ble_id
  screening_results: scope='counterparty' -> scope_id = counterparty_id

Effective risk tier formula: COALESCE(escalated_tier, direct_tier) from risk_scores
"""


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    passed: bool
    error: str | None
    # Category: forbidden_statement_type | statement_stacking |
    #           blocklist_match | table_not_allowed | empty_query
    blocked_reason: str | None


@dataclass
class SQLResult:
    rows: list[dict[str, Any]]
    row_count: int
    column_names: list[str]
    latency_ms: int


@dataclass
class TextToSQLResult:
    question: str
    generated_sql: str
    validation: ValidationResult
    sql_result: "SQLResult | None"
    is_mock: bool
    model: str
    prompt_version: str
    run_at: str


# ---------------------------------------------------------------------------
# Public service
# ---------------------------------------------------------------------------

class TextToSQLService:
    """
    Natural-language → SQL service.

    All SQL passes through validate_sql() before execution. validate_sql() is
    exposed publicly so adversarial test suites can probe it directly without
    touching the LLM generation path.
    """

    def query(
        self,
        question: str,
        fund_id: str,
        synthetic_static: bool,
        scope: str,
        scope_id: str,
        budget: "BudgetCap | None" = None,
    ) -> TextToSQLResult:
        """
        Translate a natural-language question into SQL and execute it.

        Args:
            question:         The analyst's natural-language question.
            fund_id:          Fund ID for the static-fund guard + cost logging.
            synthetic_static: True → LLM generation is blocked before it starts.
            scope:            'fund' or 'ble' (for cost log).
            scope_id:         Scope entity ID (for cost log).
            budget:           Per-run BudgetCap; $1.00 default if None.

        Returns:
            TextToSQLResult with generated_sql, validation, and sql_result.
            sql_result is None when MOCK=true or when validation fails.

        Raises:
            ValueError:        empty question, or bad scope value.
            StaticFundAIError: fund is tagged synthetic_static.
            BudgetExceededError: cost would breach cap.
        """
        if not question or not question.strip():
            raise ValueError("question must not be empty")
        if scope not in ("fund", "ble"):
            raise ValueError(f"scope must be 'fund' or 'ble', got {scope!r}")

        _budget = budget if budget is not None else BudgetCap(limit_usd=1.00)

        sql, is_mock = self._generate_sql(
            question=question,
            fund_id=fund_id,
            synthetic_static=synthetic_static,
            scope=scope,
            scope_id=scope_id,
            budget=_budget,
        )

        validation = self.validate_sql(sql)

        sql_result: SQLResult | None = None
        if validation.passed and not is_mock:
            sql_result = _execute_sql(sql)

        return TextToSQLResult(
            question=question,
            generated_sql=sql,
            validation=validation,
            sql_result=sql_result,
            is_mock=is_mock,
            model=_MODEL,
            prompt_version=_PROMPT_VERSION,
            run_at=datetime.now(timezone.utc).isoformat(),
        )

    # ------------------------------------------------------------------
    # Public validation — exposed so adversarial tests can probe directly
    # ------------------------------------------------------------------

    def validate_sql(self, sql: str) -> ValidationResult:
        """
        Run all security checks on a SQL string.

        Checks (in order):
          1. Empty query
          2. Strip comments, then detect statement stacking (semicolons)
          3. First keyword must be SELECT or WITH
          4. Blocklist scan (DDL/DML/dangerous functions/system schemas)
          5. Table allowlist (FROM/JOIN references must be in _ALLOWED_TABLES)

        Returns ValidationResult; never raises.
        """
        if not sql or not sql.strip():
            return ValidationResult(
                passed=False,
                error="Empty query",
                blocked_reason="empty_query",
            )

        # Step 1: Strip comments for analysis
        clean = _strip_comments(sql)

        # Step 2: First keyword must be SELECT or WITH.
        # Checked before the semicolon scan so that DO/DROP/etc. get a clear
        # "forbidden statement type" reason rather than a confusing stacking error
        # (e.g. DO $$ ... ; ... $$ contains a semicolon but the real problem is DO).
        first = _get_first_keyword(clean)
        if first not in ("SELECT", "WITH"):
            return ValidationResult(
                passed=False,
                error=(
                    f"Only SELECT statements are permitted; "
                    f"got first keyword {first!r}"
                ),
                blocked_reason="forbidden_statement_type",
            )

        # Step 3: Statement stacking — any semicolon that is not the sole trailing
        # character is treated as a stacking attempt.
        without_trailing_semi = clean.rstrip().rstrip(";")
        if ";" in without_trailing_semi:
            return ValidationResult(
                passed=False,
                error="Multiple statements detected (semicolon in query body)",
                blocked_reason="statement_stacking",
            )

        # Step 4: Blocklist scan
        for pattern, reason in _BLOCKLIST:
            if re.search(pattern, clean, re.IGNORECASE):
                return ValidationResult(
                    passed=False,
                    error=reason,
                    blocked_reason="blocklist_match",
                )

        # Step 5: Table allowlist
        referenced = _extract_table_names(clean)
        cte_names = _extract_cte_names(clean)
        disallowed = referenced - _ALLOWED_TABLES - cte_names
        if disallowed:
            return ValidationResult(
                passed=False,
                error=(
                    f"Query references table(s) not in the allowlist: "
                    f"{sorted(disallowed)}"
                ),
                blocked_reason="table_not_allowed",
            )

        return ValidationResult(passed=True, error=None, blocked_reason=None)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _generate_sql(
        self,
        question: str,
        fund_id: str,
        synthetic_static: bool,
        scope: str,
        scope_id: str,
        budget: "BudgetCap",
    ) -> tuple[str, bool]:
        """Return (sql_string, is_mock)."""
        assert_fund_allows_ai(fund_id, synthetic_static)

        if MOCK:
            from services.cost_logger import log_llm_call  # noqa: PLC0415
            log_llm_call(
                model=_MODEL,
                prompt_version=_PROMPT_VERSION,
                scope=scope,
                scope_id=scope_id,
                tokens=0,
                cost_usd=0.0,
                latency_ms=0,
                is_mock=True,
            )
            budget.record(0.0)
            return _MOCK_SQL, True

        prompt = _build_prompt(question)
        raw = call_llm(
            prompt=prompt,
            model=_MODEL,
            prompt_version=_PROMPT_VERSION,
            fund_id=fund_id,
            synthetic_static=synthetic_static,
            scope=scope,
            scope_id=scope_id,
            budget=budget,
            estimated_cost_usd=0.01,
        )
        generated = raw["content"].strip()
        # Strip markdown code fences if the LLM wrapped the SQL
        generated = re.sub(r"^```[a-z]*\s*", "", generated, flags=re.IGNORECASE)
        generated = re.sub(r"\s*```\s*$", "", generated)
        return generated.strip(), False


# ---------------------------------------------------------------------------
# Module-level helpers (not part of the class)
# ---------------------------------------------------------------------------

def _strip_comments(sql: str) -> str:
    """Remove SQL block comments (/* */) and line comments (--...)."""
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    sql = re.sub(r"--[^\n]*", " ", sql)
    return sql


def _get_first_keyword(clean: str) -> str:
    """Return the uppercased first word of the stripped, comment-free SQL."""
    m = re.match(r"\s*(\w+)", clean)
    return m.group(1).upper() if m else ""


def _extract_table_names(clean: str) -> set[str]:
    """
    Extract lowercased identifiers that appear immediately after FROM or JOIN.
    Does not handle quoted identifiers (not used in this schema).
    """
    pattern = r"\b(?:FROM|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_]*)"
    return {m.group(1).lower() for m in re.finditer(pattern, clean, re.IGNORECASE)}


def _extract_cte_names(clean: str) -> set[str]:
    """Extract CTE alias names defined by WITH name AS (...)."""
    pattern = r"\bWITH\b.*?\b([a-zA-Z_][a-zA-Z0-9_]*)\s+AS\s*\("
    return {m.group(1).lower() for m in re.finditer(pattern, clean, re.IGNORECASE | re.DOTALL)}


def _build_prompt(question: str) -> str:
    return (
        "You are a read-only PostgreSQL SQL generator for a KYB compliance platform.\n"
        "Generate a single SELECT query that answers the question below.\n\n"
        "Rules (strictly enforced by a post-generation validator):\n"
        "  - Only SELECT statements. No DDL, DML, COPY, GRANT, EXECUTE, DO, or SET.\n"
        "  - No semicolons except optionally at the very end.\n"
        "  - Only use tables listed in the schema. No system tables or pg_catalog.\n"
        "  - Return ONLY the SQL — no explanation, no markdown, no code fences.\n\n"
        f"Schema:\n{_SCHEMA_CONTEXT}\n\n"
        f"Question: {question}\n\n"
        "SQL:"
    )


def _execute_sql(sql: str) -> SQLResult:
    """
    Execute a pre-validated SELECT query against the read-only DB connection.

    Connection is obtained from DATABASE_URL env var.
    Transaction is immediately set READ ONLY before execution (belt-and-suspenders).
    Statement timeout is hard-capped at _STATEMENT_TIMEOUT_S seconds.
    """
    try:
        import psycopg2                    # noqa: PLC0415
        import psycopg2.extras             # noqa: PLC0415
    except ImportError:
        raise RuntimeError(
            "psycopg2 not installed. Run: uv pip install psycopg2-binary"
        ) from None

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError(
            "DATABASE_URL environment variable not set — required for real SQL execution"
        )

    t0 = time.monotonic()
    with psycopg2.connect(db_url) as conn:
        conn.set_session(readonly=True, autocommit=False)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(f"SET statement_timeout = '{_STATEMENT_TIMEOUT_S * 1000}'")
            cur.execute(sql)
            raw_rows = cur.fetchall()
            col_names = [desc[0] for desc in cur.description] if cur.description else []

    rows = [dict(r) for r in raw_rows]
    return SQLResult(
        rows=rows,
        row_count=len(rows),
        column_names=col_names,
        latency_ms=int((time.monotonic() - t0) * 1000),
    )
