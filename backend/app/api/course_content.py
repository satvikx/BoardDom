import re
from typing import Literal
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response
from sqlalchemy import func, select

from app.api.workspaces import owned_workspace
from app.core.security import CurrentTeacher, Db
from app.models.entities import (
    Artifact,
    ArtifactVersion,
    Job,
    ResearchFinding,
    Syllabus,
    SyllabusUnit,
    User,
    utcnow,
)
from app.schemas.course import (
    ConceptGraphOut,
    FindingOut,
    FindingPatch,
    GenerateIn,
    GenerateNotesIn,
    JobOut,
    NotesEdit,
    NotesOut,
    NotesSummaryOut,
    PublicationOut,
    PublicationUnit,
    RestoreIn,
    RevisionIn,
    SyllabusIn,
    SyllabusOut,
    UnitOut,
    VersionInfo,
)
from app.services.concepts import build_concepts, graph_out
from app.services.course_content import (
    KINDS,
    LAB,
    NOTES,
    Kind,
    add_version,
    allowed_for_edit,
    check_citations,
    find_artifact,
    generate_artifacts,
    generate_syllabus,
)
from app.services.guardrails import check_text
from app.services.publishing import (
    PublishError,
    course_units,
    export_markdown,
    export_pdf,
    publish,
    unit_artifacts,
)
from app.services.research import research
from app.services.usage import AIQuota

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["Syllabus and notes"])


def get_syllabus(db, workspace_id) -> Syllabus | None:
    return db.scalar(select(Syllabus).where(Syllabus.workspace_id == workspace_id))


def syllabus_out(db, syllabus: Syllabus) -> SyllabusOut:
    units = db.scalars(
        select(SyllabusUnit)
        .where(SyllabusUnit.syllabus_id == syllabus.id)
        .order_by(SyllabusUnit.position)
    ).all()
    return SyllabusOut(
        id=syllabus.id,
        status=syllabus.status,
        revision=syllabus.revision,
        approved_at=syllabus.approved_at,
        updated_at=syllabus.updated_at,
        units=[UnitOut.model_validate(u) for u in units],
    )


def check_revision(syllabus: Syllabus, expected: int) -> None:
    if syllabus.revision != expected:
        raise HTTPException(409, "The syllabus changed since you loaded it. Reload and retry.")


# ---- jobs -----------------------------------------------------------------------------------


@router.get("/jobs", response_model=list[JobOut])
def list_jobs(
    workspace_id: UUID, db: Db, teacher: CurrentTeacher, limit: int = Query(5, ge=1, le=50)
):
    owned_workspace(db, workspace_id, teacher.id)
    return db.scalars(
        select(Job)
        .where(Job.workspace_id == workspace_id)
        .order_by(Job.created_at.desc())
        .limit(limit)
    ).all()


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(workspace_id: UUID, job_id: UUID, db: Db, teacher: CurrentTeacher):
    owned_workspace(db, workspace_id, teacher.id)
    job = db.scalar(select(Job).where(Job.id == job_id, Job.workspace_id == workspace_id))
    if job is None:
        raise HTTPException(404, "Job not found.")
    return job


# ---- syllabus -------------------------------------------------------------------------------


@router.get("/syllabus", response_model=SyllabusOut | None)
def read_syllabus(workspace_id: UUID, db: Db, teacher: CurrentTeacher):
    owned_workspace(db, workspace_id, teacher.id)
    syllabus = get_syllabus(db, workspace_id)
    return syllabus_out(db, syllabus) if syllabus else None


@router.post("/syllabus/generate", response_model=JobOut, status_code=202)
def start_syllabus(
    workspace_id: UUID, request: Request, db: Db, teacher: CurrentTeacher, quota: AIQuota
):
    workspace = owned_workspace(db, workspace_id, teacher.id)
    syllabus = get_syllabus(db, workspace.id)
    if syllabus and syllabus.status == "approved":
        raise HTTPException(409, "The syllabus is approved. Reopen it before regenerating.")
    provider = request.app.state.ai
    return request.app.state.jobs.start(
        db, workspace.id, "syllabus", teacher.id, generate_syllabus(provider)
    )


