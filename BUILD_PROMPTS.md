# Claude Code Build Prompts — Use in Sequence

How to use this file: copy each prompt into Claude Code **in order**, one phase
at a time. Wait for Claude Code to confirm completion (and for you to review the
diff) before moving to the next prompt. Do not skip ahead.

Place `PRD.md` and `CLAUDE.md` (provided separately) at your project root before
Session 0. Both reflect the corrected Fund -> BLE -> Product hierarchy with
two-level risk scoring and escalation.

---

## SESSION 0 — Bootstrap (no product code yet)

```
Read /PRD.md fully before doing anything else. This is a regulatory/compliance
financial product (KYB) covering Funds, their BLEs (banking/counterparty
relationships), and BLE-level Products. Accuracy, auditability, and cost
control matter more than speed.

Do the following, in order, and stop for my confirmation after each step:

1. Confirm you've read and understood PRD.md by summarizing back to me, in
   your own words: (a) the Fund -> BLE -> Product hierarchy and why a BLE is
   its own scored, screened record rather than a tag on the Fund (Section 5,
   7), (b) the two-level risk scoring and escalation rule (Section 9), (c)
   which capabilities are deterministic vs. AI (Section 12), (d) the
   cost-protection rules including counterparty profile reuse (Section 17).
2. Propose a project folder structure reflecting the modular service
   boundaries in Section 8.2.
3. Confirm CLAUDE.md is present at the project root and that you will treat
   it as binding for all future sessions.
4. Create a BUILD_LOG.md file to track progress phase by phase.

Do not write any product/business logic code yet. Wait for my next prompt.
```

---

## PHASE 1 — Database schema + deterministic core (Fund + BLE + escalation)

```
Per PRD.md Section 8.3, implement the database schema (PostgreSQL + pgvector),
including the Fund -> BLE -> Product hierarchy: funds, bles (with
parent_fund_id and counterparty_profile_id), counterparty_profiles,
ble_products, and the scope-aware risk_scores and screening_results tables.

Per Section 9, implement the Risk Rule Engine as deterministic code:
- A BLE-level scoring function (its own weighted factors).
- A Fund-level scoring function (its own direct factors).
- The escalation rule: if any BLE under a Fund is Critical, the Fund surfaces
  as Critical, while still showing its own direct-factor score separately.
- The hard-stop override at both levels for confirmed sanctions hits.

Per Section 10, implement the Trigger & Scoping engine as deterministic code,
covering every trigger type and its correct scope (Fund, BLE, or both) per the
table in that section — including the BLE-Critical-cascades-Fund-review
trigger.

Constraints:
- Zero LLM calls anywhere in this phase.
- Write unit tests for: BLE scoring, Fund scoring, the escalation rule
  specifically (including the case where a BLE is Critical while the Fund's
  own direct factors are Low), and trigger detection at both scopes.
- Update BUILD_LOG.md when done. Wait for my confirmation before Phase 2.
```

---

## PHASE 2 — Synthetic and real-signal demo data

```
Per PRD.md Section 7, build the data seeding script for the Fund -> BLE ->
Product hierarchy:

- 45 fully synthetic Funds, tagged synthetic_static: true, spread across risk
  tiers, each with 0-1 simple BLEs (kept minimal — these are dashboard-scale
  only and must never be capable of triggering an LLM or embedding call).
- 5 live Funds, fully fictional Fund names/profiles, each with 1-2 BLEs and
  1-2 Products per BLE. For each BLE's counterparty name, make a real,
  free-tier OpenSanctions API call (via MCP) — this is real regardless of
  whether the name returns a match.

Required test cases across the 5 live Funds' BLEs:
- At least one BLE counterparty name that returns a real positive match on
  OpenSanctions (demonstrates the true-positive path and triggers the
  escalation rule end-to-end).
- At least one BLE counterparty shared across two different Funds, modeled as
  one counterparty_profiles record referenced by both bles records (tests
  shared-counterparty screening reuse and the linked-entity use case).
- At least one Fund with a UBO chain unresolved beyond layer 2.
- At least one document with an expiring/expired status.

Hard rule, per PRD Section 7.2 and CLAUDE.md rule 9: regardless of whether a
BLE counterparty name returns a real positive match, all structural and
document content (incorporation details, ownership percentages, workflow
data) must be synthetic. Do not generate any fabricated specific business
fact attributed to a name that returns a real positive match, beyond the
match result itself.

Enforce in code that synthetic_static Funds can never trigger an LLM or
embedding call downstream. Write a test that proves this.

Show me the seeded data summary, including which BLE counterparty produced
the real positive match, before moving on.
```

---

## PHASE 3 — Cost & mock-mode infrastructure (before any real API wiring)

```
Per PRD.md Section 17, before any phase wires a real Anthropic API or
embedding call, implement:

- A MOCK=true flag that routes all LLM/embedding calls to local mocks during
  dev and test, on by default.
- Idempotency checks per Fund and per BLE.
- A hard per-run budget cap in the orchestration layer.
- Bounded retries (max 2, exponential backoff) and fail-fast input validation.
- Per-call cost logging.
- Counterparty profile reuse: confirm that a shared counterparty (referenced
  by multiple BLEs) is only ever screened once, not once per BLE — write a
  test that proves a duplicate screening call is never made for the same
  counterparty_profiles record.

Confirm with me before proceeding to Phase 4.
```

