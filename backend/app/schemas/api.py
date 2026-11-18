from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, field_validator

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)]
Subject = Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)]
Level = Literal["introductory", "intermediate", "advanced"]
Duration = Annotated[int, Field(gt=0, le=1440, strict=True)]
Password = Annotated[str, Field(min_length=8, max_length=128)]
Role = Literal["admin", "teacher", "student"]
StudentLimit = Annotated[int, Field(ge=0, le=10000, strict=True)]


def normalize_email(value):
    return value.strip().lower() if isinstance(value, str) else value


class Credentials(BaseModel):
    email: EmailStr = Field(max_length=254)
    password: Password

    _normalize_email = field_validator("email", mode="before")(normalize_email)


class Register(Credentials):
    display_name: Name


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    email: str
    display_name: str
    role: Role
    must_change_password: bool
    created_at: datetime
    updated_at: datetime


class ChangePassword(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: Annotated[str, Field(min_length=1, max_length=128)]
    new_password: Password


class AdminPasswordReset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr = Field(max_length=254)
    pin: Annotated[str, Field(min_length=1, max_length=64)]
    new_password: Password

    _normalize_email = field_validator("email", mode="before")(normalize_email)


class NewAccount(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: Name
    email: EmailStr = Field(max_length=254)

    _normalize_email = field_validator("email", mode="before")(normalize_email)


class TeacherCreate(NewAccount):
    student_limit: StudentLimit | None = None


class TeacherPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # null resets the teacher to BOARDOM_DEFAULT_STUDENT_LIMIT.
    student_limit: StudentLimit | None


class AdminUserOut(BaseModel):
    id: UUID
    email: str
    display_name: str
    role: Role
    created_at: datetime
    last_login_at: datetime | None
    must_change_password: bool
    created_by_user_id: UUID | None
    created_by_name: str | None
    # Teachers only (None for other roles).
    student_count: int | None = None
    student_limit: int | None = None
    uses_default_limit: bool | None = None
    course_count: int | None = None
    file_count: int | None = None
    # Students only.
    enrollment_count: int | None = None


class CreatedAccountOut(BaseModel):
    user: AdminUserOut
    # Shown once. It is never stored in plain text and cannot be retrieved again.
    temporary_password: str


class StudentOut(BaseModel):
    id: UUID
    email: str
    display_name: str
    created_at: datetime
    last_login_at: datetime | None
    must_change_password: bool
    course_count: int


class StudentListOut(BaseModel):
    students: list[StudentOut]
    used: int
    limit: int


class CreatedStudentOut(BaseModel):
    student: StudentOut
    temporary_password: str
    used: int
    limit: int


class EnrollmentOut(BaseModel):
    student_id: UUID
    display_name: str
    email: str
    enrolled_at: datetime


class WorkspaceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Title
    description: Description | None = None
    subject: Subject | None = None
    learner_level: Level = "introductory"
    lesson_duration_minutes: Duration = 40
    has_lab: bool = False


class WorkspacePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Title | None = None
    description: Description | None = None
    subject: Subject | None = None
    learner_level: Level | None = None
    lesson_duration_minutes: Duration | None = None
    has_lab: bool | None = None

    @field_validator("title", "learner_level", "lesson_duration_minutes", "has_lab")
    @classmethod
    def required_when_present(cls, value):
        if value is None:
            raise ValueError("This field cannot be null")
        return value


class WorkspaceOut(WorkspaceCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    published_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    workspace_id: UUID
    original_filename: str
    media_type: str
    size_bytes: int
    status: Literal["uploaded"]
    created_at: datetime

    extraction_status: Literal["uploaded", "processing", "extracted", "needs_ocr", "failed"]
    extraction_error_code: str | None
    extraction_error_message: str | None
    extraction_warnings: list[str]
    extracted_at: datetime | None
    reviewed_at: datetime | None
    reviewed_by_user_id: UUID | None
    content_revision: int
    extraction_attempt_id: str | None
    extraction_started_at: datetime | None
    extraction_finished_at: datetime | None


class UnitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    position: int
    page_number: int | None
    label: str
    original_text: str
    corrected_text: str | None
    effective_text: str
    revision: int


class ContentOut(BaseModel):
    document: DocumentOut
    units: list[UnitOut]


class UnitPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    corrected_text: str | None = Field(max_length=500000)
    expected_revision: int = Field(ge=0, strict=True)


class ReviewPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reviewed: bool
    expected_content_revision: int = Field(ge=0, strict=True)


class PastedTextIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    text: Annotated[str, StringConstraints(min_length=1, max_length=500_000)]

    @field_validator("text")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Paste some text")
        return value