@router.put("/syllabus", response_model=SyllabusOut)
def save_syllabus(
    workspace_id: UUID, data: SyllabusIn, db: Db, teacher: CurrentTeacher, request: Request
):
    check_text(
        request.app.state.ai,
        request.app.state.settings,
        *(f"{u.title} {u.summary} {chr(32).join(u.topics)}" for u in data.units),
    )
    workspace = owned_workspace(db, workspace_id, teacher.id)
    syllabus = get_syllabus(db, workspace.id)
    if syllabus is None:
        if data.expected_revision != 0:
            raise HTTPException(409, "The syllabus changed since you loaded it. Reload and retry.")
        syllabus = Syllabus(workspace_id=workspace.id)
        db.add(syllabus)
        db.flush()
    else:
        check_revision(syllabus, data.expected_revision)
    if syllabus.status == "approved":
        raise HTTPException(409, "The syllabus is approved. Reopen it to edit.")
    existing = {
        u.id: u
        for u in db.scalars(select(SyllabusUnit).where(SyllabusUnit.syllabus_id == syllabus.id))
    }
    keep = set()
    for position, item in enumerate(data.units):
        if item.id is not None:
            unit = existing.get(item.id)
            if unit is None:
                raise HTTPException(422, "A unit in this syllabus no longer exists. Reload.")
            if item.id in keep:
                raise HTTPException(422, "A unit appears twice.")
            keep.add(item.id)
        else:
            unit = SyllabusUnit(syllabus_id=syllabus.id)
            db.add(unit)
        unit.position, unit.title, unit.summary = position, item.title, item.summary
        unit.topics = list(item.topics)
        unit.weeks = item.weeks
    for unit_id, unit in existing.items():
        if unit_id not in keep:
            db.delete(unit)  # Its notes go with it (ON DELETE CASCADE).
    syllabus.revision += 1
    syllabus.updated_at = utcnow()
    db.commit()
    return syllabus_out(db, syllabus)


@router.post("/syllabus/approve", response_model=SyllabusOut)
def approve_syllabus(workspace_id: UUID, data: RevisionIn, db: Db, teacher: CurrentTeacher):
    owned_workspace(db, workspace_id, teacher.id)
    syllabus = get_syllabus(db, workspace_id)
    if syllabus is None:
        raise HTTPException(404, "There is no syllabus yet.")
    check_revision(syllabus, data.expected_revision)
    count = db.scalar(
        select(func.count())
        .select_from(SyllabusUnit)
        .where(SyllabusUnit.syllabus_id == syllabus.id)
    )
    if not count:
        raise HTTPException(422, "Add at least one unit before approving.")
    syllabus.status, syllabus.approved_at = "approved", utcnow()
    syllabus.revision += 1
    db.commit()
    return syllabus_out(db, syllabus)


@router.post("/syllabus/reopen", response_model=SyllabusOut)
def reopen_syllabus(workspace_id: UUID, data: RevisionIn, db: Db, teacher: CurrentTeacher):
    owned_workspace(db, workspace_id, teacher.id)
    syllabus = get_syllabus(db, workspace_id)
    if syllabus is None:
        raise HTTPException(404, "There is no syllabus yet.")
    check_revision(syllabus, data.expected_revision)
    syllabus.status, syllabus.approved_at = "draft", None
    syllabus.revision += 1
    db.commit()
    return syllabus_out(db, syllabus)


# ---- artifacts (notes, lab manuals, lesson plans, rubric) -----------------------------------


def kind_or_404(kind: str) -> Kind:
    found = KINDS.get(kind)
    if found is None:
        raise HTTPException(404, "Unknown material type.")
    return found


def list_artifacts(db, workspace, kind: Kind) -> list[NotesSummaryOut]:
    syllabus = get_syllabus(db, workspace.id)
    if syllabus is None:
        return []
    if kind.per_unit:
        rows = db.execute(
            select(SyllabusUnit, Artifact)
            .outerjoin(
                Artifact, (Artifact.unit_id == SyllabusUnit.id) & (Artifact.kind == kind.name)
            )
            .where(SyllabusUnit.syllabus_id == syllabus.id)
            .order_by(SyllabusUnit.position)
        ).all()
    else:
        rows = [(None, find_artifact(db, workspace.id, kind.name, None))]
    out = []
    for unit, artifact in rows:
        has = artifact is not None and artifact.current_version > 0
        out.append(
            NotesSummaryOut(
                kind=kind.name,
                unit_id=unit.id if unit else None,
                unit_title=unit.title if unit else kind.label,
                position=unit.position if unit else 0,
                artifact_id=artifact.id if artifact else None,
                current_version=artifact.current_version if artifact else 0,
                published_version=artifact.published_version if artifact else None,
                updated_at=artifact.updated_at if artifact else None,
                warning_count=len(current_version(db, artifact).warnings) if has else 0,
            )
        )
    return out


