# Product Requirements Document
## AI-Native Entity Onboarding & Periodic Review Platform (KYB / BLE Compliance Command Centre)

**Status:** Draft v2.0 — Ready for build (Demo/MVP scope)
**Owner:** [Product Manager Name]
**Last Updated:** June 20, 2026
**Changelog from v1.0:** Corrected the entity hierarchy from a flat Entity model to a
nested Fund → BLE → Product structure (Section 5, 7, 8, 9, 10, 11, 13). Added
two-level risk scoring with escalation logic. Corrected the real/fictional data
boundary to apply at the BLE-counterparty level rather than the top-level entity.

---

## 1. Executive Summary

This platform is a financial-fund onboarding and ongoing-due-diligence system. A
**Fund** (the entity being onboarded) maintains relationships with one or more
**BLEs** — distinct banking/counterparty relationships, each at a specific
location — and each BLE offers one or more **Products** (e.g., Loan, Cash), which
can carry their own onboarding workflow. The system calculates a configurable,
explainable risk score at **both the Fund and BLE level**, using real-world
factors (country, sanctions/PEP screening, UBO ownership structure, document
completeness), triggers periodic and event-based reviews at the appropriate
scope, and surfaces portfolio-wide insight through a Command Centre built for
executive and compliance-analyst usability.

The system deliberately keeps **all risk-determining logic deterministic and
auditable** (rule engine, not AI), and uses AI narrowly — for reading
unstructured documents, retrieving grounded answers, translating natural-language
questions into structured queries, and drafting (human-approved) narrative
summaries. Every AI output is evaluated against a golden dataset before it is
trusted to reach the Command Centre.

This PRD covers the **Demo/MVP build**: 5 Funds running the full live pipeline,
each with 1–2 BLEs and 1–2 Products per BLE, and 45 Funds seeded as static
synthetic data for dashboard scale.

---

## 2. Problem Statement

1. **Onboarding is not one-size-fits-all.** A Fund's relationship with each BLE,
   and each BLE's Products, may require different document checklists and
   approval workflows.
2. **Ownership is often deliberately obscured.** UBO chains — at the Fund level —
   can run multiple layers deep; resolving who actually controls a Fund is the
   highest-value and highest-difficulty part of due diligence.
3. **Risk is not static, and it is not flat.** A BLE counterparty can become high
   risk independently of the Fund it sits under — and that risk needs to surface
   without being hidden inside an otherwise-clean Fund rollup.
4. **Compliance teams lack a single command view** spanning Funds and their
   underlying BLEs, currently scattered across documents, spreadsheets, and
   tribal knowledge.
5. **AI must not become an unaccountable decision-maker.** Any AI use in this
   domain must be explainable, human-gated, and never the final word on a
   regulatory decision.

---

## 3. Goals and Non-Goals (Demo/MVP)

### Goals
- Demonstrate the full pipeline — Fund onboarding → BLE/Product structure →
  two-level risk scoring → screening → periodic review triggers → Command Centre
  insight — on a small, credible dataset.
- Prove the AI techniques (RAG, MCP, text-to-SQL, LLM-as-judge) work, are
  grounded, and are cost-controlled.
- Produce a system directly extensible to production scale without
  architectural rework.

