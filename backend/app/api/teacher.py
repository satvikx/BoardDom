from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.security import CurrentTeacher, Db, password_hasher
from app.models.entities import Enrollment, User
from app.schemas.api import CreatedStudentOut, NewAccount, StudentListOut, StudentOut
from app.services.accounts import (
    delete_account,
    effective_student_limit,
    lock_teacher,
    student_count,
    temporary_password,
)
from app.services.guardrails import check_text

router = APIRouter(prefix="/teacher", tags=["Teacher: students"])


def owned_student(db, student_id: UUID, teacher_id: UUID) -> User:
    student = db.scalar(
        select(User).where(
            User.id == student_id, User.role == "student", User.created_by_user_id == teacher_id
        )
    )
    if student is None:
        raise HTTPException(404, "Student not found.")
    return student


def student_rows(db, students: list[User]) -> list[StudentOut]:
    ids = [s.id for s in students]
    courses = (
        dict(
            db.execute(
                select(Enrollment.student_id, func.count())
                .where(Enrollment.student_id.in_(ids))
                .group_by(Enrollment.student_id)
            ).all()
        )
        if ids
        else {}
    )
    return [
        StudentOut(
            id=s.id,
            email=s.email,
            display_name=s.display_name,
            created_at=s.created_at,
            last_login_at=s.last_login_at,
            must_change_password=s.must_change_password,
            course_count=courses.get(s.id, 0),
        )
        for s in students
    ]


@router.get("/students", response_model=StudentListOut)
def list_students(request: Request, db: Db, teacher: CurrentTeacher):
    students = db.scalars(
        select(User)
        .where(User.created_by_user_id == teacher.id, User.role == "student")
        .order_by(User.display_name, User.email)
    ).all()
    return StudentListOut(
        students=student_rows(db, students),
        used=len(students),
        limit=effective_student_limit(teacher, request.app.state.settings),
    )


@router.post("/students", response_model=CreatedStudentOut, status_code=201)
def create_student(data: NewAccount, request: Request, db: Db, teacher: CurrentTeacher):
    check_text(request.app.state.ai, request.app.state.settings, data.display_name)
    # Check and insert in one write transaction so concurrent requests cannot exceed the limit.
    lock_teacher(db, teacher.id)
    db.refresh(teacher)
    limit = effective_student_limit(teacher, request.app.state.settings)
    used = student_count(db, teacher.id)
    if used >= limit:
        db.rollback()
        raise HTTPException(
            409, f"Student limit reached ({used} of {limit}). Ask the admin to raise it."
        )
    password = temporary_password()
    student = User(
        email=str(data.email),
        display_name=data.display_name,
        password_hash=password_hasher.hash(password),
        role="student",
        created_by_user_id=teacher.id,
        must_change_password=True,
    )
    db.add(student)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "An account with this email already exists.") from None
    [row] = student_rows(db, [student])
    return CreatedStudentOut(student=row, temporary_password=password, used=used + 1, limit=limit)


@router.delete("/students/{student_id}", status_code=204)
def delete_student(student_id: UUID, request: Request, db: Db, teacher: CurrentTeacher):
    student = owned_student(db, student_id, teacher.id)
    delete_account(db, request.app.state.storage, student)
    return Response(status_code=204)