---

## PHASE 4 — Embeddings

```
Implement the Embedding Service using self-hosted BAAI/bge-base-en-v1.5 via
sentence-transformers, writing vectors to pgvector with scope (fund | ble) and
scope_id stored as mandatory metadata on every chunk. No external embedding
API calls.

Write a test that asserts retrieval queries always filter by scope + scope_id
and that cross-scope results (e.g., a BLE document leaking into a different
Fund's or BLE's retrieval) are never returned under any query.
```

---

## PHASE 5 — MCP tool servers

```
Implement the MCP tool servers per PRD Section 8.2:
- OpenSanctions (real, free) — reusable for both Fund UBO screening and BLE
  counterparty screening, taking a scope parameter.
- Audit History (internal) — scoped to Fund or BLE.
- Entity Relationships — Fund UBO links plus shared-counterparty links across
  BLEs.
- UBO Provider — mocked for now, same interface as a future paid vendor.

Use MOCK=true for all testing except live OpenSanctions calls, which are free.
```

---

## PHASE 6 — Extraction Service (first real Anthropic API usage)

```
Implement the Extraction Service per PRD Section 8.2 — structured field
extraction from the 5 live Funds' and their BLEs' documents, using the
cheapest viable Claude model tier.

Before marking this phase done:
1. Build the Eval A golden dataset per Section 15.2 — 10-12 hand-labeled
   examples across Fund and BLE documents.
2. Run the eval. Confirm extraction accuracy meets the >=95% bar.
Do not proceed to Phase 7 if this gate fails.
```

---

## PHASE 7 — RAG retrieval + Eval B

```
Implement the RAG Retrieval Service on top of the scoped pgvector store from
Phase 4. Build the Eval B golden dataset (~8 question/expected-chunk pairs per
documented Fund/BLE). Confirm precision@3 and zero cross-scope leakage before
proceeding to Phase 8.
```

---

## PHASE 8 — Narrative generation + LLM-as-judge guardrail gate

```
Implement narrative generation (analyst report drafting) for both Fund and BLE
scope, using a stronger Claude model tier, with a mandatory citation for every
factual claim. For Fund-scope reports where escalation has occurred, include
the escalation context (which BLE caused it) explicitly.

Implement the LLM-as-judge guardrail gate per Section 15.2 (Eval C). Build the
Eval C golden dataset and confirm the >=4/5 pass bar with zero tolerated
hallucinated claims before proceeding.
```

---

## PHASE 9 — Text-to-SQL + adversarial safety testing

```
Implement the Text-to-SQL Service: read-only DB role, query allowlisting, no
DDL/DML ever reachable. Build the Eval D golden dataset, including at least
one question that requires joining across the Fund -> BLE -> Product
hierarchy (e.g., "which Funds have a Critical BLE under them").

Run adversarial test cases — attempts to bypass Fund/BLE scope, attempts at
destructive queries — and confirm every one is blocked before this phase is
considered complete.
```

---

## PHASE 10 — Agent orchestration + Suggested Reviews workflow

```
Implement the Agent Orchestration Service and the Suggested Reviews workflow
per PRD Section 11, scope-aware throughout: trigger fires at Fund or BLE scope
-> bounded tool-calling -> structured suggestion card showing scope -> bulk
Accept/Decline -> audit log entry per scope.

Specifically implement the escalation cascade: when a BLE trigger results in
that BLE going Critical, automatically generate a corresponding Fund-level
suggested review entry referencing the cascading BLE.

Build the Eval F golden dataset (tool-selection accuracy) and confirm 100%
match before proceeding.
```

---

## PHASE 11 — Frontend

```
Build the frontend per all wireframes in PRD Section 13:
- Command Centre (13.1) — surfacing BLE-level criticals even when a Fund's
  own rollup looks fine.
- Fund Drilldown (13.2) — including the BLE list with each BLE's own
  tier/score, and the Fund's direct score vs. escalated score shown
  separately when applicable.
- BLE Drilldown (13.2b, new) — counterparty profile, Products with workflow
  reference view, BLE-scoped documents and RAG insights.
- Suggested Reviews queue (13.4) — with the scope column (Fund/BLE).
- Copilot/Ask panel (13.5) — RAG + text-to-SQL hybrid, with citations.
- Admin ruleset builder (13.6) — including the escalation toggle.
- Eval/Guardrail ops dashboard (13.7).

Wire it to the real backend for the 5 live Funds (and their BLEs) and to
seeded data for the 45 static Funds. Include the "Real: OpenSanctions" badge
on any BLE whose counterparty was screened live, per Section 7.

Use React + Tailwind per Section 8.4.
```

---

## PHASE 12 — Full QA pass

```
Per PRD Section 19, build the requirement-to-test traceability matrix,
scope-aware (Fund vs. BLE) where applicable. Run the full eval suite (A-G),
explicitly including the escalation cascade test in Eval E. Run all
guardrail/security tests from Section 18, including the no-fabricated-facts
rule for real positive screening matches. Produce a pass/fail/deferred report.

Do not consider the build complete until this report exists and we've
reviewed it together.
```

---

## Notes for any session not covered above

If I give you a new instruction mid-build that isn't one of these phases:
reference the relevant PRD section explicitly, confirm whether it affects Fund
scope, BLE scope, or both, confirm which module(s) it touches, and ask before
modifying anything outside that scope.
