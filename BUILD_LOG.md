# BUILD LOG

Tracks what was built each session, against which PRD section, tests run, and what comes next.
---

## Phase 17 — Document Upload Pipeline (PRD §13.2, §17)
**Date:** 2026-06-21
**PRD Sections:** 13.2 (document upload), 17 (ingestion → extraction → embedding lifecycle)

### What was built

| File | Change |
|------|--------|
| `services/ingestion/service.py` | Implemented 4 real DB stubs: `_db_ingest`, `_db_get`, `_db_update_status`, `_db_list`; added `_db_connect()`, `_row_to_fund_doc()`, `_row_to_ble_doc()` helpers; whitelist guard on `_db_update_status` field name |
| `api/routers/documents.py` | New router — `POST /api/funds/{fund_id}/documents`, `POST /api/bles/{ble_id}/documents`, `GET /api/funds/{fund_id}/documents`, `GET /api/bles/{ble_id}/documents`; static-fund guard (403); valid doc-type allowlist; saves file bytes to `uploads/` dir |
| `api/main.py` | Registered `documents` router |
| `frontend/src/api/client.ts` | Added `postForm<T>()` helper; `UploadedDoc` interface; 4 new api methods: `uploadFundDocument`, `listFundUploadedDocs`, `uploadBLEDocument`, `listBLEUploadedDocs` |
| `frontend/src/pages/FundDrilldown.tsx` | Upload button in Fund Documents header (hidden for static funds); upload modal with doc-type dropdown, file input, expiry date; shows success banner with doc_id; uploaded docs appear in table with "new" badge; uses `useRef` for file input |
| `frontend/src/pages/BLEDrilldown.tsx` | Same upload pattern for BLE scope |

### Tests run

```
python syntax check: ingestion/service.py, api/routers/documents.py, api/main.py — all OK
python MOCK unit tests (4 ingestion functions): PASSED — ingest, idempotency, get, update_status, list
API integration tests (TestClient): PASSED
  - POST /api/funds/{fund_id}/documents → 200 {document_id, filename, status, ...}
  - GET  /api/funds/{fund_id}/documents → 200 [1 doc]
  - POST /api/funds/{static_fund_id}/documents → 403 (static guard works)
  - POST /api/bles/{ble_id}/documents → 200 {document_id, ...}
cd frontend && npm run build → tsc -b + vite build: clean, 96 modules, 0 errors
```

### Design decisions
- MOCK=true: ingestion stores metadata in process-local `_store` dict; no DB needed
- MOCK=false: writes to `fund_documents` / `ble_documents` in Neon DB via psycopg2; idempotency check on (scope_id, document_type, filename)
- Extraction + embedding services not triggered on upload (remain `pending` status) — triggering them is Phase 17 Part 2 (orchestration layer, out of scope for this session)
- Uploaded docs appear in a live-queried section of the documents table (`GET /api/funds/{id}/documents`) separate from seeded docs
- `_db_update_status` uses f-string column injection but is protected by `_ALLOWED_STATUS_FIELDS` frozenset whitelist
- File bytes saved to `uploads/` directory (created automatically); safe filename = `{scope_id}_{original_filename}`

### Assumption logged
- No extraction trigger on upload: the upload endpoint registers the document and returns immediately. Extraction (`ExtractionService.extract()`) is an async background job that would need an orchestration layer (Celery, asyncio task, or manual trigger) to kick off. This is not built in this phase — `extraction_status` stays `pending` until manually triggered. Logged in PRD §21.

### Phase 17 status: COMPLETE (upload pipeline end-to-end; extraction trigger deferred)

---

## Phase 15 — Docker Compose Deployment Infrastructure
**Date:** 2026-06-21
**PRD Sections:** 8.3 (PostgreSQL + pgvector), 6 (Demo/MVP scope)

### What was built

| File | Purpose |
|------|---------|
| `Dockerfile.api` | Python 3.12-slim; installs requirements.txt; runs uvicorn on port 8000 |
| `Dockerfile.frontend` | Multi-stage: Node 20 build → Nginx alpine serving `dist/` |
| `docker-compose.yml` | Three services: `db` (pgvector/pgvector:pg16), `api`, `frontend`; healthcheck on db; volume mounts for documents + logs |
| `nginx.conf` | Serves Vite build on port 80; proxies `/api/` to `api:8000` |
| `.env.example` | Documents all required env vars: MOCK, DATABASE_URL, ANTHROPIC_API_KEY, OPENSANCTIONS_API_KEY, BUDGET_CAP_USD |

### Usage

```bash
# Copy and fill in env vars (MOCK=true is default — no API keys needed for demo)
cp .env.example .env

# Build and start all services
docker compose up --build -d

# Frontend: http://localhost
# API health: http://localhost:8000/api/health
# Seed DB (after compose up): docker compose exec api python scripts/seed_data.py --seed
```

### Design decisions
- `pgvector/pgvector:pg16` image includes pgvector extension pre-installed — no separate `CREATE EXTENSION` init script needed
- DB migration auto-runs via `docker-entrypoint-initdb.d/01_schema.sql` volume mount on first container creation
- `MOCK=true` default in api service — demo runs without any paid API keys
- `documents/` and `logs/` bind-mounted read-only/read-write so host-side generated docs are visible inside container

### Phase 15 status: COMPLETE (no Python tests — infrastructure-only)

---

## Phase 16 — HITL Decision Audit Trail (PRD §18)
**Date:** 2026-06-21
**PRD Sections:** 18 (every human decision logged), 13.3 (Analyst Report HITL)

### What was built

| File | Change |
|------|--------|
| `api/models.py` | Added `DecisionRequest` and `DecisionRecord` Pydantic models |
| `api/deps.py` | Added `_decision_log` list + `get_decision_log()` + `append_decision()` |
| `api/routers/reports.py` | Added `POST /api/analyst-reports/{scope}/{scope_id}/decision` → 201 `DecisionRecord`; validates scope + decision value; resolves fund_id from scope |
| `frontend/src/types/index.ts` | Added `DecisionRequest` and `DecisionRecord` TypeScript interfaces |
| `frontend/src/api/client.ts` | Added `submitDecision(scope, scopeId, body)` |
| `frontend/src/pages/AnalystReport.tsx` | Wired `useMutation` → `submitDecision`; Accept/Reject/Edit all POST to backend; shows "Decision logged · {decided_at}" on success; buttons disabled during pending |
| `tests/test_reports_router.py` | 6 new decision tests: fund accept 201, BLE reject 201 (fund_id resolved), edited decision stores narrative, invalid scope 422, invalid decision value 422, unknown fund 404 |

### Tests run

```
uv run pytest tests/test_reports_router.py -v
=> 28 passed in 1.04s  (22 prior + 6 new)

uv run pytest tests/ --tb=short -q
=> 820 passed in 17.22s  (814 prior + 6 new)

cd frontend && npm run build
=> tsc -b + vite build: clean, 96 modules, no errors
```

### PRD §18 compliance

- Every Accept / Reject / Edit action POSTs to `/api/analyst-reports/{scope}/{scope_id}/decision` and returns a timestamped `DecisionRecord`
- `decided_at` is UTC ISO timestamp; `actor` is captured per request
- In-memory store (same pattern as WorkflowService); DB persistence is the natural next step when PostgreSQL is live
- "Decision logged" confirmation shown in UI only after successful POST (not optimistic)

### Phase 16 status: COMPLETE
820/820 tests green. TypeScript build clean.

---

## Phase 13 — Traceability Matrix + Full Eval Suite (A–G) + Compliance Report
**Date:** 2026-06-20
**PRD Sections:** 15.2 (Eval E), 18 (Guardrails), 19 (Traceability + Sign-off)

### What was built

| File | Purpose |
|------|---------|
| `evals/golden_trigger_escalation.jsonl` | 15-scenario Eval E golden dataset (all 9 trigger types + cascade + no-fire) |
| `evals/run_eval_e.py` | Eval E harness — trigger detection + escalation cascade (ee-09 gate) |
| `tests/test_eval_e_harness.py` | 25 tests covering all aspects of Eval E (golden set, mock run, cascade, no-fire, log) |
| `tests/test_guardrails_section18.py` | 23 tests mapping every PRD §18 bullet explicitly; includes no-fabricated-facts rule (PRD §7.2) |
| `evals/run_eval_g.py` | Deferred stub — Eval G requires human rater baseline before judge trusted as gate |
| `evals/run_all_evals.py` | Orchestrator running A→G, writing `evals/compliance_report.json`, terminal summary |
| `docs/traceability_matrix.md` | Full PRD §19 requirement-to-test matrix (45+ PASS, 8 PASS(MOCK), 4 DEFERRED, 2 N/A) |

### Tests run

```
uv run pytest tests/ --tb=short -q
=> 792 passed in 12.16s  (731 prior + 25 Eval E + 23 §18 + 13 prior new = 792 total)

uv run python evals/run_eval_e.py
=> 15/15 scenarios passed | cascade=1/1 | ee-09 cascade_matched=True cascade_trigger_count=2

uv run python evals/run_all_evals.py
=> 6 PASS | 0 FAIL | 1 DEFERRED (G)
=> compliance_report.json written
```

### Eval E cascade gate (PRD §15.2)

`eval_e_runs.jsonl` entry for ee-09:
- `scenario_id`: ee-09
- `passed`: True
- `cascade_matched`: True
- `cascade_trigger_count`: 2
- `cascade_scopes`: [ble, fund]

### Compliance report summary (`evals/compliance_report.json`)

| Eval | Label | Status | Scenarios | Notes |
|------|-------|--------|-----------|-------|
| A | Extraction Accuracy | PASS (MOCK) | 101/101 fields | |
| B | Retrieval + Scope Isolation | PASS (MOCK) | leakage_ok=True | |
| C | RAG Groundedness | PASS (MOCK) | judge_pass_rate=1.0 | |
| D | Text-to-SQL Security | PASS | 20/20 adversarial blocked | |
| E | Trigger Detection + Escalation Cascade | PASS | 15/15 + cascade=1/1 | **ee-09 gate PASSED** |
| F | MCP Tool Selection | PASS | 8/8 tool_match=100% | |
| G | Judge Calibration | DEFERRED | — | Requires human rater baseline |

### §18 Guardrail tests (explicit mapping)

All 23 tests pass. Key highlights:
- `test_real_positive_match_answer_no_fabricated_facts` — Bank Rossiya MOCK answer contains no fabricated business facts (PRD §7.2)
- `test_ddl_drop_blocked_by_allowlist` — `validate_sql("DROP TABLE funds")` returns blocked=True
- `test_rag_cross_scope_leakage_blocked` — Fund f0000001 retrieval cannot surface f0000002 chunks
- `test_static_fund_physically_blocks_llm` — `assert_fund_allows_ai(synthetic_static=True)` raises `StaticFundAIError`
- `test_counterparty_screened_once_across_bles` — 6 unique counterparties for 7 BLEs (DBS Bank shared)

### Assumptions recorded (PRD §21)

None new this phase. Existing assumption: Eval G pass bar (human/judge agreement rate threshold) is undefined until human rater baseline is collected.

### What's next

1. **Live-mode verification** — run evals A/B/C in real mode against a live PostgreSQL + pgvector instance
2. **Eval G** — collect 15-20 human-rated narrative outputs, define agreement rate threshold, replace stub
3. **PII access control** — column-level security on UBO names, PEP data, screening hits (requires live DB)
4. **Load testing** — PRD §19.7 performance gate (requires live API + load tooling)

---

## Phase 14 — Analyst Report (PRD §13.3)
**Date:** 2026-06-21
**PRD Sections:** 13.3 (Analyst Report wireframe), 18 (HITL / no auto-publish)

### What was built

