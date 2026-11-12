"""Application settings, read from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


def _thinking_budget() -> int | None:
    raw = os.getenv("GEMINI_THINKING_BUDGET", "0").strip().lower()
    if raw in ("", "none", "default"):
        return None
    try:
        return int(raw)
    except ValueError:
        return None


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    gemini_timeout_s: float = 15.0
    gemini_max_retries: int = 1          # extra attempts for 429 / 5xx / timeouts
    gemini_backoff_s: float = 1.0
    gemini_max_concurrency: int = 4      # simultaneous in-flight Gemini calls
    gemini_thinking_budget: int | None = 0
    db_path: str = str(ROOT / "data" / "helpdesk.db")
    docs_dir: str = str(ROOT / "course_docs")
    max_question_chars: int = 500
    max_history_turns: int = 6
    rate_limit_per_min: int = 30         # per client IP, /api/chat only
    request_ttl_s: int = 120             # idempotency window for request_id

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
            gemini_model=os.getenv("GEMINI_MODEL", cls.gemini_model),
            gemini_timeout_s=_float("GEMINI_TIMEOUT_S", cls.gemini_timeout_s),
            gemini_max_retries=_int("GEMINI_MAX_RETRIES", cls.gemini_max_retries),
            gemini_backoff_s=_float("GEMINI_BACKOFF_S", cls.gemini_backoff_s),
            gemini_max_concurrency=_int("GEMINI_MAX_CONCURRENCY", cls.gemini_max_concurrency),
            gemini_thinking_budget=_thinking_budget(),
            db_path=os.getenv("DB_PATH", cls.db_path),
            docs_dir=os.getenv("DOCS_DIR", cls.docs_dir),
            rate_limit_per_min=_int("RATE_LIMIT_PER_MIN", cls.rate_limit_per_min),
        )
