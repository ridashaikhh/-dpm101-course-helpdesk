"""FastAPI application factory and routes."""
from __future__ import annotations

import logging
import time
from collections import defaultdict, deque

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import ROOT, Settings
from .db import Database
from .documents import load_documents
from .gemini_client import GeminiClient
from .service import ChatError, HelpdeskService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("helpdesk")
STATIC_DIR = ROOT / "static"


class ChatRequest(BaseModel):
    question: str = Field(..., max_length=5000)
    conversation_id: str | None = None
    request_id: str | None = None


class RateLimiter:
    """Tiny in-memory sliding-window limiter (per client IP)."""

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self.hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        q = self.hits[key]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= self.per_minute:
            return False
        q.append(now)
        if len(self.hits) > 5000:  # bound memory
            for k in [k for k, v in self.hits.items() if not v or now - v[-1] > 60]:
                del self.hits[k]
        return True


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def create_app(settings: Settings | None = None, gemini: GeminiClient | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    docs = load_documents(settings.docs_dir)
    db = Database(settings.db_path)
    gemini = gemini or GeminiClient(settings)
    service = HelpdeskService(settings, db, docs, gemini)
    limiter = RateLimiter(settings.rate_limit_per_min)

    app = FastAPI(title="DPM-101 Course Helpdesk", docs_url=None, redoc_url=None)
    app.state.service, app.state.db, app.state.settings = service, db, settings
    if not settings.gemini_api_key:
        logger.warning("GEMINI_API_KEY is not set: questions that need Gemini will return a friendly error.")

    @app.exception_handler(ChatError)
    async def chat_error_handler(_: Request, exc: ChatError):
        headers = {"Retry-After": str(int(exc.retry_after))} if exc.retry_after else None
        return JSONResponse(
            {"status": "error", "error_code": exc.code, "message": exc.message, "stats": db.stats()},
            status_code=exc.status_code, headers=headers,
        )

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception):
        logger.exception("Unhandled error")
        return JSONResponse({"status": "error", "error_code": "internal",
                             "message": "Something went wrong on our side. Please try again."}, status_code=500)

    @app.post("/api/chat")
    async def chat(body: ChatRequest, request: Request):
        if not limiter.allow(_client_ip(request)):
            db.incr(rate_limited=1)
            raise ChatError(429, "too_many_requests",
                            "You're sending questions too quickly. Please wait a few seconds and try again.", 10)
        r = await service.ask(body.question, body.conversation_id, body.request_id)
        return {
            "status": "ok",
            "answer": r.answer,
            "covered": r.covered,
            "sources": [{"file": f, "title": docs.title_for(f)} for f in r.sources],
            "served_from": r.served_from,
            "cache_type": r.cache_type,
            "duplicate": r.duplicate,
            "conversation_id": r.conversation_id,
            "request_id": r.request_id,
            "stats": db.stats(),
        }

    @app.get("/api/stats")
    async def stats():
        return db.stats()

    @app.get("/api/docs")
    async def doc_status():
        return {"docs_version": docs.version, "documents": docs.summary()}

    @app.get("/health")
    async def health():
        return {"status": "ok", "db": "ok" if db.ping() else "error",
                "gemini_configured": bool(settings.gemini_api_key),
                "documents_loaded": len(docs.documents), "documents_active": len(docs.active),
                "model": settings.gemini_model}

    @app.get("/")
    async def index():
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app

