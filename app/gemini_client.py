"""Minimal async Gemini REST client with retries and friendly, typed errors."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Callable

import httpx

from .config import Settings

logger = logging.getLogger("helpdesk.gemini")


class GeminiError(Exception):
    code = "gemini_error"
    http_status = 503
    user_message = "The assistant is temporarily unavailable. Please try again in a moment."

    def __init__(self, detail: str = "", retry_after: float | None = None):
        super().__init__(detail or self.user_message)
        self.retry_after = retry_after


class GeminiRateLimited(GeminiError):
    code = "rate_limited"
    http_status = 429
    user_message = "The assistant is very busy right now (rate limit reached). Please wait a few seconds and try again."


class GeminiTimeout(GeminiError):
    code = "timeout"
    http_status = 504
    user_message = "The assistant took too long to respond. Please try again."


class GeminiUnavailable(GeminiError):
    code = "unavailable"
    http_status = 503


class GeminiNotConfigured(GeminiError):
    code = "not_configured"
    http_status = 503
    user_message = "The assistant is not configured yet. Please contact the course team."


class GeminiBadResponse(GeminiError):
    code = "bad_response"
    http_status = 502
    user_message = "The assistant could not produce a valid answer. Please rephrase your question or try again."


@dataclass
class GeminiAnswer:
    answer: str
    covered: bool
    sources: list[str]


RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "answer": {"type": "STRING"},
        "covered": {"type": "BOOLEAN"},
        "sources": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["answer", "covered", "sources"],
}

RETRYABLE = {429, 500, 502, 503, 504}


class GeminiClient:
    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None,
                 sleep: Callable = asyncio.sleep):
        self.s = settings
        self._http = http
        self._sleep = sleep

    async def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=self.s.gemini_timeout_s)
        return self._http

    def _body(self, system: str, history: list[tuple[str, str]], question: str) -> dict:
        contents = []
        for q, a in history:
            contents.append({"role": "user", "parts": [{"text": q}]})
            contents.append({"role": "model", "parts": [{"text": a}]})
        contents.append({"role": "user", "parts": [{"text": question}]})
        gen = {
            "temperature": 0,
            "maxOutputTokens": 1024,
            "responseMimeType": "application/json",
            "responseSchema": RESPONSE_SCHEMA,
        }
        if self.s.gemini_thinking_budget is not None:
            gen["thinkingConfig"] = {"thinkingBudget": self.s.gemini_thinking_budget}
        return {"systemInstruction": {"parts": [{"text": system}]}, "contents": contents,
                "generationConfig": gen}

    async def generate(self, system: str, history: list[tuple[str, str]], question: str,
                       on_attempt: Callable[[], None] | None = None) -> GeminiAnswer:
        if not self.s.gemini_api_key:
            raise GeminiNotConfigured("GEMINI_API_KEY is not set")
        url = f"{self.s.gemini_base_url}/models/{self.s.gemini_model}:generateContent"
        headers = {"x-goog-api-key": self.s.gemini_api_key, "Content-Type": "application/json"}
        body = self._body(system, history, question)
        client = await self._client()
        last: GeminiError = GeminiUnavailable("no attempt made")
        for attempt in range(self.s.gemini_max_retries + 1):
            if on_attempt:
                on_attempt()
            started = time.monotonic()
            try:
                resp = await client.post(url, headers=headers, json=body, timeout=self.s.gemini_timeout_s)
            except httpx.TimeoutException:
                last = GeminiTimeout("request timed out")
            except httpx.HTTPError as exc:
                last = GeminiUnavailable(f"network error: {type(exc).__name__}")
            else:
                if resp.status_code == 200:
                    self.last_latency_ms = int((time.monotonic() - started) * 1000)
                    return self._parse(resp)
                retry_after = _retry_after(resp)
                logger.warning("Gemini HTTP %s (attempt %d)", resp.status_code, attempt + 1)
                if resp.status_code == 429:
                    last = GeminiRateLimited("HTTP 429", retry_after)
                elif resp.status_code in RETRYABLE:
                    last = GeminiUnavailable(f"HTTP {resp.status_code}", retry_after)
                elif resp.status_code in (401, 403):
                    raise GeminiNotConfigured(f"HTTP {resp.status_code} (check GEMINI_API_KEY)")
                else:
                    raise GeminiUnavailable(f"HTTP {resp.status_code}")
            if attempt < self.s.gemini_max_retries:
                delay = min(last.retry_after or self.s.gemini_backoff_s * (2 ** attempt), 5.0)
                await self._sleep(delay)
        raise last

    @staticmethod
    def _parse(resp: httpx.Response) -> GeminiAnswer:
        try:
            data = resp.json()
            cands = data.get("candidates") or []
            if not cands:
                raise GeminiBadResponse("no candidates (blocked?)")
            parts = cands[0].get("content", {}).get("parts", [])
            text = "".join(p.get("text", "") for p in parts).strip()
            payload = json.loads(text)
            answer = str(payload["answer"]).strip()
            if not answer:
                raise GeminiBadResponse("empty answer")
            sources = [str(x) for x in payload.get("sources", []) if isinstance(x, str)]
            return GeminiAnswer(answer, bool(payload.get("covered", False)), sources)
        except GeminiError:
            raise
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise GeminiBadResponse(f"unparseable response: {type(exc).__name__}") from exc

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()


def _retry_after(resp: httpx.Response) -> float | None:
    try:
        return float(resp.headers.get("retry-after", ""))
    except ValueError:
        return None