### Non-Goals (Demo/MVP)
- Production-scale data volume (50 Funds is sufficient; not thousands).
- Paid screening/UBO vendor integration (Moody's, ComplyAdvantage) — architecture
  supports swap-in later, not used now.
- Multi-tenant client configuration UI (single ruleset for demo; configurability
  is architected, not fully UI-exposed).
- Real external workflow engine — workflow steps/tasks are shown as a structured
  reference view; execution is out of scope.

---

## 4. Personas

| Persona | Needs |
|---|---|
| **Periodic Review (PR) Analyst** | A queue of Funds and BLEs needing review, with rationale and correct scope, without manually checking each one |
| **Compliance Officer / Approver** | Explainable risk scores at both Fund and BLE level, audit trails, final sign-off authority |
| **Executive / Head of Compliance** | Portfolio-level visibility — risk distribution across Funds *and* their BLEs, trends, SLA health |
| **Admin / Risk Config Owner** | Adjust risk weights per client, at both Fund and BLE scoring level, without engineering involvement |

---

## 5. Glossary

- **Fund (Entity)** — the top-level legal/financial entity being onboarded (e.g.,
  *Manalappam Fund*). Holds its own UBO chain, its own direct risk factors, and a
  composite risk score that reflects both itself and its BLEs.
- **BLE** — a child record under a Fund, representing a specific banking or
  counterparty relationship at a specific location (e.g., *ICBC, Noida* and
  *ICBC, Gurgaon* are two separate BLEs under the same Fund, even though they
  share the same counterparty institution). Each BLE has its own risk score, its
  own screening, and can carry multiple Products.
- **Product** — a specific financial product offered under a BLE (e.g., *Loan*,
  *Cash*). A BLE-Product combination can have its own onboarding workflow.
- **Counterparty Profile** — the shared identity/screening record for an
  institution that may appear across multiple BLEs (e.g., ICBC as an
  institution, referenced by both the Noida and Gurgaon BLEs) — screened once,
  not duplicated per BLE.
- **UBO** — Ultimate Beneficial Owner — the real person(s) who own/control a
  Fund, often hidden behind ownership layers.
- **PEP** — Politically Exposed Person — elevated risk individual due to
  political position/influence.
- **RAG** — Retrieval-Augmented Generation — LLM answers grounded in retrieved
  document content.
- **MCP** — Model Context Protocol — standardized way of exposing tools/data
  sources to an LLM/agent.
- **Golden Dataset** — Hand-verified labeled examples used to regression-test AI
  outputs.
- **LLM-as-judge** — Using an LLM to score another LLM's output against a rubric.
- **Escalation** — A Critical-tier BLE automatically surfaces and flags its
  parent Fund, regardless of the Fund's own direct-factor score (PRD Section 9).

---

## 6. Scope: Demo Phase vs Production Phase

| Area | Demo/MVP (this PRD) | Production (future phase) |
|---|---|---|
| Funds | 50 total (5 live, 45 static synthetic) | Full portfolio, thousands |
| BLEs per Fund | 1–2 (live Funds only) | Unbounded |
| Screening | OpenSanctions (free, MCP), Fund UBOs + BLE counterparties | Swap-in licensed vendor via same MCP interface |
| Embeddings | Self-hosted BAAI/bge-base-en-v1.5 | Same, or upgrade if quality demands it |
| Workflow execution | Reference view only | Real integration with external workflow engine |
| Risk config | Single hardcoded ruleset, both scoring levels | Full multi-tenant config UI |
| Infrastructure | Modular monolith | Event-driven, queue-based, horizontally scaled |
| Retrieval | pgvector | pgvector or upgrade path evaluated at scale |

---

## 7. Data Sourcing & Synthetic Data Plan

### 7.1 Hierarchy

```
Fund (Entity)
  └── BLE (counterparty + location)
        └── Product (Loan, Cash, etc.)
```

### 7.2 What is real vs. synthetic — corrected boundary

**A Fund's name may be a real entity** — specifically a real fund or organization
(not an individual) whose name appears in OpenSanctions data. Selecting real
entity names at the Fund level means the Fund's own screening call can return a
live positive or negative match, demonstrating to demo viewers that the system
operates on recognizable, real-world entities at both the Fund and BLE level.
Purely fictional fund names (e.g., *Manalappam Fund*) may also be used where a
suitable real entity name is not available or appropriate.

**The real signal lives in the screening calls, not in any invented profile.**
Any name queried against OpenSanctions — a Fund entity, a Fund's UBO, or a BLE's
counterparty — generates a real, live API result: a true positive (a name
genuinely present in OpenSanctions data) or a true negative (a clean name,
correctly returning no match). Both outcomes are real and both are worth
demonstrating.

**Hard rule (unchanged and applies at all levels):** regardless of whether a
queried name returns a real match, all structural and document content surrounding
that name is synthetic — incorporation details, ownership percentages, workflow
data, BLE/Product assignment, document content. The system must never generate
fabricated specific business facts attributed to a name that returns a real
positive match, beyond the match result itself. Screening a real name is a lookup
against public data; inventing a business relationship around that name is not.

**Individual names are never used as Fund entity names.** Individuals may appear
only as UBO records under a Fund, where they are screened for PEP/sanctions
status in exactly the same way as before.

### 7.3 Demo composition

| Layer | Count | Detail |
|---|---|---|
| Live Funds | 5 | Fully fictional fund names/profiles; full pipeline runs |
| Static Funds | 45 | Fully fictional, tagged `synthetic_static: true`, dashboard scale only — never capable of triggering an LLM or embedding call |
| BLEs per live Fund | 1–2 | Each a fictional or real counterparty name + location, screened live via OpenSanctions |
| Products per BLE | 1–2 | e.g., Loan, Cash — each with a synthetic workflow reference |

### 7.4 Synthetic data design requirements

- At least one BLE counterparty name that returns a real positive match on
  OpenSanctions (demonstrates the true-positive path and the escalation rule
  end-to-end)
- At least one BLE counterparty name shared across two different Funds (tests
  the linked-entity / shared counterparty-profile design, and the text-to-SQL
  "linked entities" use case)
- At least one Fund with a UBO chain unresolved beyond layer 2
- A spread of risk tiers across both Funds and BLEs (Low/Medium/High/Critical) —
  including at least one case where a BLE is Critical while the Fund's own
  direct factors would otherwise be Low, to validate escalation
- At least one document with an expiring/expired status

All entities, BLEs, and documents are tagged `synthetic_profile: true` or
`synthetic_static: true` at creation and this tag must be visibly surfaced in
the UI — never presented as fully real.

---

## 8. System Architecture

### 8.1 High-Level Flow

```
Ingestion -> Extraction (LLM) -> Embedding (local bge-base) -> pgvector
        -> Risk Rule Engine (deterministic, Fund + BLE level, with escalation)
        -> Trigger & Scoping (deterministic, Fund and/or BLE scope)
        -> Agent Orchestration (MCP tools + RAG) -> Generation (LLM)
        -> Guardrail/Eval Gate (LLM-as-judge) -> Command Centre
Parallel path: Text-to-SQL (constrained, read-only) for structured/portfolio queries
```

### 8.2 Backend Services (modular monolith)

- **Ingestion Service** — document upload, storage, metadata (Fund- or
  BLE-scoped)
- **Extraction Service** — LLM-based structured field pull from documents
  (cheap model tier)
- **Embedding Service** — self-hosted BAAI/bge-base-en-v1.5, writes to pgvector
- **Rule Engine Service** — deterministic risk scoring at both Fund and BLE
  level, versioned ruleset, escalation logic
- **Trigger/Scheduler Service** — deterministic detection of review triggers,
  scoped to Fund and/or BLE depending on trigger type
- **RAG Retrieval Service** — pgvector query, scoped filter (Fund or BLE)
  mandatory, never optional
- **MCP Tool Servers**:
  - OpenSanctions (screening/PEP — real, free; reused for both Fund UBOs and
    BLE counterparties)
  - Audit History (internal — last review date/outcome, Fund or BLE scoped)
  - Entity Relationships (Fund UBO links + shared BLE-counterparty links)
  - UBO Provider (mocked for demo; same interface as a future paid vendor)
- **Agent Orchestration Service** — bounded, fixed-toolset tool-calling per
  trigger type and scope
- **Text-to-SQL Service** — constrained NL→SQL generation, read-only DB role,
  query allowlisting
- **Eval Harness Service** — runs golden dataset, LLM-as-judge scoring
- **Workflow Handoff Service** — interface stub to external workflow engine
  (BLE-Product level)
- **Audit/Cost Logging Service** — logs every AI call: model, prompt version,
  tokens, cost, timestamp

### 8.3 Database (PostgreSQL + pgvector)

- `funds` — top-level entity record
- `bles` — `ble_id`, `parent_fund_id` (FK), `name`, `location`,
  `counterparty_profile_id` (FK)
- `counterparty_profiles` — shared identity/screening record for an
  institution, referenced by one or more `bles`
- `ble_products` — `product_id`, `ble_id` (FK), `product_type`,
  `workflow_template_id`
- `fund_documents`, `ble_documents` — document metadata, scoped accordingly
- `ubo_records` — Fund-level UBO chain
- `screening_results` — `scope` (`fund` | `counterparty`), `scope_id`
- `risk_scores` — `scope` (`fund` | `ble`), `scope_id`, versioned, FK to
  `ruleset_config`
- `ruleset_config` — versioned, per-client weights, applies to both scoring
  levels
- `review_audit_history`, `workflow_suggestions` — `scope` field (`fund` |
  `ble`)
- `document_embeddings` — pgvector, scoped metadata (Fund or BLE)
- `eval_runs`, `llm_call_log`

### 8.4 Frontend Modules

Command Centre shell · Fund Drilldown page (with BLE list) · BLE Drilldown page
(with Products and workflows) · Suggested Reviews queue · Copilot panel (RAG +
text-to-SQL hybrid) · Admin (ruleset builder + eval/guardrail dashboard).

**Frontend stack direction:** React + Tailwind, component-driven, citation-chip
and confidence-badge components shared across modules. Streaming responses for
Copilot answers.

---

## 9. Risk Scoring Engine (Deterministic — Never AI)

### 9.1 Two scoring levels

**BLE-level score** — computed from the BLE's own factors: counterparty
screening result, counterparty country, document completeness for that BLE.

**Fund-level score** — computed from the Fund's own direct factors (Fund UBO
chain, Fund-level PEP exposure, Fund incorporation country, Fund document
completeness), **plus an escalation rule**.

