"""
Copilot router tests — POST /copilot/ask and GET /copilot/stream (PRD §8.4).
"""
from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault("MOCK", "true")
os.environ.setdefault("MOCK_STREAM_DELAY", "0")  # no sleep in tests

from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# POST /api/copilot/ask (existing endpoint — regression)
# ---------------------------------------------------------------------------

def test_ask_200(client: TestClient):
    r = client.post("/api/copilot/ask", json={"question": "test question"})
    assert r.status_code == 200


def test_ask_returns_answer(client: TestClient):
    r = client.post("/api/copilot/ask", json={"question": "critical BLE"})
    body = r.json()
    assert body["answer"].strip()
    assert body["routing"] in ("rag", "text-to-sql", "hybrid")
    assert body["is_mock"] is True


def test_ask_empty_question(client: TestClient):
    r = client.post("/api/copilot/ask", json={"question": "  "})
    assert r.status_code == 200
    assert "Please enter a question" in r.json()["answer"]


# ---------------------------------------------------------------------------
# GET /api/copilot/stream — SSE streaming (PRD §8.4)
# ---------------------------------------------------------------------------

def test_stream_200(client: TestClient):
    r = client.get("/api/copilot/stream", params={"question": "test"})
    assert r.status_code == 200


def test_stream_content_type_event_stream(client: TestClient):
    r = client.get("/api/copilot/stream", params={"question": "test"})
    assert "text/event-stream" in r.headers.get("content-type", "")


def test_stream_contains_done_event(client: TestClient):
    r = client.get("/api/copilot/stream", params={"question": "critical BLE"})
    data_lines = [l[6:] for l in r.text.split("\n\n") if l.startswith("data: ") and l[6:].strip()]
    parsed = [json.loads(l) for l in data_lines]
    done_events = [e for e in parsed if e.get("done") is True]
    assert done_events, "SSE stream must include a done=true event"


def test_stream_done_has_routing(client: TestClient):
    r = client.get("/api/copilot/stream", params={"question": "critical BLE"})
    data_lines = [l[6:] for l in r.text.split("\n\n") if l.startswith("data: ") and l[6:].strip()]
    parsed = [json.loads(l) for l in data_lines]
    done = next(e for e in parsed if e.get("done"))
    assert done["routing"] in ("rag", "text-to-sql", "hybrid")


def test_stream_is_mock_true(client: TestClient):
    r = client.get("/api/copilot/stream", params={"question": "test"})
    data_lines = [l[6:] for l in r.text.split("\n\n") if l.startswith("data: ") and l[6:].strip()]
    parsed = [json.loads(l) for l in data_lines]
    done = next(e for e in parsed if e.get("done"))
    assert done["is_mock"] is True


def test_stream_tokens_before_done(client: TestClient):
    r = client.get("/api/copilot/stream", params={"question": "critical BLE"})
    data_lines = [l[6:] for l in r.text.split("\n\n") if l.startswith("data: ") and l[6:].strip()]
    parsed = [json.loads(l) for l in data_lines]
    token_events = [e for e in parsed if not e.get("done") and e.get("token")]
    assert token_events, "SSE stream should emit token events before the done event"


def test_stream_sql_included_for_sql_routing(client: TestClient):
    r = client.get("/api/copilot/stream", params={"question": "which funds have critical BLE"})
    data_lines = [l[6:] for l in r.text.split("\n\n") if l.startswith("data: ") and l[6:].strip()]
    parsed = [json.loads(l) for l in data_lines]
    done = next(e for e in parsed if e.get("done"))
    if done["routing"] == "text-to-sql":
        assert done["sql"] is not None


def test_stream_missing_question_422(client: TestClient):
    r = client.get("/api/copilot/stream")
    assert r.status_code == 422
