# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Boardom is a teacher's workspace for lesson ideas and source materials. Backend: FastAPI + synchronous SQLAlchemy 2 + Alembic + SQLite, managed with **uv** (Python 3.12+). Frontend: Next.js App Router + TypeScript + React 19, managed with **npm** (Node 22.13+). No external services, API keys, or Docker.

## Commands

### Setup (from repo root)

```bash
cd backend
cp .env.example .env
uv sync --locked
uv run alembic upgrade head
cd ../frontend
cp .env.example .env.local
npm ci
```

### Run locally

```bash
# backend/
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
# frontend/
npm run dev                      # http://localhost:3000
npm run build && npm run start   # production frontend
```

Use `http://localhost:3000` in the browser, not `127.0.0.1:3000`: the latter is a different origin and fails the CSRF check.

### Backend checks (from `backend/`)

```bash
uv run pytest -q
uv run pytest tests/test_extraction.py::test_name -q   # single test
uv run ruff check .
uv run ruff format --check .
uv run alembic check          # schema drift between models and migrations
```

Use `uv add` / `uv sync` / `uv run` and keep `uv.lock` up to date. Ruff uses line length 100 and rules `E,F,I,UP,B`.

### Frontend checks (from `frontend/`)

```bash
npm run lint
npm run typecheck      # runs `next typegen` first, so it works before any build
npm run format:check   # `npm run format` to fix
npm run build
```

## Architecture

### Backend (`backend/app`)

- **`main.py` `create_app(settings)`** is the app factory. Everything shared lives on `app.state`: `settings`, `session_factory`, `storage` (`FileStorage`), and `worker` (`ExtractionWorker`). Routes read these through `request.app.state`, not module globals. Tests call `create_app` with custom `Settings`.
- **Middleware in `main.py`** handles CSRF: every POST/PATCH/PUT/DELETE must have an `Origin` header exactly equal to `BOARDOM_FRONTEND_ORIGIN`, or it gets a 403. There is no CORS. All responses get `Cache-Control: no-store`. Global exception handlers turn validation errors into one 422 `detail` string and `SQLAlchemyError` into a 503.
- **`core/config.py`**: pydantic-settings with the `BOARDOM_` prefix. `.env` and relative DB/upload paths resolve from `backend/` (`BACKEND_ROOT`), not the working directory. Always use `settings.resolved_database_url` / `resolved_upload_dir`.
- **`core/security.py`** holds the `Db`, `CurrentUser`, `CurrentAdmin`, `CurrentTeacher`, and `CurrentStudent` dependency aliases. Roles are `users.role` (`admin`/`teacher`/`student`); workspace, document, and content routes use `CurrentTeacher`. `CurrentUser` returns 403 while `must_change_password` is set; only `/auth/me` and `/auth/change-password` use `AuthenticatedUser`, which skips that check. Sessions are opaque random tokens in an HttpOnly `boardom_session` cookie, and only the SHA-256 hash is stored in `SessionToken`. Logging in rotates the browser's existing session. Passwords are hashed with Argon2id.
- **Ownership**: the `owned_workspace` (`api/workspaces.py`) and `owned_document` (`api/documents.py`) helpers do the ownership checks. Another user's resource returns **404**, not 403. Reuse these helpers in new routes.
- **Schema changes go through Alembic only** (`alembic/versions/`). The app never calls `create_all()`. Tests run `alembic upgrade head` on a fresh temporary DB for each test.
- **Storage (`services/storage.py`)**: files are stored under random storage keys. The filename is metadata only. Upload size is checked incrementally while bytes are copied. Deletion uses a staged rename to `.delete-<op>-<key>`, then the DB commit, then unlink. A failure before the commit restores the files. SQLite and the filesystem can't share a transaction, so partial-failure paths are explicit (409 for missing files, 503 for storage errors).
- **Extraction pipeline (Layer 2)**:
  - `api/content.py` `POST .../extract` sets the document status to `processing` with an `extraction_attempt_id`, commits, then submits the job to `ExtractionWorker`.
  - `services/extraction.py` `ExtractionWorker` runs one job at a time (a `ThreadPoolExecutor(1)` plus a non-blocking `BoundedSemaphore(1)`; a busy worker returns 409). It runs `services/parser.py` as a **separate subprocess** with a timeout. The parser is standalone and must not import app code, the DB, or the network. It writes JSON results to a temp file.
  - `finish()` writes results only if the status is still `processing` with the same attempt id. It replaces the `SourceUnit` rows (one per PDF page, or one "Document" unit) and bumps `content_revision`.
  - Statuses: `uploaded`, `processing`, `extracted`, `failed`, `needs_ocr`.
  - On startup, `worker.recover()` marks any leftover `processing` rows as `failed`/`interrupted`. This assumes a single server process.
  - Teachers correct text via `PATCH .../units/{unit_id}`, which uses optimistic locking on `content_revision`. They mark a document reviewed via `PATCH .../review` and export via `GET .../content/download`.

