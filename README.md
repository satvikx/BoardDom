# Boardom

A teacher’s workspace for lesson ideas and source materials, with admin, teacher, and student accounts.

- **Admins** create teacher accounts, set how many students each teacher may have, and delete accounts.
- **Teachers** keep the existing workspace (course) features: lesson CRUD, PDF/Markdown/text uploads, text extraction and review. They create up to 4 student accounts by default and enroll students in their courses.
- **Students** see the courses they are enrolled in (read only).

The frontend is Next.js App Router + TypeScript; the backend is FastAPI + synchronous SQLAlchemy, Alembic, and SQLite. No API keys, Docker, paid services, or external database are needed.

## Requirements

- Python **3.12+** (verified with 3.14.2).
- [uv](https://docs.astral.sh/uv/getting-started/installation/) (verified with 0.9.12).
- Node.js **22.13+** and npm (verified with Node 24.13.0, npm 11.6.2).

Exact resolved versions are in `backend/uv.lock` and `frontend/package-lock.json`.

## Quick start

You need **Python 3.12+**, **[uv](https://docs.astral.sh/uv/getting-started/installation/)**, and **Node.js 22.13+** with npm. No API key is needed: without one, every AI feature runs offline in demo mode.

### One command

From the repository root:

```powershell
.\run_all.ps1            # Windows PowerShell
```

```bash
./run_all.sh             # macOS / Linux / Git Bash
```

Each script:

1. creates `backend/.env` and `frontend/.env.local` from the examples if they are missing;
2. runs `uv sync` and `uv run alembic upgrade head`;
3. seeds the offline demo course;
4. runs `npm install`;
5. starts both servers.

Press **Ctrl+C** to stop both servers. Options:

- `-NoSeed` / `--no-seed` skips the demo course.
- `-Prod` / `--prod` uses a production frontend build.
- `-BackendPort 8001 -FrontendPort 3001` (or the `BACKEND_PORT` / `FRONTEND_PORT` environment variables) changes the ports. The scripts set the matching origin and proxy URL.

If PowerShell refuses to run scripts, run `powershell -ExecutionPolicy Bypass -File .\run_all.ps1`.

### Step by step

Terminal 1, the backend:

```bash
cd backend
cp .env.example .env              # PowerShell: Copy-Item .env.example .env
uv sync
uv run alembic upgrade head
uv run python -m app.seed_demo    # optional: offline demo course (--reset rebuilds it)
uv run uvicorn app.main:app --reload --port 8000
```

Terminal 2, the frontend:

```bash
cd frontend
cp .env.example .env.local        # PowerShell: Copy-Item .env.example .env.local
npm install
npm run dev
```

Open **http://localhost:3000** (use `localhost`, not `127.0.0.1`) and log in:

| Account | Email | Password |
| --- | --- | --- |
| Admin | `admin@example.com` | `BoardomAdmin#2026` (admin reset PIN `482916`) |
| Demo teacher | `demo.teacher@example.com` | `DemoTeacher#2026` |
| Demo students | `asha@`, `ben@`, `chen@example.com` | `DemoStudent#2026` |

> **Change the admin password and PIN before anyone else can reach the app.** With `BOARDOM_ENVIRONMENT=production` the API refuses to start with the defaults. Changing `BOARDOM_ADMIN_PASSWORD` later does not change an existing admin's password.

### Using the AI gateway

Put these in `backend/.env` (never in `.env.example` or Git), then restart the backend:

```ini
BOARDOM_OPENAI_API_KEY=your-key
BOARDOM_OPENAI_BASE_URL=https://genailab.tcs.in/
BOARDOM_AI_VERIFY_TLS=false          # hackathon gateway only; refused in production
BOARDOM_MODEL_SMART=genailab-openai-gpt-5.6-luna
BOARDOM_MODEL_FAST=genailab-openai-gpt-5.6-luna
BOARDOM_MODEL_EMBEDDING=text-embedding-3-small
```

Check it with `uv run python -m app.ai.smoke --models --web` (in `backend/`). The command reports, separately, whether models, text, embeddings, moderation and web search each work. `BOARDOM_AI_PROVIDER=fake` forces offline demo mode even with a key set. Changing the embedding model re-embeds the sources automatically; the `[C n]` labels stay the same.

- API docs: http://localhost:8000/docs. Health check: http://localhost:8000/health
- `uv sync --locked` and `npm ci` install exactly the locked versions.

### Troubleshooting

- **Port already in use** (`address already in use` / `EADDRINUSE`): stop the other process, or pick another port.
  - Backend: run uvicorn with `--port 8001` and set `BACKEND_URL=http://127.0.0.1:8001` in `frontend/.env.local`.
  - Frontend: run `npm run dev -- --port 3001` and set `BOARDOM_FRONTEND_ORIGIN=http://localhost:3001` in `backend/.env`.
  - Restart both servers afterwards.
- **"Untrusted request origin" (403) on login or any form**: open **http://localhost:3000**, not `http://127.0.0.1:3000`. They are different origins, and only `BOARDOM_FRONTEND_ORIGIN` is accepted.
- **"Unable to connect" or 500 errors from `/api/v1`**: the backend is not running, or `BACKEND_URL` in `frontend/.env.local` points to the wrong port.
- **`no such table` / `no such column`**: run `uv run alembic upgrade head` in `backend/`.
- **Forgot the admin password**: click **Forgot admin password?** on the login page and use the reset PIN. After 5 wrong PINs, PIN reset is locked for 15 minutes (restarting the API clears the lock).
- **"Too many failed login attempts"**: 5 wrong passwords for one email lock that email for 15 minutes. Wait, or restart the API (the counter is kept in memory).

## Demo walkthrough

1. **Admin creates a teacher.** Log in as `admin@example.com`. You land on **/admin** (Users). Under **Add teacher**, enter a name and email; leave the student limit empty to use the default of 4. Copy the temporary password from the box. It is shown only once.
2. **Teacher logs in and changes the password.** Log out, then log in as the teacher with the temporary password. You are sent to **/change-password**, and nothing else works until you choose a new password. Then you land on **/dashboard**.
3. **Teacher creates a course and 4 students.** Create a workspace (a course). Open **Students** in the header, add 4 students, and note each temporary password. The indicator shows **4 of 4 students used**.
4. **A 5th student is blocked.** The form is disabled with an explanation. The API returns 409: *Student limit reached (4 of 4). Ask the admin to raise it.*
5. **Admin raises the limit.** As admin, change the teacher's **Student limit** to 5 in the users table and click **Save**.
6. **Teacher adds the 5th student.** Reload **Students**, which now shows **4 of 5**, and add the 5th. Open the course and tick students in its **Students** panel to enroll them.
7. **A student logs in.** Log in as a student with their temporary password and choose a new one. You land on **/learn**, which shows the enrolled course cards. Students see "Not allowed" on teacher and admin pages, and the API returns 403.

Lowering a limit below the current number of students never deletes anyone; it only blocks new students. Deleting a teacher (admin only, after a confirmation that lists everything removed) deletes their courses, uploaded files, and students.

## Roles and accounts

| | Admin | Teacher | Student |
| --- | --- | --- | --- |
| Home after login | `/admin` | `/dashboard` | `/learn` |
| Created by | config, on first start | admin (or public sign-up, if enabled) | their teacher |
| Workspaces, documents, extraction | 403 | own only | 403 |
| `/admin/*` | ✓ | 403 | 403 |
| `/teacher/*`, enrollments | 403 | own students and courses | 403 |
| `/student/courses` | 403 | 403 | ✓ |

- **Public sign-up is off by default.** `POST /auth/register` returns 403 and the Register links are hidden. With `BOARDOM_ALLOW_PUBLIC_SIGNUP=true`, registration creates a teacher. `GET /api/v1/config` exposes the flag.
- **Temporary passwords** are random (for example `k7mq-x2fp-9tha`). They are returned once, in the create response, and stored only as Argon2id hashes. Accounts created by an admin or a teacher must change the password at first login. Until they do, every API route except `/auth/me`, `/auth/logout`, and `/auth/change-password` returns 403, and the UI redirects to `/change-password`.
- **Student limit**: each teacher has a `student_limit`; empty means `BOARDOM_DEFAULT_STUDENT_LIMIT`. It counts the student accounts that teacher created. The check and the insert run in one write transaction. Emails are unique across all users.
- **Deletion**: the admin cannot delete themselves or another admin.
  - Deleting a teacher removes their courses (and the stored files, using the same staged deletion as workspace deletion), their students, enrollments, and sessions.
  - Deleting a student removes the account and its enrollments.
- **Admin password reset by PIN**: `POST /api/v1/auth/admin/reset-password` with `{email, pin, new_password}`.
  - It works only for an admin account. The PIN is compared with `hmac.compare_digest`.
  - A wrong PIN, an unknown email, and a non-admin email all get the same `Invalid PIN or account.` error.
  - After 5 wrong attempts, all PIN resets are locked for 15 minutes (429).
  - Success sets the password, signs out every admin session, and clears the forced-change flag.
  - The PIN comes only from configuration; no endpoint shows or changes it.
- **Login rate limiting**: 5 failed logins for one email within 15 minutes lock that email for 15 minutes (429).
  - The key is the lowercased email, deliberately not the IP: requests arrive through the Next.js proxy, so every client appears as `127.0.0.1`.
  - The limiter (`backend/app/core/ratelimit.py`) is in memory and per process. Replace it with a shared store before running several API processes.
- `last_login_at` is updated on every successful login.

### Account API

| Method and path | Role |
| --- | --- |
| `POST /auth/change-password` `{current_password, new_password}` | any signed-in user |
| `POST /auth/admin/reset-password` `{email, pin, new_password}` | none (PIN) |
| `GET /admin/users?role=&q=` | admin |
| `POST /admin/teachers` `{display_name, email, student_limit?}` | admin |
| `PATCH /admin/teachers/{id}` `{student_limit}` (`null` = default) | admin |
| `DELETE /admin/users/{id}` | admin |
| `GET /teacher/students` → `{students, used, limit}` | teacher |
| `POST /teacher/students` `{display_name, email}` | teacher |
| `DELETE /teacher/students/{id}` | teacher (own students) |
| `GET /workspaces/{id}/enrollments` | teacher (own course) |
| `PUT` / `DELETE /workspaces/{id}/enrollments/{student_id}` | teacher (own course and student) |
| `GET /student/courses` | student |

All paths are under `/api/v1`. Mutating requests need the `Origin` header described below.

## AI configuration

The AI layer lives in `backend/app/ai/`. Routes reach it through `request.app.state.ai`, which is either the real OpenAI-compatible provider or an offline fake.

Set these in `backend/.env` (the example values are in `backend/.env.example`):

| Setting | Example / default | Purpose |
| --- | --- | --- |
| `BOARDOM_OPENAI_API_KEY` | *(empty)* | Your key. Put it only in `backend/.env`, which Git ignores. Never put it in `.env.example`. |
| `BOARDOM_OPENAI_BASE_URL` | `https://genailab.tcs.in/` | OpenAI-compatible gateway. Leave it empty for api.openai.com. |
| `BOARDOM_AI_VERIFY_TLS` | `false` in the example, `true` by default | TLS certificate checking for the AI endpoint. |
| `BOARDOM_AI_PROVIDER` | `openai` | `fake` forces offline mode even when a key is set. |
| `BOARDOM_MODEL_SMART` / `BOARDOM_MODEL_FAST` | `genailab-openai-gpt-5.6-luna` | Chat models (smart for quality, fast for cheap calls). |
| `BOARDOM_MODEL_EMBEDDING` / `BOARDOM_MODEL_MODERATION` | `text-embedding-3-small` / `omni-moderation-latest` | Embedding and moderation models. |
| `BOARDOM_AI_TIMEOUT_SECONDS` / `BOARDOM_AI_MAX_RETRIES` | `60` / `2` | Per-call timeout and SDK retries. |

**Demo mode.** With no key (or an empty `BOARDOM_OPENAI_API_KEY=`), the API starts normally and logs `running AI features in offline demo mode`. AI calls then return deterministic `[demo] …` answers without any network access, and `GET /api/v1/ai/status` reports `"demo_mode": true`. The tests always run this way. In production (`BOARDOM_ENVIRONMENT=production`), the API refuses to start without a key.

**Endpoints** (teachers and admins only; students get 403, anonymous users 401):

- `GET /api/v1/ai/status`: provider name, demo mode, and configured model names. Makes no AI call.
- `POST /api/v1/ai/ping`: one tiny call on the fast model, returning the reply, token counts, latency, and cost (when a price is known).

**Smoke test.** From `backend/`:

```bash
uv run python -m app.ai.smoke --models --web
```

It reads `backend/.env` and makes a few tiny live calls, reporting each capability separately: `models` (lists the gateway's model names, with `--models`), `text`, `embed`, `moderate`, and `web` (web search, with `--web`). Each line is `OK` or `FAIL [code] message`, so you can see what your gateway supports. It never prints the key. Without a key it prints `nothing live to test` and exits with code 1.

> **Warning:** `BOARDOM_AI_VERIFY_TLS=false` turns off certificate checking for the AI endpoint, so anyone on the network path could read or alter the traffic, including your key. Use it only for the hackathon gateway. The API refuses to start with it in production.

Errors from the AI service become short, safe messages (for example 503 *The AI service is busy. Please retry shortly.*); provider response bodies and keys are never returned or logged.

## Syllabus and notes

On a course page, open **Syllabus & materials** (teachers only).

1. **Generate syllabus** drafts units (title, summary, topics) from the course's *extracted* sources, as a background job with progress. You can also write the syllabus yourself. Edit, reorder, add and remove units, then **Approve**. An approved syllabus is locked until you **Reopen** it; removing a unit deletes its notes.
2. **Generate** notes per unit (or all missing). Each unit gets sections with explanations and worked examples, key terms, and a summary.
3. **Citations**: sources are split into chunks (a new chunk at each markdown heading) and numbered per course, `[C1]`, `[C2]`, … Numbers are never reused. Notes may cite only the passages retrieved for that unit. A note citing anything else is regenerated once with feedback, and then reported as not saved. Each version stores a snapshot (file, page, excerpt) of what it cites. `[W n]` (web) citations are rejected until web research exists.
4. **Edit, Regenerate, history**: edits and regenerations add versions; nothing is overwritten. Edits may cite only real course chunks. Any older version can be viewed and restored as a new version. A stale save returns 409.

Jobs run one at a time in the API process. If the API restarts mid-job, the job is marked failed and you run it again. In demo mode (no AI key) the same flow works offline with deterministic, correctly cited output. Demo embeddings are hash-based, though, so demo retrieval is not topical.

## Course materials, concept graph, and publishing

After the syllabus is approved, the **Course materials** tabs on **Syllabus & materials** generate, edit and version four kinds of material. They all use the same pattern as unit notes: a background job, citation checks, append-only versions, and restore.

| Material | Scope | Citations |
| --- | --- | --- |
| Unit notes | per unit | required; every section must cite |
| Lab manual (aim, apparatus, procedure, observation table, viva questions) | per unit, only when the course has **Has a lab** ticked | required (except apparatus and the blank table) |
| Lesson plan | per unit; 1–3 sessions of exactly the course's session length (a warning if the minutes do not add up) | optional, must be valid |
| Assessment rubric | whole course; weighted criteria (a warning if weights ≠ 100%) | optional, must be valid |

- **Concept graph**: built from the syllabus and the notes. Duplicate names, unknown concepts, self-links and circular links are dropped. The page shows concepts in prerequisite order. The exam-prep coach uses it.
- **Publish**: requires an approved syllabus and notes for at least one unit. Publishing snapshots the current notes and lab manual versions; later edits stay private until you **Publish changes**. **Unpublish** hides the course.
- **Export**: teachers (current or published versions) and students (published) can download notes as Markdown, or as a PDF made with fpdf2. The PDF uses the built-in fonts, which cover Latin-1 only: typographic punctuation is converted, and other characters (for example emoji) appear as `?`.

## Student portal and study tools

Students see the **published** courses of their own teacher at `/learn`. Courses the teacher enrolled them in are marked **Assigned to you**. Unpublished courses and other teachers' courses are never visible (404). Each course shows the syllabus, the published unit notes and lab manuals with their sources, a per-unit **I have studied this unit** marker, and a **Study tools** panel:

- **Exam-prep chat**: the student says what they know; the reply lists the gaps and a prioritized checklist, with citations.
  - It retrieves course passages and compares the student's known concepts (accumulated over the conversation) with the concept graph. Concepts whose prerequisites are known come first, then those most others depend on.
  - Replies may cite only the retrieved passages. If the model invents a citation twice, a reply built from the graph is returned instead.
  - Questions outside the course get "That is not covered in this course." without calling the model. A question counts as in scope if it names a course concept, shares a content word with the best passage, scores at least `BOARDOM_COACH_MIN_SCORE`, or is a general "what should I study" request.
  - History is stored per student and course, and can be cleared.
- **Quiz**: 3–10 multiple-choice questions (easy, medium or hard) for a unit or the whole course, from published notes only.
  - Questions with invalid options or citations are dropped.
  - Answers stay on the server until the quiz is submitted. Grading happens on the server, and scores are stored with a history.
- **Mind map, Short notes, Flashcards**: generated from a unit's published notes and cached per notes version, so they are shared by all students. Republishing makes new ones.
- **Video**: a narrated slideshow made by a background job, shared per unit and notes version.
  - The model writes a script, Pillow draws 1280×720 slides, TTS (`BOARDOM_MODEL_TTS`) narrates each slide, and the bundled ffmpeg from imageio-ffmpeg assembles an H.264/AAC mp4.
  - Without TTS (demo mode, `BOARDOM_VIDEO_TTS=false`, or a TTS error), the video is silent with captions, timed by reading speed.
  - Files live in `BOARDOM_UPLOAD_DIR/videos/` and are deleted with their course.

In demo mode every tool works offline: the fake provider builds deterministic, correctly cited output from the course text. The fake embeddings use bag-of-words hashing, so offline search is topical. Demo videos are silent with captions.

## Course wizard, sources, and web research

- **Course wizard**: **Set up a new course** on the dashboard, or **Edit plan** on a course page, opens four steps:
  1. basics: title, subject, difficulty, session length, description;
  2. audience and schedule: audience, weeks, hours per week;
  3. theory or theory + lab: lab hours and number of experiments;
  4. topics and assessment: must-include and excluded topics, and an assessment pattern whose weights must add up to 100%.

  The client and the server (`POST /workspaces/wizard`, `PUT /workspaces/{id}/profile`) check the same rules. The syllabus generator receives the plan and then enforces it:
  - excluded topics are removed;
  - missing required topics are added to the closest unit;
  - unit lengths are scaled to the course's number of weeks.

  The job message lists anything it adjusted. The rubric follows the assessment pattern. "Theory + lab" turns on lab manuals.
- **Sources**:
  - PDF, Markdown and text files.
  - Images (`.png`, `.jpg`, `.webp`) and scanned PDFs. The isolated parser prepares the page images, and the vision model (`BOARDOM_MODEL_VISION`, default `BOARDOM_MODEL_SMART`) reads their text, up to `BOARDOM_MAX_OCR_PAGES`. In demo mode they stay "needs OCR" until a key is set; then **Extract** again.
  - **Paste text** adds a ready-to-use source.

  All text is split into chunks. Vectors are stored in **ChromaDB** (`BOARDOM_CHROMA_DIR`), and every search is filtered by course.
- **Web research**: **Run web research** on *Syllabus & materials* plans 2–4 searches and searches only `BOARDOM_TRUSTED_DOMAINS`. Each finding:
  - is screened for prompt injection and moderated;
  - gets a stable `[W n]` label;
  - waits for the teacher to **Accept** or **Ignore** it. Flagged findings are set aside and cannot be accepted.

  Accepted findings are cited as `[W n]` on syllabus units (unknown labels are dropped and reported). When web search is unavailable, for example in demo mode, the step is skipped with a message saying so.

## Guardrails

- **Moderation** of user text: course details and plans, pasted text, syllabus and material edits, account names, coach messages, uploaded source passages, and web findings. Flagged text gets a friendly 422 ("flagged by the content filter… please rephrase"); flagged source passages are excluded from AI use.
  - If the moderation service is down, text is allowed and a warning is logged. Set `BOARDOM_MODERATION_REQUIRED=true` to reject it instead.
- **Prompt-injection screening** (offline patterns) on uploaded sources, web findings, and coach messages:
  - flagged source passages stay visible to the teacher but are never embedded or sent to a model;
  - injected chat messages get a fixed reply and are not sent to the model.
- **PII scrubbing**: every log message has emails, API keys, bearer tokens, phone and card numbers redacted. Prompts are never stored.
- **Daily limits**: every AI call is recorded in `ai_calls` with its user, course, purpose, tokens, latency and cost. Starting AI work beyond `BOARDOM_DAILY_AI_CALLS_PER_USER` or `BOARDOM_DAILY_AI_COST_USD_PER_USER` returns a friendly 429 until midnight UTC.

## Evals, efficiency, and demo data

- **Evals**: `uv run python -m app.evals` (or **Admin → Evals → Run evals**) scores a small golden course on a temporary database, comparing a plain prompt (baseline) with the full pipeline:
  - retrieval hit rate @3;
  - citation validity of generated notes;
  - quiz answer correctness;
  - guardrail catch rate, with the false-positive rate.

  Results are stored in `eval_runs` and printed as a table. In demo mode the numbers show what the checks add, not real model quality.
- **Efficiency** (**Admin → Efficiency**), from `ai_calls`:
  - calls, input, cached and output tokens, cache hit rate, average latency;
  - cost per purpose (artifact kind) and per course;
  - the average cost of a generated course;
  - the naive versus pipeline comparison.

  The naive figure is an *estimate*: a pipeline that sends each course's whole source text with every generation call. Eval runs add measured baseline and full numbers. Costs appear only for models listed in `BOARDOM_MODEL_PRICES`; demo-mode "tokens" are characters.
- **Demo seed**: `uv run python -m app.seed_demo` builds, offline and in about 15 seconds:
  - a demo teacher and three students, all enrolled;
  - a published 6-week theory + lab course with its plan and three sources;
  - the syllabus, notes, lab manuals, lesson plans, rubric, concept graph, and one captioned study video.

  Rerunning it is safe. `--reset` rebuilds the demo.

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
| `BOARDOM_MAX_PDF_PAGES` | `200` | Extraction page limit |
| `BOARDOM_MAX_EXTRACTED_CHARACTERS` | `500000` | Extraction character limit |
| `BOARDOM_EXTRACTION_TIMEOUT_SECONDS` | `60` | Parser subprocess timeout |
| `BOARDOM_ALLOW_PUBLIC_SIGNUP` | `false` | Show Register; self sign-up creates teachers |
| `BOARDOM_ADMIN_EMAIL` | `admin@example.com` | Admin created on first start if missing |
| `BOARDOM_ADMIN_PASSWORD` | `BoardomAdmin#2026` | Initial admin password (never re-applied) |
| `BOARDOM_ADMIN_RESET_PIN` | `482916` | PIN for “Forgot admin password?” |
| `BOARDOM_DEFAULT_STUDENT_LIMIT` | `4` | Students per teacher unless the admin sets one |
| `BOARDOM_MODEL_TTS` | `gpt-4o-mini-tts` | Narration model for study videos |
| `BOARDOM_TTS_VOICE` | `alloy` | Narration voice |
| `BOARDOM_VIDEO_TTS` | `true` | `false`: always silent videos with captions |
| `BOARDOM_COACH_MIN_SCORE` | `0.2` | Minimum passage match before the coach answers |
| `BOARDOM_CHROMA_DIR` | `data/chroma` | ChromaDB vector index (rebuilt if deleted) |
| `BOARDOM_MODEL_VISION` | *(empty = smart model)* | Reads text from images and scans |
| `BOARDOM_MAX_OCR_PAGES` | `20` | Scanned pages read per PDF |
| `BOARDOM_TRUSTED_DOMAINS` | Wikipedia, Britannica, Khan Academy, … | Web research domains (JSON list) |
| `BOARDOM_DAILY_AI_CALLS_PER_USER` | `500` | Daily AI calls per user |
| `BOARDOM_DAILY_AI_COST_USD_PER_USER` | `5` | Daily AI cost per user (0 = off) |
| `BOARDOM_MODERATION_REQUIRED` | `false` | Reject text when moderation is unavailable |

Backend `.env` and relative database/upload paths are resolved from `backend/`, independently of the launch directory. Defaults store the database at `backend/data/boardom.db` and source files in `backend/data/uploads/`. These paths, SQLite sidecars, caches, and virtual environments are ignored by Git. UUIDs identify resources. Timestamps are stored as UTC and serialized with an explicit UTC timezone.

Frontend `BACKEND_URL` defaults to `http://127.0.0.1:8000`; it is server-side only. The UI retrieves only the non-sensitive file-size limit through `GET /api/v1/config`. If you increase the backend limit, increase `experimental.proxyClientMaxBodySize` in `frontend/next.config.ts` above that limit plus multipart overhead (currently 12 MB for a 10 MiB file), and restart/rebuild Next.

## Authentication and request security

When public sign-up is enabled, registration creates a teacher and logs them in immediately. Emails are trimmed, lowercased, validated, and unique. Passwords are 8–128 characters and stored as Argon2id hashes. Login uses a generic invalid-credentials error.

A random opaque token is sent only in an HttpOnly cookie with `SameSite=Lax`, `Path=/`, explicit expiry, and configurable `Secure`. Only its SHA-256 hash is stored in the sessions table. Logging in rotates the current browser session; logout deletes the server-side session and clears the cookie. Expired sessions are rejected. Tokens are never stored in localStorage or returned in JSON. API responses are marked `Cache-Control: no-store`.

**CSRF defense:** every POST, PATCH, PUT, and DELETE must have an `Origin` header exactly equal to `BOARDOM_FRONTEND_ORIGIN`, including registration and login. Missing, `null`, and untrusted origins receive 403. No credentialed CORS is enabled. CLI/API clients must send that Origin explicitly as well. API docs are useful for schemas and reads; mutating requests from the backend docs origin are intentionally rejected. Example health check:

```bash
curl http://127.0.0.1:8000/health
```

All workspace/document operations require a valid teacher session and check ownership. Other teachers’ courses and students return 404; other roles get 403. Downloads are authenticated attachment responses, not public file URLs.

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

Integration tests apply the Alembic migrations to a fresh temporary database and use temporary uploads for each test. They cover authentication, expiry, rotation, duplicate emails, validation, CSRF, ownership, CRUD, downloads, file cleanup, missing files, failure rollback, role checks on every route, admin seeding, PIN reset and lockout, forced password change, student limits, enrollments, account deletion, login lockout, and migrating a database that already has users (upgrade and downgrade). No external services or development records are needed.

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
2. Log in as a teacher (follow steps 1–2 of the demo walkthrough, or enable public sign-up and register). Confirm the dashboard appears.
3. Create a lesson workspace. Set subject, learner level, duration, and description.
4. Upload a small UTF-8 `.txt` or `.md` file and a PDF. Confirm **Uploaded**, filename, size, and date.
5. Refresh. Confirm the workspace and files persist.
6. Download a source and compare it to the original.
7. Edit the workspace; clear the optional description and change duration. Refresh to confirm persistence.
8. Delete a document, confirming the dialog. Delete a workspace with another file attached.
9. Log out. A direct dashboard/workspace visit should redirect to login. Log in and confirm remaining work is saved.
10. Log in as a second teacher in a private browser window. The first teacher’s workspace and download URLs must be inaccessible.
11. Try an empty file, wrong extension, fake PDF, and file over 10 MiB; confirm clear errors.

## Verified in this workspace

- 133 backend tests passed offline (including course materials, concept graph, publishing/export, student portal, coach, quizzes, study aids, and real ffmpeg video assembly with and without narration), each on a fresh migrated database.
- A clean-database demo-mode walkthrough ran through the Next.js production server: materials, concept graph, publish, PDF export, student portal, coach (in and out of scope), quiz, study aids, and a 1280×720 H.264 video streamed through the proxy.
- Ruff formatting, Alembic schema-drift check, frontend lint, TypeScript, Prettier, and production build passed. `ruff check` reports 5 pre-existing line-length (E501) findings in `services/extraction.py` and `tests/test_extraction.py`.
- The roles migration was run up and down on a copy of a real development database (2 users, 1 session): data was kept, users became teachers.
- From a fresh database, using the Quick start commands, the demo walkthrough was run over HTTP through the Next.js proxy: admin creates a teacher → teacher must change the password → course + 4 students → 5th blocked (409) → admin raises the limit → 5th added → enrollment → student changes the password and sees the course; cross-role requests got 403 and anonymous got 401. A live PIN reset signed out the admin session, and the reset password still worked after restarting the API.
- An earlier browser smoke test covered register → workspace → upload → download → edit → logout → login. The new pages were checked to compile and serve, but they were not clicked through in a browser.
- `run_all.ps1 -Prod` was run from scratch on a clean database (alternate ports). It installed, migrated, seeded the demo and started both servers. A walkthrough through the proxy then exercised:
  - the wizard (including server-side validation) and a syllabus that follows the plan (the excluded topic removed, units fitted to 8 weeks);
  - pasted-text and image sources (the image waits for OCR in demo mode), and research being skipped in demo mode;
  - moderation and chat-injection handling;
  - the seeded course and video, evals, the efficiency report, and every new page.
- Not verified here: real-model behaviour through the AI gateway (the configured key was rejected by the gateway), `run_all.sh` end to end (only a syntax check), and click-through in a browser.

The installed Starlette version emits a deprecation warning for its `httpx` TestClient adapter; the tests pass. In this restricted execution environment, TestClient and Next’s build subprocesses required running outside the sandbox. This is an environment restriction, not a required deployment mode.

## Deployment limitations

This is a local hackathon foundation. SQLite serializes writes, and files live on one machine. Use persistent storage, back up the database and uploads together, and avoid multiple application instances sharing an unmanaged filesystem. A deployment needs HTTPS, secure cookies, the exact public frontend origin, and request-body limits on the reverse proxy. Starlette may spool multipart data before the route’s incremental file-size check, so infrastructure-level body limits are needed for untrusted public traffic.

Login and PIN rate limiting are in memory and per process. There is no self-service password reset for teachers and students (their teacher or the admin recreates the account), no email verification, storage quota, expired-session pruning job, or pagination yet. Those operational features should be added before a public launch. The AI layer is a foundation (status and ping endpoints); AI usage is logged but not yet stored or budgeted.
