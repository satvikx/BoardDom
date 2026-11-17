from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import select, update

from app.api.documents import owned_document
from app.core.security import CurrentUser, Db
from app.models.entities import SourceDocument, SourceUnit, utcnow
from app.schemas.api import ContentOut, DocumentOut, ReviewPatch, UnitOut, UnitPatch

router = APIRouter(
    prefix="/workspaces/{workspace_id}/documents/{document_id}", tags=["Source content"]
)


def units(db, document_id):
    return db.scalars(
        select(SourceUnit)
        .where(SourceUnit.document_id == document_id)
        .order_by(SourceUnit.position)
    ).all()


@router.post("/extract", response_model=DocumentOut, status_code=202)
def start(workspace_id: UUID, document_id: UUID, request: Request, db: Db, user: CurrentUser):
    _, doc = owned_document(db, workspace_id, document_id, user.id)
    if doc.extraction_status not in {"uploaded", "failed", "needs_ocr"}:
        raise HTTPException(
            409,
            "Already processing or extracted. Replace by deleting and uploading again.",
        )
    worker = request.app.state.worker
    if not worker.capacity.acquire(blocking=False):
        raise HTTPException(409, "Another document is processing. Try again when it finishes.")
    attempt = uuid4().hex
    try:
        result = db.execute(
            update(SourceDocument)
            .where(
                SourceDocument.id == document_id,
                SourceDocument.extraction_status.in_(["uploaded", "failed", "needs_ocr"]),
            )
            .values(
                extraction_status="processing",
                extraction_attempt_id=attempt,
                extraction_started_at=utcnow(),
                extraction_finished_at=None,
                extraction_error_code=None,
                extraction_error_message=None,
            )
        )
        if not result.rowcount:
            raise HTTPException(409, "Extraction state changed. Reload and try again.")
        db.commit()
        db.refresh(doc)
        response = DocumentOut.model_validate(doc)
        worker.pool.submit(worker.run, doc.id, attempt, doc.storage_key, doc.media_type)
    except Exception:
        worker.capacity.release()
        db.rollback()
        raise
    return response


@router.get("/content", response_model=ContentOut)
def content(workspace_id: UUID, document_id: UUID, db: Db, user: CurrentUser):
    _, doc = owned_document(db, workspace_id, document_id, user.id)
    return dict(document=doc, units=units(db, document_id))


def lock_content(db, doc, revision):
    result = db.execute(
        update(SourceDocument)
        .where(
            SourceDocument.id == doc.id,
            SourceDocument.content_revision == revision,
            SourceDocument.extraction_status == "extracted",
        )
        .values(content_revision=SourceDocument.content_revision)
    )
    if not result.rowcount:
        raise HTTPException(
            409, "Newer content exists or extraction is incomplete. Reload before continuing."
        )


@router.patch("/units/{unit_id}", response_model=UnitOut)
def correct(
    workspace_id: UUID,
    document_id: UUID,
    unit_id: UUID,
    data: UnitPatch,
    request: Request,
    db: Db,
    user: CurrentUser,
):
    _, doc = owned_document(db, workspace_id, document_id, user.id)
    unit = db.scalar(
        select(SourceUnit).where(SourceUnit.id == unit_id, SourceUnit.document_id == doc.id)
    )
    if unit is None:
        raise HTTPException(404, "Source unit not found.")
    lock_content(db, doc, doc.content_revision)
    db.refresh(unit)
    if unit.revision != data.expected_revision:
        raise HTTPException(
            409, "Newer content exists. Your draft was not saved. Reload to compare."
        )
    replacement = unit.original_text if data.corrected_text is None else data.corrected_text
    total = (
        sum(len(u.effective_text) for u in units(db, doc.id))
        - len(unit.effective_text)
        + len(replacement)
    )
    if total > request.app.state.settings.max_extracted_characters:
        raise HTTPException(422, "Corrected content exceeds the configured character limit.")
    if unit.corrected_text != data.corrected_text:
        changed = unit.effective_text != replacement
        unit.corrected_text = data.corrected_text
        unit.revision += 1
        doc.content_revision += 1
        if changed:
            doc.reviewed_at = None
            doc.reviewed_by_user_id = None
    db.commit()
    return unit


@router.patch("/review", response_model=DocumentOut)
def review(workspace_id: UUID, document_id: UUID, data: ReviewPatch, db: Db, user: CurrentUser):
    _, doc = owned_document(db, workspace_id, document_id, user.id)
    lock_content(db, doc, data.expected_content_revision)
    if data.reviewed and not any(u.effective_text.strip() for u in units(db, doc.id)):
        raise HTTPException(422, "There is no usable text to review.")
    doc.reviewed_at = utcnow() if data.reviewed else None
    doc.reviewed_by_user_id = user.id if data.reviewed else None
    db.commit()
    return doc


@router.get("/content/download")
def export(workspace_id: UUID, document_id: UUID, db: Db, user: CurrentUser):
    _, doc = owned_document(db, workspace_id, document_id, user.id)
    if doc.extraction_status != "extracted":
        raise HTTPException(409, "Extract text successfully before exporting.")
    source = units(db, doc.id)
    text = "\n\n".join(
        f"--- {u.label} ---\n{u.effective_text}" if u.page_number else u.effective_text
        for u in source
    )
    name = doc.original_filename.replace("\\", "/").rsplit("/", 1)[-1] + ".corrected.txt"
    return Response(
        text.encode("utf-8"),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name, safe='')}"},
    )
