Last Prompt = Implement **Layer 2 of Boardom: document extraction, source preview, and teacher corrections** in the existing repository.

Layer 1 is already complete: FastAPI backend, Next.js frontend, SQLite, authentication, lesson workspaces, and file uploads. Python dependencies are managed with **uv**.

Inspect the existing implementation first. Extend its conventions and preserve working functionality. Do not rebuild authentication, restructure the entire project, or replace existing upload behavior unnecessarily.

Implement the feature, run relevant checks, and update the README. Do not stop at a plan.

## 1. Goal and scope

An educator should be able to:

1. Upload a PDF, Markdown, or text file.
2. Start content extraction.
3. See processing status and actionable errors.
4. Preview extracted text with page or section references.
5. Compare the extracted text with the original document.
6. Correct extraction mistakes.
7. Mark the source as reviewed.
8. Refresh the app and retain all changes.

This layer prepares trustworthy source material for future AI features.

### Out of scope

Do not implement:

- AI artifact generation.
- LLM calls or API-key configuration.
- OCR or handwritten-note transcription.
- Embeddings, vector databases, or semantic search.
- PowerPoint generation.
- Elaborate frontend design.
- Arbitrary execution or rendering of uploaded HTML.

No external service should be required to use this layer.

## 2. Inspect before implementing

Review:

- Repository instructions.
- Existing backend routes, models, schemas, migrations, and services.
- Authentication and workspace ownership checks.
- File-storage conventions.
- Frontend API helpers and components.
- Existing tests and development commands.

Briefly identify the current implementation and explain your proposed changes, then proceed.

Keep dependency management consistent:

- Use `uv add`, `uv sync`, and `uv run`.
- Update the existing Python lockfile.
- Preserve the frontend’s current package manager.

Use the existing database/session patterns rather than introducing a second architecture.

## 3. Extraction behavior

Support the formats already accepted by Layer 1.

### Text-based PDFs

Use a suitable local Python PDF library such as `pypdf`.

Requirements:

- Extract text page by page.
- Preserve original PDF page numbers, starting from 1.
- Preserve useful line breaks.
- Normalize line endings and remove invalid null characters.
- Avoid aggressive transformations that can alter formulas, code indentation, lists, or paragraphs.
- Retain empty pages in the page representation.
- Identify pages with no usable extracted text.
- Capture extraction warnings when possible.

Do not promise faithful extraction of tables, mathematical notation, columns, or reading order.

If a PDF has no usable text:

- Set status to `needs_ocr`.
- Explain that scanned/image-only PDFs require OCR, which is not available yet.
- Do not mark it successfully extracted with empty content.

If some pages contain text and others do not:

- Keep the successfully extracted content.
- Show a partial-extraction warning naming the affected pages.
- Explain that those pages may be blank or image-based; do not assert they are definitely scanned.
- Do not silently discard those pages.

Handle encrypted/password-protected, malformed, and unreadable PDFs with actionable errors. Password entry is out of scope.

### Markdown

- Decode as UTF-8, including UTF-8 BOM where applicable.
- Preserve the original Markdown as editable text.
- Represent the document as one editable source unit in this layer.
- Label it “Document,” without invented page numbers.
- Do not split Markdown with a naive heading regex that could misinterpret fenced code blocks.
- Do not render raw HTML from uploaded Markdown.

### Plain text

- Decode as UTF-8, including UTF-8 BOM where applicable.
- Normalize line endings.
- Preserve paragraphs and meaningful whitespace.
- Represent the document as one editable source unit.
- Label it “Document.”

Handle empty or whitespace-only content clearly.

### Resource limits

Add configurable limits for extraction, such as:

- Maximum PDF pages: default 200.
- Maximum total extracted characters: default 500,000.
- Extraction timeout: default 60 seconds.

Validate limits and report failures clearly.

Do not silently truncate a document and mark it complete. If a limit is exceeded, fail with an explanation.

## 4. Data model and migrations

Adapt names to the existing project, but preserve these concepts.

### Extend SourceDocument

Add extraction-related fields:

- `extraction_status`
- `extraction_error_code`, nullable
- `extraction_error_message`, nullable
- `extraction_warnings`, structured JSON or an appropriate equivalent
- `extracted_at`, nullable
- `reviewed_at`, nullable
- `reviewed_by_user_id`, nullable
- `content_revision`, integer
- `extraction_attempt_id`, nullable unique attempt token
- `extraction_started_at`, nullable
- `extraction_finished_at`, nullable

Suggested statuses:

- `uploaded`
- `processing`
- `extracted`
- `needs_ocr`
- `failed`

Keep processing state separate from review state. “Extracted” does not mean “Reviewed.”

Reuse the existing upload status field if appropriate, with a migration that preserves existing records.

### Add SourceUnit

A SourceUnit is a persisted page or document-level text unit.

