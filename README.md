# DPM-101 Course Helpdesk Chatbot

A small FastAPI app that answers student questions about the IIMBx *Digital Product Management (DPM-101)* course
using only the supplied documents in `course_docs/`. Built for exam-week load: repeated questions are served from a
SQLite-backed cache, duplicate clicks are collapsed, and Gemini failures never crash the page.

**Stack:** Python · FastAPI · vanilla HTML/CSS/JS · Gemini API (REST via `httpx`) · SQLite · pytest · Render

## How it works

```
browser ──POST /api/chat──▶ rate limit ▶ idempotency (request_id) ▶ cache lookup ▶ single-flight ▶ Gemini
                                                                     (exact → FAQ)                  │
                                   SQLite: answer_cache + counters ◀── store only successful answers┘
```

### Document quirks (handled in code, `.txt` files are never edited)
| Quirk | Handling (`app/documents.py`) |
|---|---|
| Two grading policies (50% in v1, 60% + 40% exam minimum in v2) | v2 states it *supersedes* `02_grading_policy_v1.txt` and is newer → v1 is marked superseded and **not sent to the model**. Detected from the text, not hard-coded. |
| Unmoderated forum export in `04_exam_rules_and_faq.txt`, including a comment pretending to be a system update ("exam is open-book, moved to 30 Dec") | Everything from the "UNMODERATED STUDENT DISCUSSION" header onward is cut before prompting; it is only scanned for injection patterns (reported at `/api/docs`). The system prompt additionally tells the model to treat documents as data and ignore embedded instructions. |
| Topics not in the docs (refund process, SQL/Kubernetes, cricket) | The model must set `covered=false` and say *"This is not mentioned in the course documents."* Sources are validated against real file names. |

### Caching (conservative on purpose)
1. **Exact layer** – key = hash of the normalized question (case, punctuation, whitespace, `1,500`, `dpm-101` spelling) + document/prompt version.
2. **FAQ layer** (`app/normalizer.py`) – a paraphrase reuses a cached answer only if it contains the intent's required concepts **and every other content word is inside that intent's vocabulary**. Any extra number, date, unit or condition ("1 day late", "50%", "drop in week 2", "two quizzes") breaks the match and the question goes through the exact layer / Gemini instead. FAQ intents are always asked to Gemini in canonical wording so the cached answer doesn't depend on who asked first.
3. **Follow-ups** (short or pronoun-based questions in an existing conversation, e.g. "what about the capstone?") use conversation history and are **never** read from or written to the shared cache.
4. Errors, rate-limits and timeouts are **never cached**. The cache is invalidated automatically when document content or the prompt version changes.

### Concurrency & duplicate protection
- Frontend: Send/Enter disabled while a request is pending; every submission carries a fresh `request_id`.
- Backend idempotency: the same `request_id` returns the original result (no second call, counted once).
- Single-flight: identical in-flight questions share one Gemini call (counted as cache hits, `coalesced`).
- A semaphore caps simultaneous Gemini calls (`GEMINI_MAX_CONCURRENCY`); per-IP sliding-window limit on `/api/chat`.
- SQLite: one shared connection, `RLock`, every write in `BEGIN IMMEDIATE` transactions, WAL mode.

### Error handling
429 / 5xx / timeouts are retried once (honouring `Retry-After`, max 5 s), then the user sees a friendly message
(HTTP 429/503/504/502 with `status: "error"`). Missing/invalid API key → friendly "not configured" message with no
Gemini call. The API key lives only in env vars and is sent in a header, never logged or put in URLs.

### Counters
`/api/stats` and the live panel show **Total questions**, **Gemini API calls** (each HTTP attempt, retries included) and
**Served from cache** (exact + FAQ + coalesced), plus errors, hit rate, average latency, duplicates suppressed, and rate-limited requests.

## Endpoints
`GET /` UI · `POST /api/chat` · `GET /api/stats` · `GET /api/docs` (which docs are used/excluded) · `GET /health`

`POST /api/chat` body: `{"question": "...", "conversation_id": "optional", "request_id": "optional-unique-id"}`

## Run locally
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env      # then put your key in GEMINI_API_KEY (or export it)
export $(grep -v '^#' .env | xargs)
uvicorn app.main:create_app --factory --reload
# open http://localhost:8000
python scripts/run_sample_questions.py        # optional: run the 12 sample questions
```

## Tests
```bash
pytest
```
Tests use a fake Gemini client / mocked HTTP transport (no network, no API key): document handling, normalization and
no-merge guards, caching, paraphrase reuse, concurrency, idempotency, error handling, persistence, Gemini client retries/parsing, and API endpoints.

## Deploy on Render
1. Push this repo to GitHub. 2. Render → *New → Blueprint* (uses `render.yaml`) or a Web Service with
build `pip install -r requirements.txt` and start `uvicorn app.main:create_app --factory --host 0.0.0.0 --port $PORT --workers 1`.
3. Set `GEMINI_API_KEY` in the dashboard. 4. Health check path: `/health`.

> **Render free tier filesystem is ephemeral.** The SQLite file (cache + counters) can be lost on restart, redeploy or
> spin-down; the free tier also sleeps after inactivity, so the first request can be slow. The app recreates an empty DB
> automatically and simply re-warms the cache. For durable data use a paid instance with a persistent disk and set `DB_PATH`
> to a path on it (e.g. `/var/data/helpdesk.db`).

## Known limitations
- Run a single worker/instance: single-flight, idempotency and conversation memory are in-process (cache + counters are in SQLite).
- Conversation memory is in-process too; it resets on restart.
- The FAQ vocabulary is hand-curated for the supplied docs; unknown paraphrases fall back to a (correct) Gemini call rather than risking a wrong merge.
- Gemini answers are validated structurally (JSON, known source files) but not fact-checked beyond the prompt rules.

## AI sessions
Exported AI session transcripts go in `ai_sessions/` (required by the assignment).