def start_artifacts(db, request, workspace, kind: Kind, unit_ids, teacher):
    syllabus = get_syllabus(db, workspace.id)
    if syllabus is None or syllabus.status != "approved":
        raise HTTPException(409, f"Approve the syllabus before generating {kind.label.lower()}s.")
    if kind.needs_lab and not workspace.has_lab:
        raise HTTPException(409, "This course has no lab. Turn on “Has a lab” in the details.")
    if not kind.per_unit and unit_ids:
        raise HTTPException(422, f"The {kind.label.lower()} covers the whole course.")
    return request.app.state.jobs.start(
        db,
        workspace.id,
        kind.job,
        teacher.id,
        generate_artifacts(request.app.state.ai, kind.name, unit_ids or None, teacher.id),
    )


@router.get("/artifacts", response_model=list[NotesSummaryOut])
def list_kind(workspace_id: UUID, kind: str, db: Db, teacher: CurrentTeacher):
    workspace = owned_workspace(db, workspace_id, teacher.id)
    return list_artifacts(db, workspace, kind_or_404(kind))


@router.post("/artifacts/generate", response_model=JobOut, status_code=202)
def generate_kind(
    workspace_id: UUID,
    data: GenerateIn,
    request: Request,
    db: Db,
    teacher: CurrentTeacher,
    quota: AIQuota,
):
    workspace = owned_workspace(db, workspace_id, teacher.id)
    return start_artifacts(db, request, workspace, kind_or_404(data.kind), data.unit_ids, teacher)


@router.get("/notes", response_model=list[NotesSummaryOut])
def list_notes(workspace_id: UUID, db: Db, teacher: CurrentTeacher):
    workspace = owned_workspace(db, workspace_id, teacher.id)
    return list_artifacts(db, workspace, KINDS[NOTES])


@router.post("/notes/generate", response_model=JobOut, status_code=202)
def start_notes(
    workspace_id: UUID,
    data: GenerateNotesIn,
    request: Request,
    db: Db,
    teacher: CurrentTeacher,
    quota: AIQuota,
):
    workspace = owned_workspace(db, workspace_id, teacher.id)
    return start_artifacts(db, request, workspace, KINDS[NOTES], data.unit_ids, teacher)


def owned_artifact(db, workspace_id: UUID, artifact_id: UUID, teacher_id, kind=None) -> Artifact:
    owned_workspace(db, workspace_id, teacher_id)
    query = select(Artifact).where(
        Artifact.id == artifact_id, Artifact.workspace_id == workspace_id
    )
    if kind:
        query = query.where(Artifact.kind == kind)
    artifact = db.scalar(query)
    if artifact is None or not artifact.current_version:
        raise HTTPException(404, "Not found.")
    return artifact


def version(db, artifact: Artifact, number: int) -> ArtifactVersion:
    found = db.scalar(
        select(ArtifactVersion).where(
            ArtifactVersion.artifact_id == artifact.id, ArtifactVersion.number == number
        )
    )
    if found is None:
        raise HTTPException(404, "Version not found.")
    return found


def current_version(db, artifact: Artifact) -> ArtifactVersion:
    return version(db, artifact, artifact.current_version)


def artifact_out(db, artifact: Artifact, shown: ArtifactVersion) -> NotesOut:
    unit = db.get(SyllabusUnit, artifact.unit_id) if artifact.unit_id else None
    history = db.execute(
        select(ArtifactVersion, User.display_name)
        .outerjoin(User, User.id == ArtifactVersion.created_by_user_id)
        .where(ArtifactVersion.artifact_id == artifact.id)
        .order_by(ArtifactVersion.number.desc())
    ).all()
    return NotesOut(
        artifact_id=artifact.id,
        kind=artifact.kind,
        unit_id=artifact.unit_id,
        unit_title=unit.title if unit else KINDS[artifact.kind].label,
        number=shown.number,
        current_version=artifact.current_version,
        published_version=artifact.published_version,
        origin=shown.origin,
        markdown=shown.markdown,
        citations=shown.citations,
        warnings=shown.warnings,
        versions=[
            VersionInfo(
                number=v.number, origin=v.origin, created_at=v.created_at, created_by_name=name
            )
            for v, name in history
        ],
    )


def read(db, workspace_id, artifact_id, teacher, number, kind=None):
    artifact = owned_artifact(db, workspace_id, artifact_id, teacher.id, kind)
    shown = version(db, artifact, number) if number else current_version(db, artifact)
    return artifact_out(db, artifact, shown)


