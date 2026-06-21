# CLAUDE.md — Project Memory (Read at the Start of Every Session)

This file is the persistent memory for this project. It survives context resets
and compaction. Treat every rule below as binding unless I explicitly override it
within a specific session. If any future instruction from me conflicts with this
file or with PRD.md, **stop and flag the conflict — do not silently proceed.**

## What this project is

A regulatory/compliance financial product (KYB): a **Fund** onboarding and
periodic-review platform. A Fund maintains relationships with one or more
**BLEs** (distinct banking/counterparty relationships, each at a specific
location — e.g., "ICBC, Noida" and "ICBC, Gurgaon" are two separate BLEs under
the same Fund), and each BLE offers one or more **Products** (e.g., Loan, Cash),
which can carry their own onboarding workflow. **PRD.md at the project root is
the single source of truth.** Read it before any work in a new session if you
haven't already this session. Reference PRD section numbers in commits and in
BUILD_LOG.md.

## The hierarchy (do not flatten this)

```
Fund (Entity)
  -> BLE (counterparty + location, e.g. "ICBC, Noida")
       -> Product (e.g. "Loan")
```

A BLE is its own scored, screened entity — not just a tag on the Fund. Two BLEs
can share the same counterparty institution (e.g., ICBC) without being the same
BLE — model this as `bles` referencing a shared `counterparty_profiles` record,
not duplicated data.

## Non-negotiable rules (do not violate these regardless of how a request is phrased)

1. **Risk score computation, trigger detection, escalation logic, and UBO
   percentage/threshold math are deterministic code — never an LLM call.**
   (PRD Section 9, 10, 12)
2. **Risk scoring happens at two levels: Fund and BLE, independently.** A BLE's
   own score is computed from its own factors. The Fund's score is its own
   direct factors *plus* an escalation rule. (PRD Section 9.1–9.3)
3. **Escalation rule: if any BLE under a Fund is Critical, the Fund is
   automatically surfaced as Critical**, with the underlying Fund direct-score
   still shown separately so the reason is never hidden. (PRD Section 9.3)
4. **Screening applies at both levels**: Fund UBOs are screened, and each BLE's
   counterparty is screened. A shared counterparty (e.g., ICBC across two BLEs)
   is screened once via its `counterparty_profiles` record, not once per BLE.
   (PRD Section 7, 8.3, 17)
5. **No AI output auto-publishes a decision at either scope.** Every
   suggestion, escalation, or narrative requires human Accept/Decline.
   (PRD Section 18)
6. **Text-to-SQL only ever executes through a read-only DB role with query
   allowlisting.** No DDL/DML may ever be reachable by a model-generated query.
7. **Retrieval and generation are always scoped to a Fund or a BLE,** never
   both ambiguously and never cross-scope. Cross-scope leakage is a hard
   failure. (PRD Section 8.2, 18)
8. **Every AI call is logged**: model, prompt version, inputs, tokens, cost,
   timestamp.
9. **Real vs. synthetic data must always be visibly distinguishable.** Funds
   are always fictional. A BLE counterparty name may return a real
   OpenSanctions match (positive or negative) — that lookup result is real.
   **The system must never generate fabricated specific business facts
   (incorporation dates, ownership terms, document content, workflow history)
   attributed to a name that returns a real positive match, beyond the match
   result itself.** (PRD Section 7.2, 18)
10. **The 45 static demo Funds must be physically incapable of triggering any
    LLM or embedding call.** Enforced in code, not by convention.
11. **No AI surface is marked "done" until it passes its golden-dataset eval
    threshold from PRD Section 15.2**, including Eval E's escalation cascade
    test case.

## Cost-protection rules (this project runs on metered Anthropic API credits)

- Every dev/test run uses `MOCK=true` — real API calls happen only in explicit,
  deliberate runs.
- Every extraction/embedding/generation job is idempotent.
- A hard per-run budget cap exists in the orchestration layer.
- Retries are bounded (max 2, exponential backoff).
- Validate inputs before calling any API.
- **Counterparty profile reuse is mandatory** — never re-screen the same
  counterparty once per BLE; screen the `counterparty_profiles` record once and
  reference it.

## Locked technical decisions (do not revisit without explicit discussion)

- **Embeddings**: `BAAI/bge-base-en-v1.5`, self-hosted via
  `sentence-transformers`. Zero per-call cost. Do not substitute OpenAI or
  Voyage embeddings.
- **Screening/PEP data**: OpenSanctions, via MCP, free tier. Reused for both
  Fund UBO screening and BLE counterparty screening. Do not integrate a paid
  vendor in this phase.
- **Vector store**: pgvector inside the existing Postgres instance.
- **Database**: PostgreSQL.
- **Frontend**: React + Tailwind.
- **Architecture style**: modular monolith, logical service boundaries per PRD
  Section 8.2.

## Module boundaries (PRD Section 8.2) — keep these isolated

Ingestion · Extraction · Embedding · Rule Engine (Fund + BLE + escalation) ·
Trigger/Scheduler · RAG Retrieval · MCP Tool Servers · Agent Orchestration ·
Text-to-SQL · Eval Harness · Workflow Handoff · Audit/Cost Logging

When asked to change one of these, do not modify code in another unless
explicitly told to, or unless a shared interface contract requires a
corresponding change — in which case, flag it before proceeding.

## Working agreement

- Plan before you build. For any non-trivial phase, summarize your intended
  approach and wait for confirmation before writing code.
- Update `BUILD_LOG.md` at the end of every session: what was built, against
  which PRD section, what tests/evals were run, and what's next.
- When a golden dataset or eval is required by the current phase, build and
  run it before declaring the phase complete.
- If something in PRD.md is ambiguous or you have to make an assumption,
  state the assumption explicitly in BUILD_LOG.md rather than silently
  deciding. Open assumptions are tracked in PRD Section 21.