### 9.2 Default weights (per scoring level, configurable per client)

| Factor | Default Weight | Inputs |
|---|---|---|
| Country | 20% | Incorporation/operating country (Fund) or counterparty country (BLE) vs. FATF/Basel risk lists |
| Screening | 30% | Sanctions/PEP hit severity (OpenSanctions) |
| PEP | 20% | PEP tier of associated individuals |
| UBO | 20% | Ownership layers, % unresolved, high-risk jurisdiction in chain (Fund level only) |
| Documents | 10% | Completeness, expiry status |

### 9.3 Escalation rule

If any BLE under a Fund is scored Critical, the Fund is automatically surfaced
as Critical in the Command Centre and high-risk queues, regardless of the
Fund's own direct-factor score. The underlying Fund-level score is still shown
separately (e.g., "Fund direct score: Medium — escalated to Critical due to BLE:
ICBC, Noida") so the reason is never obscured.

**Hard-stop override (both levels):** a confirmed sanctions hit on a Fund UBO or
a BLE counterparty auto-escalates that scope to Critical regardless of weighted
total.

All scores are versioned against the ruleset that produced them
(`ruleset_version`) for full audit reproducibility, at both scoring levels.

---

## 10. Periodic Review & Trigger Engine

Deterministic triggers (no AI in detection), each carrying an explicit scope:

| Trigger | Scope |
|---|---|
| Risk tier change (either direction) | Fund or BLE, whichever changed |
| New sanctions/PEP hit | Fund (on UBO) or BLE (on counterparty) |
| Adverse media severity/volume change (AI-assisted classification only) | Fund or BLE |
| UBO/ownership structure change crossing threshold | Fund |
| Document expiry | Fund or BLE, whichever document |
| Country/jurisdiction risk reclassification | Fund or BLE |
| Linked-entity / shared-counterparty contagion | Both — a shared counterparty escalation cascades to every Fund referencing it |
| BLE escalates to Critical | Cascades a Fund-level suggested review automatically |
| SLA breach on a scheduled review | Fund or BLE, whichever was due |

---

## 11. Suggested Reviews Workflow (Human-in-the-Loop)

1. Trigger fires (deterministic) at its appropriate scope → Fund or BLE id
   queued, with scope recorded
2. Agent Orchestration gathers context: `get_audit_history()`,
   `get_live_screening_status()` (OpenSanctions), scoped RAG ("what changed
   since last review")
3. Structured suggestion card assembled — scope (Fund/BLE), trigger reason,
   last review context, grounded "what changed" summary
4. PR Analyst reviews queue, **bulk Accept/Decline**, scope visible per row
5. Accept → id + scope + trigger context + suggested workflow template handed
   to workflow engine (reference view only in demo)
6. Every suggestion (accepted, declined, or expired) logged for audit — decline
   patterns inform future threshold tuning, per scope

---

## 12. AI Use Case Summary — What Uses AI and What Doesn't

| Capability | Technique | AI? |
|---|---|---|
| Risk score computation (Fund and BLE) | Rule engine | **No — deterministic** |
| Escalation logic (BLE → Fund) | Rule engine | **No — deterministic** |
| Trigger detection (either scope) | Rule engine | **No — deterministic** |
| Final approval/escalation decision | Human | **No — human only** |
| UBO percentage math/threshold checks | Code (graph traversal) | **No — deterministic** |
| Document field extraction | LLM (cheap tier) | Yes |
| Entity-scoped document Q&A | RAG | Yes |
| Adverse media novelty/severity classification | LLM (cheap tier) | Yes |
| Portfolio-level structured questions | Text-to-SQL | Yes (generation only) |
| Analyst report narrative draft | LLM (stronger tier), human-approved | Yes |
| Output quality gating | LLM-as-judge | Yes |

---

## 13. UI Wireframes

### 13.1 Command Centre
```
COMMAND CENTRE                              [Filters] [Refresh]
Portfolio Pulse: 50 Funds | 5 live-tracked | 38 High/Critical (Fund or BLE)
[Risk distribution chart]   [30-day trend]
----------------------------------------------------------
High-Risk Queue   Fund | BLE (if escalated) | Tier | Score | Trigger | ->
 Manalappam Fund  | ICBC, Noida (Critical)  | Critical | 91 | Sanctions | -> Drilldown
```

### 13.2 Fund Drilldown Page
```
< Back   Manalappam Fund
Fund Direct Score: MEDIUM (58)   Escalated: CRITICAL (BLE: ICBC, Noida)
Ruleset v4
------------------------------------------------------------
FUND PROFILE
  Incorp: [Country] | UBO chain: [n] layers, [resolved/unresolved]
------------------------------------------------------------
BLEs UNDER THIS FUND                          [+ Add BLE]
  ICBC, Noida   CRITICAL (91)  Sanctions hit  -> BLE Drilldown
  ICBC, Gurgaon MEDIUM (54)    Clean          -> BLE Drilldown
------------------------------------------------------------
FUND DOCUMENTS                              [Upload Document]
  Incorporation Cert  verified, embedded
  UBO Declaration     verified, embedded
------------------------------------------------------------
RAG INSIGHTS (Fund-scoped, citation-grounded)
  Ask: "What does the UBO declaration say about ownership %?"
------------------------------------------------------------
[View Risk Breakdown]   [View Analyst Report]
```

### 13.2b BLE Drilldown Page (new)
```
< Back to Manalappam Fund   BLE: ICBC, Noida          [Real: OpenSanctions]
Tier: CRITICAL (91)   Ruleset v4
------------------------------------------------------------
COUNTERPARTY PROFILE
  Institution: ICBC | Location: Noida | Screening: Sanctions hit (real)
------------------------------------------------------------
PRODUCTS UNDER THIS BLE                       [+ Add Product]
  Product: Loan — Workflow: BLE Loan Onboarding v2
   Steps: 1 KYC Docs (done) 2 Screening Check (done, OpenSanctions)
          3 Compliance Sign-off (pending)
   Tasks: Assigned J.Smith, Due Jun 25
  (Read-only reference view - workflow execution is external)
------------------------------------------------------------
BLE DOCUMENTS                                [Upload Document]
  Counterparty Agreement   verified, embedded
------------------------------------------------------------
[View Risk Breakdown]   [View Analyst Report]
```

### 13.3 Analyst Report (Fund or BLE scope)
```
[Scope: Fund | BLE] Manalappam Fund / ICBC, Noida - CRITICAL (91)
Generated Jun 19, Ruleset v4
EXECUTIVE SUMMARY (grounded narrative, citations)
RISK FACTOR BREAKDOWN (Country/Screening/PEP/UBO/Docs bars)
ESCALATION CONTEXT (if Fund: which BLE caused escalation, if any)
ADVERSE MEDIA / SCREENING (cited findings)
DOCUMENT STATUS
RECOMMENDED ACTION (AI-suggested) [Accept] [Edit] [Reject]
Audit footer: trigger, docs used, retrieval method, judge score
```

### 13.4 Suggested Reviews Queue
```
SUGGESTED PERIODIC REVIEWS              [Select All] [Bulk]
Scope | Fund/BLE | Trigger | Last Review | What Changed | Accept/Decline
BLE   | ICBC, Noida | Sanctions hit | Mar 2026 | [summary] | [accept][decline]
Fund  | Manalappam  | BLE escalation cascade | n/a | [summary] | [accept][decline]
```

### 13.5 Copilot / Ask Panel
```
ASK
"Which Funds have a Critical BLE under them?"
 Routed via: Text-to-SQL
 -> Manalappam Fund (via ICBC, Noida, sanctions hit)
"What changed in ICBC Noida's screening status last month?"
 Routed via: RAG (BLE-scoped)
 -> [Grounded answer with citation chips]
```

### 13.6 Admin: Ruleset Builder
```
RISK RUBRIC - Ruleset v4                              [Publish]
Applies to: ( ) Fund level  ( ) BLE level  ( ) Both
Country [20%]  Screening [30%]  PEP [20%]  UBO [20%]  Docs [10%]
Hard-stop: Sanctions hit -> auto-Critical [enabled]
Escalation: BLE Critical -> Fund surfaced Critical [enabled]
```

### 13.7 Eval/Guardrail Ops Dashboard
```
AI GUARDRAIL STATUS
Last run: 5 Funds, 8 BLEs | Avg groundedness: 0.91
Flagged (below threshold): 0 | Cost this run: $X.XX
Text-to-SQL queries blocked by guardrail: 0
```

---

## 14. Embeddings

- **Model:** `BAAI/bge-base-en-v1.5`, self-hosted (e.g., via
  `sentence-transformers`)
- **Why:** zero per-call cost, no metering risk, removes embeddings entirely
  from Anthropic credit exposure; quality is sufficient at demo scale
- **Storage:** pgvector, with `scope` + `scope_id` (Fund or BLE) stored as
  mandatory metadata on every chunk — retrieval is always scoped, cross-scope
  retrieval is a hard failure condition

---

## 15. Eval Harness & Golden Dataset

### 15.1 Dataset
5 live Funds and their BLEs/documents carry the full golden set. The 45 static
Funds never enter any golden set.

### 15.2 Eval Categories

| # | Eval | Golden Set Size | Metric | Pass Bar |
|---|---|---|---|---|
| A | Extraction accuracy | ~10–12 examples | Field-level exact/tolerance match | ≥95% |
| B | Retrieval quality (bge-base) | ~8 per scoped entity | Precision@3, zero cross-scope leakage | Top-3 correct; leakage = hard fail |
| C | RAG groundedness | ~6 per documented scope | LLM-as-judge, 1–5 | ≥4/5 avg, zero hallucinated claims |
| D | Text-to-SQL correctness | ~8–10 | Result-set exact match | 100%; adversarial inputs blocked |
| E | Trigger detection + escalation | Scenario-based, incl. BLE→Fund cascade | Unit test pass/fail | 100%, zero flakiness |
| F | MCP tool-selection accuracy | ~8 scenarios | Exact match on tool(s) called | 100% |
| G | LLM-as-judge calibration | 15–20 sampled | Human/judge agreement rate | Defined before judge trusted as gate |

### 15.3 Harness Mechanics
- Runs on every prompt/model change and before any demo run
- Logs pass/fail, score, cost of the eval run itself, and latency
- Hard regression gate — failing category blocks that AI surface from "publish"
- Judge calls use the cheapest viable model tier
- Eval runs are idempotent/cached — no re-spend on unchanged source

---

## 16. Cost Table

| Component | Cost Tier |
|---|---|
| Rule engine, triggers, dashboards, graph queries | Free |
| OpenSanctions screening (MCP, Fund UBOs + BLE counterparties) | Free (non-commercial demo use) |
| Embeddings (self-hosted bge-base) | Free |
| Extraction, text-to-SQL generation, tool selection | Negligible |
| Narrative generation (5 live Funds + their BLEs only) | Moderate, bounded by demo scope |
| LLM-as-judge | Moderate, sampled not exhaustive |
| Copilot ad-hoc queries | Variable, usage-driven |

---

## 17. Cost Engineering — Credit Protection (Non-Negotiable Build Requirements)

- **Mock mode** for all dev/test — `MOCK=true` flag routes around real API calls
- **Idempotency** — every job checks "already processed at this version"
- **Hard per-run budget cap** — orchestration tracks cumulative spend, hard-stops
- **Bounded retries** — max 1–2, exponential backoff, never unbounded
- **Fail fast on bad input** — validate before calling out
- **Status field per doc/Fund/BLE** (`extracted`, `embedded`, `summarized`)
- **Counterparty profile reuse** — a shared BLE counterparty (e.g., ICBC across
  two BLEs) is screened once, not once per BLE, avoiding duplicate calls
- **Cost logged per call**, visible in the Eval/Guardrail dashboard same-day
- **Demo scope hard-locked in code** — only the 5 designated live Fund ids (and
  their BLEs) can trigger any LLM call; the 45 static Funds are physically
  incapable of it

---

## 18. Regulatory & Compliance Guardrails

- **Explainability** — every risk score (Fund or BLE) traceable to a versioned
  ruleset; escalation reasons always shown, never silently rolled up
- **Human-in-the-loop** — no AI output auto-publishes a decision at either scope
- **Audit trail** — every AI call and human decision logged
- **Read-only data access** — text-to-SQL via read-only DB role with allowlisting
- **Scope isolation** — retrieval/generation hard-scoped to the Fund or BLE in
  question; cross-scope leakage is a hard failure, tested adversarially
- **PII handling** — UBO names, PEP status, screening hits access-controlled
- **Vendor swap safety** — OpenSanctions MCP interface identical to a future
  paid vendor's, for both Fund and BLE screening
- **Guardrail gate** — LLM-as-judge groundedness threshold required before any
  narrative reaches the Command Centre
- **Data labeling integrity** — real vs. synthetic visibly tagged at all times;
  a real screening match never implies a fabricated business profile around it
- **No fabricated facts about real positive matches** — beyond the screening
  result itself, no system-generated content may assert specific business facts
  about a name that returns a genuine match (Section 7.2)

---

## 19. QA & Testing Plan (Post-Build, Against This PRD)

1. Traceability matrix — every requirement mapped to a test/eval, scope-aware
   (Fund vs. BLE) where applicable
2. Functional/unit testing — rule engine (both scoring levels + escalation),
   trigger logic, workflow handoff stub, DB queries
3. AI eval regression — golden dataset (Section 15) cleared before sign-off
4. Guardrail/security testing — read-only role, query allowlist, scope-isolation
   under adversarial queries
5. LLM-as-judge calibration check
6. UAT — Command Centre, Fund Drilldown, BLE Drilldown, Suggested Reviews,
   Analyst Report walked through against usability requirements
7. Cost/performance testing against Section 16/17 budget expectations
8. Final sign-off — every requirement marked pass/fail/deferred

---

## 20. Out of Scope (This Phase)

- Paid screening/UBO vendors (Moody's, ComplyAdvantage, Orbis)
- Real external workflow engine execution
- Multi-tenant configuration UI
- Production-scale data volume and event-driven infrastructure
- Graph database (Neo4j) — relational queries sufficient at this scale

---

## 21. Open Assumptions & Risks

- OpenSanctions free-tier API key valid for the demo window (30-day trial
  confirmed; revisit if demo timeline extends)
- Fund → BLE → Product hierarchy and escalation rule are now locked decisions
  (this changelog); document checklists per BLE-Product combination to be
  confirmed with compliance SMEs before workflow templates are finalized
- Self-hosted embedding quality assumed sufficient at this scale — validated
  via Eval B before being trusted further
- External workflow engine integration point is a stub in this phase
- Whether Fund-level UBO screening results should independently contribute to
  BLE escalation (vs. only BLE→Fund) is not yet addressed — current design is
  one-directional (BLE escalates Fund, not the reverse) and should be revisited
  if a real-world case requires it

---

*End of PRD v2.0*