def edit(db, workspace_id, artifact_id, data: NotesEdit, teacher, kind=None):
    artifact = owned_artifact(db, workspace_id, artifact_id, teacher.id, kind)
    previous = current_version(db, artifact)
    allowed = allowed_for_edit(db, workspace_id, previous)
    spec = KINDS[artifact.kind]
    result = check_citations(spec, data.markdown, set(allowed))
    if result.invalid:
        raise HTTPException(
            422,
            "These citations do not match any course source: "
            + ", ".join(f"[{m}]" for m in result.invalid)
            + ". Use labels such as [C3] from the source list.",
        )
    saved = add_version(
        db,
        artifact,
        markdown=data.markdown,
        citation_map={m: allowed[m] for m in result.used},
        warnings=result.warnings,
        origin="edited",
        user_id=teacher.id,
        expected=data.expected_version,
    )
    if saved is None:
        db.rollback()
        raise HTTPException(409, "A newer version was saved meanwhile. Reload to compare.")
    db.commit()
    return artifact_out(db, artifact, saved)


def restore(db, workspace_id, artifact_id, number, data: RestoreIn, teacher, kind=None):
    artifact = owned_artifact(db, workspace_id, artifact_id, teacher.id, kind)
    old = version(db, artifact, number)
    saved = add_version(
        db,
        artifact,
        markdown=old.markdown,
        citation_map=old.citations,
        warnings=old.warnings,
        origin="restored",
        user_id=teacher.id,
        expected=data.expected_version,
    )
    if saved is None:
        db.rollback()
        raise HTTPException(409, "A newer version was saved meanwhile. Reload to compare.")
    db.commit()
    return artifact_out(db, artifact, saved)


Number = Query(default=None, ge=1)


@router.get("/artifacts/{artifact_id}", response_model=NotesOut)
def read_artifact(
    workspace_id: UUID, artifact_id: UUID, db: Db, teacher: CurrentTeacher, number: int = Number
):
    """Current version, or an older one with ?number=N (read-only history view)."""
    return read(db, workspace_id, artifact_id, teacher, number)


@router.put("/artifacts/{artifact_id}", response_model=NotesOut)
def edit_artifact(
    workspace_id: UUID,
    artifact_id: UUID,
    data: NotesEdit,
    db: Db,
    teacher: CurrentTeacher,
    request: Request,
):
    check_text(request.app.state.ai, request.app.state.settings, data.markdown)
    return edit(db, workspace_id, artifact_id, data, teacher)


@router.post("/artifacts/{artifact_id}/restore/{number}", response_model=NotesOut)
def restore_artifact(
    workspace_id: UUID,
    artifact_id: UUID,
    number: int,
    data: RestoreIn,
    db: Db,
    teacher: CurrentTeacher,
):
    return restore(db, workspace_id, artifact_id, number, data, teacher)


@router.get("/notes/{artifact_id}", response_model=NotesOut)
def read_notes(
    workspace_id: UUID, artifact_id: UUID, db: Db, teacher: CurrentTeacher, number: int = Number
):
    return read(db, workspace_id, artifact_id, teacher, number, NOTES)


@router.put("/notes/{artifact_id}", response_model=NotesOut)
def edit_notes(
    workspace_id: UUID,
    artifact_id: UUID,
    data: NotesEdit,
    db: Db,
    teacher: CurrentTeacher,
    request: Request,
):
    check_text(request.app.state.ai, request.app.state.settings, data.markdown)
    return edit(db, workspace_id, artifact_id, data, teacher, NOTES)


@router.post("/notes/{artifact_id}/restore/{number}", response_model=NotesOut)
def restore_notes(
    workspace_id: UUID,
    artifact_id: UUID,
    number: int,
    data: RestoreIn,
    db: Db,
    teacher: CurrentTeacher,
):
    return restore(db, workspace_id, artifact_id, number, data, teacher, NOTES)


# ---- concept graph --------------------------------------------------------------------------


@router.get("/concepts", response_model=ConceptGraphOut)
def read_concepts(workspace_id: UUID, db: Db, teacher: CurrentTeacher):
    owned_workspace(db, workspace_id, teacher.id)
    return graph_out(db, workspace_id)


@router.post("/concepts/build", response_model=JobOut, status_code=202)
def start_concepts(
    workspace_id: UUID, request: Request, db: Db, teacher: CurrentTeacher, quota: AIQuota
):
    workspace = owned_workspace(db, workspace_id, teacher.id)
    syllabus = get_syllabus(db, workspace.id)
    if syllabus is None or syllabus.status != "approved":
        raise HTTPException(409, "Approve the syllabus before building the concept graph.")
    return request.app.state.jobs.start(
        db, workspace.id, "concepts", teacher.id, build_concepts(request.app.state.ai)
    )


