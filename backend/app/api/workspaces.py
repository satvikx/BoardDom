from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import select

from app.core.security import CurrentTeacher, Db
from app.models.entities import CourseProfile, SourceDocument, Workspace, utcnow
from app.schemas.api import WorkspaceCreate, WorkspaceOut, WorkspacePatch
from app.schemas.course import CourseProfileIn, CourseProfileOut, WizardIn
from app.services.guardrails import check_text
from app.services.video import remove_video_files, video_keys

router = APIRouter(prefix="/workspaces", tags=["Workspaces"])


def owned_workspace(db, workspace_id: UUID, user_id: UUID) -> Workspace:
    workspace = db.scalar(
        select(Workspace).where(Workspace.id == workspace_id, Workspace.owner_id == user_id)
    )
    if workspace is None:
        raise HTTPException(404, "Workspace not found.")
    return workspace


@router.post("", response_model=WorkspaceOut, status_code=201)
def create_workspace(data: WorkspaceCreate, db: Db, user: CurrentTeacher, request: Request):
    check_text(
        request.app.state.ai, request.app.state.settings, data.title, data.subject, data.description
    )
    workspace = Workspace(owner_id=user.id, **data.model_dump())
    db.add(workspace)
    db.commit()
    return workspace


def plan_text(profile: CourseProfileIn) -> str:
    """The free-text parts of a course plan, for moderation."""
    parts = [profile.audience, *profile.must_include, *profile.exclude]
    return " | ".join(parts + [a.name for a in profile.assessment])


def save_profile(db, workspace: Workspace, data: CourseProfileIn) -> CourseProfile:
    profile = db.get(CourseProfile, workspace.id) or CourseProfile(workspace_id=workspace.id)
    values = data.model_dump()
    values["assessment"] = [dict(a) for a in values["assessment"]]
    for key, value in values.items():
        setattr(profile, key, value)
    db.add(profile)
    workspace.has_lab = data.mode == "theory_lab"
    workspace.updated_at = utcnow()
    return profile


@router.post("/wizard", response_model=WorkspaceOut, status_code=201)
def create_with_wizard(data: WizardIn, request: Request, db: Db, user: CurrentTeacher):
    """Create a course and its plan in one step (the multi-step setup form)."""
    check_text(
        request.app.state.ai,
        request.app.state.settings,
        data.title,
        data.subject,
        data.description,
        plan_text(data.profile),
    )
    workspace = Workspace(
        owner_id=user.id,
        title=data.title,
        subject=data.subject,
        description=data.description,
        learner_level=data.learner_level,
        lesson_duration_minutes=data.lesson_duration_minutes,
    )
    db.add(workspace)
    db.flush()
    save_profile(db, workspace, data.profile)
    db.commit()
    return workspace


@router.get("/{workspace_id}/profile", response_model=CourseProfileOut | None)
def read_profile(workspace_id: UUID, db: Db, user: CurrentTeacher):
    workspace = owned_workspace(db, workspace_id, user.id)
    return db.get(CourseProfile, workspace.id)


@router.put("/{workspace_id}/profile", response_model=CourseProfileOut)
def update_profile(
    workspace_id: UUID, data: CourseProfileIn, db: Db, user: CurrentTeacher, request: Request
):
    check_text(request.app.state.ai, request.app.state.settings, plan_text(data))
    workspace = owned_workspace(db, workspace_id, user.id)
    profile = save_profile(db, workspace, data)
    db.commit()
    return profile


@router.get("", response_model=list[WorkspaceOut])
def list_workspaces(db: Db, user: CurrentTeacher):
    return db.scalars(
        select(Workspace)
        .where(Workspace.owner_id == user.id)
        .order_by(Workspace.updated_at.desc(), Workspace.id.desc())
    ).all()


@router.get("/{workspace_id}", response_model=WorkspaceOut)
def get_workspace(workspace_id: UUID, db: Db, user: CurrentTeacher):
    return owned_workspace(db, workspace_id, user.id)


@router.patch("/{workspace_id}", response_model=WorkspaceOut)
def update_workspace(
    workspace_id: UUID, data: WorkspacePatch, db: Db, user: CurrentTeacher, request: Request
):
    check_text(
        request.app.state.ai, request.app.state.settings, data.title, data.subject, data.description
    )
    workspace = owned_workspace(db, workspace_id, user.id)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(workspace, key, value)
    workspace.updated_at = utcnow()
    db.commit()
    return workspace


@router.delete("/{workspace_id}", status_code=204)
def delete_workspace(workspace_id: UUID, request: Request, db: Db, user: CurrentTeacher):
    workspace = owned_workspace(db, workspace_id, user.id)
    documents = db.scalars(
        select(SourceDocument).where(SourceDocument.workspace_id == workspace.id)
    ).all()
    videos = video_keys(db, [workspace.id])
    request.app.state.storage.delete_records(db, documents, lambda: db.delete(workspace))
    remove_video_files(request.app.state.settings, videos)
    request.app.state.vector_index.delete_workspaces([workspace_id])
    return Response(status_code=204)
