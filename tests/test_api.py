from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.gemini_client import GeminiUnavailable
from app.main import create_app

Q1 = "What is the minimum score needed to pass the course and get a Verified Certificate?"


@pytest.fixture
def client(settings, fake):
    with TestClient(create_app(settings, fake)) as c:
        yield c


def test_health_stats_docs_and_index(client):
    h = client.get("/health").json()
    assert h["status"] == "ok" and h["db"] == "ok" and h["documents_active"] == 3
    assert "test-key" not in str(h)
    assert client.get("/api/stats").json()["total_questions"] == 0
    docs = client.get("/api/docs").json()["documents"]
    assert {d["file"]: d["used_as_knowledge"] for d in docs}["02_grading_policy_v1.txt"] is False
    assert "DPM-101" in client.get("/").text


def test_chat_success_and_cache(client, fake):
    r1 = client.post("/api/chat", json={"question": Q1, "request_id": "a1"}).json()
    assert r1["status"] == "ok" and r1["served_from"] == "gemini"
    assert r1["sources"] == [{"file": "03_grading_policy_v2.txt",
                              "title": "03 - Grading & Late Submission Policy (Version 2 - UPDATED)"}]
    r2 = client.post("/api/chat", json={"question": Q1, "request_id": "a2",
                                        "conversation_id": r1["conversation_id"]}).json()
    assert r2["served_from"] == "cache"
    assert r2["stats"]["total_questions"] == 2 and r2["stats"]["api_calls"] == 1 and r2["stats"]["cache_hits"] == 1
    assert len(fake.calls) == 1


def test_validation(client):
    assert client.post("/api/chat", json={"question": "  "}).status_code == 400
    assert client.post("/api/chat", json={"question": "x" * 501}).status_code == 400
    assert client.post("/api/chat", json={"question": "hi", "request_id": "bad id!"}).status_code == 400
    assert client.post("/api/chat", json={}).status_code == 422


def test_upstream_failure_is_friendly(client, fake):
    fake.errors = [GeminiUnavailable("HTTP 503")]
    r = client.post("/api/chat", json={"question": Q1})
    body = r.json()
    assert r.status_code == 503 and body["status"] == "error" and "try again" in body["message"].lower()
    assert "Traceback" not in r.text


def test_per_ip_rate_limit(settings, fake):
    with TestClient(create_app(replace(settings, rate_limit_per_min=2), fake)) as c:
        codes = [c.post("/api/chat", json={"question": Q1}).status_code for _ in range(3)]
        assert codes == [200, 200, 429]
        assert c.get("/api/stats").json()["rate_limited"] == 1