# ---- publishing and export ------------------------------------------------------------------


def publication_out(db, workspace) -> PublicationOut:
    units = course_units(db, workspace.id)
    found = unit_artifacts(db, workspace.id)
    rows = []
    for unit in units:
        notes, lab = found.get((NOTES, unit.id)), found.get((LAB, unit.id))
        rows.append(
            PublicationUnit(
                unit_id=unit.id,
                title=unit.title,
                notes_current=notes.current_version if notes else 0,
                notes_published=notes.published_version if notes else None,
                lab_current=lab.current_version if lab else 0,
                lab_published=lab.published_version if lab else None,
            )
        )
    pending = any(
        r.notes_current
        and r.notes_current != r.notes_published
        or r.lab_current
        and r.lab_current != r.lab_published
        for r in rows
    )
    return PublicationOut(
        published_at=workspace.published_at, unpublished_changes=pending, units=rows
    )


@router.get("/publication", response_model=PublicationOut)
def read_publication(workspace_id: UUID, db: Db, teacher: CurrentTeacher):
    return publication_out(db, owned_workspace(db, workspace_id, teacher.id))


@router.post("/publish", response_model=PublicationOut)
def publish_course(workspace_id: UUID, db: Db, teacher: CurrentTeacher):
    workspace = owned_workspace(db, workspace_id, teacher.id)
    try:
        publish(db, workspace)
    except PublishError as exc:
        raise HTTPException(409, str(exc)) from None
    return publication_out(db, workspace)


@router.post("/unpublish", response_model=PublicationOut)
def unpublish_course(workspace_id: UUID, db: Db, teacher: CurrentTeacher):
    workspace = owned_workspace(db, workspace_id, teacher.id)
    workspace.published_at = None
    db.commit()
    return publication_out(db, workspace)


def export_response(db, workspace, fmt: str, which: str) -> Response:
    text = export_markdown(db, workspace, which)
    stem = re.sub(r"[^A-Za-z0-9]+", "-", workspace.title).strip("-")[:60] or "course"
    if fmt == "pdf":
        body, media, name = export_pdf(text, workspace.title), "application/pdf", f"{stem}.pdf"
    else:
        body, media, name = text.encode("utf-8"), "text/markdown; charset=utf-8", f"{stem}.md"
    return Response(
        body,
        media_type=media,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"},
    )


@router.get("/export")
def export_notes(
    workspace_id: UUID,
    db: Db,
    teacher: CurrentTeacher,
    format: Literal["md", "pdf"] = "md",
    which: Literal["current", "published"] = "current",
):
    workspace = owned_workspace(db, workspace_id, teacher.id)
    return export_response(db, workspace, format, which)


# ---- web research ---------------------------------------------------------------------------


def finding_out(f: ResearchFinding) -> FindingOut:
    return FindingOut(
        id=f.id,
        label=f"W{f.ordinal}",
        query=f.query,
        title=f.title,
        url=f.url,
        summary=f.summary,
        status=f.status,
        flagged=f.flagged,
        flag_reason=f.flag_reason,
        created_at=f.created_at,
    )


@router.post("/research", response_model=JobOut, status_code=202)
def start_research(
    workspace_id: UUID, request: Request, db: Db, teacher: CurrentTeacher, quota: AIQuota
):
    workspace = owned_workspace(db, workspace_id, teacher.id)
    state = request.app.state
    return state.jobs.start(
        db, workspace.id, "research", teacher.id, research(state.ai, state.settings)
    )


@router.get("/research", response_model=list[FindingOut])
def list_findings(workspace_id: UUID, db: Db, teacher: CurrentTeacher):
    owned_workspace(db, workspace_id, teacher.id)
    rows = db.scalars(
        select(ResearchFinding)
        .where(ResearchFinding.workspace_id == workspace_id)
        .order_by(ResearchFinding.ordinal)
    ).all()
    return [finding_out(f) for f in rows]


@router.patch("/research/{finding_id}", response_model=FindingOut)
def review_finding(
    workspace_id: UUID, finding_id: UUID, data: FindingPatch, db: Db, teacher: CurrentTeacher
):
    owned_workspace(db, workspace_id, teacher.id)
    finding = db.scalar(
        select(ResearchFinding).where(
            ResearchFinding.id == finding_id, ResearchFinding.workspace_id == workspace_id
        )
    )
    if finding is None:
        raise HTTPException(404, "Finding not found.")
    if finding.flagged and data.status == "accepted":
        raise HTTPException(409, "This finding looked like prompt injection and cannot be used.")
    finding.status = data.status
    db.commit()
    return finding_out(finding)
