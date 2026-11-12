"""Core chat logic: caching, single-flight de-duplication, idempotency, history."""
from __future__ import annotations

import asyncio
import hashlib
import re
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, replace

from .config import Settings
from .db import Database
from .documents import DocumentSet
from .gemini_client import GeminiAnswer, GeminiClient, GeminiError
from .normalizer import is_context_dependent, match_faq, normalize
from .prompts import build_system_prompt

ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")
MAX_CONVERSATIONS = 2000


class ChatError(Exception):
    def __init__(self, status_code: int, code: str, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.status_code, self.code, self.message, self.retry_after = status_code, code, message, retry_after


@dataclass
class ChatResult:
    answer: str
    covered: bool
    sources: list[str]
    served_from: str          # "gemini" | "cache" | "coalesced"
    cache_type: str | None    # "exact" | "faq" | None
    conversation_id: str
    request_id: str | None
    duplicate: bool = False


@dataclass
class _Entry:
    question: str
    task: asyncio.Task
    created: float


def _key(prefix: str, value: str, version: str) -> str:
    return f"{prefix}:" + hashlib.sha256(f"{version}|{value}".encode()).hexdigest()


class HelpdeskService:
    def __init__(self, settings: Settings, db: Database, docs: DocumentSet, gemini: GeminiClient):
        self.s, self.db, self.docs, self.gemini = settings, db, docs, gemini
        self.system_prompt = build_system_prompt(docs.knowledge_block())
        self._sem = asyncio.Semaphore(settings.gemini_max_concurrency)
        self._inflight: dict[str, asyncio.Task] = {}
        self._requests: dict[str, _Entry] = {}
        self._conversations: OrderedDict[str, list[tuple[str, str]]] = OrderedDict()
        db.purge_other_versions(docs.version)

    # ------------------------------------------------------------------ API
    async def ask(self, question: str, conversation_id: str | None = None,
                  request_id: str | None = None) -> ChatResult:
        q = " ".join((question or "").split())
        if not q:
            raise ChatError(400, "empty_question", "Please type a question.")
        if len(q) > self.s.max_question_chars:
            raise ChatError(400, "too_long", f"Please keep your question under {self.s.max_question_chars} characters.")
        if conversation_id and not ID_RE.match(conversation_id):
            raise ChatError(400, "bad_conversation_id", "Invalid conversation id.")
        if request_id and not ID_RE.match(request_id):
            raise ChatError(400, "bad_request_id", "Invalid request id.")
        cid = conversation_id or uuid.uuid4().hex
        self._prune_requests()

        if request_id:
            entry = self._requests.get(request_id)
            if entry:  # double-click / retry of the same submission -> share the original result
                if entry.question != q:
                    raise ChatError(409, "request_id_reuse", "This request id was already used for a different question.")
                self.db.incr(duplicates_suppressed=1)
                result = await asyncio.shield(entry.task)
                return replace(result, duplicate=True)
            task = asyncio.ensure_future(self._process(q, cid, request_id))
            self._requests[request_id] = _Entry(q, task, time.monotonic())
            task.add_done_callback(_swallow)
            return await asyncio.shield(task)
        return await asyncio.shield(asyncio.ensure_future(self._process(q, cid, None)))

    # ------------------------------------------------------------ internals
    async def _process(self, q: str, cid: str, request_id: str | None) -> ChatResult:
        self.db.incr(total_questions=1)
        try:
            return await self._answer(q, cid, request_id)
        except ChatError:
            self.db.incr(errors=1)
            raise

    async def _answer(self, q: str, cid: str, request_id: str | None) -> ChatResult:
        norm = normalize(q)
        history = list(self._conversations.get(cid, []))
        ver = self.docs.version

        if is_context_dependent(norm, bool(history)):
            # Follow-up that depends on earlier turns: use history, never read/write shared cache.
            ans = await self._call_gemini(q, history)
            return self._finish(q, cid, request_id, ans, "gemini", None)

        intent = match_faq(norm)
        exact_key = _key("exact", norm, ver)
        faq_key = _key("faq", intent.id, ver) if intent else None

        hit = self.db.cache_get(exact_key, ver)
        cache_type = "exact"
        if hit is None and faq_key:
            hit = self.db.cache_get(faq_key, ver)
            cache_type = "faq"
        if hit:
            self.db.incr(cache_hits=1, **{f"cache_hits_{cache_type}": 1})
            return self._finish(q, cid, request_id, GeminiAnswer(hit["answer"], hit["covered"], hit["sources"]),
                                "cache", cache_type)

        flight_key = faq_key or exact_key
        leader = self._inflight.get(flight_key)
        if leader is not None:
            ans = await asyncio.shield(leader)      # identical question already being answered
            self.db.incr(cache_hits=1, coalesced=1)
            return self._finish(q, cid, request_id, ans, "coalesced", None)

        # FAQ intents are always asked in canonical wording so the cached answer is wording-independent.
        asked = intent.canonical if intent else q
        task = asyncio.ensure_future(self._fetch_and_cache(asked, norm, exact_key, faq_key, intent.id if intent else None))
        self._inflight[flight_key] = task
        task.add_done_callback(lambda _t, k=flight_key: self._inflight.pop(k, None))
        task.add_done_callback(_swallow)
        ans = await asyncio.shield(task)
        return self._finish(q, cid, request_id, ans, "gemini", None)

    async def _fetch_and_cache(self, asked: str, norm: str, exact_key: str, faq_key: str | None,
                               intent_id: str | None) -> GeminiAnswer:
        ans = await self._call_gemini(asked, [])
        ver = self.docs.version
        # Only successful, validated answers reach this point: errors are never cached.
        self.db.cache_put(exact_key, "exact", norm, ans.answer, ans.sources, ans.covered, ver)
        if faq_key:
            self.db.cache_put(faq_key, "faq", intent_id or "", ans.answer, ans.sources, ans.covered, ver)
        return ans

    async def _call_gemini(self, question: str, history: list[tuple[str, str]]) -> GeminiAnswer:
        async with self._sem:
            started = time.monotonic()
            try:
                ans = await self.gemini.generate(self.system_prompt, history, question,
                                                 on_attempt=lambda: self.db.incr(api_calls=1))
            except GeminiError as exc:
                raise ChatError(exc.http_status, exc.code, exc.user_message, exc.retry_after) from exc
            except Exception as exc:  # never let an unexpected failure crash the request
                raise ChatError(503, "unexpected", GeminiError.user_message) from exc
            self.db.incr(api_successes=1, api_latency_ms_total=int((time.monotonic() - started) * 1000))
        valid = self.docs.active_filenames
        seen: list[str] = []
        for name in ans.sources:
            if name in valid and name not in seen:
                seen.append(name)
        return GeminiAnswer(ans.answer, ans.covered, seen)

    def _finish(self, q: str, cid: str, request_id: str | None, ans: GeminiAnswer,
                served_from: str, cache_type: str | None) -> ChatResult:
        turns = self._conversations.setdefault(cid, [])
        turns.append((q, ans.answer))
        del turns[: -self.s.max_history_turns]
        self._conversations.move_to_end(cid)
        while len(self._conversations) > MAX_CONVERSATIONS:
            self._conversations.popitem(last=False)
        return ChatResult(ans.answer, ans.covered, list(ans.sources), served_from, cache_type, cid, request_id)

    def _prune_requests(self) -> None:
        cutoff = time.monotonic() - self.s.request_ttl_s
        for rid in [r for r, e in self._requests.items() if e.created < cutoff and e.task.done()]:
            del self._requests[rid]


def _swallow(task: asyncio.Task) -> None:
    """Mark exceptions as retrieved so asyncio doesn't log 'never retrieved' noise."""
    if not task.cancelled():
        task.exception()