Fields:

- `id`: UUID
- `document_id`
- `position`: zero-based ordering index
- `page_number`: nullable, one-based for PDFs
- `label`: for example, “Page 3” or “Document”
- `original_text`: immutable extraction output
- `corrected_text`: nullable teacher override
- `revision`: integer for optimistic concurrency
- `created_at`
- `updated_at`

Define effective text explicitly:

- If `corrected_text` is null, use `original_text`.
- Otherwise, use `corrected_text`, including when it is an intentionally empty string.

Do not use truthiness to choose between original and corrected text.

Keep SourceUnit IDs stable across ordinary teacher edits. They will become citation anchors in later layers.

Add useful indexes and uniqueness constraints, including ordering uniqueness within a document.

Use an Alembic migration. Preserve existing users, workspaces, documents, and uploaded files.

Do not introduce embedding chunks or AI tables yet.

## 5. Processing lifecycle

Use a simple, reliable local processing approach without Redis or Celery.

Required behavior:

1. Teacher explicitly clicks “Extract text.”
2. Backend atomically claims the document for processing.
3. Backend returns an accepted response promptly.
4. Extraction runs outside the request’s event loop.
5. Frontend polls for completion.
6. Successful results are committed together.
7. Failures set a clear terminal status and error.

Use a bounded local worker approach and enforce the timeout. A thread timeout that leaves unlimited work running is insufficient. A subprocess-based extractor is acceptable and makes hard timeouts easier to enforce.

Keep worker concurrency small for SQLite.

### Prevent duplicate work

- A second extraction request for a processing document should not start another worker.
- Return a clear conflict or current-processing response.
- Use an atomic database claim, not only an in-memory flag.
- Only the active extraction attempt may commit its result.
- Use separate database sessions per worker/task.
- Do not pass request-scoped database sessions into background work.

### Handle interruption

If the server restarts during processing:

- The document must not remain `processing` forever.
- Recover stale/interrupted attempts and allow retry.
- Document the single-backend-process limitation of the local implementation.

### Retrying and re-extraction

For this layer:

- Allow extraction from `uploaded`, `failed`, and `needs_ocr`.
- Do not allow re-extraction of successfully extracted documents.
- Explain that replacing the source requires deleting it and uploading it again.

This protects teacher corrections and keeps citation IDs stable without introducing document-version history yet.

### Deletion during processing

Handle deletion safely:

- A deleted document must not be recreated by a late worker.
- A worker must verify that its document and attempt still exist before committing.
- Clean up temporary files.
- Preserve Layer 1’s file and metadata cleanup behavior.

## 6. API

Follow the repository’s existing route prefix and response conventions.

Suggested routes:

### Start extraction

`POST /api/v1/workspaces/{workspace_id}/documents/{document_id}/extract`

- Requires ownership.
- Returns HTTP 202 with current status and attempt identifier.
- Rejects invalid transitions.
- Does not start duplicate jobs.

### Retrieve extraction state

`GET /api/v1/workspaces/{workspace_id}/documents/{document_id}/content`

Return:

- Document metadata.
- Extraction status.
- Warnings and actionable error details.
- Review state.
- Current content revision.
- Ordered SourceUnits, including original text, corrected text, effective text, and revisions.

If content is too large for a comfortable single response, paginate SourceUnits using the project’s existing conventions. Keep the frontend and API consistent.

Also include extraction status in the existing document-list response.

### Correct a SourceUnit

`PATCH /api/v1/workspaces/{workspace_id}/documents/{document_id}/units/{unit_id}`

Request:

- `corrected_text`
- `expected_revision`

Behavior:

- Validate ownership and the complete workspace/document/unit relationship.
- Accept empty text intentionally.
- Use an atomic revision check.
- Return HTTP 409 when the revision is stale.
- Increment unit revision and document content revision.
- Clear document review status after a real content change.
- Preserve original extraction text.

A null `corrected_text` should reset the unit to its original extracted text. Document that behavior.

Do not overwrite another editor’s changes silently.

### Mark reviewed or reopen review

`PATCH /api/v1/workspaces/{workspace_id}/documents/{document_id}/review`

Request:

- `reviewed`: boolean
- `expected_content_revision`

Behavior:

- Only successfully extracted documents with usable effective content can be marked reviewed.
- Atomically check the content revision.
- Record the reviewing user and time.
- Allow review to be reopened.
- Any subsequent content edit invalidates review.

A review mark means the teacher has reviewed the available text; it must not hide partial-extraction warnings.

### Download corrected source text

`GET /api/v1/workspaces/{workspace_id}/documents/{document_id}/content/download`

- Return effective text as a UTF-8 `.txt` attachment.
- Include clear page separators for PDFs.
- Use a safe download filename.
- Keep original-file download available separately.
- This is corrected source export, not an AI artifact package.

