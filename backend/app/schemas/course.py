from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.schemas.api import Description, Level, Title

UnitTitle = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Topic = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Revision = Annotated[int, Field(ge=0, strict=True)]


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    kind: str
    status: Literal["queued", "running", "succeeded", "failed"]
    progress: int
    total: int
    message: str | None
    created_at: datetime
    finished_at: datetime | None


class UnitIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID | None = None  # Keep an existing unit (and its notes); omit for a new unit.
    title: UnitTitle
    summary: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] = ""
    topics: list[Topic] = Field(default_factory=list, max_length=12)
    weeks: Annotated[int, Field(ge=1, le=52, strict=True)] | None = None


class SyllabusIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: Revision
    units: list[UnitIn] = Field(max_length=20)


class RevisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: Revision


class UnitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    position: int
    title: str
    summary: str
    topics: list[str]
    weeks: int | None = None
    citations: dict = Field(default_factory=dict)


class SyllabusOut(BaseModel):
    id: UUID
    status: Literal["draft", "approved"]
    revision: int
    approved_at: datetime | None
    updated_at: datetime
    units: list[UnitOut]


class GenerateNotesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    unit_ids: list[UUID] | None = Field(default=None, max_length=20)  # None = every unit


class GenerateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["unit_notes", "lab_manual", "lesson_plan", "rubric"]
    unit_ids: list[UUID] | None = Field(default=None, max_length=20)  # None = every unit


class NotesSummaryOut(BaseModel):
    kind: str
    unit_id: UUID | None  # None for course-level materials (rubric)
    unit_title: str
    position: int
    artifact_id: UUID | None
    current_version: int
    published_version: int | None
    updated_at: datetime | None
    warning_count: int


class VersionInfo(BaseModel):
    number: int
    origin: Literal["generated", "edited", "restored"]
    created_at: datetime
    created_by_name: str | None


class Citation(BaseModel):
    document: str
    page: int | None
    excerpt: str


class NotesOut(BaseModel):
    artifact_id: UUID
    kind: str
    unit_id: UUID | None
    unit_title: str
    number: int
    current_version: int
    published_version: int | None
    origin: str
    markdown: str
    citations: dict[str, Citation]
    warnings: list[str]
    versions: list[VersionInfo]


class NotesEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    markdown: Annotated[str, StringConstraints(min_length=1, max_length=200_000)]
    expected_version: Revision


class RestoreIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: Revision


class ConceptOut(BaseModel):
    id: UUID
    name: str
    description: str
    unit_id: UUID | None
    unit_title: str | None
    level: int
    prerequisite_ids: list[UUID]


class ConceptGraphOut(BaseModel):
    concepts: list[ConceptOut]
    edge_count: int


class PublicationUnit(BaseModel):
    unit_id: UUID
    title: str
    notes_current: int
    notes_published: int | None
    lab_current: int
    lab_published: int | None


class PublicationOut(BaseModel):
    published_at: datetime | None
    unpublished_changes: bool
    units: list[PublicationUnit]


PlanTopic = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class AssessmentItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
    weight_percent: Annotated[int, Field(ge=1, le=100, strict=True)]


class CourseProfileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    audience: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    weeks: Annotated[int, Field(ge=1, le=52, strict=True)]
    hours_per_week: Annotated[int, Field(ge=1, le=40, strict=True)]
    mode: Literal["theory", "theory_lab"] = "theory"
    lab_hours_per_week: Annotated[int, Field(ge=0, le=20, strict=True)] = 0
    experiments: Annotated[int, Field(ge=0, le=30, strict=True)] = 0
    must_include: list[PlanTopic] = Field(default_factory=list, max_length=30)
    exclude: list[PlanTopic] = Field(default_factory=list, max_length=30)
    assessment: list[AssessmentItem] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def consistent(self):
        if self.mode == "theory_lab":
            if not self.lab_hours_per_week or not self.experiments:
                raise ValueError("A course with a lab needs lab hours per week and experiments.")
        elif self.lab_hours_per_week or self.experiments:
            raise ValueError("Lab hours and experiments apply only to theory + lab courses.")

        def unique(items):
            seen, out = set(), []
            for item in items:
                if item.lower() not in seen:
                    seen.add(item.lower())
                    out.append(item)
            return out

        self.must_include, self.exclude = unique(self.must_include), unique(self.exclude)
        both = {t.lower() for t in self.must_include} & {t.lower() for t in self.exclude}
        if both:
            raise ValueError(
                f"Topics cannot be both required and excluded: {', '.join(sorted(both))}."
            )
        names = [a.name.lower() for a in self.assessment]
        if len(set(names)) != len(names):
            raise ValueError("Each assessment component needs a different name.")
        total = sum(a.weight_percent for a in self.assessment)
        if total != 100:
            raise ValueError(f"Assessment weights must add up to 100% (now {total}%).")
        return self


class CourseProfileOut(CourseProfileIn):
    model_config = ConfigDict(from_attributes=True)
    updated_at: datetime


class WizardIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Title
    subject: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    description: Description | None = None
    learner_level: Level = "introductory"
    lesson_duration_minutes: Annotated[int, Field(gt=0, le=1440, strict=True)] = 60
    profile: CourseProfileIn


class FindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    label: str
    query: str
    title: str
    url: str
    summary: str
    status: Literal["pending", "accepted", "ignored"]
    flagged: bool
    flag_reason: str | None
    created_at: datetime


class FindingPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["accepted", "ignored", "pending"]
