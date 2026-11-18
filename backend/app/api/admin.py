import threading
from datetime import timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from app.core.security import CurrentAdmin, Db, password_hasher
from app.models.entities import (
    AICall,
    Enrollment,
    EvalRun,
    SourceChunk,
    SourceDocument,
    User,
    Workspace,
    utcnow,
)
from app.schemas.api import AdminUserOut, CreatedAccountOut, TeacherCreate, TeacherPatch
from app.services.accounts import delete_account, effective_student_limit, temporary_password
from app.services.guardrails import check_text
from app.services.usage import AIQuota

router = APIRouter(prefix="/admin", tags=["Administration"])


def grouped_counts(db, key, statement) -> dict:
    return dict(db.execute(statement.group_by(key)).all())


def admin_rows(db, users: list[User], settings) -> list[AdminUserOut]:
    students = grouped_counts(
        db,
        User.created_by_user_id,
        select(User.created_by_user_id, func.count()).where(User.role == "student"),
    )
    courses = grouped_counts(db, Workspace.owner_id, select(Workspace.owner_id, func.count()))
    files = grouped_counts(
        db,
        Workspace.owner_id,
        select(Workspace.owner_id, func.count(SourceDocument.id)).join(
            SourceDocument, SourceDocument.workspace_id == Workspace.id
        ),
    )
    enrollments = grouped_counts(
        db, Enrollment.student_id, select(Enrollment.student_id, func.count())
    )
    creator_ids = {u.created_by_user_id for u in users if u.created_by_user_id}
    creators = (
        dict(db.execute(select(User.id, User.display_name).where(User.id.in_(creator_ids))).all())
        if creator_ids
        else {}
    )
    rows = []
    for u in users:
        row = AdminUserOut(
            id=u.id,
            email=u.email,
            display_name=u.display_name,
            role=u.role,
            created_at=u.created_at,
            last_login_at=u.last_login_at,
            must_change_password=u.must_change_password,
            created_by_user_id=u.created_by_user_id,
            created_by_name=creators.get(u.created_by_user_id),
        )
        if u.role == "teacher":
            row.student_count = students.get(u.id, 0)
            row.student_limit = effective_student_limit(u, settings)
            row.uses_default_limit = u.student_limit is None
            row.course_count = courses.get(u.id, 0)
            row.file_count = files.get(u.id, 0)
        elif u.role == "student":
            row.enrollment_count = enrollments.get(u.id, 0)
        rows.append(row)
    return rows


@router.get("/users", response_model=list[AdminUserOut])
def list_users(
    request: Request,
    db: Db,
    admin: CurrentAdmin,
    role: Literal["admin", "teacher", "student"] | None = None,
    q: str | None = Query(default=None, max_length=254),
):
    statement = select(User).order_by(User.role, User.display_name, User.email)
    if role:
        statement = statement.where(User.role == role)
    if q and q.strip():
        needle = q.strip().lower()
        statement = statement.where(
            or_(
                func.lower(User.display_name).contains(needle, autoescape=True),
                func.lower(User.email).contains(needle, autoescape=True),
            )
        )
    return admin_rows(db, db.scalars(statement).all(), request.app.state.settings)


@router.post("/teachers", response_model=CreatedAccountOut, status_code=201)
def create_teacher(data: TeacherCreate, request: Request, db: Db, admin: CurrentAdmin):
    check_text(request.app.state.ai, request.app.state.settings, data.display_name)
    password = temporary_password()
    teacher = User(
        email=str(data.email),
        display_name=data.display_name,
        password_hash=password_hasher.hash(password),
        role="teacher",
        created_by_user_id=admin.id,
        must_change_password=True,
        student_limit=data.student_limit,
    )
    db.add(teacher)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "An account with this email already exists.") from None
    [row] = admin_rows(db, [teacher], request.app.state.settings)
    return CreatedAccountOut(user=row, temporary_password=password)


def get_teacher(db, user_id: UUID) -> User:
    teacher = db.scalar(select(User).where(User.id == user_id, User.role == "teacher"))
    if teacher is None:
        raise HTTPException(404, "Teacher not found.")
    return teacher


@router.patch("/teachers/{user_id}", response_model=AdminUserOut)
def update_teacher(
    user_id: UUID, data: TeacherPatch, request: Request, db: Db, admin: CurrentAdmin
):
    teacher = get_teacher(db, user_id)
    # Lowering below the current count never deletes students; it only blocks new ones.
    teacher.student_limit = data.student_limit
    db.commit()
    [row] = admin_rows(db, [teacher], request.app.state.settings)
    return row


@router.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: UUID, request: Request, db: Db, admin: CurrentAdmin):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found.")
    if user.id == admin.id:
        raise HTTPException(403, "You cannot delete your own account.")
    delete_account(db, request.app.state.storage, user, request.app.state.settings)
    return Response(status_code=204)


# ---- evals ----------------------------------------------------------------------------------


def eval_out(run: EvalRun) -> dict:
    return {
        "id": str(run.id),
        "status": run.status,
        "provider": run.provider,
        "results": run.results,
        "message": run.message,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
    }


