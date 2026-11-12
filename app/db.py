"""SQLite persistence for the answer cache and counters.

One shared connection guarded by an RLock; every write runs inside an explicit
BEGIN IMMEDIATE transaction so concurrent requests cannot corrupt counters.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

COUNTERS = (
    "total_questions",      # every accepted question (excludes rejected/invalid/duplicate clicks)
    "api_calls",            # every HTTP attempt sent to Gemini (retries included)
    "cache_hits",           # answers served without a new Gemini call (exact + faq + coalesced)
    "cache_hits_exact",
    "cache_hits_faq",
    "coalesced",            # identical in-flight questions that shared one Gemini call
    "errors",               # questions that ended in a friendly error message
    "rate_limited",         # requests rejected by our own per-IP limiter
    "duplicates_suppressed",  # repeated submissions of the same request_id
    "api_latency_ms_total",
    "api_successes",
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS stats (name TEXT PRIMARY KEY, value INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS answer_cache (
    cache_key   TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,
    question    TEXT NOT NULL,
    answer      TEXT NOT NULL,
    sources     TEXT NOT NULL,
    covered     INTEGER NOT NULL,
    docs_version TEXT NOT NULL,
    created_at  REAL NOT NULL,
    hits        INTEGER NOT NULL DEFAULT 0
);
"""


class Database:
    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None, timeout=10)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            if path != ":memory:":
                self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.executescript(SCHEMA)
            with self.tx() as c:
                c.executemany("INSERT OR IGNORE INTO stats(name, value) VALUES (?, 0)", [(n,) for n in COUNTERS])

    @contextmanager
    def tx(self):
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    def ping(self) -> bool:
        with self._lock:
            return self._conn.execute("SELECT 1").fetchone()[0] == 1

    # ---- counters -------------------------------------------------------
    def incr(self, **deltas: int) -> None:
        for name in deltas:
            if name not in COUNTERS:
                raise KeyError(f"unknown counter {name}")
        with self.tx() as c:
            for name, delta in deltas.items():
                c.execute("UPDATE stats SET value = value + ? WHERE name = ?", (delta, name))

    def stats(self) -> dict:
        with self._lock:
            rows = self._conn.execute("SELECT name, value FROM stats").fetchall()
            cached = self._conn.execute("SELECT COUNT(*) FROM answer_cache").fetchone()[0]
        s = {r["name"]: r["value"] for r in rows}
        total, hits = s["total_questions"], s["cache_hits"]
        s["cache_hit_rate"] = round(hits / total, 3) if total else 0.0
        s["avg_api_latency_ms"] = (
            round(s["api_latency_ms_total"] / s["api_successes"]) if s["api_successes"] else 0
        )
        s["cached_answers"] = cached
        return s

    # ---- cache ----------------------------------------------------------
    def cache_get(self, key: str, docs_version: str) -> dict | None:
        with self.tx() as c:
            row = c.execute(
                "SELECT * FROM answer_cache WHERE cache_key = ? AND docs_version = ?", (key, docs_version)
            ).fetchone()
            if not row:
                return None
            c.execute("UPDATE answer_cache SET hits = hits + 1 WHERE cache_key = ?", (key,))
        return {
            "answer": row["answer"],
            "sources": json.loads(row["sources"]),
            "covered": bool(row["covered"]),
        }

    def cache_put(self, key: str, kind: str, question: str, answer: str, sources: list[str],
                  covered: bool, docs_version: str) -> None:
        with self.tx() as c:
            c.execute(
                "INSERT OR REPLACE INTO answer_cache"
                "(cache_key, kind, question, answer, sources, covered, docs_version, created_at, hits) "
                "VALUES (?,?,?,?,?,?,?,?, COALESCE((SELECT hits FROM answer_cache WHERE cache_key=?),0))",
                (key, kind, question, answer, json.dumps(sources), int(covered), docs_version, time.time(), key),
            )

    def purge_other_versions(self, docs_version: str) -> int:
        with self.tx() as c:
            return c.execute("DELETE FROM answer_cache WHERE docs_version != ?", (docs_version,)).rowcount
