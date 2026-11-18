"""`uv run python -m app.seed_demo [--reset]` - an offline demo course in about a minute.

Creates (once) a demo teacher, three students and a fully generated, published sample
course: wizard plan, sources, syllabus, unit notes, lab manuals, lesson plans, rubric,
concept graph and one study video. Always uses the offline demo AI provider, so it works
without an API key. Run `alembic upgrade head` first. --reset rebuilds the demo course.
"""

import io
import sys
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy import select

from app.ai.fake_provider import FakeProvider
from app.core.config import Settings
from app.core.security import password_hasher
from app.db.session import build_engine, session_factory
from app.models.entities import (
    CourseProfile,
    Enrollment,
    Job,
    SourceDocument,
    SourceUnit,
    Syllabus,
    User,
    Video,
    Workspace,
    utcnow,
)
from app.services import demo_ai
from app.services.accounts import delete_account, ensure_admin
from app.services.concepts import build_concepts
from app.services.course_content import generate_artifacts, generate_syllabus, syllabus_units
from app.services.publishing import publish
from app.services.storage import FileStorage
from app.services.usage import ai_actor, make_sink
from app.services.vector_index import ChromaIndex
from app.services.video import make_video

TEACHER = ("Demo Teacher", "demo.teacher@example.com", "DemoTeacher#2026")
STUDENTS = [
    ("Asha Rao", "asha@example.com"),
    ("Ben Okafor", "ben@example.com"),
    ("Chen Li", "chen@example.com"),
]
STUDENT_PASSWORD = "DemoStudent#2026"
SOURCES = {
    "Energy in plants.md": (
        "# Photosynthesis\n\nPlants turn light energy into chemical energy. Chlorophyll in the "
        "leaves absorbs light. Carbon dioxide and water become glucose and oxygen.\n\n"
        "# Leaf structure\n\nLeaves are thin and flat to absorb light. Stomata let carbon "
        "dioxide in and oxygen out. Guard cells open and close the stomata.\n"
    ),
    "Energy in cells.md": (
        "# Respiration\n\nCells release the energy stored in glucose. Aerobic respiration "
        "happens in the mitochondria and needs oxygen. Muscles respire faster during exercise."
        "\n\n# Enzymes\n\nEnzymes are proteins that speed up chemical reactions. Each enzyme has "
        "an active site that fits one substrate. High temperatures denature enzymes.\n"
    ),
    "Ecosystems.md": (
        "# Food chains\n\nEnergy flows from producers to consumers. About ninety percent of the "
        "energy is lost as heat at each step. A simple chain is grass, rabbit, fox.\n\n"
        "# Decomposers\n\nBacteria and fungi break down dead material. They return nutrients "
        "to the soil so plants can grow again.\n"
    ),
}
PLAN = dict(
    audience="Year 10 science students",
    weeks=6,
    hours_per_week=3,
    mode="theory_lab",
    lab_hours_per_week=2,
    experiments=4,
    must_include=["Enzymes"],
    exclude=["Genetics"],
    assessment=[
        {"name": "Quizzes", "weight_percent": 20},
        {"name": "Lab reports", "weight_percent": 30},
        {"name": "Final exam", "weight_percent": 50},
    ],
)


def step(label: str) -> None:
    print(f"  - {label}", flush=True)


def run_job(db, workspace, user, kind: str, fn) -> str:
    """Run a job body synchronously (same code the background runner uses)."""
    job = Job(workspace_id=workspace.id, kind=kind, created_by_user_id=user.id, status="running")
    db.add(job)
    db.commit()
    with ai_actor(user.id, workspace.id):
        message = fn(db, job, lambda done, total: None)
    job.status, job.message, job.finished_at = "succeeded", message, utcnow()
    db.commit()
    return message or ""


def account(db, name, email, password, role, creator=None) -> User:
    user = User(
        email=email,
        display_name=name,
        password_hash=password_hasher.hash(password),
        role=role,
        created_by_user_id=creator.id if creator else None,
        student_limit=5 if role == "teacher" else None,
    )
    db.add(user)
    db.flush()
    return user


