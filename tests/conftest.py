import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import ROOT, Settings  # noqa: E402
from app.db import Database  # noqa: E402
from app.documents import load_documents  # noqa: E402
from app.gemini_client import GeminiAnswer  # noqa: E402
from app.service import HelpdeskService  # noqa: E402

DOCS_DIR = str(ROOT / "course_docs")


@pytest.fixture
def anyio_backend():
    return "asyncio"


class FakeGemini:
    """Stands in for GeminiClient; records every call and can raise queued errors."""

    def __init__(self, delay: float = 0.0):
        self.calls: list[dict] = []
        self.errors: list[Exception] = []
        self.delay = delay

    async def generate(self, system, history, question, on_attempt=None):
        if on_attempt:
            on_attempt()
        self.calls.append({"question": question, "history": list(history), "system": system})
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.errors:
            raise self.errors.pop(0)
        return GeminiAnswer(f"ANSWER[{question}]", True, ["03_grading_policy_v2.txt", "bogus.txt"])


@pytest.fixture
def settings(tmp_path):
    return Settings(gemini_api_key="test-key", db_path=str(tmp_path / "t.db"), docs_dir=DOCS_DIR,
                    rate_limit_per_min=1000)


@pytest.fixture
def fake():
    return FakeGemini()


@pytest.fixture
def docs():
    return load_documents(DOCS_DIR)


@pytest.fixture
def make_service(settings, docs):
    def _make(gemini, s=None):
        s = s or settings
        return HelpdeskService(s, Database(s.db_path), docs, gemini)
    return _make
