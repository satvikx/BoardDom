from uuid import UUID

from fastapi import APIRouter, Response
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.api.teacher import owned_student
from app.api.workspaces import owned_workspace
from app.core.security import CurrentTeacher, Db
from app.models.entities import Enrollment, User
from app.schemas.api import EnrollmentOut

router = APIRouter(prefix="/workspaces/{workspace_id}/enrollments", tags=["Enrollments"])


@router.get("", response_model=list[EnrollmentOut])
def list_enrollments(workspace_id: UUID, db: Db, teacher: CurrentTeacher):
    workspace = owned_workspace(db, workspace_id, teacher.id)
    rows = db.execute(
        select(User, Enrollment.created_at)
        .join(Enrollment, Enrollment.student_id == User.id)
        .where(Enrollment.workspace_id == workspace.id)
        .order_by(User.display_name, User.email)
    ).all()
    return [
        EnrollmentOut(student_id=u.id, display_name=u.display_name, email=u.email, enrolled_at=at)
        for u, at in rows
    ]


@router.put("/{student_id}", status_code=204)
def enroll(workspace_id: UUID, student_id: UUID, db: Db, teacher: CurrentTeacher):
    workspace = owned_workspace(db, workspace_id, teacher.id)
    student = owned_student(db, student_id, teacher.id)
    exists = db.scalar(
        select(Enrollment.id).where(
            Enrollment.workspace_id == workspace.id, Enrollment.student_id == student.id
        )
    )
    if exists is None:
        db.add(Enrollment(workspace_id=workspace.id, student_id=student.id))
        try:
            db.commit()
        except IntegrityError:  # Concurrent identical PUT: already enrolled.
            db.rollback()
    return Response(status_code=204)


@router.delete("/{student_id}", status_code=204)
def unenroll(workspace_id: UUID, student_id: UUID, db: Db, teacher: CurrentTeacher):
    workspace = owned_workspace(db, workspace_id, teacher.id)
    student = owned_student(db, student_id, teacher.id)
    db.execute(
        delete(Enrollment).where(
            Enrollment.workspace_id == workspace.id, Enrollment.student_id == student.id
        )
    )
    db.commit()
    return Response(status_code=204)
