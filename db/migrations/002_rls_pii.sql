-- PRD §18 — PII Access Control and Row-Level Security
-- Runs after 001_initial_schema.sql (docker-entrypoint-initdb.d ordering: 02_*)
--
-- Three roles:
--   admin_role   — full access (compliance officers, DB admins)
--   api_role     — application service account (SELECT on most tables, used by FastAPI)
--   analyst_role — restricted read: cannot see raw UBO names or raw screening JSON
--
-- PII protection:
--   ubo_records      → RLS enabled; analyst_role sees sanitized view only (no ubo_name)
--   screening_results → RLS enabled; analyst_role sees sanitized view (no raw_result JSON)
-- ---------------------------------------------------------------------------

-- ---------------------------------------------------------------------------
-- Roles (idempotent via exception blocks)
-- ---------------------------------------------------------------------------

DO $$ BEGIN
    CREATE ROLE admin_role NOLOGIN;
EXCEPTION WHEN duplicate_object THEN
    RAISE NOTICE 'admin_role already exists, skipping';
END $$;

DO $$ BEGIN
    CREATE ROLE analyst_role NOLOGIN;
EXCEPTION WHEN duplicate_object THEN
    RAISE NOTICE 'analyst_role already exists, skipping';
END $$;

DO $$ BEGIN
    CREATE ROLE api_role LOGIN PASSWORD 'api_dev_secret';
EXCEPTION WHEN duplicate_object THEN
    RAISE NOTICE 'api_role already exists, skipping';
END $$;

-- ---------------------------------------------------------------------------
-- Schema usage
-- ---------------------------------------------------------------------------

GRANT USAGE ON SCHEMA public TO admin_role, analyst_role, api_role;

-- ---------------------------------------------------------------------------
-- admin_role — unrestricted read/write on all tables
-- ---------------------------------------------------------------------------

GRANT ALL ON ALL TABLES IN SCHEMA public TO admin_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO admin_role;

-- ---------------------------------------------------------------------------
-- api_role — full SELECT + INSERT/UPDATE on operational tables
--            (application service account — used by FastAPI)
-- ---------------------------------------------------------------------------

GRANT SELECT, INSERT, UPDATE ON
    funds,
    counterparty_profiles,
    bles,
    ble_products,
    fund_documents,
    ble_documents,
    risk_scores,
    review_triggers,
    workflow_suggestions,
    review_audit_history,
    document_embeddings,
    eval_runs,
    llm_call_log,
    ruleset_config,
    ubo_records,
    screening_results
TO api_role;

GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO api_role;

-- ---------------------------------------------------------------------------
-- analyst_role — read-only; NO access to raw PII tables
-- ---------------------------------------------------------------------------

GRANT SELECT ON
    funds,
    counterparty_profiles,
    bles,
    ble_products,
    fund_documents,
    ble_documents,
    risk_scores,
    review_triggers,
    workflow_suggestions,
    review_audit_history,
    eval_runs,
    ruleset_config
TO analyst_role;

-- Explicitly deny direct access to PII tables
REVOKE ALL ON ubo_records FROM analyst_role;
REVOKE ALL ON screening_results FROM analyst_role;

-- Deny raw embeddings (vectors contain chunked PII text)
REVOKE ALL ON document_embeddings FROM analyst_role;

-- Deny cost/LLM log (contains prompt text which may reference PII)
REVOKE ALL ON llm_call_log FROM analyst_role;

-- ---------------------------------------------------------------------------
-- Row-Level Security on PII tables
-- ---------------------------------------------------------------------------

ALTER TABLE ubo_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE screening_results ENABLE ROW LEVEL SECURITY;

-- admin_role and api_role can see all rows
CREATE POLICY ubo_admin_api ON ubo_records
    TO admin_role, api_role
    USING (true);

CREATE POLICY screening_admin_api ON screening_results
    TO admin_role, api_role
    USING (true);

-- analyst_role has no direct row-level policy (REVOKE above prevents access)
-- Analysts access PII via sanitized views below

-- ---------------------------------------------------------------------------
-- Sanitized views for analyst_role
-- ---------------------------------------------------------------------------

-- UBO view: hides ubo_name (PII) and parent_ubo_id linkage
CREATE OR REPLACE VIEW analyst_ubo_view AS
SELECT
    ubo_id,
    fund_id,
    -- ubo_name intentionally omitted (PII)
    ownership_pct,
    layer_depth,
    jurisdiction,
    resolved,
    pep_tier,
    synthetic_profile,
    created_at
FROM ubo_records;

-- Screening view: hides screened_name and raw_result JSON
CREATE OR REPLACE VIEW analyst_screening_view AS
SELECT
    screening_id,
    scope,
    scope_id,
    -- screened_name intentionally omitted (PII)
    result_status,
    hit_severity,
    hit_type,
    -- raw_result intentionally omitted (may contain PII from OpenSanctions payload)
    screened_at,
    opensanctions_dataset,
    is_mock
FROM screening_results;

GRANT SELECT ON analyst_ubo_view TO analyst_role;
GRANT SELECT ON analyst_screening_view TO analyst_role;

-- ---------------------------------------------------------------------------
-- Document embeddings: analysts use a chunk-text-redacted view
-- (chunk_text may contain document excerpts with PII)
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW analyst_embeddings_view AS
SELECT
    embedding_id,
    scope,
    scope_id,
    document_id,
    chunk_index,
    -- chunk_text intentionally omitted
    -- embedding vector intentionally omitted
    created_at
FROM document_embeddings;

GRANT SELECT ON analyst_embeddings_view TO analyst_role;
