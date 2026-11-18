import io
import re
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.workspaces import owned_workspace
from app.core.security import CurrentTeacher, Db
from app.models.entities import SourceDocument, SourceUnit, utcnow
from app.schemas.api import DocumentOut, PastedTextIn
from app.services.guardrails import check_text

router = APIRouter(prefix="/workspaces/{workspace_id}/documents", tags=["Source documents"])


def owned_document(db, workspace_id, document_id, user_id):
    workspace = owned_workspace(db, workspace_id, user_id)
    document = db.scalar(
        select(SourceDocument).where(
            SourceDocument.id == document_id, SourceDocument.workspace_id == workspace.id
        )
    )
    if document is None:
        raise HTTPException(404, "Document not found.")
    return workspace, document


@router.post("", response_model=DocumentOut, status_code=201)
def upload_document(
    workspace_id: UUID, file: UploadFile, request: Request, db: Db, user: CurrentTeacher
):
    workspace = owned_workspace(db, workspace_id, user.id)
    storage = request.app.state.storage
    key, name, media_type, size = storage.save(file)
    document = SourceDocument(
        workspace_id=workspace.id,
        original_filename=name,
        storage_key=key,
        media_type=media_type,
        size_bytes=size,
    )
    try:
        db.add(document)
        workspace.updated_at = utcnow()
        db.commit()
    except Exception:
        db.rollback()
        storage.remove(key)
        raise
    return document


@router.post("/text", response_model=DocumentOut, status_code=201)
def paste_text(
    workspace_id: UUID, data: PastedTextIn, request: Request, db: Db, user: CurrentTeacher
):
    """Pasted text becomes a .txt source that is extracted immediately."""
    check_text(request.app.state.ai, request.app.state.settings, data.title, data.text)
    workspace = owned_workspace(db, workspace_id, user.id)
    text = data.text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    if len(text) > request.app.state.settings.max_extracted_characters:
        raise HTTPException(422, "The text is longer than the configured character limit.")
    name = re.sub(r"[^\w\- ]+", "", data.title).strip()[:100] or "Pasted text"
    storage = request.app.state.storage
    key, filename, media_type, size = storage.save(
        UploadFile(file=io.BytesIO(text.encode("utf-8")), filename=f"{name}.txt")
    )
    now = utcnow()
    document = SourceDocument(
        workspace_id=workspace.id,
        original_filename=filename,
        storage_key=key,
        media_type=media_type,
        size_bytes=size,
        extraction_status="extracted",
        content_revision=1,
        extracted_at=now,
        extraction_started_at=now,
        extraction_finished_at=now,
    )
    try:
        db.add(document)
        db.flush()
        db.add(
            SourceUnit(
                document_id=document.id,
                position=0,
                page_number=None,
                label="Pasted text",
                original_text=text,
            )
        )
        workspace.updated_at = now
        db.commit()
    except Exception:
        db.rollback()
        storage.remove(key)
        raise
    return document


@router.get("", response_model=list[DocumentOut])
def list_documents(workspace_id: UUID, db: Db, user: CurrentTeacher):
    owned_workspace(db, workspace_id, user.id)
    return db.scalars(
        select(SourceDocument)
        .where(SourceDocument.workspace_id == workspace_id)
        .order_by(SourceDocument.created_at.desc())
    ).all()


@router.get("/{document_id}/download")
def download_document(
    workspace_id: UUID, document_id: UUID, request: Request, db: Db, user: CurrentTeacher
):
    _, document = owned_document(db, workspace_id, document_id, user.id)
    file = request.app.state.storage.open_download(document.storage_key)

    def chunks():
        with file:
            while chunk := file.read(64 * 1024):
                yield chunk

    # Never reflect raw control characters or directory components into a header.
    filename = document.original_filename.replace("\\", "/").rsplit("/", 1)[-1] or "document"
    return StreamingResponse(
        chunks(),
        media_type=document.media_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename, safe='')}",
            "Content-Length": str(document.size_bytes),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/{document_id}", status_code=204)
def delete_document(
    workspace_id: UUID, document_id: UUID, request: Request, db: Db, user: CurrentTeacher
):
    workspace, document = owned_document(db, workspace_id, document_id, user.id)

    def delete_metadata():
        db.delete(document)
        workspace.updated_at = utcnow()

    request.app.state.storage.delete_records(db, [document], delete_metadata)
    return Response(status_code=204)
