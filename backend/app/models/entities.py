from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from app.db.session import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator):
    """Persist naive UTC (SQLite); always expose timezone-aware UTC."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return value.astimezone(UTC).replace(tzinfo=None) if value is not None else None

    def process_result_value(self, value, dialect):
        return value.replace(tzinfo=UTC) if value is not None else None


ROLES = ("admin", "teacher", "student")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('admin', 'teacher', 'student')", name="user_role"),
        CheckConstraint(
            "student_limit IS NULL OR student_limit >= 0", name="nonnegative_student_limit"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    display_name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    role: Mapped[str] = mapped_column(String(20), default="teacher", server_default="teacher")
    # Admin for teachers, teacher for students, NULL for seeded admin / public sign-up.
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    must_change_password: Mapped[bool] = mapped_column(default=False, server_default=false())
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # Teachers only. NULL means BOARDOM_DEFAULT_STUDENT_LIMIT.
    student_limit: Mapped[int | None]


class SessionToken(Base):
    __tablename__ = "sessions"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Workspace(Base):
    __tablename__ = "workspaces"
    __table_args__ = (
        CheckConstraint("lesson_duration_minutes > 0", name="positive_duration"),
        CheckConstraint(
            "learner_level IN ('introductory', 'intermediate', 'advanced')", name="learner_level"
        ),
        Index("ix_workspaces_owner_updated", "owner_id", "updated_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    subject: Mapped[str | None] = mapped_column(String(100))
    learner_level: Mapped[str] = mapped_column(String(20), default="introductory")
    lesson_duration_minutes: Mapped[int] = mapped_column(default=40)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    has_lab: Mapped[bool] = mapped_column(default=False, server_default=false())
    # Set while students can see the course; NULL = not published.
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Enrollment(Base):
    __tablename__ = "enrollments"
    __table_args__ = (UniqueConstraint("workspace_id", "student_id"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    student_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class SourceDocument(Base):
    __tablename__ = "source_documents"
    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="positive_size"),
        CheckConstraint("status = 'uploaded'", name="uploaded_status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    original_filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(32), unique=True)
    media_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int]
    status: Mapped[str] = mapped_column(String(20), default="uploaded")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    extraction_status: Mapped[str] = mapped_column(
        String(20), default="uploaded", server_default="uploaded", index=True
    )
    extraction_error_code: Mapped[str | None] = mapped_column(String(50))
    extraction_error_message: Mapped[str | None] = mapped_column(Text)
    extraction_warnings: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    extracted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    reviewed_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    content_revision: Mapped[int] = mapped_column(default=0, server_default="0")
    extraction_attempt_id: Mapped[str | None] = mapped_column(String(32), unique=True)
    extraction_started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    extraction_finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class SourceUnit(Base):
    __tablename__ = "source_units"
    __table_args__ = (UniqueConstraint("document_id", "position"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_documents.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int]
    page_number: Mapped[int | None]
    label: Mapped[str] = mapped_column(String(100))
    original_text: Mapped[str] = mapped_column(Text)
    corrected_text: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    @property
    def effective_text(self):
        return self.original_text if self.corrected_text is None else self.corrected_text


class SourceChunk(Base):
    """Retrieval unit cut from an extracted SourceUnit. `ordinal` is the course-wide [C n] label.

    Ordinals are never reused within a course, so a citation snapshot never points at a
    different passage after re-indexing.
    """

    __tablename__ = "source_chunks"
    __table_args__ = (UniqueConstraint("workspace_id", "ordinal"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_documents.id", ondelete="CASCADE"), index=True
    )
    content_revision: Mapped[int]
    ordinal: Mapped[int]
    page_number: Mapped[int | None]
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list] = mapped_column(JSON)
    # Vectors from another model are not comparable: such chunks are re-embedded.
    embedding_model: Mapped[str] = mapped_column(String(100), server_default="")
    # Possible prompt injection: kept for the teacher to see, never sent to the model.
    flagged: Mapped[bool] = mapped_column(default=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ChunkCounter(Base):
    """Next [C n] ordinal per course; only ever grows, so labels are never reused."""

    __tablename__ = "chunk_counters"

    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    next_ordinal: Mapped[int] = mapped_column(default=1)


class Syllabus(Base):
    __tablename__ = "syllabi"
    __table_args__ = (CheckConstraint("status IN ('draft', 'approved')", name="syllabus_status"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), unique=True
    )
    status: Mapped[str] = mapped_column(String(20), default="draft")
    revision: Mapped[int] = mapped_column(default=0)
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class SyllabusUnit(Base):
    __tablename__ = "syllabus_units"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    syllabus_id: Mapped[UUID] = mapped_column(
        ForeignKey("syllabi.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int]
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text, default="")
    topics: Mapped[list] = mapped_column(JSON, default=list)
    weeks: Mapped[int | None]  # teaching weeks planned for this unit
    # {"C3": snapshot, "W1": snapshot} - sources the generator cited for this unit.
    citations: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")


class Artifact(Base):
    """A generated teaching artifact (unit notes now; lab manuals, lesson plans later)."""

    __tablename__ = "artifacts"
    __table_args__ = (UniqueConstraint("workspace_id", "kind", "unit_id"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(30))
    unit_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("syllabus_units.id", ondelete="CASCADE"), index=True
    )
    current_version: Mapped[int] = mapped_column(default=0)
    # Version students see; set on publish so later teacher edits stay private until republish.
    published_version: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class ArtifactVersion(Base):
    __tablename__ = "artifact_versions"
    __table_args__ = (
        UniqueConstraint("artifact_id", "number"),
        CheckConstraint("origin IN ('generated', 'edited', 'restored')", name="version_origin"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    artifact_id: Mapped[UUID] = mapped_column(
        ForeignKey("artifacts.id", ondelete="CASCADE"), index=True
    )
    number: Mapped[int]
    origin: Mapped[str] = mapped_column(String(20))
    markdown: Mapped[str] = mapped_column(Text)
    # {"C3": {"document": ..., "page": ..., "excerpt": ...}} snapshot at save time.
    citations: Mapped[dict] = mapped_column(JSON, default=dict)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')", name="job_status"
        ),
        Index("ix_jobs_workspace_created", "workspace_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    progress: Mapped[int] = mapped_column(default=0)
    total: Mapped[int] = mapped_column(default=0)
    message: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Concept(Base):
    __tablename__ = "concepts"
    __table_args__ = (UniqueConstraint("workspace_id", "key"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(200))  # normalized name, for matching
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    unit_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("syllabus_units.id", ondelete="SET NULL")
    )
    position: Mapped[int] = mapped_column(default=0)


class ConceptEdge(Base):
    """`prerequisite_id` must be understood before `concept_id`."""

    __tablename__ = "concept_edges"
    __table_args__ = (
        UniqueConstraint("prerequisite_id", "concept_id"),
        CheckConstraint("prerequisite_id <> concept_id", name="no_self_edge"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    prerequisite_id: Mapped[UUID] = mapped_column(ForeignKey("concepts.id", ondelete="CASCADE"))
    concept_id: Mapped[UUID] = mapped_column(ForeignKey("concepts.id", ondelete="CASCADE"))


class UnitProgress(Base):
    """A student marked a unit as studied."""

    __tablename__ = "unit_progress"
    __table_args__ = (UniqueConstraint("student_id", "unit_id"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    student_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    unit_id: Mapped[UUID] = mapped_column(
        ForeignKey("syllabus_units.id", ondelete="CASCADE"), index=True
    )
    completed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        CheckConstraint("role IN ('student', 'coach')", name="chat_role"),
        Index("ix_chat_course_student", "workspace_id", "student_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    student_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(10))
    content: Mapped[str] = mapped_column(Text)
    in_scope: Mapped[bool] = mapped_column(default=True)
    citations: Mapped[dict] = mapped_column(JSON, default=dict)
    checklist: Mapped[list] = mapped_column(JSON, default=list)
    known: Mapped[list] = mapped_column(JSON, default=list)  # concept names recognized
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Quiz(Base):
    __tablename__ = "quizzes"
    __table_args__ = (
        CheckConstraint("difficulty IN ('easy', 'medium', 'hard')", name="quiz_difficulty"),
        Index("ix_quizzes_course_student", "workspace_id", "student_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    student_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    unit_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("syllabus_units.id", ondelete="SET NULL")
    )
    difficulty: Mapped[str] = mapped_column(String(10))
    # [{question, options, answer_index, explanation, citations}] - answers never sent early.
    questions: Mapped[list] = mapped_column(JSON)
    answers: Mapped[list | None] = mapped_column(JSON)
    score: Mapped[int | None]
    total: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class StudyAid(Base):
    """Mind map / short notes / flashcards for one published notes version (shared cache)."""

    __tablename__ = "study_aids"
    __table_args__ = (
        UniqueConstraint("unit_id", "tool", "notes_version"),
        CheckConstraint("tool IN ('mind_map', 'short_notes', 'flashcards')", name="study_aid_tool"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    unit_id: Mapped[UUID] = mapped_column(ForeignKey("syllabus_units.id", ondelete="CASCADE"))
    tool: Mapped[str] = mapped_column(String(20))
    notes_version: Mapped[int]
    content: Mapped[dict] = mapped_column(JSON)
    citations: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Video(Base):
    __tablename__ = "videos"
    __table_args__ = (
        CheckConstraint("status IN ('queued', 'running', 'ready', 'failed')", name="video_status"),
        Index("ix_videos_unit_version", "unit_id", "notes_version"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    unit_id: Mapped[UUID] = mapped_column(ForeignKey("syllabus_units.id", ondelete="CASCADE"))
    notes_version: Mapped[int]
    status: Mapped[str] = mapped_column(String(10), default="queued")
    message: Mapped[str | None] = mapped_column(Text)
    has_audio: Mapped[bool] = mapped_column(default=False)
    storage_key: Mapped[str | None] = mapped_column(String(32))
    duration_seconds: Mapped[float | None]
    slide_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class CourseProfile(Base):
    """Answers from the course wizard; the syllabus generator follows them."""

    __tablename__ = "course_profiles"
    __table_args__ = (CheckConstraint("mode IN ('theory', 'theory_lab')", name="course_mode"),)

    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    audience: Mapped[str] = mapped_column(String(200))
    weeks: Mapped[int]
    hours_per_week: Mapped[int]
    mode: Mapped[str] = mapped_column(String(20), default="theory")
    lab_hours_per_week: Mapped[int] = mapped_column(default=0)
    experiments: Mapped[int] = mapped_column(default=0)
    must_include: Mapped[list] = mapped_column(JSON, default=list)
    exclude: Mapped[list] = mapped_column(JSON, default=list)
    assessment: Mapped[list] = mapped_column(JSON, default=list)  # [{name, weight_percent}]
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class ResearchFinding(Base):
    __tablename__ = "research_findings"
    __table_args__ = (
        UniqueConstraint("workspace_id", "ordinal"),
        CheckConstraint("status IN ('pending', 'accepted', 'ignored')", name="finding_status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    ordinal: Mapped[int]  # cited as [W n]
    query: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(String(300))
    url: Mapped[str] = mapped_column(String(2000))
    summary: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="pending")
    flagged: Mapped[bool] = mapped_column(default=False)
    flag_reason: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class AICall(Base):
    """One model call, for limits, cost and the efficiency page. Never stores prompt text."""

    __tablename__ = "ai_calls"
    __table_args__ = (
        Index("ix_ai_calls_user_created", "user_id", "created_at"),
        Index("ix_ai_calls_workspace", "workspace_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    workspace_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="SET NULL")
    )
    purpose: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(100))
    pipeline: Mapped[str] = mapped_column(String(20), default="full")
    input_tokens: Mapped[int] = mapped_column(default=0)
    cached_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    latency_ms: Mapped[int] = mapped_column(default=0)
    cost_usd: Mapped[float | None]
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class EvalRun(Base):
    __tablename__ = "eval_runs"
    __table_args__ = (
        CheckConstraint("status IN ('running', 'succeeded', 'failed')", name="eval_status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    status: Mapped[str] = mapped_column(String(10), default="running")
    provider: Mapped[str] = mapped_column(String(50))
    results: Mapped[dict] = mapped_column(JSON, default=dict)
    message: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
