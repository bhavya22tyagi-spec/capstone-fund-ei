-- PRD Section 8.3 — PostgreSQL + pgvector schema
-- Fund -> BLE -> Product hierarchy with scope-aware risk scores, screening, and embeddings.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ---------------------------------------------------------------------------
-- Ruleset configuration (versioned weights for Fund and BLE scoring levels)
-- ---------------------------------------------------------------------------
CREATE TABLE ruleset_config (
    ruleset_id      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    version         VARCHAR(20) NOT NULL UNIQUE,
    -- 'fund', 'ble', or 'both' (both = same weights applied to each level)
    scope_level     VARCHAR(10) NOT NULL CHECK (scope_level IN ('fund', 'ble', 'both')),
    weight_country  NUMERIC(6,4) NOT NULL,
    weight_screening NUMERIC(6,4) NOT NULL,
    weight_pep      NUMERIC(6,4) NOT NULL,
    -- UBO weight applies at Fund level only; set to 0 for BLE-level configs
    weight_ubo      NUMERIC(6,4) NOT NULL DEFAULT 0,
    weight_documents NUMERIC(6,4) NOT NULL,
    is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Funds (top-level entities — PRD §5, §7.2)
-- ---------------------------------------------------------------------------
CREATE TABLE funds (
    fund_id                 UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    name                    VARCHAR(255) NOT NULL,
    incorporation_country   VARCHAR(3),   -- ISO 3166-1 alpha-3
    -- synthetic_profile: always true in demo; visibly surfaced in UI (PRD §7.4)
    synthetic_profile       BOOLEAN     NOT NULL DEFAULT TRUE,
    -- synthetic_static: true for the 45 dashboard-scale Funds; physically
    -- prevents LLM/embedding calls (enforced in code, not convention — PRD §17)
    synthetic_static        BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Counterparty profiles (shared across BLEs — screened once, PRD §5, §17)
-- ---------------------------------------------------------------------------
CREATE TABLE counterparty_profiles (
    counterparty_id     UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    institution_name    VARCHAR(255) NOT NULL,
    country             VARCHAR(3),   -- ISO 3166-1 alpha-3
    last_screened_at    TIMESTAMPTZ,
    screening_status    VARCHAR(20)  CHECK (screening_status IN ('clean', 'hit', 'pending', 'error')),
    synthetic_profile   BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- BLEs (counterparty + location, child of Fund — PRD §5, §8.3)
-- ---------------------------------------------------------------------------
CREATE TABLE bles (
    ble_id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_fund_id          UUID        NOT NULL REFERENCES funds(fund_id) ON DELETE CASCADE,
    counterparty_profile_id UUID        NOT NULL REFERENCES counterparty_profiles(counterparty_id),
    location                VARCHAR(255) NOT NULL,
    synthetic_profile       BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- The same counterparty at the same location under the same Fund is one BLE
    UNIQUE (parent_fund_id, counterparty_profile_id, location)
);

-- ---------------------------------------------------------------------------
-- BLE Products (PRD §5, §8.3)
-- ---------------------------------------------------------------------------
CREATE TABLE ble_products (
    product_id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    ble_id              UUID        NOT NULL REFERENCES bles(ble_id) ON DELETE CASCADE,
    product_type        VARCHAR(100) NOT NULL,  -- e.g. 'Loan', 'Cash'
    workflow_template_id VARCHAR(100),
    status              VARCHAR(50) NOT NULL DEFAULT 'active',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Fund-level documents (PRD §8.3)
-- ---------------------------------------------------------------------------
CREATE TABLE fund_documents (
    document_id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    fund_id             UUID        NOT NULL REFERENCES funds(fund_id) ON DELETE CASCADE,
    document_type       VARCHAR(100) NOT NULL,
    filename            VARCHAR(255),
    status              VARCHAR(50) CHECK (status IN ('pending', 'verified', 'expired', 'rejected')),
    expiry_date         DATE,
    -- Per-doc processing status for idempotency (PRD §17)
    extraction_status   VARCHAR(50) CHECK (extraction_status IN ('pending', 'extracted', 'failed')),
    embedding_status    VARCHAR(50) CHECK (embedding_status IN ('pending', 'embedded', 'failed')),
    synthetic_profile   BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- BLE-level documents (PRD §8.3)
-- ---------------------------------------------------------------------------
CREATE TABLE ble_documents (
    document_id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    ble_id              UUID        NOT NULL REFERENCES bles(ble_id) ON DELETE CASCADE,
    document_type       VARCHAR(100) NOT NULL,
    filename            VARCHAR(255),
    status              VARCHAR(50) CHECK (status IN ('pending', 'verified', 'expired', 'rejected')),
    expiry_date         DATE,
    extraction_status   VARCHAR(50) CHECK (extraction_status IN ('pending', 'extracted', 'failed')),
    embedding_status    VARCHAR(50) CHECK (embedding_status IN ('pending', 'embedded', 'failed')),
    synthetic_profile   BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- UBO records — Fund-level ownership chain (PRD §5, §9.2)
-- ---------------------------------------------------------------------------
CREATE TABLE ubo_records (
    ubo_id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    fund_id             UUID        NOT NULL REFERENCES funds(fund_id) ON DELETE CASCADE,
    ubo_name            VARCHAR(255) NOT NULL,
    ownership_pct       NUMERIC(5,2),
    layer_depth         INTEGER     NOT NULL DEFAULT 1,
    jurisdiction        VARCHAR(3),   -- ISO country code
    parent_ubo_id       UUID        REFERENCES ubo_records(ubo_id),  -- multi-layer chains
    resolved            BOOLEAN     NOT NULL DEFAULT FALSE,
    -- 0 = none, 1 = highest risk PEP tier (senior officials), 3 = lowest
    pep_tier            SMALLINT    CHECK (pep_tier IN (0, 1, 2, 3)),
    synthetic_profile   BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Screening results — scope-aware (PRD §8.3, §9.3)
-- scope: 'fund' (Fund entity or UBO) | 'counterparty' (BLE counterparty profile)
-- ---------------------------------------------------------------------------
CREATE TABLE screening_results (
    screening_id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    scope                   VARCHAR(20) NOT NULL CHECK (scope IN ('fund', 'counterparty')),
    scope_id                UUID        NOT NULL,  -- fund_id or counterparty_id
    screened_name           VARCHAR(255) NOT NULL,
    result_status           VARCHAR(20) NOT NULL CHECK (result_status IN ('clean', 'hit', 'error', 'pending')),
    hit_severity            VARCHAR(20) CHECK (hit_severity IN ('none', 'low', 'medium', 'high', 'confirmed')),
    hit_type                VARCHAR(50),  -- 'sanctions', 'pep', 'adverse_media'
    raw_result              JSONB,
    screened_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    opensanctions_dataset   VARCHAR(100),
    is_mock                 BOOLEAN     NOT NULL DEFAULT FALSE
);

-- ---------------------------------------------------------------------------
-- Risk scores — scope-aware, versioned (PRD §8.3, §9)
-- scope: 'fund' | 'ble'
-- direct_score/direct_tier: the entity's own factors only
-- escalated_tier: set only when BLE→Fund escalation applies (PRD §9.3)
-- ---------------------------------------------------------------------------
CREATE TABLE risk_scores (
    score_id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    scope               VARCHAR(10) NOT NULL CHECK (scope IN ('fund', 'ble')),
    scope_id            UUID        NOT NULL,
    ruleset_version     VARCHAR(20) NOT NULL REFERENCES ruleset_config(version),
    direct_score        NUMERIC(6,2) NOT NULL,
    direct_tier         VARCHAR(20) NOT NULL CHECK (direct_tier IN ('low', 'medium', 'high', 'critical')),
    -- escalated_tier is set when a Critical BLE forces the Fund to Critical (PRD §9.3)
    escalated_tier      VARCHAR(20) CHECK (escalated_tier IN ('low', 'medium', 'high', 'critical')),
    escalation_reason   TEXT,
    hard_stop           BOOLEAN     NOT NULL DEFAULT FALSE,
    factor_scores       JSONB       NOT NULL,  -- per-factor breakdown for auditability
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Review triggers queue — deterministic engine output (PRD §10)
-- ---------------------------------------------------------------------------
CREATE TABLE review_triggers (
    trigger_id      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    scope           VARCHAR(10) NOT NULL CHECK (scope IN ('fund', 'ble', 'both')),
    fund_id         UUID        REFERENCES funds(fund_id),
    ble_id          UUID        REFERENCES bles(ble_id),
    trigger_type    VARCHAR(100) NOT NULL,
    trigger_detail  JSONB,
    fired_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed       BOOLEAN     NOT NULL DEFAULT FALSE
);

-- ---------------------------------------------------------------------------
-- Workflow suggestions — scope-aware (PRD §11, §8.3)
-- ---------------------------------------------------------------------------
CREATE TABLE workflow_suggestions (
    suggestion_id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    scope                       VARCHAR(10) NOT NULL CHECK (scope IN ('fund', 'ble')),
    scope_id                    UUID        NOT NULL,
    trigger_type                VARCHAR(100) NOT NULL,
    trigger_detail              TEXT,
    suggested_workflow_template VARCHAR(100),
    status                      VARCHAR(20) NOT NULL DEFAULT 'pending'
                                    CHECK (status IN ('pending', 'accepted', 'declined', 'expired')),
    ai_narrative                TEXT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at                 TIMESTAMPTZ,
    resolved_by                 VARCHAR(255)
);

-- ---------------------------------------------------------------------------
-- Review audit history — scope-aware (PRD §8.3, §18)
-- ---------------------------------------------------------------------------
CREATE TABLE review_audit_history (
    audit_id        UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    scope           VARCHAR(10) NOT NULL CHECK (scope IN ('fund', 'ble')),
    scope_id        UUID        NOT NULL,
    action          VARCHAR(100) NOT NULL,
    actor           VARCHAR(255),
    notes           TEXT,
    performed_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Document embeddings — pgvector, scope-aware (PRD §14, §8.3)
-- bge-base-en-v1.5 produces 768-dimensional vectors.
-- scope + scope_id are mandatory on every chunk — cross-scope retrieval is
-- a hard failure (PRD §18).
-- ---------------------------------------------------------------------------
CREATE TABLE document_embeddings (
    embedding_id    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    scope           VARCHAR(10) NOT NULL CHECK (scope IN ('fund', 'ble')),
    scope_id        UUID        NOT NULL,
    document_id     UUID        NOT NULL,
    chunk_index     INTEGER     NOT NULL,
    chunk_text      TEXT        NOT NULL,
    embedding       vector(768),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (document_id, chunk_index)
);

-- ---------------------------------------------------------------------------
-- Eval runs (PRD §15)
-- ---------------------------------------------------------------------------
CREATE TABLE eval_runs (
    eval_run_id     UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    eval_category   CHAR(1)     NOT NULL CHECK (eval_category IN ('A','B','C','D','E','F','G')),
    run_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    pass_count      INTEGER,
    fail_count      INTEGER,
    score           NUMERIC(5,4),
    cost_usd        NUMERIC(10,6),
    latency_ms      INTEGER,
    notes           TEXT
);

-- ---------------------------------------------------------------------------
-- LLM call log — every AI call logged (PRD §8, §17, §18)
-- ---------------------------------------------------------------------------
CREATE TABLE llm_call_log (
    call_id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    scope           VARCHAR(10) CHECK (scope IN ('fund', 'ble')),
    scope_id        UUID,
    call_type       VARCHAR(100) NOT NULL,  -- 'extraction','rag','narrative','judge','text_to_sql'
    model_id        VARCHAR(100) NOT NULL,
    prompt_version  VARCHAR(50),
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    cost_usd        NUMERIC(10,6),
    latency_ms      INTEGER,
    is_mock         BOOLEAN     NOT NULL DEFAULT FALSE,
    called_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------
CREATE INDEX idx_bles_fund               ON bles(parent_fund_id);
CREATE INDEX idx_bles_counterparty       ON bles(counterparty_profile_id);
CREATE INDEX idx_ble_products_ble        ON ble_products(ble_id);
CREATE INDEX idx_fund_documents_fund     ON fund_documents(fund_id);
CREATE INDEX idx_ble_documents_ble       ON ble_documents(ble_id);
CREATE INDEX idx_ubo_fund                ON ubo_records(fund_id);
CREATE INDEX idx_screening_scope         ON screening_results(scope, scope_id);
CREATE INDEX idx_risk_scores_scope       ON risk_scores(scope, scope_id);
CREATE INDEX idx_risk_scores_computed    ON risk_scores(computed_at DESC);
CREATE INDEX idx_triggers_unprocessed    ON review_triggers(processed, fired_at) WHERE NOT processed;
CREATE INDEX idx_embeddings_scope        ON document_embeddings(scope, scope_id);
CREATE INDEX idx_suggestions_status      ON workflow_suggestions(status, scope);
CREATE INDEX idx_audit_scope             ON review_audit_history(scope, scope_id);
CREATE INDEX idx_llm_log_scope           ON llm_call_log(scope, scope_id);