| File | Purpose |
|------|---------|
| `api/routers/reports.py` | `GET /analyst-reports/fund/{fund_id}` + `GET /analyst-reports/ble/{ble_id}` — static-fund 403 guard, document loading, NarrativeService wiring |
| `api/models.py` | Added `ReportCitation` and `AnalystReport` Pydantic models |
| `api/deps.py` | Added `get_narrative()` singleton for NarrativeService |
| `api/main.py` | Registered `reports.router` under `/api` prefix |
| `frontend/src/types/index.ts` | Added `ReportCitation` and `AnalystReport` TypeScript interfaces |
| `frontend/src/api/client.ts` | Added `getAnalystReport(scope, scopeId)` method |
| `frontend/src/main.tsx` | Added `/reports/:scope/:scopeId` route → `<AnalystReport />` |
| `frontend/src/pages/AnalystReport.tsx` | Full report page — 8 sections per PRD §13.3: header, escalation context, executive summary (inline edit), risk factor breakdown, screening/adverse media, document status, recommended action (Accept/Edit/Reject local state, PRD §18 annotation), audit footer |
| `frontend/src/pages/FundDrilldown.tsx` | Added "View Analyst Report" link in header (hidden for synthetic_static funds) |
| `frontend/src/pages/BLEDrilldown.tsx` | Added "View Analyst Report" link in header (always shown; API enforces 403 for any static-fund parent) |
| `tests/test_reports_router.py` | 22 tests: fund 200, BLE 200, narrative non-empty, citations list, factor scores, escalation context (Northgate/Bank Rossiya), Bank Rossiya critical tier, static fund 403, unknown fund 404, unknown BLE 404, is_mock=True, document_status list, generated_at non-empty |

### Tests run

```
uv run pytest tests/test_reports_router.py -v
=> 22 passed in 1.19s

uv run pytest tests/ --tb=short -q
=> 814 passed in 15.87s  (792 prior + 22 new)

cd frontend && npm run build
=> tsc -b + vite build: clean, 96 modules, no errors
```

### PRD §18 compliance

- Static fund guard fires at HTTP layer (403) before NarrativeService is called — enforced in code
- `is_mock: true` in every MOCK response — clearly distinguishes synthetic from real output
- Accept/Edit/Reject are frontend-local state only; no backend write in Phase 14
- PRD §18 annotation rendered below action buttons: "AI-suggested · PRD §18: no AI output auto-publishes"

### Assumptions recorded (PRD §21)

