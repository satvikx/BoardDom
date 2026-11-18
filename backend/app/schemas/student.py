from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.schemas.course import Citation


class StudentCourseOut(BaseModel):
    id: UUID
    title: str
    subject: str | None
    description: str | None
    learner_level: str
    lesson_duration_minutes: int
    has_lab: bool
    teacher_name: str
    published_at: datetime
    assigned: bool  # the teacher enrolled this student in the course
    units_total: int
    units_done: int


class StudentUnitOut(BaseModel):
    id: UUID
    position: int
    title: str
    summary: str
    topics: list[str]
    has_notes: bool
    has_lab_manual: bool
    studied: bool


class CourseDetailOut(BaseModel):
    course: StudentCourseOut
    units: list[StudentUnitOut]


class PublishedDocOut(BaseModel):
    unit_id: UUID
    unit_title: str
    version: int
    markdown: str
    citations: dict[str, Citation]


class ChatIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class ChecklistItemOut(BaseModel):
    item: str
    why: str


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    role: Literal["student", "coach"]
    content: str
    in_scope: bool
    citations: dict[str, Citation]
    checklist: list[ChecklistItemOut]
    known: list[str]
    created_at: datetime


class ChatTurnOut(BaseModel):
    question: ChatMessageOut
    reply: ChatMessageOut


class QuizIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    unit_id: UUID | None = None  # None = the whole course
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    count: Annotated[int, Field(ge=3, le=10, strict=True)] = 5


class QuizQuestionOut(BaseModel):
    question: str
    options: list[str]
    # Only after submission:
    answer_index: int | None = None
    chosen: int | None = None
    correct: bool | None = None
    explanation: str | None = None
    sources: dict[str, Citation] | None = None


class QuizOut(BaseModel):
    id: UUID
    unit_title: str | None
    difficulty: str
    total: int
    score: int | None
    created_at: datetime
    submitted_at: datetime | None
    questions: list[QuizQuestionOut]


class QuizSummaryOut(BaseModel):
    id: UUID
    unit_title: str | None
    difficulty: str
    total: int
    score: int | None
    created_at: datetime
    submitted_at: datetime | None


class QuizAnswersIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answers: list[Annotated[int, Field(ge=0, le=3, strict=True)] | None] = Field(max_length=10)


class StudyAidOut(BaseModel):
    tool: Literal["mind_map", "short_notes", "flashcards"]
    unit_id: UUID
    notes_version: int
    content: dict
    citations: dict[str, Citation]


class VideoOut(BaseModel):
    status: Literal["none", "queued", "running", "ready", "failed"]
    message: str | None = None
    has_audio: bool = False
    duration_seconds: float | None = None
    slide_count: int = 0
    notes_version: int | None = None