def seed(reset: bool = False) -> int:
    settings = Settings()
    engine = build_engine(settings.resolved_database_url)
    factory = session_factory(engine, ChromaIndex(settings.resolved_chroma_dir))
    storage = FileStorage(settings.resolved_upload_dir, settings.max_upload_bytes)
    provider = FakeProvider(demo_mode=True)  # offline on purpose, even if a key is set
    demo_ai.install(provider)
    provider.usage_sink = make_sink(factory)
    ensure_admin(factory, settings)
    with factory() as db:
        existing = db.scalar(select(User).where(User.email == TEACHER[1]))
        if existing and not reset:
            print("The demo is already seeded (use --reset to rebuild it).")
            credentials()
            return 0
        if existing:
            print("Removing the previous demo teacher, course and students...")
            delete_account(db, storage, existing, settings)
        print("Seeding the offline demo...")
        teacher = account(
            db, *TEACHER, "teacher", db.scalar(select(User).where(User.role == "admin"))
        )
        students = [account(db, n, e, STUDENT_PASSWORD, "student", teacher) for n, e in STUDENTS]
        workspace = Workspace(
            owner_id=teacher.id,
            title="Energy in Living Things",
            subject="Biology",
            description="How living things capture, release and pass on energy.",
            learner_level="intermediate",
            lesson_duration_minutes=50,
            has_lab=True,
        )
        db.add(workspace)
        db.flush()
        db.add(CourseProfile(workspace_id=workspace.id, **PLAN))
        db.commit()
        step("teacher, 3 students, course with a 6-week theory + lab plan")

        for name, text in SOURCES.items():
            key, filename, media_type, size = storage.save(
                UploadFile(file=io.BytesIO(text.encode()), filename=name)
            )
            doc = SourceDocument(
                workspace_id=workspace.id,
                original_filename=filename,
                storage_key=key,
                media_type=media_type,
                size_bytes=size,
                extraction_status="extracted",
                content_revision=1,
                extracted_at=utcnow(),
            )
            db.add(doc)
            db.flush()
            db.add(
                SourceUnit(
                    document_id=doc.id,
                    position=0,
                    page_number=None,
                    label="Document",
                    original_text=text,
                )
            )
        db.commit()
        step(f"{len(SOURCES)} source documents")

        step(run_job(db, workspace, teacher, "syllabus", generate_syllabus(provider)))
        syllabus = db.scalar(select(Syllabus).where(Syllabus.workspace_id == workspace.id))
        syllabus.status, syllabus.approved_at = "approved", utcnow()
        syllabus.revision += 1
        db.commit()
        step("syllabus approved")
        for kind, job in (
            ("unit_notes", "notes"),
            ("lab_manual", "lab_manual"),
            ("lesson_plan", "lesson_plan"),
            ("rubric", "rubric"),
        ):
            step(
                run_job(
                    db,
                    workspace,
                    teacher,
                    job,
                    generate_artifacts(provider, kind, None, teacher.id),
                )
            )
        step(run_job(db, workspace, teacher, "concepts", build_concepts(provider)))
        publish(db, workspace)
        for student in students:
            db.add(Enrollment(workspace_id=workspace.id, student_id=student.id))
        db.commit()
        step("published and all students enrolled")

        unit = syllabus_units(db, syllabus.id)[0]
        from app.services.student_tools import published as published_notes

        video = Video(
            id=uuid4(),
            workspace_id=workspace.id,
            unit_id=unit.id,
            notes_version=published_notes(db, workspace.id, unit.id).number,
        )
        db.add(video)
        db.commit()
        step(run_job(db, workspace, students[0], "video", make_video(provider, settings, video.id)))
    provider.usage_sink.flush()
    provider.usage_sink.close()
    engine.dispose()
    print("Done.")
    credentials()
    return 0


def credentials() -> None:
    print(f"\nTeacher:  {TEACHER[1]} / {TEACHER[2]}")
    print("Students: " + ", ".join(e for _, e in STUDENTS) + f" / {STUDENT_PASSWORD}")
    print("Open http://localhost:3000 and log in.")


if __name__ == "__main__":
    raise SystemExit(seed(reset="--reset" in sys.argv))