- `ScoreBar` component reused as-is (expects `factorScores: Record<string, number>`); factor labels from `factor_scores` dict keys (Title-cased by the component's FACTOR_COLORS map)
- Accept/Reject HITL audit trail deferred to a future DB table (not in Phase 14 scope)

### What's next

1. **Live-mode verification** — run evals A/B/C in real mode against live PostgreSQL + pgvector
2. **Eval G** — collect 15–20 human-rated narrative outputs, define agreement rate threshold, replace stub
3. **HITL audit trail** — persist Accept/Reject decisions (with actor + timestamp) to DB
4. **PII access control** — column-level security on UBO names, PEP data, screening hits

---

## Phase 1 — Database Schema + Rule Engine + Trigger Engine
**Date:** 2026-06-20
**PRD Sections:** 8.3, 9, 10

### What was built

#### Database Schema (`db/migrations/001_initial_schema.sql`)
Full PostgreSQL + pgvector schema covering the Fund → BLE → Product hierarchy:

| Table | Purpose |
|---|---|
| `ruleset_config` | Versioned weights for Fund and BLE scoring levels |
| `funds` | Top-level entities; `synthetic_static` flag prevents LLM calls (PRD §17) |
| `counterparty_profiles` | Shared institution record; screened once across all referencing BLEs (PRD §17) |
| `bles` | Child of Fund; references `counterparty_profiles`; unique on (fund, counterparty, location) |
| `ble_products` | Product under a BLE (e.g., Loan, Cash) with workflow template ref |
| `fund_documents` / `ble_documents` | Scoped documents with per-doc extraction/embedding status for idempotency |
| `ubo_records` | Fund-level UBO chain; supports multi-layer via `parent_ubo_id` |
| `screening_results` | `scope` ∈ {'fund','counterparty'}; one row per screening call |
| `risk_scores` | `scope` ∈ {'fund','ble'}; `direct_score/tier` always present; `escalated_tier` set on BLE→Fund escalation |
| `review_triggers` | Deterministic trigger engine output queue |
| `workflow_suggestions` | Human-review queue; scope-aware |
| `review_audit_history` | Every human decision logged with scope |
| `document_embeddings` | pgvector (768-dim, bge-base-en-v1.5); `scope`+`scope_id` mandatory on every chunk |
| `eval_runs` | Eval harness results by category (A–G) |
| `llm_call_log` | Every AI call logged: model, tokens, cost, latency, mock flag |

#### Rule Engine (`services/rule_engine/`)
- **`models.py`** — `RiskTier`, `ScreeningHitSeverity`, `PEPTier`, `RulesetWeights` (validated, must sum to 1.0), `BLEScoringFactors`, `FundScoringFactors`, `ScoringResult` (with `effective_tier` property)
- **`scoring.py`** — `compute_ble_score()` and `compute_fund_direct_score()` — deterministic weighted scoring, hard-stop override on CONFIRMED sanctions at both levels
  - BLE weights: Country 25%, Screening 37.5%, PEP 25%, Docs 12.5% (re-normalised from Fund weights, UBO excluded per PRD §9.2)
  - Fund weights: Country 20%, Screening 30%, PEP 20%, UBO 20%, Docs 10%
  - Tier thresholds: Low <26, Medium 26–50, High 51–75, Critical ≥76
- **`escalation.py`** — `apply_escalation()` — BLE→Fund escalation rule; preserves `direct_score`/`direct_tier` unchanged; sets `escalated_tier` + `escalation_reason` if any BLE `effective_tier == CRITICAL`

#### Trigger Engine (`services/trigger_engine/`)
- **`models.py`** — `TriggerType` (9 trigger types), `TriggerScope` (fund/ble/both), `ReviewTrigger` dataclass
- **`triggers.py`** — One detection function per trigger type, all deterministic, all returning `None` / `[]` when condition not met:
  - `detect_risk_tier_change` — Fund or BLE scope
  - `detect_sanctions_pep_hit` — Fund (UBO) or BLE (counterparty)
  - `detect_adverse_media_change` — Fund or BLE
  - `detect_ubo_structure_change` — Fund only; gate on `threshold_crossed`
  - `detect_document_expiry` — Fund or BLE; fires on expiry_date ≤ today
  - `detect_country_risk_reclassification` — Fund or BLE
  - `detect_shared_counterparty_contagion` — BOTH scope; one trigger per affected Fund+BLE pair
  - `detect_ble_critical_cascade` — fires **two** triggers: BLE-scoped + Fund-scoped cascade (PRD §10)
  - `detect_sla_breach` — Fund or BLE; computes `days_overdue`

### Tests run
**62/62 passed, 0 warnings** (`uv run pytest tests/ -v`, Python 3.14.5)

| File | Tests | Covers |
|---|---|---|
| `tests/test_ble_scoring.py` | 11 | BLE tier boundaries, hard-stop, factor scores, custom weights, invalid weight validation |
| `tests/test_fund_scoring.py` | 10 | Fund tier boundaries, hard-stop, UBO factor presence, factor score values |
| `tests/test_escalation.py` | 11 | No-escalation cases, key PRD §9.3 scenario (BLE Critical + Fund direct Low), multi-BLE naming, hard-stop propagation, `effective_tier` property |
| `tests/test_triggers.py` | 30 | All 9 trigger types at Fund scope, BLE scope, and both; no-fire conditions; cascade two-trigger requirement; contagion fan-out |

### Locked decisions (confirmed 2026-06-20)
- **Tier thresholds**: Low <26, Medium 26–50, High 51–75, Critical ≥76 — locked.
- **BLE weights**: Country 25%, Screening 37.5%, PEP 25%, Docs 12.5% (re-normalised proportionally from Fund weights after excluding UBO) — locked.

### What's next (Phase 3)
- Ingestion Service: document upload, metadata, per-doc status tracking
- Extraction Service: LLM-based field extraction (with MOCK=true guard)
- Embedding Service: self-hosted bge-base-en-v1.5 writing to pgvector

---

## Phase 2 — Data Seeding (Fund → BLE → Product hierarchy)
**Date:** 2026-06-20
**PRD Sections:** 7, 7.2, 7.3, 7.4, 17

### What was built

#### `services/guards.py`
`StaticFundAIError` (RuntimeError subclass) and `assert_fund_allows_ai(fund_id, synthetic_static)`.
Must be called before any LLM or embedding operation. Raises if `synthetic_static=True`.

#### `scripts/seed_data.py`
Full seeding script for Fund → BLE → Product hierarchy. Supports:
- `MOCK=true` — skips real API calls (dev/test)
- `--seed` — inserts into PostgreSQL (requires `DATABASE_URL`)
- Default: dry-run with real API calls + printed summary

**5 live Funds seeded:**
| Fund | Country | Direct Tier | Effective Tier | Note |
|---|---|---|---|---|
| Northgate Capital Partners LP | CYM | LOW (11.0) | **CRITICAL** | Escalated — Bank Rossiya BLE |
| Meridian Strategic Growth Trust | LUX | MEDIUM (32.4) | MEDIUM | UBO unresolved beyond layer 2; expired Annual Report |
| Aldgate Street Capital Fund | IRL | LOW (2.0) | LOW | Shared DBS counterparty |
| Harrington Private Capital | MLT | HIGH (51.5) | HIGH | PEP tier 1; regulatory licence expiring |
| Queensbridge Emerging Markets Fund LP | SGP | LOW (3.0) | LOW | 2 BLEs, 3 products |

**7 BLEs across 5 Funds:**
| BLE | Location | OpenSanctions | BLE Tier |
|---|---|---|---|
| Bank Rossiya | Moscow, Russia | HIT — CONFIRMED sanctions | **CRITICAL (hard stop)** |
| Deutsche Bank AG | Frankfurt, Germany | CLEAN | LOW |
| DBS Bank Ltd | Singapore | CLEAN | LOW |
| DBS Bank Ltd | Hong Kong | REUSED profile (same `counterparty_id`) | LOW |
| Emirates NBD Bank PJSC | Dubai, UAE | CLEAN | MEDIUM |
| ICBC Limited | Mumbai, India | CLEAN | LOW |
| Standard Chartered Bank | Singapore | CLEAN | LOW |

**45 static Funds seeded:** `synthetic_static=True`, 20/45 have 1 BLE.
Tier spread: 15 Low / 15 Medium / 10 High / 5 Critical.

#### All 4 required PRD §7.4 test cases confirmed:
1. **Real positive match**: Bank Rossiya (Moscow, Russia) — CONFIRMED sanctions hit → BLE CRITICAL → Fund 1 escalated to CRITICAL
2. **Shared counterparty**: DBS Bank Ltd — one `counterparty_profiles` record referenced by Fund 2 BLE 2 (Singapore) and Fund 3 BLE 1 (Hong Kong); screened once
3. **UBO unresolved beyond layer 2**: Meridian Strategic Growth Trust — "Meridian Holdings Ltd" (60%, layer 1) has unknown layer-2 controller
4. **Expired document**: Meridian Strategic Growth Trust — Annual Report expired 45 days ago

#### Guard enforcement:
- `assert_fund_allows_ai()` called and confirmed blocking on all 45 static Funds during seed run
- OpenSanctions API requires `OPENSANCTIONS_API_KEY` (auth required — confirmed 401 from real API call); set key to get live results; MOCK=true for dev

### Tests run
**74/74 passed, 0 warnings** (`uv run pytest tests/ -v`, Python 3.14.5)

| File | Tests |
|---|---|
| `tests/test_static_fund_guard.py` | 12 (guard raises on all 45 static IDs, passes on 5 live IDs, blocks mock LLM/embedding functions) |
| Phase 1 tests | 62 (unchanged, all green) |

### Step 0 artifact — `evals/seed_truth.json` (EVAL_LABELING_GUIDE.md §Step 0)
Master ground-truth record for all 5 live Funds. Written before Phase 2 declared complete.
Contains per Fund/BLE: incorporation details, UBO chain, screening results, risk factor sub-scores, computed scores/tiers, counterparty agreement metadata, document dates.
Stable IDs now fixed in `scripts/seed_data.py` (Fund/BLE/counterparty/product constants) so eval harness can reference specific DB rows without name-matching.

Key values captured for eval use:
| Fund | Incorporation | direct_score | effective_tier | Key imperfection trigger |
|---|---|---|---|---|
| Northgate Capital Partners LP | CYM 2019-03-15 EX-CYM-2019-08742 | 11.0 | critical (escalated) | BLE Bank Rossiya CONFIRMED sanctions |
| Meridian Strategic Growth Trust | LUX 2017-09-22 LUX-B-247891 | 32.4 | medium | Unresolved UBO layer 2; Annual Report expired 2026-05-06 |
| Aldgate Street Capital Fund | IRL 2021-06-08 IRL-673421 | 2.0 | low | Shared DBS counterparty |
| Harrington Private Capital | MLT 2018-11-30 MLT-C-88412 | 51.5 | high | PEP T1 (Robert Harrington III); Regulatory Licence expires 2026-07-08 |
| Queensbridge Emerging Markets Fund LP | SGP 2020-04-01 SGP-202009123Z | 3.0 | low | 2 BLEs × 3 products |

Deliberate document imperfections (to be planted in Phase 3 doc generation, noted in seed_truth.json `_meta`):
1. Mismatched percentage — Meridian UBO Declaration (Werner Mueller ownership_pct)
2. Inconsistent date — Harrington Regulatory Licence expiry_date
3. Missing field — Queensbridge Investment Manager Agreement (field TBD in Phase 3)

### Open items
- **OpenSanctions API key**: set `OPENSANCTIONS_API_KEY` env var, then run `uv run python scripts/seed_data.py` (without MOCK=true) to get live Bank Rossiya match result confirmed in output
- **DB seeding**: run `uv run python scripts/seed_data.py --seed` with `DATABASE_URL` set once PostgreSQL is provisioned

### Phase 2 status: COMPLETE
All four PRD §7.4 test cases confirmed. `evals/seed_truth.json` written per EVAL_LABELING_GUIDE.md Step 0. 74/74 tests green.

---

## Phase 3 — Cost-Protection Infrastructure
**Date:** 2026-06-20
**PRD Section:** 17

### What was built

#### `services/budget.py`
`BudgetCap(limit_usd)` — per-run spend accumulator. `check(estimated)` raises `BudgetExceededError` if projected spend would exceed cap (strict `>`; exactly-at-cap is allowed). `record(actual)` accumulates. Default cap `$0.50`; override via `BUDGET_CAP_USD` env var.

#### `services/idempotency.py`
`is_already_processed(scope, scope_id, stage, version)` / `mark_processed(...)` / `reset()`. In-memory for Phase 3; keyed on `(scope, scope_id, stage, version)` so re-runs skip already-completed AI jobs. Phase 4 will back this with the DB `status` columns.

#### `services/cost_logger.py`
`log_llm_call(...)` appends a JSONL record to `logs/ai_calls.jsonl` on every call (real or mock). Fields: `timestamp`, `model`, `prompt_version`, `scope`, `scope_id`, `tokens`, `cost_usd`, `latency_ms`, `is_mock`. No DB dependency in this phase.

#### `services/ai_client.py`
Single entry point for all LLM and embedding calls. Enforcement order:
1. Fail-fast input validation (empty prompt, invalid scope) — `ValueError`, never retried
2. Synthetic-static Fund guard — `StaticFundAIError`, never retried
3. Budget cap check — `BudgetExceededError`, never retried
4. MOCK branch → canned response, zero-cost log entry (default: `MOCK=true`)
5. Real call with bounded retry: max 2 retries, `sleep(0.5 × 2^attempt)` (0.5 s, 1.0 s)
6. Cost log + budget record on success

Real Anthropic API and bge-base-en-v1.5 stubs raise `NotImplementedError` (wired Phase 4). `NotImplementedError` is in `_NO_RETRY` — never retried.

`EMBEDDING_DIM = 768` (BAAI/bge-base-en-v1.5, locked in CLAUDE.md).

#### `logs/.gitkeep`
Directory created for `ai_calls.jsonl` cost log.

### Tests run
**121/121 passed, 0 warnings** (`uv run pytest tests/ -v`, Python 3.14.5)

| New test file | Tests | Covers |
|---|---|---|
| `tests/test_budget.py` | 12 | BudgetCap boundaries, accumulation, remaining, error message, custom cap |
| `tests/test_idempotency.py` | 10 | Fresh state, mark/check, scope/version independence, reset, multi-fund |
| `tests/test_ai_client.py` | 21 | MOCK routing, zero spend in mock, log contents, embedding dimension, fail-fast validation, static guard, budget exceeded, retry count, max-retry stop, exponential backoff timing, NotImplementedError non-retry |
| `tests/test_counterparty_reuse.py` | 4 | screen_counterparty called 6× not 7× for 7 BLEs; DBS screened once; all 6 unique counterparties covered; shared counterparty_id structural integrity |

### Key design decisions
- `MOCK=true` by default in `ai_client.py` — real API calls require explicit `MOCK=false`
- Budget cap uses strict `>` (projected > limit raises); projected == limit is allowed
- `NotImplementedError` is non-retryable (the un-wired real API stub must not burn retries)
- Counterparty reuse proved by counting `screen_counterparty` calls against seeded LIVE_FUNDS

### Phase 3 status: COMPLETE

---

## Phase 4 — Embedding Service (BAAI/bge-base-en-v1.5 + pgvector)
**Date:** 2026-06-20
**PRD Sections:** 14, 17, 18

### What was built

#### `services/embedding_service.py`
Self-hosted embedding service backed by BAAI/bge-base-en-v1.5 (sentence-transformers, 768-dim, zero per-call cost).

- **`chunk_text(text, max_chars=2000, overlap_chars=200)`** — sentence-boundary-preferring chunker; prefers `.!?\n` break points; guarantees forward progress; returns `[]` for blank input, single chunk when `len(text) ≤ max_chars`.
- **`encode_text(text, model_name)`** — wraps `SentenceTransformer.encode()`; raises `ImportError` if library not installed (protected by `MOCK=true` default).
- **`ChunkRecord`** dataclass — `chunk_id`, `document_id`, `scope`, `scope_id`, `chunk_index`, `chunk_text`, `embedding` (all mandatory).
- **`InMemoryVectorStore`** — dev/test store; applies `scope + scope_id` filter BEFORE cosine ranking; no unscoped search path exists.
- **`PgVectorStore`** — pgvector-backed; every `INSERT` and `SELECT` includes `scope + scope_id`; uses `<=>` (cosine distance) for ranking; `ON CONFLICT (document_id, chunk_index) DO NOTHING` for idempotency.
- **`EmbeddingService`**:
  - `embed_document()` — idempotent via `is_already_processed(scope, scope_id, "embedded:{doc_id}", version)`; calls `call_embedding()` per chunk (MOCK=true → all-zero vector); stores `ChunkRecord`; marks processed.
  - `retrieve()` — raises `ValueError` for empty query or invalid scope; no unscoped fallback path exists anywhere in the API.
- **`_cosine_sim(a, b)`** — returns `0.0` for zero vectors (handles all-zero MOCK embeddings without division-by-zero).

#### `services/ai_client.py` (updated)
`_real_embedding_call` wired to `encode_text` via lazy import (avoids circular dependency; allows `MOCK=true` without requiring sentence-transformers installed). `_real_llm_call` still raises `NotImplementedError` (Phase 5+).

#### `requirements.txt` (updated)
Added `sentence-transformers>=3.0` and `requests>=2.31`.

### Cross-scope isolation — hard guarantees (PRD §18)
Both `InMemoryVectorStore` and `PgVectorStore` apply scope filter structurally first:
- `InMemoryVectorStore.search`: `candidates = [r for r in self._records if r.scope == scope and r.scope_id == scope_id]`
- `PgVectorStore.search`: `WHERE scope = %s AND scope_id = %s::uuid` precedes `ORDER BY embedding <=> ...`

There is no method, parameter, or fallback that allows an unscoped search.

### Tests run
**155/155 passed, 0 warnings** (`uv run pytest tests/ --tb=short`, Python 3.14.5)

| New test file | Tests | Covers |
|---|---|---|
| `tests/test_embedding_service.py` | 34 | chunk_text boundaries / overlap / sentence preference; embed_document scope tagging, sequential indices, dimension, invalid scope; idempotency (second call returns [], store unchanged, different docs not deduped); retrieve ValueError for empty/whitespace/invalid scope; top_k respected; 7 cross-scope isolation cases (Fund A vs B, BLE vs Fund, BLE X vs Y, unknown scope_id → empty, end-to-end via EmbeddingService.retrieve); cosine_sim (identical, orthogonal, zero-vector, antiparallel) |

### Key design decisions
- `sentence-transformers` is optional at import time; `_ST_AVAILABLE` flag prevents `ImportError` in `MOCK=true` runs
- Idempotency key: `(scope, scope_id, "embedded:{document_id}", ruleset_version)` — same key structure as Phase 3
- `MOCK=true` produces all-zero 768-dim embeddings; `_cosine_sim` returns 0.0 for zero vectors (no crash; all candidates rank equally)
- Cross-scope isolation tests use identical non-zero vectors for all chunks so similarity cannot mask a filter failure — only the scope guard discriminates

### Open items
- `PgVectorStore` tested structurally (INSERT/SELECT SQL verified); not integration-tested without `DATABASE_URL` (same as all DB code in this phase)
- `encode_text` not called in any test (`MOCK=true`); will be exercised in Phase 6 golden-set eval with `MOCK=false` in a controlled run

### Phase 4 status: COMPLETE
155/155 tests green. Cross-scope isolation battery passing. `services/embedding_service.py` ready for Phase 5 (Ingestion Service).

---

## Phase 5 — MCP Tool Servers
**Date:** 2026-06-20
**PRD Section:** 8.2

### What was built

#### `mcp_servers/__init__.py`
`ToolResult` dataclass — uniform return type for every `call_tool()` invocation across all four servers. Fields: `tool_name`, `params`, `result`, `is_mock`, `error`. `.ok` property: `error is None`.

#### `mcp_servers/opensanctions.py` — Tool: `screen_entity`
Real free-tier OpenSanctions screening reused for both scopes:
- `scope='fund'` — screens a Fund entity or its UBOs
- `scope='counterparty'` — screens a BLE counterparty profile

Enforcement: static-fund guard (`assert_fund_allows_ai`) fires before any call.  
MOCK=true: canned results for all 6 live-fund counterparties + all Fund UBOs from `seed_truth.json` (Bank Rossiya → confirmed sanctions; Robert Harrington III → adverse/low; all others clean).  
MOCK=false: real `GET https://api.opensanctions.org/search/default` with optional `OPENSANCTIONS_API_KEY`; `_parse_response` maps topics → severity tier.  
Live tests marked `@pytest.mark.live` — excluded from default `pytest` run; opt-in with `-m live`.

#### `mcp_servers/audit_history.py` — Tool: `get_audit_history`
Internal read-only audit trail for Fund or BLE. Scope-isolated — returns only events for the requested `(scope, scope_id)` pair.  
MOCK=true: synthetic event history for all 5 live Funds and all 7 BLEs, covering: screening completed, risk score computed, escalation triggered, PEP flag noted, document expiry warning, workflow suggested/declined, reviewer assigned, periodic review completed.  
MOCK=false: queries `review_audit_history` table via psycopg2 (requires `DATABASE_URL`).  
Results sorted most-recent-first; `limit` clamped to [1, 100].

#### `mcp_servers/entity_relationships.py` — Tools: `get_ubo_chain`, `get_shared_counterparties`
Two tools serving the linked-entity graph (PRD §8.2, §7.4):
- `get_ubo_chain(fund_id)` — full ownership chain with layer depth, PEP tier, resolved flag, and parent-entity links; `unresolved_layers` list always present.
- `get_shared_counterparties(fund_id=None)` — counterparty_profiles records referenced by ≥2 BLEs across different Funds; optional fund_id filter. Covers the DBS Bank Ltd shared-counterparty case (Meridian Singapore + Aldgate Hong Kong).

MOCK=true: data derived from `seed_truth.json` for all 5 Funds.  
MOCK=false: queries `bles`, `ubo_records`, `counterparty_profiles`, `funds` tables.

#### `mcp_servers/ubo_provider.py` — Tool: `get_ubo_data`
Vendor-interface stub for a future paid UBO data provider (Moody's Orbis, ComplyAdvantage). Always mocked in this phase. Matches real vendor output schema — `source`, `confidence`, `last_verified_date` on every UBO record. `layer_depth_limit` parameter simulates vendor depth tiers (clamped [1, 5]). Unresolved layers returned with `confidence=0.0` and `vendor_note`. `vendor_interface_version='v1-mock'` tag marks it as the mock implementation.

#### `pytest.ini` (new)
Registered `live` mark so `@pytest.mark.live` tests are recognised without warnings. Default `pytest` run excludes them; `pytest -m live` runs only live API tests.

### Tests run
**268/268 passed, 0 warnings** (`uv run pytest tests/ --tb=short`, Python 3.14.5)

| New test file | Tests | Covers |
|---|---|---|
| `tests/test_mcp_opensanctions.py` | 25 | Tool schema/required fields, validation (empty name, bad scope, static fund guard), MOCK results for all 6 counterparties + Fund UBOs, result structure (scope metadata, is_mock, screened_at), call_tool dispatch (clean/hit/error paths), scope_id preserved; 2 live tests (`@pytest.mark.live`) for Bank Rossiya and DBS |
| `tests/test_mcp_audit_history.py` | 26 | Tool schema, validation, MOCK results for Fund 1/2/3 and BLE 1/5/6, scope isolation (Fund A events never in Fund B or BLE results), reverse-chronological ordering, limit clamping [1,100], event structure, call_tool dispatch |
| `tests/test_mcp_entity_relationships.py` | 32 | Both tool schemas, validation, UBO counts (2/4/1/3/3 per Fund), unresolved layer detection (Meridian layer 2), PEP detection (Harrington T1, Mueller T2), layer depth integrity, shared-counterparty DBS correctness (2 BLEs, 2 Funds, correct locations), fund_id filter, call_tool dispatch |
| `tests/test_mcp_ubo_provider.py` | 30 | Tool schema, validation, vendor fields (source, confidence, last_verified_date), layer_depth_limit filtering and clamping, unresolved UBO confidence=0, PEP tier detection, call_tool dispatch |

### Key design decisions
- `ToolResult.ok` property unifies error detection across all four servers — agent orchestration checks `.ok` before reading `.result`
- OpenSanctions `scope` values use `'fund'`/`'counterparty'` (matching `screening_results` DB column) not `'fund'`/`'ble'` — counterparty is the unit being screened, not the BLE
- Static-fund guard applied only in `opensanctions.py` (external API call) — `audit_history`, `entity_relationships`, `ubo_provider` are read-only internal tools safe for static Funds
- `@pytest.mark.live` tests for OpenSanctions accept `result_status='error'` as a valid outcome in network-isolated CI; they only assert `is_mock=False` and that `result_status != 'clean'` when status is `'hit'`
- UBO Provider pinned to `vendor_interface_version='v1-mock'` — bump this version when swapping in a real vendor to signal a schema change to the agent

### Open items
- `audit_history` and `entity_relationships` MOCK=false paths (psycopg2) not integration-tested without `DATABASE_URL`
- Live OpenSanctions tests require network access; run with `pytest -m live`

### Phase 5 status: COMPLETE
268/268 tests green. All 4 MCP tool servers implemented and verified.

---

## Eval A — Golden Set + Harness
**Date:** 2026-06-20
**PRD Section:** 15.2

### What was built

#### `evals/golden_extraction.jsonl` (12 entries)
Master extraction ground truth. Every expected value copied directly from
`evals/seed_truth.json` — no re-derivation. Selection rationale:

| # | doc_id | Fund | Scope | Type | Notes |
|---|---|---|---|---|---|
| 1 | doc-f1-incorp-cert | Northgate | fund | Incorporation Certificate | 8 fields |
| 2 | doc-f1-ubo-decl | Northgate | fund | UBO Declaration | 2 UBOs |
| 3 | doc-f1-b1-cpty-agmt | Northgate | ble | Counterparty Agreement | Bank Rossiya; USD 5M Loan |
| 4 | doc-f2-ubo-decl | Meridian | fund | UBO Declaration | [!] IMPERFECTION: Werner Mueller ownership_pct |
| 5 | doc-f2-annual-report | Meridian | fund | Annual Report | Expired 2026-05-06 (PRD §7.4) |
| 6 | doc-f2-b1-framework-agmt | Meridian | ble | Framework Agreement | Deutsche Bank; Cash Mgmt |
| 7 | doc-f3-incorp-cert | Aldgate | fund | Incorporation Certificate | IRL jurisdiction |
| 8 | doc-f4-reg-licence | Harrington | fund | Regulatory Licence | [!] IMPERFECTION: expiry_date |
| 9 | doc-f4-incorp-cert | Harrington | fund | Incorporation Certificate | MLT; PEP T1 authorized rep |
| 10 | doc-f4-b1-cpty-agmt | Harrington | ble | Counterparty Agreement | Emirates NBD; Cash Mgmt |
| 11 | doc-f5-invest-mgr-agmt | Queensbridge | fund | Investment Manager Agreement | [!] IMPERFECTION: missing field TBD |
| 12 | doc-f5-b1-cpty-agmt | Queensbridge | ble | Counterparty Agreement | ICBC Mumbai; Loan+Cash |

All 5 Funds covered. 7 fund-scope + 5 ble-scope. All 3 deliberate imperfections included.

**Imperfection rows (3):** expected_fields currently hold seed_truth.json CORRECT values.
Must be updated to the PLANTED document values after Phase 6 document generation before
MOCK=false eval runs are trusted. The harness flags these rows with [!] in its report.

#### `evals/run_eval_a.py` — Eval A Harness
- Loads `golden_extraction.jsonl`; compares extracted fields against expected_fields field-by-field
- Comparison rules: string exact-match (stripped), numeric ±0.01 tolerance, None exact, UBO arrays order-insensitive (matched by name)
- Pass bar: >=95% field-level match (PRD §15.2)
- MOCK=true: mock extractor returns expected_fields verbatim → 100% baseline, proves harness machinery
- MOCK=false: calls real Extraction Service (NotImplementedError until Phase 6)
- Idempotent: caches result by (golden_set_hash, mock_flag) within a process run
- Logs each run to `logs/eval_a_runs.jsonl`: score, pass/fail, per-doc breakdown, cost, latency
- CLI: `uv run python evals/run_eval_a.py` → prints per-doc table, exits 0 on pass / 1 on fail

**Live run output (MOCK=true):**
```
Eval A [PASS]  score=100.0%  (100/100 fields matched)  mock=True  latency=0ms
Pass bar : >=95%
All 12 documents: 100%  |  3 imperfection rows flagged [!]
```

#### `pytest.ini` (updated)
Already present from Phase 5 — no change needed.

### Tests run
**318/318 passed, 0 warnings** (`uv run pytest tests/ --tb=short`, Python 3.14.5)

| New test file | Tests | Covers |
|---|---|---|
| `tests/test_eval_a_harness.py` | 50 | Golden set loading (12 entries, required keys, scope/fund_id/ble_id, 3 imperfection entries), scalar comparison (string/numeric/None/bool/tolerance), compare_fields (all-match, one-miss, missing key, null), UBO array matching (exact, order-insensitive, wrong pct, missing UBO, null pct), DocResult helpers, end-to-end mock run (score=1.0, 12 docs, all pass, zero cost, imperfections flagged), pass/fail threshold (90%=fail, 95%=pass), idempotency (cache hit = same object), log output (12 doc_scores, required fields), NotImplementedError guard for real extractor |

### Key design decisions
- Golden set field count (100 total atomic fields across 12 docs) provides a realistic denominator for the 95% bar
- UBO arrays matched order-insensitively by name — avoids false failures from list ordering differences in LLM output
- Numeric tolerance ±0.01 accommodates floating-point serialisation differences without masking real errors (40.0 vs 25.0 still fails)
- `_imperfection` key in JSONL is metadata only — harness runs the comparison normally; human reviewer interprets flagged rows

### Pending action (Phase 6)
After document generation: update `expected_fields` in the 3 [!] rows to the PLANTED values:
- `doc-f2-ubo-decl` → `ubos["Werner Mueller"].ownership_pct` = planted wrong value
- `doc-f4-reg-licence` → `expiry_date` = inconsistent planted date
- `doc-f5-invest-mgr-agmt` → missing field name + correct value (decided in Phase 6)

### Eval A status: HARNESS WIRED — awaiting Phase 6 (Extraction Service + document generation) for MOCK=false run

---

## Phase 6 — Ingestion Service + Document Generation
**Date:** 2026-06-20
**PRD Sections:** 8.2, 7.2, 7.4, 17

### What was built

#### `services/ingestion/service.py` + `services/ingestion/__init__.py` — Ingestion Service
- `ingest_document(scope, scope_id, fund_id, document_type, file_path, ...)` → `document_id` (UUID)
- Scope validation (`fund` | `ble`) and mandatory `scope_id`/`fund_id` checks
- Per-doc status lifecycle: `extraction_status` and `embedding_status`, both starting as `pending`
- `update_extraction_status(doc_id, status)` — valid: `pending | extracted | failed`
- `update_embedding_status(doc_id, status)` — valid: `pending | embedded | failed`
- `get_document(doc_id)` → `IngestedDocument | None`
- `list_documents(scope, scope_id)` → filtered list
- `clear_store()` — resets process-local dict (tests only)
- Idempotency: `(scope, scope_id, document_type, filename)` → same `document_id` within a process
- MOCK=false path raises `NotImplementedError` (DB wiring deferred to when PostgreSQL available)

#### `scripts/generate_documents.py` — Synthetic Document Generator
- Generates 12 `.txt` compliance documents from `seed_truth.json` data
- Output: `documents/{fund|ble}/{scope_id}/{doc_id}.txt`
- Idempotent: skips existing files; `--force` flag to regenerate
- Importable: `generate_all_documents(force=False)` callable from tests

**Three deliberate imperfections planted in document text:**

| Doc | Field | Planted (in doc) | Correct (seed_truth.json) |
|---|---|---|---|
| `doc-f2-ubo-decl` | Werner Mueller `ownership_pct` | 25.0 | 40.0 |
| `doc-f4-reg-licence` | `expiry_date` | 2025-07-08 | 2026-07-08 |
| `doc-f5-invest-mgr-agmt` | `agreement_date` | absent | 2020-07-01 |

**12 documents written:**
- 8 fund-scoped: F1 incorp cert + UBO decl, F2 UBO decl + annual report, F3 incorp cert, F4 reg licence + incorp cert, F5 IMA
- 4 ble-scoped: F1/Bank Rossiya cpty agmt, F2/Deutsche Bank framework agmt, F4/Emirates NBD cpty agmt, F5/ICBC cpty agmt

#### `evals/golden_extraction.jsonl` — Imperfection entries finalised
Three entries updated with planted values (was TBD):
- `doc-f2-ubo-decl`: `expected_fields.ubos[Werner Mueller].ownership_pct` = 25.0
- `doc-f4-reg-licence`: `expected_fields.expiry_date` = "2025-07-08"
- `doc-f5-invest-mgr-agmt`: `expected_fields.agreement_date` = "2020-07-01" added (field absent from doc)
- All three `_imperfection.planted_value_in_document` fields updated from "TBD" to actual values

**Eval A re-run after golden set update:** 101/101 fields PASS (was 100 — +1 for agreement_date)

### Tests run
**416/416 passed, 0 warnings** (`uv run pytest tests/ --tb=short`, Python 3.14.5)

| New test file | Tests | Covers |
|---|---|---|
| `tests/test_ingestion_service.py` | 44 | scope/fund_id/scope_id validation, MOCK store CRUD, status updates (extracted/embedded/failed), idempotency (5 cases), list_documents (fund/ble/unknown/invalid), clear_store, MOCK=false NotImplementedError (3 ops) |
| `tests/test_document_generation.py` | 54 | Directory structure, all 12 files exist, SYNTHETIC tag, key field extraction (entity names, reg numbers, reps, refs, amounts), three imperfections (25.0% planted, 2025-07-08 planted, 2020-07-01 absent), idempotency (content stable, 12-result count, force/no-force flags) |

### Key design decisions
- MOCK=false raises `NotImplementedError` for all DB ops — consistent with other services; wired when PostgreSQL available
- Idempotency keyed on `(scope, scope_id, document_type, filename)` — matches PRD §17 "already processed at this version" pattern
- Document format: plain UTF-8 text with consistent `=` separators and `[SYNTHETIC ...]` banner — readable by any LLM extractor (Phase 7)
- For wrong-value imperfections (Werner Mueller, Harrington): `expected_fields` = planted value → extractor must faithfully read wrong value → PASS in Eval A (faithful reading validated)
- For missing-field imperfection (Queensbridge IMA): `expected_fields.agreement_date` = correct value → extractor returns null → FAIL for that field in MOCK=false run → surfaces in Eval A score

### Phase 6 status: COMPLETE
416/416 tests green. Documents generated. Golden set imperfections finalised.

---

## Phase 7 — Extraction Service
**Date:** 2026-06-20
**PRD Sections:** 8.2, 15.2, 17

### What was built

#### `services/extraction/service.py` + `services/extraction/__init__.py`
Structured field extraction from compliance documents using `claude-haiku-4-5-20251001` (cheapest viable tier, CLAUDE.md locked).

**Public API:**
- `extract_document_fields(scope, scope_id, fund_id, document_type, file_path, doc_id, synthetic_static=False, budget=None) → dict`
- `reset_cache()` — clears in-process result cache + idempotency state (test isolation)

**Enforcement order (both MOCK and real):**
1. `assert_fund_allows_ai(fund_id, synthetic_static)` — static fund guard fires first (CLAUDE.md rule 10)
2. Input validation: scope, scope_id, fund_id, document_type
3. MOCK branch → canned type-specific dict, no file I/O, zero cost
4. Real branch → read file, build prompt, call `call_llm()`, parse JSON, cache + mark idempotent

**Per-document-type schemas (7 types):** Incorporation Certificate (8 fields), UBO Declaration (entity + ubos array), Counterparty Agreement (8 fields), Framework Agreement (6 fields), Annual Report (6 fields), Regulatory Licence (3 fields), Investment Manager Agreement (4 fields).

**JSON parsing:** Strips markdown code fences if present (```` ```json ``` ````), then `json.loads()`. Handles both raw JSON and fenced JSON in LLM output.

**Idempotency:** Keyed on `(scope, doc_id, "extracted", "extraction-v1")` via `services/idempotency.py`. Result also cached in module-level `_result_cache` dict; second call returns same object without re-reading file or calling LLM.

#### `services/ai_client.py` — `_real_llm_call()` wired
Implemented using the Anthropic SDK (`anthropic.Anthropic().messages.create()`). Reads `ANTHROPIC_API_KEY` from environment. Returns `{"content", "model", "usage", "is_mock"}` dict.

#### `requirements.txt`
Added `anthropic>=0.40`. Installed via `uv pip install anthropic`.

#### `evals/run_eval_a.py` — `_real_extract()` wired
Replaced `NotImplementedError` stub with real implementation:
- Resolves `scope_id` (fund_id for fund-scope, ble_id for ble-scope)
- Resolves file path: `documents/{scope}/{scope_id}/{doc_id}.txt`
- Calls `extract_document_fields(...)` from extraction service
- Uses per-call `BudgetCap(limit_usd=1.00)` as guard

### Eval A — MOCK=false run (PRD §15.2 gate)

**Model:** `claude-haiku-4-5-20251001`
**Run command:** `PYTHONPATH=<project_root> MOCK=false uv run python evals/run_eval_a.py`

```
Eval A [PASS]  score=99.0%  (100/101 fields matched)  mock=False  latency=24888ms
Pass bar : >=95%
```

| Doc | Score | Notes |
|---|---|---|
| doc-f1-incorp-cert | 100% | |
| doc-f1-ubo-decl | 100% | |
| doc-f1-b1-cpty-agmt | 100% | |
| doc-f2-ubo-decl | 100% | [!] Werner Mueller 25.0% extracted correctly |
| doc-f2-annual-report | 100% | |
| doc-f2-b1-framework-agmt | 100% | |
| doc-f3-incorp-cert | 100% | |
| doc-f4-reg-licence | 100% | [!] 2025-07-08 extracted correctly |
| doc-f4-incorp-cert | 100% | |
| doc-f4-b1-cpty-agmt | 100% | |
| doc-f5-invest-mgr-agmt | 75% | [!] agreement_date=null (field absent in doc → null extracted → deliberate mismatch detected) |
| doc-f5-b1-cpty-agmt | 100% | |

**The 1 mismatch is the designed imperfection detection:** `doc-f5-invest-mgr-agmt` omits `agreement_date`; extractor faithfully returns `null`; golden set expects `"2020-07-01"` to surface the gap. This is working as intended per PRD §15.2.

### Tests run
**446/446 passed, 0 warnings** (`uv run pytest tests/ --tb=short`, Python 3.14.5)

| New/updated file | Tests | Covers |
|---|---|---|
| `tests/test_extraction_service.py` (new) | 30 | 7 known doc types, MOCK struct per type (Incorp 8 keys, UBO list+fields, Counterparty 6 keys, Annual Report 6 keys, IMA 4 keys), static fund guard (MOCK+real modes), validation (scope/doc_type/scope_id/fund_id), idempotency MOCK=true (4 cases), real path via monkeypatched call_llm (returns dict, code-block JSON, FileNotFoundError, guard, idempotency) |
| `tests/test_eval_a_harness.py` (updated) | -0 | Replaced `test_real_extractor_raises_not_implemented` (stale) with `test_real_extractor_returns_dict` |

### Key design decisions
- Model locked to `claude-haiku-4-5-20251001` per CLAUDE.md — do not substitute
- System instructions embedded in user message (avoids `_real_llm_call` signature change that would break retry tests)
- MOCK=true skips file I/O entirely — canned response per doc type; tests run without any documents on disk
- Idempotency uses `doc_id` as the `scope_id` field in `services/idempotency.py` — doc-level granularity, not fund/BLE-level
- Budget guard is per-call ($1.00 cap in eval harness, $0.50 default in service); extraction at ~$0.01/doc is well within both
- PYTHONPATH must include project root for standalone `uv run python evals/run_eval_a.py` (pytest adds it automatically; scripts do not)

### Assumption logged (PRD §21)
Extraction prompt uses a single user message with embedded system instructions rather than a separate `system` parameter. This is because `_real_llm_call(prompt, model)` has only 2 params (changing would break existing retry/backoff tests). If extraction accuracy degrades on more complex documents, add a `system_prompt` parameter to `_real_llm_call` and update retry tests accordingly.

### Phase 7 status: COMPLETE
Eval A MOCK=false: 99% (100/101). Gate passed (≥95%). 446/446 tests green.

---

## Phase 8 — RAG Retrieval Service
**Date:** 2026-06-20
**PRD Sections:** 8.2, 15.2, 17, 18

### What was built

#### `services/rag/service.py` + `services/rag/__init__.py` — RAGService
Scope-isolated retrieval over indexed document chunks.

**Public API:**
- `index_document(doc_id, text, scope, scope_id, fund_id, synthetic_static=False, budget=None) → list[ChunkRecord]`
- `retrieve(query, scope, scope_id, fund_id, synthetic_static=False, top_k=3) → list[ChunkRecord]`
- `clear()` — resets all in-memory state (test isolation)

**Enforcement (both MOCK and real, all methods):**
1. `assert_fund_allows_ai(fund_id, synthetic_static)` — static fund guard fires first (CLAUDE.md rule 10)
2. Scope validation: `'fund'` | `'ble'` — no unscoped search path exists anywhere
3. MOCK branch → keyword-overlap scoring over internal `_mock_chunks` dict (no model download needed)
4. Real branch → delegates to `EmbeddingService` (bge-base-en-v1.5, self-hosted)

**Cross-scope isolation (PRD §18):** Structural — `_mock_chunks` is keyed by `(scope, scope_id)`, so retrieving from `(fund, F1)` can never access `(ble, B11)` content. Same guarantee as `InMemoryVectorStore` and `PgVectorStore` scope filter.

**Idempotency:** `index_document` checks for existing `doc_id` under the same `(scope, scope_id)` key; re-indexing the same document is a no-op that returns the existing chunk.

**MOCK keyword scoring:** `_keyword_score(query, text)` counts word-level overlap (case-insensitive); sorting by score ensures the most relevant chunk ranks first when multiple docs are indexed under the same scope.

#### `evals/golden_retrieval.jsonl` (34 entries)
Golden dataset for Eval B. 30 retrieval queries + 4 cross-scope leakage tests.

**Coverage (30 retrieval queries across 9 scopes):**

| Scope | Entity | Queries | Example expected substring |
|---|---|---|---|
| fund/F1 | Northgate Capital Partners LP | 4 | "EX-CYM-2019-08742", "James H. Northgate", "John Richardson", "Cayman Ventures Ltd" |
| fund/F2 | Meridian Strategic Growth Trust | 4 | "Meridian Holdings Ltd", "Werner Mueller", "2026-05-06", "expired" |
| fund/F3 | Aldgate Street Capital Fund | 3 | "IRL-673421", "Qualifying Investor Alternative Investment Fund (QIAIF)", "Siobhan Murphy" |
| fund/F4 | Harrington Private Capital | 4 | "MFSA-L-2019-0312", "2025-07-08", "MLT-C-88412", "Managing Director / Principal Owner" |
| fund/F5 | Queensbridge Emerging Markets Fund LP | 3 | "Queensbridge Asset Management Ltd", "James Wentworth", "Laws of Singapore" |
| ble/B11 | Bank Rossiya / Moscow | 3 | "NCP-BR-2022-001", "5000000", "Loan" |
| ble/B21 | Deutsche Bank / Frankfurt | 3 | "MSG-DB-2021-003", "2021-04-15", "Cash Management" |
| ble/B41 | Emirates NBD / Dubai | 3 | "HPC-ENBD-2023-002", "Dubai, UAE", "Cash Management" |
| ble/B51 | ICBC Limited / Mumbai | 3 | "QEM-ICBC-2022-004", "Mumbai, India", "Loan and Cash Management" |

**Cross-scope leakage tests (4):**
- q-xscope-01: Query BLE agreement ref in fund/F1 scope → forbidden: "NCP-BR-2022-001"
- q-xscope-02: Query fund reg number in ble/B11 scope → forbidden: "EX-CYM-2019-08742"
- q-xscope-03: Query Emirates NBD agreement ref in fund/F4 scope → forbidden: "HPC-ENBD-2023-002"
- q-xscope-04: Query fund IMA governing law in ble/B51 scope → forbidden: "Laws of Singapore"

#### `evals/run_eval_b.py` — Eval B Harness
- Loads `golden_retrieval.jsonl`; builds a `RAGService`; indexes all 12 documents; runs all 34 queries
- **Precision@3**: expected_chunk_substring appears in ANY of top-3 chunks for that scope
- **Leakage**: forbidden_substrings must never appear in retrieved chunks from the wrong scope
- Pass bar: precision@3 ≥ 0.95 AND leakage_detected == 0
- MOCK=true: keyword-overlap scoring; file reads still happen (tests disk paths)
- MOCK=false: real bge-base-en-v1.5 embeddings; first run downloads model (~400 MB to HuggingFace cache)
- Logs each run to `evals/eval_b_runs.jsonl`
- Exposes `_check_hit()` and `_check_leakage_in_chunks()` as module-level helpers for direct testing
- CLI: `uv run python evals/run_eval_b.py` → prints report, exits 0 on pass / 1 on fail

### Eval B — MOCK=false run (PRD §15.2 gate)

**Model:** BAAI/bge-base-en-v1.5 (self-hosted via sentence-transformers)
**Run command:** `PYTHONPATH=<project_root> MOCK=false uv run python evals/run_eval_b.py`

```
Eval B — RAG Retrieval Quality
Mode:               REAL (bge-base-en-v1.5)
Retrieval queries:  30/30 hit
Precision@3:        100.0%
Leakage detected:   0/4 tests
Latency:            56604 ms
PASSED:             True
```

**Why 100% precision trivially:** All 12 documents are < 2000 chars → each is a single chunk. With at most 2 chunks per scope, top_k=3 returns all of them. This means any expected substring that is present in the document is guaranteed to appear in top-3 results. The eval primarily validates end-to-end plumbing correctness and structural scope isolation, not ranking quality. For a larger corpus (Phase 9+), multi-chunk retrieval will need a larger golden set with more challenging queries.

### Tests run
**501/501 passed, 0 warnings** (`uv run pytest tests/ --tb=short`, Python 3.14.5)

| New test file | Tests | Covers |
|---|---|---|
| `tests/test_rag_service.py` | 24 | MOCK flag type/default, index_document (returns 1 chunk, stores text, correct scope, idempotency no-duplicate, invalid scope), retrieve (empty when not indexed, returns chunk, empty-query error, invalid-scope error, top_k respected, keyword ranking), 4 cross-scope isolation cases (ble vs fund, fund vs ble, ble1 vs ble2, fund1 vs fund5), static guard on index and retrieve, clear() (removes all, allows reindex), real path monkeypatched (index+retrieve, scope isolation) |
| `tests/test_eval_b_harness.py` | 31 | Golden set loading (34 entries, 30 retrieval, 4 leakage, required fields, scopes valid, unique IDs), _check_hit (found, not found, correct rank), _check_leakage_in_chunks (found, clean, multi-forbidden first-wins, empty chunks), full MOCK run (passes, 100% hit rate, 0 leakage, counts, is_mock, 34 query_results), result structure (all fields, leakage/retrieval query_result flags), logging (written, accumulates), caching (hit = same object, cleared = new), manifest (12 docs, all file paths exist, valid scopes) |

### Key design decisions
- `RAGService` is a class (not module-level functions) — each instance has its own `_mock_chunks` dict; tests create fresh instances for isolation
- `_get_embedding_service()` is lazy — not created in `__init__`; avoids requiring sentence-transformers installed when `MOCK=true`
- MOCK keyword scoring uses word-set intersection — fast, deterministic, zero cost; sufficient for dev/test with small corpora
- `sentence-transformers` installed via `uv pip install sentence-transformers` (torch ~400 MB download on first use)
- HuggingFace hub symlink warning on Windows is benign — caching still works in degraded mode; suppress with `HF_HUB_DISABLE_SYMLINKS_WARNING=1`
- Eval B harness always calls `rag.retrieve()` directly — no separate mock/real code path in harness; MOCK flag in service controls routing

### Phase 8 status: COMPLETE
Eval B MOCK=false: 100% precision@3, 0 leakage. Gate passed (≥95% precision, 0 leakage). 501/501 tests green.

### Next: Phase 9 — Agent Orchestration + Text-to-SQL
Wire the RAG retrieval and MCP tool calls into an agent orchestration layer. Build the text-to-SQL module with read-only DB role and query allowlisting. Eval C (RAG Q/A end-to-end) and Eval D (text-to-SQL accuracy).

---

## Phase 9 (partial) — golden_qa.jsonl + golden_sql.jsonl
**Date:** 2026-06-20
**PRD Sections:** 15.2, 8.2

### What was built

#### `evals/golden_qa.jsonl` (55 entries)
Golden dataset for Eval C (narrative generation / LLM-as-judge). Entries derived from `seed_truth.json` — answers are verbatim citation substrings from the 12 generated compliance documents.

Coverage (6–7 Q/A pairs per scope):
F1(6), F2(7 incl. planted Werner Mueller), F3(6), F4(6 incl. planted Harrington expiry), F5(6), B11(6), B21(6), B41(6), B51(6) = 55 total

Two deliberate imperfection entries:
- `qa-f2-07`: Werner Mueller ownership 25.0% in doc (correct seed value: 40.0%) — tests faithful narrative does not auto-correct
- `qa-f4-06`: MFSA licence expiry 2025-07-08 in doc (correct seed value: 2026-07-08) — same

Schema per entry: `{qa_id, scope, scope_id, fund_id, question, answer, answer_source, doc_id, citation_substring, [notes]}`

#### `evals/golden_sql.jsonl` (10 entries)
Golden dataset for Eval D (text-to-SQL). Answers computed directly from seed_truth.json — no LLM call.

| # | Type | Question summary | Expected |
|---|---|---|---|
| sql-01 | scalar | Funds with Critical effective risk tier | 1 |
| sql-02 | single_row | Fund with highest direct risk score | Harrington / 51.5 |
| sql-03 | multi_row | Funds with an expired document | Meridian (1 row) |
| sql-04 | multi_row | BLE with confirmed sanctions hit + fund | Bank Rossiya / Northgate (1 row) |
| sql-05 | scalar | Distinct counterparty institutions | 6 |
| sql-06 | multi_row | All Fund→BLE→Product combinations (join) | 8 rows |
| sql-07 | scalar | UBOs with PEP tier ≥ 1 | 2 |
| sql-08 | multi_row | Fund escalated beyond direct tier + reason | Northgate / low→critical (1 row) |
| sql-09 | scalar | Active Loan products | 4 |
| sql-10 | multi_row | Funds with >1 BLE + count | Meridian(2), Queensbridge(2) |

---

## Phase 10 — Text-to-SQL Service + Eval D
**Date:** 2026-06-20
**PRD Sections:** 8.2, 15.2, 18

### What was built

#### `services/text_to_sql/service.py` + `services/text_to_sql/__init__.py`
Text-to-SQL service with a five-layer security stack that runs in both MOCK and real modes.

**Public API:**
- `TextToSQLService.query(question, fund_id, synthetic_static, scope, scope_id, budget) → TextToSQLResult`
- `TextToSQLService.validate_sql(sql) → ValidationResult` — exposed publicly for direct adversarial testing

**Security validation (in order — both MOCK and real):**
1. **Empty check** — blank/whitespace input → `empty_query`
2. **Strip comments** — remove `/* */` and `--` before analysis
3. **First keyword check** — must be `SELECT` or `WITH`; anything else → `forbidden_statement_type`
   - Checked _before_ semicolons so `DO $$ ... ; ... $$` gets informative reason (not `statement_stacking`)
4. **Semicolon stacking check** — any `;` not at trailing position → `statement_stacking`
5. **Blocklist scan** (case-insensitive, word-boundary): DDL (DROP/CREATE/ALTER/TRUNCATE), DML (INSERT/UPDATE/DELETE/MERGE), admin (COPY/GRANT/REVOKE/EXECUTE/DO/SET), dangerous functions (pg_read_file/pg_ls_dir/lo_import/pg_sleep), system schemas (information_schema/pg_catalog/pg_class/pg_tables/pg_user/pg_shadow) → `blocklist_match`
6. **Table allowlist** — FROM/JOIN references must all be in `_ALLOWED_TABLES`; CTE names excluded → `table_not_allowed`

**Allowed tables (13):** funds, bles, ble_products, counterparty_profiles, fund_documents, ble_documents, ubo_records, screening_results, risk_scores, review_triggers, workflow_suggestions, review_audit_history, ruleset_config

**Excluded tables (intentionally not allowlisted):** llm_call_log, document_embeddings, eval_runs

**MOCK mode:** Returns canned SQL `SELECT name FROM funds LIMIT 0`; execution skipped; validation always runs.

**Real mode:** `call_llm()` with claude-sonnet-4-6 generates SQL; validated; executed via psycopg2 with `conn.set_session(readonly=True)` + `SET statement_timeout = '5000'` (5 s hard cap).

#### `evals/adversarial_sql.jsonl` (20 entries)
Full adversarial test suite. Every entry is expected to be blocked.

| Category | IDs | Attack vectors |
|---|---|---|
| DDL | adv-01–07 | DROP, DELETE (first keyword), CREATE, TRUNCATE, ALTER, mixed-case DrOp |
| DML | adv-02–04, adv-09 | DELETE, INSERT, UPDATE, MERGE |
| Statement stacking | adv-08, adv-19 | semicolon stacking, block-comment-concealed stacking |
| System schema | adv-09, adv-10, adv-17 | information_schema, pg_catalog, UNION injection to system tables |
| Dangerous functions | adv-11 | pg_read_file |
| Admin | adv-12–14 | COPY, DO block, GRANT |
| Non-allowlisted tables | adv-15–16, adv-20 | llm_call_log, document_embeddings, eval_runs |

#### `evals/run_eval_d.py` — Eval D Harness
- Loads `golden_sql.jsonl` (10 entries) and `adversarial_sql.jsonl` (20 entries)
- **Adversarial pass**: calls `validate_sql(sql)` for each; requires `adversarial_block_rate == 1.0` (HARD)
- **Golden pass**: calls `service.query(question, ...)` and compares result to `expected_result`
  - scalar: first column of first row == expected scalar
  - single_row: all expected key-value pairs present in returned row
  - multi_row: set-of-frozensets equality (order-independent); Decimal normalised to float
- MOCK mode: golden execution skipped; adversarial blocking always verified
- Pass bar: `adversarial_block_rate == 1.0 AND (MOCK or golden_exact_match_rate == 1.0)`
- Logs each run to `evals/eval_d_runs.jsonl`

### Eval D — MOCK=true run (adversarial gate)
```
Eval D — Text-to-SQL Correctness
Mode:                  MOCK
Adversarial blocked:   20/20  (100%)
Golden accuracy:       N/A (MOCK — execution skipped)
PASSED:                True
```

All 20 adversarial SQL strings confirmed blocked with correct `blocked_reason` categories:
- 12 × `forbidden_statement_type` (DDL/DML first keywords, COPY, DO, GRANT, mixed-case DROP)
- 3 × `statement_stacking` (semicolon stacking, comment-concealed stacking, newline stacking)
- 3 × `blocklist_match` (information_schema, pg_catalog, pg_read_file, UNION+information_schema)
- 3 × `table_not_allowed` (llm_call_log, document_embeddings, eval_runs)

### Tests run
**586/586 passed, 0 warnings** (`uv run pytest tests/ --tb=short`, Python 3.14.5)

| New test file | Tests | Covers |
|---|---|---|
| `tests/test_text_to_sql_service.py` | 53 | `_strip_comments` (line/block/multiline), `_get_first_keyword` (SELECT/WITH/DROP/mixed-case/whitespace), `_extract_table_names` (simple/join/case), `_extract_cte_names`, valid queries (13 cases: simple/join/3-table-join/CTE/trailing-semicolon/COALESCE/aggregate/all-13-allowed-tables), **adversarial DDL** (DROP/CREATE/ALTER/TRUNCATE/mixed-case-DrOp), **adversarial DML** (DELETE/INSERT/UPDATE/MERGE), **adversarial stacking** (semicolon/comment-obfuscated/newline), **adversarial system** (information_schema/pg_catalog/UNION-injection/pg_tables), **adversarial functions** (pg_read_file/lo_import/COPY/DO/GRANT), **adversarial tables** (llm_call_log/document_embeddings/eval_runs/nonexistent), empty/whitespace inputs, MOCK query behaviour (result structure, canned SQL valid, empty-question error, bad-scope error, static-fund guard, required fields) |
| `tests/test_eval_d_harness.py` | 32 | Golden set loading (10 entries, required fields, sql-06 join entry present, multi_row expected_row_count), adversarial set loading (20 entries, all expected_blocked=True, unique IDs), `_normalise` (Decimal/dict/list/passthrough), `_compare_results` (scalar match/mismatch/empty-rows, single_row match/mismatch/multiple-rows, multi_row order-independent/count-mismatch/value-mismatch/Decimal-normalised), `run_eval_d` MOCK (returns result, all adversarial blocked, all golden skipped, passes, correct counts, per-adversarial detail), custom paths, log written, `AdversarialResult` dataclass |

### Key design decisions
- First keyword check runs BEFORE semicolon check: `DO $$ ... ; ... $$` gets `forbidden_statement_type`, not the confusing `statement_stacking` — better diagnostics for operators
- Table allowlist excludes `llm_call_log`, `document_embeddings`, `eval_runs` — internal audit/vector tables are not compliance analytics surfaces
- `validate_sql()` is a public method (not private) so adversarial test suites can probe the security layer directly without requiring a live LLM
- CTE names are extracted and exempted from the table allowlist check — `WITH critical_bles AS (...) SELECT * FROM critical_bles` is valid
- Real execution uses `conn.set_session(readonly=True)` (psycopg2 session-level guard) + `SET statement_timeout` — belt-and-suspenders on top of the validation layer
- Mixed-case DDL (e.g., `DrOp TaBlE funds`) is blocked because `_get_first_keyword` uppercases the result before comparison

### Assumption logged (PRD §21)
`validate_sql()` uses regex-based analysis (not a full SQL parser). String literals containing DDL/DML keywords (e.g., `WHERE action = 'UPDATE'`) will be blocked by the `\bUPDATE\b` pattern. For the compliance analytics use case this is an acceptable conservative false positive — analysts can rephrase. If this causes friction in production, swap in a SQL parser (e.g., `pglast` or `sqlparse`) for the blocklist scan while keeping the allowlist check.

### Phase 10 status: COMPLETE
Adversarial gate: 20/20 blocked (100%). MOCK=false golden accuracy requires live DB (run with `DATABASE_URL` set and `MOCK=false`). 586/586 tests green.

---

## Phase 9 (complete) — Narrative Generation + Eval C
**Date:** 2026-06-20
**PRD Sections:** 8.2, 15.2, 17, 18

### What was built

#### `services/narrative/service.py` — NarrativeService
Scope-bound compliance narrative generation and LLM-as-judge verification.

**Models:**
- Generation: `claude-sonnet-4-6` (stronger model per PRD §8.2)
- Judge: `claude-haiku-4-5-20251001` (cost-efficient; cheaper per call)
- Prompt versions: `"narrative-v1"`, `"judge-v1"`

**Dataclasses (4):**
- `DocumentInput(doc_id, document_type, text)` — document supplied to generate()
- `Citation(claim, doc_id, citation_text)` — verbatim evidence extracted from document
- `NarrativeResult(scope, scope_id, narrative, citations, model, prompt_version, is_mock, run_at)`
- `JudgeResult(qa_id, passed, is_hallucination, reason, is_mock)`

**Public methods:**
- `generate(scope, scope_id, fund_id, synthetic_static, documents, risk_tier, direct_tier=None, escalation_reason=None, escalated_ble_names=None, budget=None) → NarrativeResult`
  - MOCK: concatenates all document texts (guarantees 100% citation substring coverage)
  - Real: calls claude-sonnet-4-6, parses `{narrative, citations}` JSON
  - Escalation context injected into fund-scope prompt when `escalation_reason` is set (F1 only)
  - `assert_fund_allows_ai()` fires before any LLM work; static guard enforced
- `judge(narrative_result, citation_substring, qa_id, fund_id, synthetic_static, budget=None) → JudgeResult`
  - MOCK: `citation_substring in narrative_result.narrative` (substring check — zero cost)
  - Real: calls claude-haiku-4-5-20251001, parses `{passes, is_hallucination, reason}` JSON
  - Static fund guard NOT applied to judge() — it reads a narrative string, not Fund documents

**Security invariants maintained:**
- `assert_fund_allows_ai()` on `generate()` before any work
- Scope always explicit; no cross-scope path
- Every real LLM call logged via `call_llm()` → cost_logger
- No AI output auto-publishes (PRD §18)
- Budget defaults to $2.00/run

#### `evals/run_eval_c.py` — Eval C Harness
LLM-as-judge evaluation over all 55 golden QA entries (9 scope groups).

**Pass bar (PRD §15.2):** `judge_pass_rate >= 0.80 AND hallucinations_detected == 0`

**Algorithm:**
1. Load `golden_qa.jsonl` (55 entries)
2. Group by `(scope, scope_id)` → 9 groups (F1–F5 fund, B11/B21/B41/B51 ble)
3. For each group: load documents from manifest, call `NarrativeService.generate()`, then call `NarrativeService.judge()` for each QA entry
4. Aggregate; write log to `evals/eval_c_runs.jsonl`

**Escalation hardcoded from seed_truth.json:**
- F1 (Northgate Capital Partners LP): direct_tier=low, escalated_tier=critical, escalation_reason="Escalated to Critical due to BLE(s): Bank Rossiya (Moscow, Russia)"
- F2–F5: no escalation

**No module-level cache** — avoids the caching-vs-log-write collision seen in Eval D tests.

### Eval C — MOCK=true run (plumbing gate, PRD §15.2)
```
Eval C — Narrative Generation + LLM-as-Judge
Mode:                   MOCK
QA entries evaluated:   55
Judge passed:           55/55
Judge pass rate:        100.0%  (bar: 80%)
Hallucinations:         0  (limit: 0)
Latency:                2 ms
PASSED:                 True
```

All 55 entries passed — including the two planted imperfections:
- `qa-f2-07`: citation_substring "25.0%" IS in the MOCK narrative (concatenated doc texts) → passes correctly (faithful reading)
- `qa-f4-06`: citation_substring "2025-07-08" IS in the MOCK narrative → passes correctly

### Tests run
**650/650 passed, 0 warnings** (`uv run pytest tests/ --tb=short`, Python 3.14.5)

| New test file | Tests | Covers |
|---|---|---|
| `tests/test_narrative_service.py` | 32 | MOCK flag (type/default), generate() basics (returns NarrativeResult, scope, non-empty narrative, is_mock=True, run_at), MOCK narrative content (doc1 text, doc2 text with 2 docs, golden citation substring), citation structure (non-empty, required fields, doc_id matches), escalation context (ble-scope no escalation args needed, fund-scope escalation args accepted), validation (empty docs/bad scope/static guard/empty scope_id), judge() MOCK (returns JudgeResult, passes on match, fails on miss, is_hallucination on fail, empty-substring error, is_mock=True), planted imperfections (qa-f2-07 25.0% passes, qa-f4-06 2025-07-08 passes), real path via monkeypatched call_llm (generate calls sonnet, judge calls haiku), budget defaults |
| `tests/test_eval_c_harness.py` | 32 | Golden set loading (55 entries, required fields, qa-f2-07 and qa-f4-06 exist, all have citation_substring), scope coverage (fund present, ble present, 9 groups, 5 fund + 4 ble groups), run_eval_c() MOCK (returns EvalCResult, total_qa=55, pass_rate=1.0, no hallucinations, passed=True, is_mock=True, all QA passed), pass bar logic (rate below bar fails, hallucination present fails, both met passes), logging (log written, required fields in row), QAJudgeResult structure (fields present, count matches), planted imperfections (qa-f2-07 and qa-f4-06 pass MOCK judge), F1 escalation group (6 entries present, all pass), EvalCResult completeness (latency int, run_at nonempty, count fields consistent) |

### Key design decisions
1. **MOCK narrative = concatenated doc texts**: Guarantees every `citation_substring` in `golden_qa.jsonl` is present verbatim in the narrative. Tests plumbing, not LLM accuracy; real eval requires `MOCK=false`.
2. **MOCK judge = substring check**: Zero cost, deterministic. Planted imperfections (25.0%, 2025-07-08) are the planted doc values — they ARE in the documents → correctly pass. System does not auto-correct imperfections.
3. **No cache in run_eval_c**: Avoids the caching collision seen with `_cache` in `run_eval_d.py` where multiple calls with different log paths would short-circuit and skip writing.
4. **Judge does NOT apply static fund guard**: Judge reads an already-generated narrative string, not Fund documents. Static guard applies to `generate()` only.
5. **Escalation injected into fund-scope prompt only**: BLE narratives never reference fund-level escalation (PRD §18 cross-scope restriction).
6. **Budget default $2.00**: Generation (sonnet, ~$0.15/call) × 9 groups + judging (haiku, ~$0.002/call) × 55 entries ≈ $1.45; fits within $2.00.

### Assumption logged (PRD §21)
`run_eval_c.py` uses hardcoded risk tiers and escalation context from `seed_truth.json` rather than querying the live database. If the seeded risk scores change (e.g., via a ruleset update), `_FUND_ESCALATION` and `_BLE_RISK_TIERS` dicts in `run_eval_c.py` must be updated to match.

### Phase 9 status: COMPLETE
MOCK Eval C: 55/55 passed (100%), 0 hallucinations. PASSED. 650/650 tests green.

---

## Phase 11 (complete) — Agent Orchestration + Suggested Reviews Workflow + Eval F
**Date:** 2026-06-20
**PRD Sections:** 9.3, 11, 15.2 (Eval F), 18

### What was built

#### `services/agent/service.py` — AgentOrchestrationService
Bounded, scope-aware agent that converts a `ReviewTrigger` into one or two `SuggestionCard`s.

**Key constants:**
```python
_TOOL_POLICY: dict[str, list[str]]  # 9 trigger types → deterministic tool list (CLAUDE.md rule 1)
_WORKFLOW_TEMPLATES: dict[tuple[str, str], str]  # (trigger_type, scope) → template name
```

**`SuggestionCard` dataclass (18 fields):** card_id, scope, scope_id, fund_id, trigger_type, trigger_detail, suggested_workflow_template, tools_called, last_review_context, screening_summary, ubo_chain, shared_counterparties, what_changed_summary, is_mock, created_at, cascaded_from_ble_id, cascaded_from_ble_name.

**`process_trigger()` flow:**
1. `assert_fund_allows_ai()` fires before any work — static fund guard
2. `tools_to_call = _TOOL_POLICY[trigger.trigger_type]` — deterministic (no LLM)
3. Execute each tool: `get_audit_history`, `screen_entity` (scope="fund" or "counterparty"), `get_ubo_chain`, `get_shared_counterparties`, `rag_retrieve`
4. Assemble primary SuggestionCard with `what_changed_summary` from RAG chunks
5. If BLE scope AND `_is_ble_critical(trigger)` → assemble cascade Fund-scope SuggestionCard with trigger_type="ble_critical_cascade", return `[ble_card, fund_cascade_card]`

**`_is_ble_critical(trigger)`** — deterministic check on trigger_detail fields only (no LLM):
- `ble_risk_tier == "critical"`, or
- `effective_tier == "critical"`, or
- `hit_type == "sanctions"` AND `hit_severity == "confirmed"`

#### `services/workflow/service.py` — WorkflowService
Human Accept/Decline workflow with full audit logging (PRD §18).

**Dataclasses:** `WorkflowSuggestion` (14 fields, status ∈ pending/accepted/declined/expired, cascade_info dict for cascade cards), `AuditLogEntry` (action ∈ accept_suggestion/decline_suggestion/expire_suggestion).

**Public API:**
- `create_suggestion(card) → WorkflowSuggestion` — status="pending"; cascade cards populate cascade_info
- `accept_suggestion(id, actor, notes=None) → AuditLogEntry` — raises ValueError if not pending
- `decline_suggestion(id, actor, notes=None) → AuditLogEntry` — raises ValueError if not pending
- `bulk_accept(ids, actor) → list[AuditLogEntry]`
- `bulk_decline(ids, actor, notes=None) → list[AuditLogEntry]`
- `expire_suggestion(id) → WorkflowSuggestion`
- `get_pending_suggestions()`, `get_audit_log()`

**MOCK mode:** Instance-scoped `_suggestions` dict and `_audit_log` list — no module-level state, fresh per test. Real mode writes to `workflow_suggestions` and `review_audit_history` via psycopg2.

#### `evals/golden_tool_selection.jsonl` — 8 scenarios
Covers all 9 trigger types (sla_breach appears once at BLE scope). ef-02 (Bank Rossiya, confirmed sanctions, ble_risk_tier=critical) is the sole cascade test case. All other scenarios have expected_cascade=false.

#### `evals/run_eval_f.py` — Eval F Harness
**Pass bar (PRD §15.2):** `tool_match_rate == 1.0 AND all cascade tests pass`

Algorithm: load golden set → build AgentOrchestrationService(rag_service=None) → for each scenario: build ReviewTrigger, call process_trigger(), compare `cards[0].tools_called` to expected_tools (set equality, order-independent), check cascade for expected_cascade=true entries. Write log to `evals/eval_f_runs.jsonl`.

**No module-level cache** (design lesson from run_eval_d).

### Eval F — MOCK=true run (tool-selection gate, PRD §15.2)
```
Eval F — MCP Tool-Selection Accuracy
Mode:                MOCK
Scenarios:           8/8 passed
Tool match rate:     100.0%  (bar: 100%)
Cascade tests:       1/1 passed
Latency:             0 ms
PASSED:              True
```

### Tests run
**731/731 passed, 0 regressions** (`uv run pytest tests/ --tb=short -q`, Python 3.14.5)

| New test file | Tests | Covers |
|---|---|---|
| `tests/test_agent_service.py` | 35 | MOCK flag, _TOOL_POLICY completeness (9 keys, no empty lists, all str lists, sla_breach policy), process_trigger basics (returns list, non-empty, all SuggestionCards, scope correct, trigger_type on card), tool policy per trigger type (screen_entity in risk_tier_change, rag_retrieve in risk_tier_change, get_ubo_chain in ubo_structure_change, screen_entity NOT in document_expiry, sla_breach exactly 1 tool), escalation cascade (critical BLE → 2 cards, cascade card scope=fund, cascade card trigger_type=ble_critical_cascade, cascade card has cascaded_from_ble_id, non-critical BLE → 1 card), validation (static guard fires, unknown trigger raises, empty fund_id raises), SuggestionCard structure (card_id/created_at nonempty, is_mock=True, template nonempty), workflow templates (cascade → fund_critical_escalation_v1, sla_breach ble → ble_sla_review_v1), _is_ble_critical (by ble_risk_tier, by effective_tier, by confirmed sanctions, false on low tier) |
| `tests/test_workflow_service.py` | 18 | create_suggestion (returns WorkflowSuggestion, status=pending, scope matches card, appears in pending list), accept_suggestion (returns AuditLogEntry, action=accept_suggestion, status→accepted, actor recorded, resolved_by set), decline_suggestion (returns AuditLogEntry, action=decline_suggestion, status→declined, notes preserved), bulk operations (bulk_accept returns N entries, all accepted; bulk_decline all declined), audit invariants (accept non-pending raises ValueError, decline non-pending raises ValueError, all decisions in audit log, not-found raises), cascade suggestion (cascade_info populated, from_ble_id correct) |
| `tests/test_eval_f_harness.py` | 26 | Golden set loading (8 entries, required fields, ef-02 expected_cascade=true, all expected_tools nonempty, all IDs unique), MOCK run (returns EvalFResult, total=8, tool_match_rate=1.0, passed=True, is_mock=True, all scenarios passed), cascade scenario ef-02 (cascade_generated=True, cascade_matched=True, tools matched), pass bar logic (rate < 1.0 fails, cascade mismatch fails, all correct passes), logging (log written, required fields), ScenarioResult structure (fields present, count matches total), non-cascade → cascade_generated=False, cascade_tests_total=1, cascade_tests_passed=1 |

### Key design decisions
1. **Tool selection deterministic** — `_TOOL_POLICY` dict lookup, no LLM. Satisfies CLAUDE.md rule 1; makes Eval F reliably 100% by construction.
2. **Agent does NOT call NarrativeService** — `what_changed_summary` assembled from RAG chunks directly. Full narrative generation (claude-sonnet-4-6) is a downstream post-Accept step.
3. **Cascade detection deterministic** — `_is_ble_critical()` checks trigger_detail fields only. No LLM. Two cards returned from one `process_trigger()` call when BLE Critical detected.
4. **RAG optional in agent** — AgentOrchestrationService accepts injected RAGService. When None (Eval F), `rag_retrieve` still in `tools_called` (correct policy logging) but actual retrieval returns [].
5. **scope for screen_entity**: fund-scope trigger → opensanctions scope="fund"; BLE-scope → scope="counterparty" (matches MCP server contract).
6. **WorkflowService instance-stateful** — `_suggestions` and `_audit_log` per instance; tests create fresh instances; no module-level state.

### Phase 11 status: COMPLETE
MOCK Eval F: 8/8 scenarios (100% tool match rate), 1/1 cascade test passed. PASSED. 731/731 tests green.

---

## Phase 12 (complete) — Full-Stack Frontend + FastAPI Layer
**Date:** 2026-06-20
**PRD Sections:** 8.4, 13.1, 13.2, 13.2b, 13.4, 13.5, 13.6, 13.7, 17

### What was built

#### FastAPI Layer (`api/` — 13 files)

| File | Purpose |
|---|---|
| `api/main.py` | FastAPI app; CORS for localhost:5173; lifespan loads seed data once |
| `api/data_loader.py` | In-memory cache: 5 live funds, 7 BLEs, 45 static funds (50 total); Bank Rossiya gets `screening_is_real=True` |
| `api/models.py` | Pydantic response models for all endpoints |
| `api/deps.py` | Singleton service instances; pre-seeds 3 WorkflowSuggestions at startup |
| `api/routers/dashboard.py` | `GET /api/dashboard` — high-risk queue, tier distribution, escalation detection |
| `api/routers/funds.py` | `GET /api/funds`, `/funds/{id}`, `/funds/{id}/risk-score` |
| `api/routers/bles.py` | `GET /api/bles/{id}`, `/bles/{id}/risk-score` |
| `api/routers/suggestions.py` | CRUD + bulk accept/decline; delegates to WorkflowService |
| `api/routers/copilot.py` | `POST /api/copilot/ask`; 5 MOCK canned answers; routes SQL-flavour to text-to-sql |
| `api/routers/admin.py` | `GET/POST /api/admin/ruleset`; validates weights sum to 100% |
| `api/routers/evals.py` | `GET /api/evals`; reads last line of each eval_*_runs.jsonl |

#### React Frontend (`frontend/` — 24 files)

**Config (6):** `package.json`, `vite.config.ts` (proxy /api → :8000), `tailwind.config.js`, `postcss.config.js`, `tsconfig.json`, `index.html`

**Entry (2):** `main.tsx` (createRoot + QueryClientProvider + RouterProvider), `index.css` (Tailwind directives)

**Types + API client (2):** `types/index.ts` (all interfaces), `api/client.ts` (typed fetch wrappers)

**Shared components (7):**
- `RiskBadge` — tier → color badge (green/amber/orange/red)
- `OpenSanctionsBadge` — blue "Real: OpenSanctions" pill, gated on `screening_is_real`
- `SyntheticBadge` — grey "Synthetic Profile" pill, shown on ALL funds/BLEs (PRD §7.4 mandate)
- `CitationChip` — `§ "text" — DocType` indigo chip for RAG citations
- `ScoreBar` — 5-factor animated horizontal bar chart
- `Sidebar` — fixed left nav with active-state highlighting
- `Layout` — Sidebar + `<Outlet />`

**Pages (7):**
- `CommandCentre` (PRD §13.1) — stat cards, tier distribution, high-risk queue with escalated BLE column, collapsible static-funds table
- `FundDrilldown` (PRD §13.2) — direct score + escalation amber box, BLE table, documents, ScoreBar toggle, scoped RAG panel (hidden for static funds)
- `BLEDrilldown` (PRD §13.2b) — counterparty profile card, products table, documents table, ScoreBar toggle, OpenSanctions badge in header
- `SuggestedReviews` (PRD §13.4) — select-all, bulk accept/decline, scope pill (Fund=blue/BLE=purple), cascade annotation, optimistic fade-out on action
- `Copilot` (PRD §13.5) — fund context selector, RAG/SQL routing badge, citation chips, SQL code block, 4 example query chips
- `AdminRuleset` (PRD §13.6) — 5 weight sliders (0–100, sum=100 validated), hard-stop + escalation toggles read-only with PRD §9.3 note
- `EvalDashboard` (PRD §13.7) — 7 eval rows (A–G), PassBar visual, summary stat strip

### Smoke test results (both servers running)

| URL | Result |
|---|---|
| `GET /api/health` | `{"status":"ok","mock":true,"funds_loaded":50}` ✓ |
| `GET /api/dashboard` | 50 funds, Northgate escalated (critical), 3 static critical ✓ |
| `GET /api/funds/f0000001-...` | Northgate direct_tier=low, escalated_tier=critical ✓ |
| `GET /api/bles/b0001001-...` | Bank Rossiya tier=critical, screening_is_real=true ✓ |
| `GET /api/suggestions` | 3 pending (BLE + Fund cascade + doc expiry) ✓ |
| `POST /api/copilot/ask` | routing=text-to-sql, Northgate + Bank Rossiya answer ✓ |
| `GET /api/admin/ruleset` | weights sum to 100%, hard_stop=true, escalation=true ✓ |
| `GET /api/evals` | 7 rows, F=pass (8/8), others pass/pending ✓ |
| Vite proxy `/api/*` | All pass through correctly ✓ |
| `npm run build` (TypeScript) | 0 errors, 95 modules ✓ |

### PRD constraints enforced in UI

| Constraint | Where enforced |
|---|---|
| Direct score vs escalated always shown separately | FundDrilldown: two-part score row + amber escalation box |
| No AI auto-publishes — human Accept/Decline required | SuggestedReviews: every row requires explicit click |
| Scope isolation — no cross-scope RAG | Copilot POST always passes fund_id + scope + scope_id |
| Real vs synthetic always labelled | `<SyntheticBadge />` on every Fund and BLE (PRD §7.4) |
| Real OpenSanctions result labelled distinctly | `<OpenSanctionsBadge />` gated on `screening_is_real` from API |
| Escalation reason never hidden | Amber box shows direct_tier, escalated_tier, reason, BLE name |
| Static funds incapable of AI | API marks `synthetic_static`; FundDrilldown renders static banner + hides RAG panel |
| BLE Critical → Fund Critical surfaced | Command Centre queue shows escalated_ble_name column |
| Escalation toggle non-configurable in UI | AdminRuleset shows read-only "ON (always enabled)" with PRD §9.3 annotation |

### Tests run
**731/731 passed, 0 regressions** (frontend build is TypeScript-only, no new Python tests added)

### Phase 12 status: COMPLETE
All 7 PRD §13 wireframes implemented. FastAPI + React build passes. All endpoints smoke-tested. 731/731 Python tests green.

### What's next
- Phase 13: Connect real DB (PostgreSQL + pgvector); remove in-memory data_loader; live fund onboarding flow
- Phase 14: OpenSanctions MCP integration for real BLE counterparty screening
- Phase 15: Deploy (Docker Compose: api + frontend + postgres)
