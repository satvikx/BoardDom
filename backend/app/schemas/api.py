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


class Credentials(BaseModel):
    email: EmailStr = Field(max_length=254)
    password: Password

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value):
        return value.strip().lower() if isinstance(value, str) else value


class Register(Credentials):
    display_name: Name


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    email: str
    display_name: str
    created_at: datetime
    updated_at: datetime


class WorkspaceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Title
    description: Description | None = None
    subject: Subject | None = None
    learner_level: Level = "introductory"
    lesson_duration_minutes: Duration = 40


class WorkspacePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Title | None = None
    description: Description | None = None
    subject: Subject | None = None
    learner_level: Level | None = None
    lesson_duration_minutes: Duration | None = None

    @field_validator("title", "learner_level", "lesson_duration_minutes")
    @classmethod
    def required_when_present(cls, value):
        if value is None:
            raise ValueError("This field cannot be null")
        return value


class WorkspaceOut(WorkspaceCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
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