### Frontend (`frontend/`)

- **The browser calls only relative `/api/v1/*` URLs.** `next.config.ts` rewrites them to `BACKEND_URL` (server-side only, default `http://127.0.0.1:8000`), so the browser never talks to FastAPI directly.
- `experimental.proxyClientMaxBodySize` (12mb) must stay above `BOARDOM_MAX_UPLOAD_BYTES` plus multipart overhead. Change both together.
- `lib/api.ts` has the typed `api<T>()` fetch wrapper, `ApiError`, and shared types. `components/AuthProvider.tsx` holds the auth state.
- `frontend/AGENTS.md`: this Next.js version (16.x) has breaking changes from older releases. Before writing Next.js code, read the relevant guide in `frontend/node_modules/next/dist/docs/` and heed deprecation notices. `next dev` re-adds that block to AGENTS.md automatically.

## Notes

- The README's "Layer 1 only / documents remain Uploaded" wording predates the extraction layer. The code is the source of truth.
- Accounts: the admin is seeded from config on startup (`services/accounts.py`, never overwritten). Login (per email) and admin PIN reset (global) use the in-memory `core/ratelimit.py` limiter on `app.state`. Student limits are enforced in `api/teacher.py` after a write lock (`lock_teacher`).
- AI (`app/ai/`): `build_provider(settings)` sets `app.state.ai` to `OpenAIProvider` (key set) or the offline `FakeProvider` (no key = demo mode; tests always use it). `/ai/*` routes use `CurrentStaff` (teacher or admin). `AIError` maps to a safe JSON error in `main.py`.
- Syllabus/notes: `services/retrieval.py` (chunks + JSON embeddings, `[C n]` ordinals from `chunk_counters`, never reused), `services/course_content.py` (prompts, structured outputs, citation-checked generation, `add_version`), `services/jobs.py` (`JobRunner` on `app.state.jobs`, one active job per course+kind), `services/demo_ai.py` (FakeProvider builders that parse the same prompt format). Routes in `api/course_content.py`.
- Materials: `course_content.KINDS` registry (notes, lab manual, lesson plan, rubric); generic `/artifacts` routes, `/notes` kept as aliases. `services/concepts.py` (graph build/clean, gap ordering), `services/publishing.py` (publish snapshots `published_version`; md/PDF export). Student side: `api/student.py`, `services/student_tools.py` (visibility, coach, quizzes, cached study aids), `services/video.py` (Pillow + TTS + imageio-ffmpeg). Demo builders in `services/demo_ai.py` parse the same prompt blocks (`format_passages`, `notes_block`, `units_block`).
- Round 3:
  - Course wizard: `CourseProfile` and `POST /workspaces/wizard`; `course_content.profile_block` and `apply_profile` enforce the plan.
  - OCR for images and scans: `provider.read_image`, called from `ExtractionWorker.recognize`.
  - ChromaDB vectors: `services/vector_index.py`, reached as `db.info["vector_index"]` (set by `session_factory(engine, index)`).
  - Web research: `services/research.py`; accepted findings become `[W n]` citations on syllabus units.
  - Guardrails: `services/guardrails.py` (injection screen, moderation `check_text`, PII log scrubber).
  - Usage and limits: `services/usage.py` (queued `UsageRecorder` on `app.state.usage`, `ai_actor` context, `AIQuota` dependency).
  - Also: `app/evals`, `app/seed_demo.py`, `run_all.ps1`, `run_all.sh`.
- Shell heredocs mangle backslash escapes in this environment. Write code containing backslash escapes (newline, hex bytes) with the editor tools, not with `python - <<EOF`.
- SQLite migrations: `alembic/env.py` turns foreign keys off for the migration connection, because batch mode rebuilds tables and a DROP of `users` would otherwise cascade-delete rows.
- Known gaps (README "Deployment limitations"): rate limiting is per process; no teacher/student self-service password reset, pagination, expired-session pruning, or production hardening yet.
