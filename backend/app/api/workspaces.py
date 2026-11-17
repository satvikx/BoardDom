from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import select

from app.core.security import CurrentUser, Db
from app.models.entities import SourceDocument, Workspace, utcnow
from app.schemas.api import WorkspaceCreate, WorkspaceOut, WorkspacePatch

router = APIRouter(prefix="/workspaces", tags=["Workspaces"])


def owned_workspace(db, workspace_id: UUID, user_id: UUID) -> Workspace:
    workspace = db.scalar(
        select(Workspace).where(Workspace.id == workspace_id, Workspace.owner_id == user_id)
    )
    if workspace is None:
        raise HTTPException(404, "Workspace not found.")
    return workspace


@router.post("", response_model=WorkspaceOut, status_code=201)
def create_workspace(data: WorkspaceCreate, db: Db, user: CurrentUser):
    workspace = Workspace(owner_id=user.id, **data.model_dump())
    db.add(workspace)
    db.commit()
    return workspace


@router.get("", response_model=list[WorkspaceOut])
def list_workspaces(db: Db, user: CurrentUser):
    return db.scalars(
        select(Workspace)
        .where(Workspace.owner_id == user.id)
        .order_by(Workspace.updated_at.desc(), Workspace.id.desc())
    ).all()


@router.get("/{workspace_id}", response_model=WorkspaceOut)
def get_workspace(workspace_id: UUID, db: Db, user: CurrentUser):
    return owned_workspace(db, workspace_id, user.id)


@router.patch("/{workspace_id}", response_model=WorkspaceOut)
def update_workspace(workspace_id: UUID, data: WorkspacePatch, db: Db, user: CurrentUser):
    workspace = owned_workspace(db, workspace_id, user.id)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(workspace, key, value)
    workspace.updated_at = utcnow()
    db.commit()
    return workspace


@router.delete("/{workspace_id}", status_code=204)
def delete_workspace(workspace_id: UUID, request: Request, db: Db, user: CurrentUser):
    workspace = owned_workspace(db, workspace_id, user.id)
    documents = db.scalars(
        select(SourceDocument).where(SourceDocument.workspace_id == workspace.id)
    ).all()
    request.app.state.storage.delete_records(db, documents, lambda: db.delete(workspace))
    return Response(status_code=204)