Use 404 for missing or unowned resources consistently with Layer 1.

## 7. Minimal frontend

Extend the existing workspace document list.

Each document should show:

- Filename.
- Extraction status.
- Review status.
- “Extract text” action when eligible.
- “Review text” action after successful extraction.
- Retry action after a recoverable failure.
- Clear OCR-needed messaging where relevant.

### Source review screen

Use a simple route or panel consistent with the application.

Include:

- Document title.
- Original-file download/open action.
- Extraction warnings.
- Page/unit navigation.
- A textarea for effective text.
- Save button.
- Reset-to-original action.
- Original extracted text available in a read-only view.
- Reviewed/unreviewed indicator.
- “Mark reviewed” and “Reopen review” actions.
- Download corrected text.

For PDFs, prefer a browser-native PDF viewer beside the editor if authenticated preview fits the existing architecture. If implemented, serve it through an ownership-checked endpoint. Do not expose storage paths or public file URLs.

If inline viewing is unreliable, a clear authenticated “Open original” or download action is sufficient.

### Interaction requirements

- Poll only while processing.
- Stop polling on terminal states and component unmount.
- Use a modest interval such as 1–2 seconds.
- Handle session expiration and network failures.
- Disable duplicate extraction/save requests.
- Show save success and failure.
- Preserve unsaved edits after a failed save.
- Warn before navigating away from unsaved changes.
- On a revision conflict, explain that newer content exists and offer reload without silently discarding the local draft.
- Make review actions require all local edits to be saved first.
- Use accessible labels and basic responsive styling.

Avoid rich-text editing, complex animation, or a large new UI library.

## 8. Security and content handling

Continue existing authentication, ownership checks, CSRF protection, and safe file-storage practices.

Additionally:

- Treat all document content as untrusted data.
- Render editable text as text, not HTML.
- Do not execute macros, embedded scripts, or document instructions.
- Never log full document contents.
- Never return internal filesystem paths or raw stack traces.
- Prevent users from editing units through a different document/workspace URL.
- Keep parser failures isolated from the web request lifecycle.

Use only local extraction in this layer.

## 9. Tests

Add focused automated tests with small generated fixtures and isolated database/storage locations.

Cover:

### Extraction

- UTF-8 TXT extraction.
- UTF-8 BOM handling.
- Markdown preservation, including fenced code.
- PDF extraction with correct page order and numbers.
- Blank PDF produces `needs_ocr`.
- Mixed text/blank PDF preserves pages and produces warnings.
- Encrypted or malformed PDF produces an actionable failure.
- Character/page limits reject excessive content without silent truncation.
- Timeout produces a terminal failure and releases worker capacity.

### Persistence and editing

- Original extraction text remains unchanged after correction.
- Corrected text persists.
- Empty corrected text is preserved.
- Null correction restores original text.
- Stale unit revision returns 409.
- Content edits invalidate review.
- Stale document revision prevents marking outdated content reviewed.
- Corrected-text download uses effective text in document order.

### Lifecycle and authorization

- Duplicate extraction requests do not create duplicate jobs or SourceUnits.
- Interrupted processing can be recovered and retried.
- A stale worker attempt cannot overwrite newer state.
- Deletion during extraction cannot recreate the document.
- Users cannot view, extract, edit, review, or export another user’s documents.
- Unit/document/workspace mismatches are rejected.

Mock scheduling or parser delays where appropriate; do not make the suite depend on lengthy sleeps.

Run the existing Layer 1 regression tests as well as the new tests.

Run backend lint/format checks and frontend type/build checks according to existing project scripts.

Test migrations against both a fresh database and a database with Layer 1 records, using temporary copies/fixtures rather than altering user data.

## 10. README and completion report

Update the README with:

- Layer 2 functionality.
- Any new uv dependency/setup commands.
- Migration instructions.
- Extraction configuration and limits.
- How to extract, correct, review, and export text.
- Scanned-PDF and OCR limitations.
- Known limitations with tables, formulas, columns, and PDF reading order.
- Local worker/restart behavior.
- A short manual smoke-test checklist.

The manual workflow should include:

1. Log in.
2. Upload a text-based PDF.
3. Extract it.
4. Check page-linked content.
5. Correct a sentence and save.
6. Refresh and confirm persistence.
7. Mark reviewed.
8. Edit again and confirm review is invalidated.
9. Download corrected text.
10. Upload a blank/scanned PDF and confirm helpful OCR messaging.

At completion, report:

- What changed.
- How to run migrations and start the app.
- Which checks passed.
- Any limitations or checks that could not be run.

Stop after Layer 2. Do not implement AI generation.


Status = Extraction and review are now wired into the app. The parser preserves PDF pages, including blank ones, and stores corrections separately from the original text. I’m checking migrations and failure cases next, including timeouts, conflicting edits, and deletion while extraction is running.