def run_evals_in_background(app, run_id) -> None:
    from app.evals import run_evals

    factory = app.state.session_factory
    try:
        results = run_evals(app.state.ai, app.state.settings)
        status, message = "succeeded", None
    except Exception as exc:  # noqa: BLE001 - shown on the admin page
        results, status, message = {}, "failed", f"Evals failed ({type(exc).__name__})."
    with factory() as db:
        run = db.get(EvalRun, run_id)
        if run:
            run.status, run.results, run.message = status, results, message
            run.finished_at = utcnow()
            db.commit()


@router.get("/evals")
def list_evals(db: Db, admin: CurrentAdmin):
    runs = db.scalars(select(EvalRun).order_by(EvalRun.started_at.desc()).limit(10)).all()
    return [eval_out(r) for r in runs]


@router.post("/evals", status_code=202)
def start_evals(request: Request, db: Db, admin: CurrentAdmin, quota: AIQuota):
    running = db.scalar(select(EvalRun).where(EvalRun.status == "running"))
    if running and running.started_at > utcnow() - timedelta(minutes=30):
        raise HTTPException(409, "An evaluation is already running.")
    run = EvalRun(provider=request.app.state.ai.name, created_by_user_id=admin.id)
    db.add(run)
    db.commit()
    threading.Thread(
        target=run_evals_in_background, args=(request.app, run.id), daemon=True
    ).start()
    return eval_out(run)


# ---- efficiency -----------------------------------------------------------------------------

GENERATION = ("syllabus", "unit_notes", "lab_manual", "lesson_plan", "rubric")


def summarize(rows) -> dict:
    calls = len(rows)
    tin = sum(r.input_tokens for r in rows)
    cached = sum(r.cached_tokens for r in rows)
    out = sum(r.output_tokens for r in rows)
    costs = [r.cost_usd for r in rows if r.cost_usd is not None]
    return {
        "calls": calls,
        "input_tokens": tin,
        "cached_tokens": cached,
        "output_tokens": out,
        "cache_hit_rate": round(cached / tin, 3) if tin else None,
        "avg_latency_ms": round(sum(r.latency_ms for r in rows) / calls) if calls else None,
        "cost_usd": round(sum(costs), 6) if costs else None,
    }


@router.get("/efficiency")
def efficiency(request: Request, db: Db, admin: CurrentAdmin):
    """Token, latency and cost figures from ai_calls, plus a naive-pipeline estimate."""
    request.app.state.usage.flush()
    rows = db.scalars(select(AICall)).all()
    by_purpose: dict[str, list] = {}
    by_course: dict = {}
    by_pipeline: dict[str, list] = {}
    for r in rows:
        by_purpose.setdefault(r.purpose, []).append(r)
        by_pipeline.setdefault(r.pipeline, []).append(r)
        if r.workspace_id:
            by_course.setdefault(r.workspace_id, []).append(r)
    titles = dict(
        db.execute(
            select(Workspace.id, Workspace.title).where(Workspace.id.in_(list(by_course)))
        ).all()
    )
    # Naive pipeline estimate: every generation call sends the course's whole source text
    # instead of the few retrieved passages. Fake-provider "tokens" are characters.
    sizes = dict(
        db.execute(
            select(SourceChunk.workspace_id, func.sum(func.length(SourceChunk.text)))
            .where(SourceChunk.workspace_id.in_(list(by_course)))
            .group_by(SourceChunk.workspace_id)
        ).all()
    )
    courses, naive_total, ours_total = [], 0, 0
    for workspace_id, items in by_course.items():
        generation = [r for r in items if r.purpose in GENERATION]
        chars = sizes.get(workspace_id) or 0
        per_call = chars if all(r.model.startswith("fake") for r in items) else chars // 4
        ours = sum(r.input_tokens for r in generation)
        naive = sum(max(r.input_tokens, per_call) for r in generation)
        naive_total, ours_total = naive_total + naive, ours_total + ours
        courses.append(
            {
                "workspace_id": str(workspace_id),
                "title": titles.get(workspace_id, "(deleted course)"),
                **summarize(items),
                "generation_calls": len(generation),
                "naive_input_tokens": naive,
                "pipeline_input_tokens": ours,
            }
        )
    generated = [c for c in courses if c["generation_calls"]]
    per_course = None
    if generated:
        costs = [c["cost_usd"] for c in generated if c["cost_usd"] is not None]
        per_course = {
            "courses": len(generated),
            "avg_tokens": round(
                sum(c["input_tokens"] + c["output_tokens"] for c in generated) / len(generated)
            ),
            "avg_cost_usd": round(sum(costs) / len(costs), 6) if costs else None,
        }
    return {
        "totals": summarize(rows),
        "by_purpose": [
            {"purpose": p, **summarize(items)}
            for p, items in sorted(by_purpose.items(), key=lambda kv: -len(kv[1]))
        ],
        "by_course": sorted(courses, key=lambda c: -c["calls"]),
        "by_pipeline": {p: summarize(items) for p, items in by_pipeline.items()},
        "per_generated_course": per_course,
        "naive_vs_pipeline": {
            "naive_input_tokens": naive_total,
            "pipeline_input_tokens": ours_total,
            "saving": round(1 - ours_total / naive_total, 3) if naive_total else None,
        },
        "token_unit": "characters (demo provider)"
        if rows and all(r.model.startswith("fake") for r in rows)
        else "tokens",
        "prices_known_for": sorted(request.app.state.settings.model_prices),
    }
