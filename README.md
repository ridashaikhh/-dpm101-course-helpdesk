# IIMBx DPM-101 Course Helpdesk Chatbot

> **Live Demo:** [https://dpm101-helpdesk-msdb.onrender.com](https://dpm101-helpdesk-msdb.onrender.com)

A lightweight, deployable FastAPI helpdesk chatbot built for the IIMBx *Digital Product Management (DPM-101)* course. The application is designed to answer student queries during high-traffic exam periods strictly using the four supplied course documents in `course_docs/`, while providing resilient caching, duplicate suppression, concurrency protection, and zero-crash error handling.

**Tech Stack:** Python · FastAPI · Vanilla HTML/CSS/JavaScript · Google Gemini API (REST via `httpx`) · SQLite · pytest · Render

---

## Architecture & Request Flow

```
Client Browser
   │
   ▼
[ Rate Limiter ] ───▶ Per-IP sliding-window limiter (30 req/min)
   │
   ▼
[ Idempotency Guard ] ───▶ Deduplicates repeat clicks via request_id (120s TTL)
   │
   ▼
[ Caching Layer ] ───────▶ 1. Exact match (normalized text hash)
   │                       2. Safe FAQ intent match (strict concept & vocabulary match)
   │
   ├──▶ Cache Hit ───────▶ Served instantly from SQLite (answer_cache)
   │
   ▼ Cache Miss
[ Single-Flight Coalescer ] ──▶ Merges identical concurrent in-flight requests
   │
   ▼
[ Concurrency Semaphore ] ───▶ Caps parallel Gemini API calls (default: 4)
   │
   ▼
[ Gemini 2.5 Flash REST API ] ──▶ Temperature 0, structured JSON output
   │
   ▼
[ SQLite Storage ] ──────▶ Saves validated answers to cache & updates atomic counters
```

---

## Key Features & Document Handling

The application handles internal document quirks dynamically in Python code without modifying the raw `.txt` files:

| Quirk / Requirement | Solution & Implementation (`app/`) |
|---|---|
| **Conflicting Grading Policies** | `03_grading_policy_v2.txt` declares that it supersedes `02_grading_policy_v1.txt`. `app/documents.py` detects this claim and verifies dates (`05 Oct 2026 > 10 Jan 2026`), excluding v1 completely from the context sent to Gemini. |
| **Untrusted Student Forum Content** | Section 3 of `04_exam_rules_and_faq.txt` contains unmoderated forum posts and a simulated prompt injection. `_split_untrusted()` cuts off all content from the untrusted heading onward. |
| **Prompt Injection Defense** | Layer 1 cuts untrusted content before prompt generation. Layer 2 enforces system prompt Rule 2: documents are treated strictly as data, never as executable instructions. |
| **Strict Out-of-Scope Fallback** | Uncovered topics (e.g., refunds, SQL/Kubernetes, cricket) return `covered: false` and the exact standard notice: *"This is not mentioned in the course documents."* |
| **Conservative 2-Tier Caching** | **Exact:** Case, whitespace, and punctuation-normalized hash.<br>**FAQ:** Intent concept matches with strict closed-vocabulary checking. Any query with extra numbers, dates, or altered constraints (e.g., "1 day late", "50%", "two quizzes") bypasses the FAQ cache. |
| **Follow-up Context Isolation** | Follow-up questions in an ongoing conversation use conversation history but are never written to or read from the shared FAQ cache. |
| **Concurrency & Single-Flight** | Frontend disables submit during in-flight requests. Backend idempotency checks `request_id`, and `_inflight` coalesces concurrent identical questions into a single Gemini call. |
| **Safe Error Handling** | 429, 5xx, and timeout responses are retried once with backoff. Exhausted failures return friendly JSON error responses with proper HTTP status codes. Transient errors are never cached. |
| **Concurrency-Safe SQLite** | Single connection guarded by `threading.RLock`, WAL journal mode, and `BEGIN IMMEDIATE` transactions for atomic writes and counter updates. |

---

## API Endpoints

- `GET /` — Responsive web chat interface with live counters.
- `POST /api/chat` — Main conversation endpoint. Accepts `{"question": "...", "conversation_id": "...", "request_id": "..."}`.
- `GET /api/stats` — Real-time performance metrics (total questions, API calls, cache hits, hit rate, latency, suppressed duplicates).
- `GET /api/docs` — Summary of loaded, active, and superseded course documents.
- `GET /health` — Health check endpoint reporting service, database, and document status.

---

## Environment Variables

Configure these settings in `.env` (local) or your hosting environment. **Never commit actual API keys or secrets to version control.**

| Variable | Required | Default | Description |
|---|---|---|---|
| `GEMINI_API_KEY` | **Yes** | `""` | Google Gemini API key. Missing keys yield a friendly 503 response instead of crashing. |
| `GEMINI_MODEL` | No | `gemini-2.5-flash` | Gemini model identifier. |
| `GEMINI_THINKING_BUDGET` | No | `0` | Thinking token budget (`0` turns thinking off for minimum latency). |
| `GEMINI_TIMEOUT_S` | No | `15.0` | HTTP request timeout in seconds. |
| `GEMINI_MAX_RETRIES` | No | `1` | Retry attempts for transient 429/5xx status codes and timeouts. |
| `GEMINI_MAX_CONCURRENCY` | No | `4` | Maximum parallel in-flight requests to the Gemini API. |
| `DB_PATH` | No | `./data/helpdesk.db` | Filesystem path for the SQLite database. |
| `RATE_LIMIT_PER_MIN` | No | `30` | Maximum requests per minute per client IP for `/api/chat`. |

---

## Local Setup & Execution

### Prerequisites
- Python 3.10 to 3.14
- Google Gemini API key

### Installation Steps

1. **Clone the repository:**
   ```bash
   git clone https://github.com/ridashaikhh/-dpm101-course-helpdesk.git
   cd ./-dpm101-course-helpdesk
   ```

2. **Create and activate a virtual environment:**
   - **Linux / macOS:**
     ```bash
     python -m venv .venv
     source .venv/bin/activate
     ```
   - **Windows (PowerShell):**
     ```powershell
     python -m venv .venv
     .\.venv\Scripts\Activate.ps1
     ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements-dev.txt
   ```

4. **Configure environment:**
   ```bash
   cp .env.example .env
   # Edit .env and paste your GEMINI_API_KEY
   ```

5. **Start the application:**
   ```bash
   uvicorn app.main:create_app --factory --reload --host 127.0.0.1 --port 8000
   ```
   Open `http://localhost:8000` in your browser.

6. **Run sample test questions (optional):**
   ```bash
   python scripts/run_sample_questions.py
   ```

---

## Automated Tests

The test suite covers document parsing, conflict resolution, prompt injection stripping, normalization, exact/FAQ caching, request deduplication, concurrency coalescing, Gemini error handling, and API endpoints using mocked transports (no external network or API key required):

```bash
pytest
```

All 53 unit and integration tests execute and pass in under 5 seconds.

---

## Render Deployment

The repository includes a `render.yaml` blueprint configured for Render's Web Service:

1. Push your repository to GitHub.
2. In the Render Dashboard, click **New → Blueprint** and link the repository (or create a **Web Service** manually).
3. **Build Command:** `pip install -r requirements.txt`
4. **Start Command:** `uvicorn app.main:create_app --factory --host 0.0.0.0 --port $PORT --workers 1`
5. **Health Check Path:** `/health`
6. Add `GEMINI_API_KEY` under Environment Variables in the Render dashboard.

---

## Important Constraints & Limitations

- **Ephemeral Filesystem on Render Free Tier:** Render free tier instances use an ephemeral filesystem. The SQLite database (`/tmp/helpdesk.db`), including cached answers and counters, resets whenever the free instance spins down, sleeps after 15 minutes of inactivity, or redeploys. The application automatically re-creates an empty database and initialized counters on startup, and answers are cached on-demand as questions are asked (automatic cache pre-warming is not implemented). For durable storage, attach a persistent disk on a paid tier or point `DB_PATH` to persistent storage.
- **Single-Worker Process:** In-process concurrency mechanisms (request deduplication, single-flight coalescing, per-IP rate limiting, and conversational turn history) reside in memory. The service must run with `--workers 1`.
- **In-Memory Conversation History:** Follow-up conversation context is stored in memory and resets on server restart.
- **Hand-Curated FAQ Vocabulary:** The FAQ paraphrase normalizer uses a strict vocabulary subset curated specifically for DPM-101 course topics. Unrecognized paraphrases safely fall through to Gemini and exact caching to prevent false merges.

---

## AI Development Session Log

The exported AI session transcript documenting the prompts and responses used during development is located at:
- [ai_sessions/claude-development-session.md](ai_sessions/claude-development-session.md)
