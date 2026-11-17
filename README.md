# Boardom

A teacher’s workspace for lesson ideas and source materials.

**Layer 1 is implemented:** email/password accounts, persistent sessions, lesson workspace CRUD, and private PDF/Markdown/text uploads, listings, downloads, and deletion. The frontend is Next.js App Router + TypeScript; the backend is FastAPI + synchronous SQLAlchemy, Alembic, and SQLite.

AI generation, content extraction, OCR, embeddings, vector search, slides, quizzes, and interactive activities are intentionally deferred. Documents remain **Uploaded**; they are not processed.

## Requirements

- Python **3.12+** (verified with 3.13.5).
- Node.js **22.13+** (verified with 22.23.5) and npm.
- [uv](https://docs.astral.sh/uv/getting-started/installation/) for Python dependencies.

No API keys, Docker, paid services, or external database are needed. Exact resolved versions are recorded in `backend/uv.lock` and `frontend/package-lock.json`. Next.js installation requirements are documented [here](https://nextjs.org/docs/app/getting-started/installation); the Node requirement above also covers the lint tooling.

## Setup

Run from the repository root:

```bash
cd backend
cp .env.example .env
uv sync --locked
uv run alembic upgrade head
cd ../frontend
cp .env.example .env.local
npm ci
```

The migration creates the tables. The application never calls `create_all()`. If you change the database URL, run the migration for the new database before starting the API.

## Run locally

Terminal 1, from the repository root:

```bash
cd backend
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Terminal 2, from the repository root:

```bash
cd frontend
npm run dev
```

- Application: **http://localhost:3000**
- API docs: **http://127.0.0.1:8000/docs**
- API health: **http://127.0.0.1:8000/health**

Use `localhost` in the browser consistently. `127.0.0.1:3000` is a different origin and is rejected by the default CSRF configuration. If port 3000 is occupied, stop the other server or set the frontend origin to match the actual port. Next’s same-origin rewrite forwards `/api/v1/*` to FastAPI; browser code uses relative URLs only.

To run the production frontend locally:

```bash
cd frontend
npm run build
npm run start
```

The backend must also be running. `BACKEND_URL` is read by Next’s server configuration; rebuild if changing it for a production build.

## Configuration and storage

Copy the example environment files before editing them. Never commit real `.env` files.

| Backend setting | Default | Purpose |
| --- | --- | --- |
| `BOARDOM_DATABASE_URL` | `sqlite:///data/boardom.db` | SQLAlchemy database URL |
| `BOARDOM_UPLOAD_DIR` | `data/uploads` | Private file storage |
| `BOARDOM_MAX_UPLOAD_BYTES` | `10485760` | 10 MiB per file |
| `BOARDOM_SESSION_LIFETIME_SECONDS` | `604800` | Seven days, fixed expiry |
| `BOARDOM_COOKIE_SECURE` | `false` | Set `true` for HTTPS deployments |
| `BOARDOM_FRONTEND_ORIGIN` | `http://localhost:3000` | Exact allowed browser Origin |
| `BOARDOM_ENVIRONMENT` | `development` | `development`, `test`, or `production` |

Backend `.env` and relative database/upload paths are resolved from `backend/`, independently of the launch directory. Defaults store the database at `backend/data/boardom.db` and source files in `backend/data/uploads/`. These paths, SQLite sidecars, caches, and virtual environments are ignored by Git. UUIDs identify resources. Timestamps are stored as UTC and serialized with an explicit UTC timezone.

Frontend `BACKEND_URL` defaults to `http://127.0.0.1:8000`; it is server-side only. The UI retrieves only the non-sensitive file-size limit through `GET /api/v1/config`. If you increase the backend limit, increase `experimental.proxyClientMaxBodySize` in `frontend/next.config.ts` above that limit plus multipart overhead (currently 12 MB for a 10 MiB file), and restart/rebuild Next.

## Authentication and request security

Registration **logs the educator in immediately**. Emails are trimmed, lowercased, validated, and unique. Passwords are 8–128 characters and stored as Argon2id hashes. Login uses a generic invalid-credentials error.

A random opaque token is sent only in an HttpOnly cookie with `SameSite=Lax`, `Path=/`, explicit expiry, and configurable `Secure`. Only its SHA-256 hash is stored in the sessions table. Logging in rotates the current browser session; logout deletes the server-side session and clears the cookie. Expired sessions are rejected. Tokens are never stored in localStorage or returned in JSON. API responses are marked `Cache-Control: no-store`.

**CSRF defense:** every POST, PATCH, PUT, and DELETE must have an `Origin` header exactly equal to `BOARDOM_FRONTEND_ORIGIN`, including registration and login. Missing, `null`, and untrusted origins receive 403. No credentialed CORS is enabled. CLI/API clients must send that Origin explicitly as well. API docs are useful for schemas and reads; mutating requests from the backend docs origin are intentionally rejected. Example health check:

```bash
curl http://127.0.0.1:8000/health
```

All workspace/document operations require a valid session and check ownership. Other users’ resources return 404. Downloads are authenticated attachment responses, not public file URLs.

## Upload and deletion behavior

- One file per multipart request: `.pdf`, `.md`, or `.txt` (extension case-insensitive).
- Empty, oversized, unsupported, invalid UTF-8, and invalid PDF-signature uploads are rejected.
- File size is checked incrementally as bytes are copied, independently of Content-Length.
- PDF validation checks the `%PDF-` signature only; no parsing, extraction, or malware scanning is performed.
- Filenames are metadata. Random server-generated storage keys determine filesystem paths.
- Failed validation or database insertion removes partial/new files.
- Deleting documents or workspaces removes metadata and associated files.

Deletion first stages files with a `.delete-<operation-id>-<storage-key>` name in the same directory. A filesystem or database failure before commit restores staged files and retains metadata. Missing files produce 409; storage failures produce 503. If metadata commits but final unlinking fails, the response explicitly reports incomplete cleanup (503); it does not claim success.

SQLite and the filesystem cannot share an atomic transaction. A process crash can leave orphan files or staged deletion files. For recovery, stop writes and back up the database and upload directory together. For each staged file, its final 32-character suffix is the original storage key: if a `source_documents` row still references that key, restore the file to that key; otherwise remove the orphan after confirming the metadata deletion. A post-commit cleanup error can leave an outdated list onscreen until refresh.

## Checks

Backend, from `backend/`:

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run alembic check
```

Integration tests apply the initial Alembic migration to a fresh temporary database and use temporary uploads for each test. They cover authentication, expiry, rotation, duplicate emails, validation, CSRF, ownership, CRUD, downloads, file cleanup, missing files, and failure rollback. No external services or development records are needed.

To explicitly test a new development-style database (POSIX shell):

```bash
BOARDOM_DATABASE_URL=sqlite:///data/migration-smoke.db uv run alembic upgrade head
```

Frontend, from `frontend/`:

```bash
npm run lint
npm run typecheck
npm run format:check
npm run build
```

`npm run typecheck` generates Next route types before running TypeScript, so it works before the first build. `npm run format` formats frontend source. ESLint uses the Next, React Hooks, and TypeScript plugins directly to keep the lint dependency set compatible with ESLint 10.

## Manual smoke test

1. Start both services and open http://localhost:3000.
2. Register with a display name, email, and password. Confirm the dashboard appears.
3. Create a lesson workspace. Set subject, learner level, duration, and description.
4. Upload a small UTF-8 `.txt` or `.md` file and a PDF. Confirm **Uploaded**, filename, size, and date.
5. Refresh. Confirm the workspace and files persist.
6. Download a source and compare it to the original.
7. Edit the workspace; clear the optional description and change duration. Refresh to confirm persistence.
8. Delete a document, confirming the dialog. Delete a workspace with another file attached.
9. Log out. A direct dashboard/workspace visit should redirect to login. Log in and confirm remaining work is saved.
10. Register another account in a private browser window. The first account’s workspace and download URLs must be inaccessible.
11. Try an empty file, wrong extension, fake PDF, and file over 10 MiB; confirm clear errors.

## Verified in this workspace

- 35 backend integration tests passed, including a fresh migrated database per test.
- Ruff lint and formatting, Alembic schema-drift check, frontend lint, TypeScript, Prettier, and production build passed.
- Browser smoke test passed: register → create workspace → upload Markdown → refresh → download → edit duration → refresh → logout → protected-page redirect → login and reopen saved work. Downloaded bytes matched the source file.
- Document/workspace deletion and cross-user access were verified by backend integration tests.

The installed Starlette version emits a deprecation warning for its `httpx` TestClient adapter; the tests pass. In this restricted execution environment, TestClient and Next’s build subprocesses required running outside the sandbox. This is an environment restriction, not a required deployment mode.

## Deployment limitations

This is a local hackathon foundation. SQLite serializes writes, and files live on one machine. Use persistent storage, back up the database and uploads together, and avoid multiple application instances sharing an unmanaged filesystem. A deployment needs HTTPS, secure cookies, the exact public frontend origin, and request-body limits on the reverse proxy. Starlette may spool multipart data before the route’s incremental file-size check, so infrastructure-level body limits are needed for untrusted public traffic.

There is no password reset, email verification, rate limiting, account deletion, storage quota, expired-session pruning job, or pagination yet. Those operational features should be added before a public launch. No AI or content-processing layer is implemented.
