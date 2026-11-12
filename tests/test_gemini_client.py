import json
from dataclasses import replace

import httpx
import pytest

from app.config import Settings
from app.gemini_client import (GeminiBadResponse, GeminiClient, GeminiNotConfigured, GeminiRateLimited,
                               GeminiTimeout, GeminiUnavailable)

pytestmark = pytest.mark.anyio
S = Settings(gemini_api_key="secret-key", gemini_max_retries=1)


def ok_body(payload):
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}]}


def make(handler, settings=S):
    sleeps = []

    async def fake_sleep(d):
        sleeps.append(d)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return GeminiClient(settings, http=http, sleep=fake_sleep), sleeps


async def test_success_parses_and_keeps_key_out_of_url():
    seen = {}

    def h(req):
        seen["url"], seen["key"] = str(req.url), req.headers.get("x-goog-api-key")
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json=ok_body({"answer": "60%", "covered": True, "sources": ["a.txt"]}))

    c, _ = make(h)
    attempts = []
    a = await c.generate("sys", [("q0", "a0")], "q1", on_attempt=lambda: attempts.append(1))
    assert (a.answer, a.covered, a.sources) == ("60%", True, ["a.txt"]) and len(attempts) == 1
    assert "secret-key" not in seen["url"] and seen["key"] == "secret-key"
    assert [m["role"] for m in seen["body"]["contents"]] == ["user", "model", "user"]
    assert seen["body"]["generationConfig"]["temperature"] == 0


async def test_rate_limit_retries_once_then_raises():
    n = []

    def h(req):
        n.append(1)
        return httpx.Response(429, headers={"retry-after": "2"})

    c, sleeps = make(h)
    attempts = []
    with pytest.raises(GeminiRateLimited):
        await c.generate("s", [], "q", on_attempt=lambda: attempts.append(1))
    assert len(n) == 2 and len(attempts) == 2 and sleeps == [2.0]


async def test_transient_500_then_success():
    codes = iter([500, 200])

    def h(req):
        code = next(codes)
        if code == 500:
            return httpx.Response(500)
        return httpx.Response(200, json=ok_body({"answer": "x", "covered": False, "sources": []}))

    c, _ = make(h)
    assert (await c.generate("s", [], "q")).answer == "x"


async def test_timeout_maps_to_friendly_error():
    def h(req):
        raise httpx.ReadTimeout("slow")

    c, _ = make(h)
    with pytest.raises(GeminiTimeout):
        await c.generate("s", [], "q")


async def test_bad_key_is_not_retried():
    n = []

    def h(req):
        n.append(1)
        return httpx.Response(403)

    c, _ = make(h)
    with pytest.raises(GeminiNotConfigured):
        await c.generate("s", [], "q")
    assert len(n) == 1


async def test_client_error_not_retried_as_unavailable():
    c, _ = make(lambda r: httpx.Response(400))
    with pytest.raises(GeminiUnavailable):
        await c.generate("s", [], "q")


@pytest.mark.parametrize("resp", [
    httpx.Response(200, json={"candidates": []}),
    httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "not json"}]}}]}),
    httpx.Response(200, json=ok_body({"answer": "", "covered": True, "sources": []})),
    httpx.Response(200, json=ok_body({"nope": 1})),
])
async def test_malformed_responses(resp):
    c, _ = make(lambda r: resp)
    with pytest.raises(GeminiBadResponse):
        await c.generate("s", [], "q")


async def test_no_key_makes_no_request():
    c, _ = make(lambda r: pytest.fail("should not call"), replace(S, gemini_api_key=""))
    with pytest.raises(GeminiNotConfigured):
        await c.generate("s", [], "q")
