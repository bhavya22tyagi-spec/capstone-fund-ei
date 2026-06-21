"""
Copilot router: RAG + text-to-SQL hybrid.

Routing heuristic (MOCK mode):
  - SQL keywords ("which", "how many", "list all", "count", "show me all") → text-to-sql
  - Otherwise → RAG

Both paths return a structured CopilotAnswer with answer text and citations.
In MOCK mode, canned answers are returned keyed on seed Fund/BLE data.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from api.data_loader import LIVE_FUNDS, LIVE_BLES
from api.deps import get_text_to_sql
from api.models import CitationItem, CopilotAnswer, CopilotRequest

MOCK: bool = os.getenv("MOCK", "true").lower() == "true"

_SEED_PATH = Path(__file__).parent.parent.parent / "evals" / "seed_truth.json"
_RAG_FALLBACK_MODEL = "claude-haiku-4-5-20251001"
_RAG_FALLBACK_VERSION = "rag-context-fallback-v1"


def _build_fund_context(fund_id: str, scope: str, scope_id: str) -> str:
    """Build structured context from fund/BLE data to inject into LLM prompt."""
    lines: list[str] = []

    if scope == "fund" and fund_id in LIVE_FUNDS:
        fund = LIVE_FUNDS[fund_id]
        lines.append(f"Fund: {fund['name']}")
        lines.append(f"Incorporation country: {fund.get('incorporation_country', 'unknown')}")
        lines.append(f"Direct risk tier: {fund.get('direct_tier', 'unknown')}")
        lines.append(f"Direct risk score: {fund.get('direct_score', 'unknown')}")
        if fund.get("escalated_tier"):
            lines.append(f"Escalated tier: {fund['escalated_tier']}")
            lines.append(f"Escalation reason: {fund.get('escalation_reason', '')}")

        fund_bles = [b for b in LIVE_BLES.values() if b.get("fund_id") == fund_id]
        if fund_bles:
            lines.append("\nBanking/Legal Entities (BLEs):")
            for ble in fund_bles:
                lines.append(f"  - {ble['name']}: tier={ble.get('tier')}, score={ble.get('score')}")

    elif scope == "ble" and scope_id in LIVE_BLES:
        ble = LIVE_BLES[scope_id]
        lines.append(f"BLE: {ble['name']}")
        lines.append(f"Risk tier: {ble.get('tier')}")
        lines.append(f"Risk score: {ble.get('score')}")
        if fund_id in LIVE_FUNDS:
            lines.append(f"Parent fund: {LIVE_FUNDS[fund_id]['name']}")

    try:
        with open(_SEED_PATH, encoding="utf-8") as fh:
            seed = json.load(fh)
        for fund_raw in seed.get("live_funds", []):
            if fund_raw["fund_id"] == fund_id:
                ubos = [u for u in fund_raw.get("ubos", []) if not u.get("name", "").startswith("[")]
                if ubos:
                    lines.append("\nUBO Chain:")
                    for u in ubos:
                        lines.append(f"  - {u['name']}: {u.get('ownership_pct', '?')}% ownership, PEP tier {u.get('pep_tier', 0)}")
                docs = fund_raw.get("documents", [])
                if docs:
                    lines.append("\nDocuments:")
                    for d in docs:
                        lines.append(f"  - {d.get('document_type')}: status={d.get('status')}, expiry={d.get('expiry_date', 'N/A')}")
                break
    except Exception:
        pass

    return "\n".join(lines) if lines else "No structured data available for this fund/BLE."


def _llm_context_answer(question: str, scope: str, scope_id: str, fund_id: str) -> tuple[str, list]:
    """Answer using LLM with injected fund context — fallback when embeddings unavailable."""
    from services.ai_client import call_llm
    from services.budget import BudgetCap

    context = _build_fund_context(fund_id, scope, scope_id)
    prompt = (
        "You are a compliance analyst assistant for a KYB (Know Your Business) platform. "
        "Answer the following question based ONLY on the structured data provided below. "
        "Do not invent facts not present in the data. Be concise and factual.\n\n"
        f"FUND/BLE DATA:\n{context}\n\n"
        f"QUESTION: {question}\n\n"
        "Answer:"
    )
    budget = BudgetCap(limit_usd=float(os.getenv("BUDGET_CAP_USD", "0.50")))
    result = call_llm(
        prompt=prompt,
        model=_RAG_FALLBACK_MODEL,
        prompt_version=_RAG_FALLBACK_VERSION,
        fund_id=fund_id,
        synthetic_static=False,
        scope=scope,
        scope_id=scope_id,
        budget=budget,
        estimated_cost_usd=0.002,
    )
    return result["content"], []
_MOCK_STREAM_DELAY: float = float(os.getenv("MOCK_STREAM_DELAY", "0.001"))

router = APIRouter()

_SQL_KEYWORDS = re.compile(
    r"\b(which|how many|list|count|show me all|all funds|all bles)\b", re.I
)

_DEFAULT_FUND_ID = "f0000001-f000-0000-0000-000000000001"
_DEFAULT_SCOPE_ID = _DEFAULT_FUND_ID

# ---------------------------------------------------------------------------
# Canned MOCK answers keyed on question keyword patterns
# ---------------------------------------------------------------------------
_MOCK_ANSWERS: list[tuple[re.Pattern, dict]] = [
    (
        re.compile(r"critical ble|critical banking|ble.*critical|critical.*ble", re.I),
        {
            "routing": "text-to-sql",
            "answer": (
                "1 Fund has a Critical BLE:\n\n"
                "• **Northgate Capital Partners LP** — BLE: Bank Rossiya (Moscow, Russia) "
                "[CRITICAL, score 100.0]\n  Confirmed sanctions hit (OFAC SDN + EU restrictive measures). "
                "Fund's own direct score is LOW (11), but BLE Critical triggers escalation per PRD §9.3."
            ),
            "sql": (
                "SELECT f.name AS fund_name, b.location, cp.institution_name,\n"
                "       rs.direct_tier AS ble_tier, rs.direct_score\n"
                "FROM funds f\n"
                "JOIN bles b ON b.parent_fund_id = f.fund_id\n"
                "JOIN counterparty_profiles cp ON cp.counterparty_id = b.counterparty_profile_id\n"
                "JOIN risk_scores rs ON rs.scope = 'ble' AND rs.scope_id = b.ble_id\n"
                "WHERE rs.direct_tier = 'critical'\n"
                "ORDER BY rs.direct_score DESC"
            ),
            "citations": [],
        },
    ),
    (
        re.compile(r"expired|expiry|expiring|overdue", re.I),
        {
            "routing": "text-to-sql",
            "answer": (
                "2 documents with expired or expiring status:\n\n"
                "• **Meridian Strategic Growth Trust** — Annual Report [expired, 2026-05-06]\n"
                "• **Harrington Private Capital** — Regulatory Licence [expiring 2026-07-08, within 18 days]"
            ),
            "sql": (
                "SELECT f.name AS fund_name, fd.document_type, fd.status, fd.expiry_date\n"
                "FROM fund_documents fd\n"
                "JOIN funds f ON f.fund_id = fd.fund_id\n"
                "WHERE fd.status IN ('expired') OR fd.expiry_date <= CURRENT_DATE + INTERVAL '30 days'\n"
                "ORDER BY fd.expiry_date"
            ),
            "citations": [],
        },
    ),
    (
        re.compile(r"bank rossiya|screening.*rossiya|rossiya.*screening|rossiya.*status", re.I),
        {
            "routing": "rag",
            "answer": (
                "Bank Rossiya (Moscow, Russia) has a **confirmed sanctions hit** under OFAC SDN "
                "and EU restrictive measures. The counterparty agreement (NCP-BR-2022-001) covers a "
                "USD 5,000,000 Loan facility. BLE risk score: 100.0 (CRITICAL, hard-stop). "
                "Escalation to Fund level (Northgate Capital Partners LP) is active per PRD §9.3."
            ),
            "sql": None,
            "citations": [
                {
                    "text": "Bank Rossiya is listed under OFAC SDN and EU Council Regulation "
                            "No 269/2014 as a restricted entity subject to asset freeze.",
                    "doc_id": "doc-f1-b1-counterparty-agreement",
                    "document_type": "Counterparty Agreement",
                },
                {
                    "text": "Confirmed sanctions hit recorded. hit_severity=confirmed, hit_type=sanctions.",
                    "doc_id": "screening-b0001001",
                    "document_type": "Screening Result",
                },
            ],
        },
    ),
    (
        re.compile(r"ubo|ownership|beneficial owner", re.I),
        {
            "routing": "rag",
            "answer": (
                "UBO chain findings across the 5 live Funds:\n\n"
                "• **Northgate Capital Partners LP** — 2 UBOs (John Richardson 70%, "
                "Cayman Ventures Ltd 30%). Fully resolved, PEP tier 0.\n"
                "• **Meridian Strategic Growth Trust** — UBO chain unresolved at layer 2. "
                "Meridian Holdings Ltd (60%) controls is unresolved beyond layer 1. "
                "Werner Mueller (effective 40% via EU Capital Partners SA) — PEP Tier 2.\n"
                "• **Harrington Private Capital** — Robert Harrington III (51%, PEP Tier 1 — "
                "Former Minister of Finance, Malta). Primary escalation driver."
            ),
            "sql": None,
            "citations": [
                {
                    "text": "Werner Mueller effective ownership: 40% via EU Capital Partners SA. "
                            "PEP designation: Senior Official, European Banking Supervisory Committee.",
                    "doc_id": "doc-f2-ubo-declaration",
                    "document_type": "UBO Declaration",
                },
            ],
        },
    ),
    (
        re.compile(r"high.?risk|risk.*fund|fund.*risk", re.I),
        {
            "routing": "text-to-sql",
            "answer": (
                "High and Critical risk Funds (by effective tier):\n\n"
                "• **Northgate Capital Partners LP** — CRITICAL (escalated; direct LOW)\n"
                "• **Harrington Private Capital** — HIGH (direct score 51.5)\n\n"
                "38 of 50 funds (incl. static) are High or Critical tier."
            ),
            "sql": (
                "SELECT f.name, rs.direct_tier, rs.escalated_tier,\n"
                "       COALESCE(rs.escalated_tier, rs.direct_tier) AS effective_tier,\n"
                "       rs.direct_score\n"
                "FROM funds f\n"
                "JOIN risk_scores rs ON rs.scope = 'fund' AND rs.scope_id = f.fund_id\n"
                "WHERE COALESCE(rs.escalated_tier, rs.direct_tier) IN ('high','critical')\n"
                "ORDER BY rs.direct_score DESC"
            ),
            "citations": [],
        },
    ),
]

_FALLBACK_ANSWER = {
    "routing": "rag",
    "answer": (
        "I searched the Fund documents for your query but could not find a specific match "
        "in MOCK mode. In real mode, this query would retrieve the top-3 relevant document "
        "chunks from the pgvector store (bge-base-en-v1.5 embeddings, scoped to the selected Fund or BLE)."
    ),
    "sql": None,
    "citations": [],
}


def _route_question(question: str) -> str:
    return "text-to-sql" if _SQL_KEYWORDS.search(question) else "rag"


def _mock_answer(question: str, routing: str) -> dict:
    for pattern, ans in _MOCK_ANSWERS:
        if pattern.search(question):
            return ans
    return {**_FALLBACK_ANSWER, "routing": routing}


@router.post("/copilot/ask", response_model=CopilotAnswer)
def ask(body: CopilotRequest) -> CopilotAnswer:
    question = body.question.strip()
    if not question:
        return CopilotAnswer(
            question=question,
            routing="rag",
            answer="Please enter a question.",
            sql=None,
            citations=[],
            is_mock=MOCK,
        )

    routing = _route_question(question)

    if MOCK:
        ans = _mock_answer(question, routing)
        return CopilotAnswer(
            question=question,
            routing=ans["routing"],
            answer=ans["answer"],
            sql=ans.get("sql"),
            citations=[CitationItem(**c) for c in ans.get("citations", [])],
            is_mock=True,
        )

    # Real mode: delegate to services
    fund_id = body.fund_id or _DEFAULT_FUND_ID
    scope = body.scope or "fund"
    scope_id = body.scope_id or fund_id

    if routing == "text-to-sql":
        svc = get_text_to_sql()
        result = svc.query(
            question=question,
            fund_id=fund_id,
            synthetic_static=False,
            scope=scope,
            scope_id=scope_id,
        )
        rows_text = ""
        if result.sql_result and result.sql_result.rows:
            rows_text = "\n".join(str(r) for r in result.sql_result.rows[:10])
        answer = f"SQL query executed.\n\nResults:\n{rows_text or '(no rows returned)'}"
        return CopilotAnswer(
            question=question,
            routing="text-to-sql",
            answer=answer,
            sql=result.generated_sql,
            citations=[],
            is_mock=False,
        )
    else:
        try:
            from api.deps import get_rag
            rag = get_rag()
            chunks = rag.retrieve(
                query=question,
                scope=scope,
                scope_id=scope_id,
                fund_id=fund_id,
                synthetic_static=False,
            )
            answer_parts = [c.chunk_text for c in chunks[:3]]
            answer = "\n\n---\n\n".join(answer_parts) if answer_parts else None
            citations = [
                CitationItem(
                    text=c.chunk_text[:200],
                    doc_id=c.document_id,
                    document_type="Document Chunk",
                )
                for c in chunks[:3]
            ]
        except Exception:
            answer = None
            citations = []

        if not answer:
            answer, _ = _llm_context_answer(question, scope, scope_id, fund_id)

        return CopilotAnswer(
            question=question,
            routing="rag",
            answer=answer,
            sql=None,
            citations=citations,
            is_mock=False,
        )


@router.get("/copilot/stream")
async def stream_copilot(
    question: str = Query(..., min_length=1),
    fund_id: str | None = Query(None),
    scope: str | None = Query(None),
    scope_id: str | None = Query(None),
) -> StreamingResponse:
    """
    SSE streaming Copilot endpoint (PRD §8.4).

    Emits token events as: data: {"token": "...", "done": false}
    Final event:           data: {"token": "", "done": true, "routing": ..., "sql": ..., "citations": [...], "is_mock": ...}

    MOCK mode: streams canned answer word-by-word with MOCK_STREAM_DELAY between tokens.
    Real mode: falls back to single-event response (full Claude streaming TBD).
    """
    q = question.strip()
    routing = _route_question(q)

    async def _event_stream():
        if not q:
            yield f"data: {json.dumps({'token': '', 'done': True, 'routing': 'rag', 'sql': None, 'citations': [], 'is_mock': MOCK})}\n\n"
            return

        if MOCK:
            ans = _mock_answer(q, routing)
            words = ans["answer"].split(" ")
            for i, word in enumerate(words):
                token = word + ("" if i == len(words) - 1 else " ")
                yield f"data: {json.dumps({'token': token, 'done': False})}\n\n"
                if _MOCK_STREAM_DELAY > 0:
                    await asyncio.sleep(_MOCK_STREAM_DELAY)
            yield (
                f"data: {json.dumps({'token': '', 'done': True, 'routing': ans['routing'], 'sql': ans.get('sql'), 'citations': ans.get('citations', []), 'is_mock': True})}\n\n"
            )
            return

        # Real mode — synchronous result emitted as a single event
        act_scope = scope or "fund"
        act_scope_id = scope_id or fund_id or _DEFAULT_FUND_ID
        act_fund_id = fund_id or _DEFAULT_FUND_ID

        if routing == "text-to-sql":
            svc = get_text_to_sql()
            result = svc.query(
                question=q,
                fund_id=act_fund_id,
                synthetic_static=False,
                scope=act_scope,
                scope_id=act_scope_id,
            )
            rows_text = ""
            if result.sql_result and result.sql_result.rows:
                rows_text = "\n".join(str(r) for r in result.sql_result.rows[:10])
            answer = f"SQL query executed.\n\nResults:\n{rows_text or '(no rows returned)'}"
            yield (
                f"data: {json.dumps({'token': answer, 'done': True, 'routing': 'text-to-sql', 'sql': result.generated_sql, 'citations': [], 'is_mock': False})}\n\n"
            )
        else:
            try:
                from api.deps import get_rag
                rag = get_rag()
                chunks = rag.retrieve(
                    query=q,
                    scope=act_scope,
                    scope_id=act_scope_id,
                    fund_id=act_fund_id,
                    synthetic_static=False,
                )
                parts = [c.chunk_text for c in chunks[:3]]
                answer = "\n\n---\n\n".join(parts) if parts else None
                citations = [
                    {"text": c.chunk_text[:200], "doc_id": c.document_id, "document_type": "Document Chunk"}
                    for c in chunks[:3]
                ]
            except Exception:
                answer = None
                citations = []

            if not answer:
                answer, _ = _llm_context_answer(q, act_scope, act_scope_id, act_fund_id)

            yield (
                f"data: {json.dumps({'token': answer, 'done': True, 'routing': 'rag', 'sql': None, 'citations': citations, 'is_mock': False})}\n\n"
            )

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
