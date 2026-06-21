# Eval Labeling & Document Authoring Guide — Low-Effort Workflow

## The core trick (read this first)

Ground truth for a synthetic golden dataset doesn't have to come from independent
human research. It can come from **the seed data that defines the synthetic
entity in the first place** — because *you already know the right answer*, you
(or Claude Code, on your instruction) wrote it when the Fund/BLE/UBO was
invented. Your job shifts from "author the answer key" to "verify Claude Code's
output matches the input it was given." That's a fast review, not a slow
derivation.

**Important caveat — this shortcut has a shelf life.** It works because the data
is synthetic and was generated to spec. Once this product handles real future
entities and real future documents, nobody will have "written" the correct
answer in advance — that's when true independent human verification becomes
necessary again. Treat this guide as specific to the demo/golden-seed phase.

---

## Step 0 — Lock in `seed_truth.json` before anything else

Before Phase 2 finishes, make sure Claude Code saves a single structured file
that is the master record of every fact used to generate the 5 live Funds, their
BLEs, and their documents — separate from the documents themselves.

**Prompt to give Claude Code (insert into Phase 2, before declaring it done):**
```
Before finishing Phase 2, write all the synthetic ground-truth values you used
to generate the 5 live Funds, their BLEs, Products, UBO chains, and documents
into a single file: /evals/seed_truth.json. Structure it as one record per
Fund/BLE, with every field a document or extraction step might reference
(UBO name, ownership %, country, incorporation date, counterparty name,
screening result, document type, etc.) This file is the source of truth for
all golden datasets going forward — do not let it drift from the documents you
generate from it.
```

This file is what makes everything below fast.

---

## 1. Authoring the synthetic documents

**What changes:** this is almost entirely Claude Code's work. Documents are
*generated from* `seed_truth.json`, not independently written — there's no
"correct answer" to verify here, just a templating job.

**Prompt:**
```
Generate the document files (Incorporation Cert, UBO Declaration, Bank
Reference, Counterparty Agreement, etc.) for the 5 live Funds and their BLEs,
populated entirely from /evals/seed_truth.json. Use realistic boilerplate
language. Per PRD Section 7.4, deliberately introduce the required
imperfections (one missing field, one inconsistent date, one mismatched
percentage between two documents) and note exactly where you placed each one
in BUILD_LOG.md.
```

**Your review (10–15 min total):** open each generated document, skim it against
the corresponding entry in `seed_truth.json`, confirm it reads naturally and the
deliberate imperfections are actually present. You're proofreading, not writing.

---

## 2. Eval A — Extraction ground truth

**What changes:** the "expected extraction" for each document is just the
relevant fields already sitting in `seed_truth.json` — Claude Code can draft the
full golden set without you writing a single expected value from scratch.

**Prompt (use when Phase 6 starts):**
```
Build /evals/golden_extraction.jsonl. For each of the 10-12 documents selected
for Eval A, create one entry: {doc_id, expected_fields: {...}}, where every
expected value is copied directly from /evals/seed_truth.json — not
re-derived, not guessed. Show me the file as a table before we wire it into
the eval harness.
```

**Your review checklist (per row, ~1 min each, ~12 min total):**
- Open the source document
- Confirm the expected value actually appears in the document text as written
  (this catches a templating bug, not a labeling error)
- Tick approve, or flag a mismatch for Claude Code to fix

---

## 3. Eval C — Grounded Q&A with citations

**What changes:** the correct answer to "what does the UBO declaration say
about ownership %" is, again, already in `seed_truth.json`. Claude Code can
draft question + answer + citation location directly from it.

**Prompt (use when Phase 8 starts):**
```
Build /evals/golden_qa.jsonl. For each documented Fund/BLE, draft 6
question/answer pairs where the answer is taken directly from
/evals/seed_truth.json, and identify the exact section/paragraph of the
generated document that supports it as the citation. Do not generate the
answer by running extraction or RAG on the document — derive it from the seed
data, then locate it in the document text. Show me the drafted set before we
wire it in.
```

**Your review checklist (~1–2 min each, ~30–40 min total for ~30 pairs):**
- Read the question
- Open the cited section of the document
- Confirm the citation actually supports the stated answer (this is the one
  thing only you can verify — Claude Code locating its own citation correctly
  is exactly what's being tested)
- Tick approve, or correct the citation/answer

---

## 4. Eval D — Text-to-SQL correct results

**What changes:** once the seed data is fixed, the correct answer to a
portfolio question ("which Funds have a Critical BLE under them") is
computable directly from that same seed data with a small deterministic
script — not something you work out by hand.

**Prompt (use when Phase 9 starts):**
```
Build /evals/golden_sql.jsonl. Draft 8-10 natural-language questions a
compliance analyst might ask (include at least one that requires joining
Fund -> BLE -> Product). For each, write a small script that computes the
correct result directly from the seeded database state (not via an LLM call),
and store the question alongside that computed result. Show me the questions
and computed results in a table before we wire it in.
```

**Your review checklist (~2 min each, ~15–20 min total):**
- Read the question
- Sanity-check the computed result against what you know was seeded (e.g.,
  "yes, this should include Manalappam Fund because of the ICBC Noida hit")
- You're spot-checking plausibility, not re-running the query yourself

---

## Putting an approved golden set in front of the eval harness

Once you've reviewed and approved (or corrected) a file, tell Claude Code:
```
I've reviewed and approved /evals/golden_extraction.jsonl [or golden_qa.jsonl
/ golden_sql.jsonl]. Wire it into the Eval Harness Service and run it now.
Report the pass/fail result per PRD Section 15.2's bar before we proceed.
```

---

## Realistic total time, with this workflow

| Task | Without this workflow | With this workflow |
|---|---|---|
| Document authoring | Hours | ~10–15 min review |
| Eval A | 1–2 hrs | ~12 min review |
| Eval C | 2–3 hrs | ~30–40 min review |
| Eval D | 1–2 hrs | ~15–20 min review |
| **Total** | **5–8+ hrs** | **~1–1.5 hrs**, spread across the relevant phases |

You're still the final check on everything — nothing publishes without your
approval — but the heavy lifting of drafting moves to Claude Code, and your job
narrows to verifying its output against data you already locked in.
