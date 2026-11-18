import logging
import secrets

from fastapi import HTTPException
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import password_hasher
from app.models.entities import SourceDocument, User, Workspace

logger = logging.getLogger(__name__)
# No look-alike characters (0/o, 1/l/i) so the password can be read aloud or retyped.
TEMP_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


def temporary_password() -> str:
    """Readable random password, e.g. 'k7mq-x2fp-9tha' (about 59 bits of entropy)."""
    return "-".join("".join(secrets.choice(TEMP_ALPHABET) for _ in range(4)) for _ in range(3))


def ensure_admin(session_factory, settings: Settings) -> None:
    """Create the configured admin once. Never touches an existing account's password."""
    with session_factory() as db:
        existing = db.scalar(select(User).where(User.email == settings.admin_email))
        if existing is not None:
            if existing.role != "admin":
                logger.warning("Configured admin email belongs to a non-admin account.")
            return
        db.add(
            User(
                email=settings.admin_email,
                display_name="Administrator",
                password_hash=password_hasher.hash(settings.admin_password),
                role="admin",
            )
        )
        try:
            db.commit()
        except IntegrityError:  # Another process seeded it first.
            db.rollback()


def effective_student_limit(teacher: User, settings: Settings) -> int:
    if teacher.student_limit is not None:
        return teacher.student_limit
    return settings.default_student_limit


def student_count(db: Session, teacher_id) -> int:
    return db.scalar(
        select(func.count())
        .select_from(User)
        .where(User.created_by_user_id == teacher_id, User.role == "student")
    )


def lock_teacher(db: Session, teacher_id) -> None:
    """Take the write lock (SQLite) / row lock before counting students.

    A no-op UPDATE starts the write transaction so two concurrent creations cannot
    both see room under the limit.
    """
    db.execute(update(User).where(User.id == teacher_id).values(student_limit=User.student_limit))


def delete_account(db: Session, storage, user: User, settings=None) -> None:
    """Delete a teacher (with courses, files, students) or a student (with enrollments).

    Sessions and enrollments go by ON DELETE CASCADE. Files use the same staged
    deletion as workspace deletion, so a storage failure leaves everything intact.
    """
    if user.role == "admin":
        raise HTTPException(403, "Administrator accounts cannot be deleted.")
    documents = []
    if user.role == "teacher":
        documents = db.scalars(
            select(SourceDocument)
            .join(Workspace, SourceDocument.workspace_id == Workspace.id)
            .where(Workspace.owner_id == user.id)
        ).all()

    def delete_metadata():
        if user.role == "teacher":
            db.execute(
                delete(User).where(User.created_by_user_id == user.id, User.role == "student")
            )
        db.execute(delete(User).where(User.id == user.id))

    from app.services.video import remove_video_files, video_keys

    owned = db.scalars(select(Workspace.id).where(Workspace.owner_id == user.id)).all()
    videos = video_keys(db, owned) if user.role == "teacher" else []
    storage.delete_records(db, documents, delete_metadata)
    if videos and settings is not None:
        remove_video_files(settings, videos)
    index = db.info.get("vector_index")
    if index is not None and owned:
        index.delete_workspaces(owned)
