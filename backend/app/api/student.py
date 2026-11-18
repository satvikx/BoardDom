"""Student portal: published courses of the student's own teacher, and study tools."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy import delete, func, select

from app.api.course_content import export_response
from app.core.security import CurrentStudent, Db
from app.models.entities import (
    ChatMessage,
    Enrollment,
    Quiz,
    SyllabusUnit,
    UnitProgress,
    User,
    Video,
    Workspace,
)
from app.schemas.student import (
    ChatIn,
    ChatMessageOut,
    ChatTurnOut,
    CourseDetailOut,
    PublishedDocOut,
    QuizAnswersIn,
    QuizIn,
    QuizOut,
    QuizQuestionOut,
    QuizSummaryOut,
    StudentCourseOut,
    StudentUnitOut,
    StudyAidOut,
    VideoOut,
)
from app.services.course_content import LAB, NOTES
from app.services.guardrails import check_text, screen_injection
from app.services.student_tools import (
    MAX_HISTORY,
    coach_reply,
    course_units,
    grade,
    make_quiz,
    published,
    published_unit,
    study_aid,
    visible_course,
)
from app.services.usage import AIQuota, ai_actor
from app.services.video import make_video, video_path

router = APIRouter(prefix="/student", tags=["Student"])
INJECTION_REPLY = (
    "I can only help with this course's material. That message looked like an attempt to "
    "change my instructions, so it was not sent to the AI. Ask me about the course topics."
)


def course_out(db, workspace: Workspace, student) -> StudentCourseOut:
    units = course_units(db, workspace.id)
    done = db.scalar(
        select(func.count())
        .select_from(UnitProgress)
        .where(
            UnitProgress.student_id == student.id,
            UnitProgress.unit_id.in_([u.id for u in units]),
        )
    )
    assigned = db.scalar(
        select(Enrollment.id).where(
            Enrollment.workspace_id == workspace.id, Enrollment.student_id == student.id
        )
    )
    teacher = db.get(User, workspace.owner_id)
    return StudentCourseOut(
        id=workspace.id,
        title=workspace.title,
        subject=workspace.subject,
        description=workspace.description,
        learner_level=workspace.learner_level,
        lesson_duration_minutes=workspace.lesson_duration_minutes,
        has_lab=workspace.has_lab,
        teacher_name=teacher.display_name,
        published_at=workspace.published_at,
        assigned=assigned is not None,
        units_total=len(units),
        units_done=done,
    )


def course_unit(db, workspace, unit_id: UUID) -> SyllabusUnit:
    unit = next((u for u in course_units(db, workspace.id) if u.id == unit_id), None)
    if unit is None:
        raise HTTPException(404, "Unit not found.")
    return unit


@router.get("/courses", response_model=list[StudentCourseOut])
def my_courses(db: Db, student: CurrentStudent):
    workspaces = db.scalars(
        select(Workspace)
        .where(
            Workspace.owner_id == student.created_by_user_id,
            Workspace.published_at.is_not(None),
        )
        .order_by(Workspace.title, Workspace.id)
    ).all()
    out = [course_out(db, w, student) for w in workspaces]
    return sorted(out, key=lambda c: (not c.assigned, c.title.lower()))


@router.get("/courses/{course_id}", response_model=CourseDetailOut)
def course_detail(course_id: UUID, db: Db, student: CurrentStudent):
    workspace = visible_course(db, student, course_id)
    studied = set(
        db.scalars(select(UnitProgress.unit_id).where(UnitProgress.student_id == student.id))
    )
    units = [
        StudentUnitOut(
            id=u.id,
            position=u.position,
            title=u.title,
            summary=u.summary,
            topics=u.topics,
            has_notes=published(db, workspace.id, u.id, NOTES) is not None,
            has_lab_manual=workspace.has_lab and published(db, workspace.id, u.id, LAB) is not None,
            studied=u.id in studied,
        )
        for u in course_units(db, workspace.id)
    ]
    return CourseDetailOut(course=course_out(db, workspace, student), units=units)


def published_doc(db, student, course_id, unit_id, kind) -> PublishedDocOut:
    workspace = visible_course(db, student, course_id)
    if kind == LAB and not workspace.has_lab:
        raise HTTPException(404, "This course has no lab.")
    unit, version = published_unit(db, workspace.id, unit_id, kind)
    return PublishedDocOut(
        unit_id=unit.id,
        unit_title=unit.title,
        version=version.number,
        markdown=version.markdown,
        citations=version.citations,
    )


@router.get("/courses/{course_id}/units/{unit_id}/notes", response_model=PublishedDocOut)
def unit_notes(course_id: UUID, unit_id: UUID, db: Db, student: CurrentStudent):
    return published_doc(db, student, course_id, unit_id, NOTES)


@router.get("/courses/{course_id}/units/{unit_id}/lab", response_model=PublishedDocOut)
def unit_lab(course_id: UUID, unit_id: UUID, db: Db, student: CurrentStudent):
    return published_doc(db, student, course_id, unit_id, LAB)


@router.put("/courses/{course_id}/units/{unit_id}/progress", status_code=204)
def mark_studied(course_id: UUID, unit_id: UUID, db: Db, student: CurrentStudent):
    unit = course_unit(db, visible_course(db, student, course_id), unit_id)
    exists = db.scalar(
        select(UnitProgress.id).where(
            UnitProgress.student_id == student.id, UnitProgress.unit_id == unit.id
        )
    )
    if exists is None:
        db.add(UnitProgress(student_id=student.id, unit_id=unit.id))
        db.commit()
    return Response(status_code=204)


@router.delete("/courses/{course_id}/units/{unit_id}/progress", status_code=204)
def unmark_studied(course_id: UUID, unit_id: UUID, db: Db, student: CurrentStudent):
    unit = course_unit(db, visible_course(db, student, course_id), unit_id)
    db.execute(
        delete(UnitProgress).where(
            UnitProgress.student_id == student.id, UnitProgress.unit_id == unit.id
        )
    )
    db.commit()
    return Response(status_code=204)


@router.get("/courses/{course_id}/export")
def export_course(
    course_id: UUID, db: Db, student: CurrentStudent, format: Literal["md", "pdf"] = "md"
):
    return export_response(db, visible_course(db, student, course_id), format, "published")


# ---- coach ----------------------------------------------------------------------------------


@router.get("/courses/{course_id}/coach", response_model=list[ChatMessageOut])
def coach_history(course_id: UUID, db: Db, student: CurrentStudent):
    workspace = visible_course(db, student, course_id)
    recent = db.scalars(
        select(ChatMessage)
        .where(ChatMessage.workspace_id == workspace.id, ChatMessage.student_id == student.id)
        .order_by(
            ChatMessage.created_at.desc(), ChatMessage.role
        )  # reply before its question, then reversed
        .limit(MAX_HISTORY)
    ).all()
    return list(reversed(recent))


@router.post("/courses/{course_id}/coach", response_model=ChatTurnOut)
def coach(
    course_id: UUID,
    data: ChatIn,
    request: Request,
    db: Db,
    student: CurrentStudent,
    quota: AIQuota,
):
    workspace = visible_course(db, student, course_id)
    state = request.app.state
    check_text(state.ai, state.settings, data.message)
    screen = screen_injection(data.message)
    if screen.flagged:
        # Never forwarded to the model; stored so the conversation stays honest.
        text, cited, checklist, in_scope, known = INJECTION_REPLY, {}, [], False, []
    else:
        with ai_actor(student.id, workspace.id):
            text, cited, checklist, in_scope, known = coach_reply(
                db, state.ai, state.settings, workspace, student, data.message
            )
    question = ChatMessage(
        workspace_id=workspace.id, student_id=student.id, role="student", content=data.message
    )
    db.add(question)
    db.flush()
    reply = ChatMessage(
        workspace_id=workspace.id,
        student_id=student.id,
        role="coach",
        content=text,
        in_scope=in_scope,
        citations=cited,
        checklist=checklist,
        known=known,
        created_at=question.created_at,
    )
    db.add(reply)
    db.commit()
    return ChatTurnOut(question=question, reply=reply)


@router.delete("/courses/{course_id}/coach", status_code=204)
def clear_coach(course_id: UUID, db: Db, student: CurrentStudent):
    workspace = visible_course(db, student, course_id)
    db.execute(
        delete(ChatMessage).where(
            ChatMessage.workspace_id == workspace.id, ChatMessage.student_id == student.id
        )
    )
    db.commit()
    return Response(status_code=204)


# ---- quizzes --------------------------------------------------------------------------------


def unit_title(db, quiz: Quiz) -> str | None:
    unit = db.get(SyllabusUnit, quiz.unit_id) if quiz.unit_id else None
    return unit.title if unit else None


def quiz_out(db, quiz: Quiz) -> QuizOut:
    done = quiz.submitted_at is not None
    questions = []
    for i, q in enumerate(quiz.questions):
        graded = {}
        if done:
            chosen = quiz.answers[i]
            graded = {
                "answer_index": q["answer_index"],
                "chosen": chosen,
                "correct": chosen == q["answer_index"],
                "explanation": q["explanation"],
                "sources": q.get("sources", {}),
            }
        questions.append(
            QuizQuestionOut.model_validate(
                {"question": q["question"], "options": q["options"], **graded}
            )
        )
    return QuizOut(
        id=quiz.id,
        unit_title=unit_title(db, quiz),
        difficulty=quiz.difficulty,
        total=quiz.total,
        score=quiz.score,
        created_at=quiz.created_at,
        submitted_at=quiz.submitted_at,
        questions=questions,
    )


def own_quiz(db, student, quiz_id: UUID) -> Quiz:
    quiz = db.scalar(select(Quiz).where(Quiz.id == quiz_id, Quiz.student_id == student.id))
    if quiz is None:
        raise HTTPException(404, "Quiz not found.")
    visible_course(db, student, quiz.workspace_id)
    return quiz


@router.post("/courses/{course_id}/quizzes", response_model=QuizOut, status_code=201)
def new_quiz(
    course_id: UUID, data: QuizIn, request: Request, db: Db, student: CurrentStudent, quota: AIQuota
):
    workspace = visible_course(db, student, course_id)
    unit = course_unit(db, workspace, data.unit_id) if data.unit_id else None
    with ai_actor(student.id, workspace.id):
        quiz = make_quiz(
            db, request.app.state.ai, workspace, student, unit, data.difficulty, data.count
        )
    return quiz_out(db, quiz)


@router.get("/courses/{course_id}/quizzes", response_model=list[QuizSummaryOut])
def quiz_history(course_id: UUID, db: Db, student: CurrentStudent):
    workspace = visible_course(db, student, course_id)
    quizzes = db.scalars(
        select(Quiz)
        .where(Quiz.workspace_id == workspace.id, Quiz.student_id == student.id)
        .order_by(Quiz.created_at.desc())
        .limit(20)
    ).all()
    return [
        QuizSummaryOut(
            id=q.id,
            unit_title=unit_title(db, q),
            difficulty=q.difficulty,
            total=q.total,
            score=q.score,
            created_at=q.created_at,
            submitted_at=q.submitted_at,
        )
        for q in quizzes
    ]


@router.get("/quizzes/{quiz_id}", response_model=QuizOut)
def read_quiz(quiz_id: UUID, db: Db, student: CurrentStudent):
    return quiz_out(db, own_quiz(db, student, quiz_id))


@router.post("/quizzes/{quiz_id}/submit", response_model=QuizOut)
def submit_quiz(quiz_id: UUID, data: QuizAnswersIn, db: Db, student: CurrentStudent):
    quiz = own_quiz(db, student, quiz_id)
    grade(quiz, data.answers)
    db.commit()
    return quiz_out(db, quiz)


# ---- study aids -----------------------------------------------------------------------------

Tool = Literal["mind_map", "short_notes", "flashcards"]


@router.post("/courses/{course_id}/units/{unit_id}/aids/{tool}", response_model=StudyAidOut)
def make_aid(
    course_id: UUID,
    unit_id: UUID,
    tool: Tool,
    request: Request,
    db: Db,
    student: CurrentStudent,
    quota: AIQuota,
):
    """Cached per unit and published notes version; generated on first request."""
    workspace = visible_course(db, student, course_id)
    unit = course_unit(db, workspace, unit_id)
    with ai_actor(student.id, workspace.id):
        aid = study_aid(db, request.app.state.ai, workspace, unit, tool)
    return StudyAidOut(
        tool=aid.tool,
        unit_id=aid.unit_id,
        notes_version=aid.notes_version,
        content=aid.content,
        citations=aid.citations,
    )


# ---- video ----------------------------------------------------------------------------------


def latest_video(db, workspace_id, unit_id, notes_version) -> Video | None:
    return db.scalar(
        select(Video)
        .where(
            Video.workspace_id == workspace_id,
            Video.unit_id == unit_id,
            Video.notes_version == notes_version,
        )
        .order_by(Video.created_at.desc())
    )


def video_out(video: Video | None, notes_version: int) -> VideoOut:
    if video is None:
        return VideoOut(status="none", notes_version=notes_version)
    return VideoOut(
        status=video.status,
        message=video.message,
        has_audio=video.has_audio,
        duration_seconds=video.duration_seconds,
        slide_count=video.slide_count,
        notes_version=video.notes_version,
    )


@router.get("/courses/{course_id}/units/{unit_id}/video", response_model=VideoOut)
def video_status(course_id: UUID, unit_id: UUID, db: Db, student: CurrentStudent):
    workspace = visible_course(db, student, course_id)
    unit, version = published_unit(db, workspace.id, unit_id)
    return video_out(latest_video(db, workspace.id, unit.id, version.number), version.number)


@router.post("/courses/{course_id}/units/{unit_id}/video", response_model=VideoOut, status_code=202)
def start_video(
    course_id: UUID,
    unit_id: UUID,
    request: Request,
    db: Db,
    student: CurrentStudent,
    quota: AIQuota,
):
    """Shared per unit and notes version: an existing or in-progress video is reused."""
    workspace = visible_course(db, student, course_id)
    unit, version = published_unit(db, workspace.id, unit_id)
    existing = latest_video(db, workspace.id, unit.id, version.number)
    if existing and existing.status in ("queued", "running", "ready"):
        return video_out(existing, version.number)
    video = Video(workspace_id=workspace.id, unit_id=unit.id, notes_version=version.number)
    db.add(video)
    db.commit()
    state = request.app.state
    try:
        state.jobs.start(
            db, workspace.id, "video", student.id, make_video(state.ai, state.settings, video.id)
        )
    except HTTPException:
        db.delete(video)
        db.commit()
        raise HTTPException(
            409, "Another video for this course is being made. Try again in a minute."
        ) from None
    return video_out(video, version.number)


@router.get("/courses/{course_id}/units/{unit_id}/video/file")
def video_file(course_id: UUID, unit_id: UUID, request: Request, db: Db, student: CurrentStudent):
    workspace = visible_course(db, student, course_id)
    unit, version = published_unit(db, workspace.id, unit_id)
    video = latest_video(db, workspace.id, unit.id, version.number)
    if video is None or video.status != "ready":
        raise HTTPException(404, "The video is not ready.")
    path = video_path(request.app.state.settings, video.storage_key)
    if not path.exists():
        video.status, video.message = "failed", "The video file was missing. Make it again."
        db.commit()
        raise HTTPException(409, "The video file is missing. Make it again.")
    return FileResponse(path, media_type="video/mp4", filename=f"{unit.title[:60]}.mp4")
