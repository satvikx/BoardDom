import hashlib
import secrets
from datetime import timedelta
from typing import Annotated

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.entities import SessionToken, User, utcnow

COOKIE_NAME = "boardom_session"
password_hasher = PasswordHasher()
DUMMY_HASH = password_hasher.hash(secrets.token_urlsafe(32))
Db = Annotated[Session, Depends(get_db)]


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def verify_password(encoded: str, password: str) -> bool:
    try:
        return password_hasher.verify(encoded, password)
    except (VerificationError, InvalidHashError):
        return False


def create_session(db: Session, user: User, request: Request, response: Response) -> None:
    settings = request.app.state.settings
    # Rotate the current browser's session on successful authentication.
    old = request.cookies.get(COOKIE_NAME)
    if old:
        previous = db.scalar(
            select(SessionToken).where(SessionToken.token_hash == token_digest(old))
        )
        if previous:
            db.delete(previous)
    token = secrets.token_urlsafe(32)
    expires = utcnow() + timedelta(seconds=settings.session_lifetime_seconds)
    db.add(SessionToken(user_id=user.id, token_hash=token_digest(token), expires_at=expires))
    db.commit()
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
        max_age=settings.session_lifetime_seconds,
        expires=expires,
    )


def authenticated_user(request: Request, db: Db) -> User:
    """Any signed-in user, including one who still has to change a temporary password."""
    token = request.cookies.get(COOKIE_NAME)
    session = (
        db.scalar(
            select(SessionToken).where(
                SessionToken.token_hash == token_digest(token), SessionToken.expires_at > utcnow()
            )
        )
        if token
        else None
    )
    user = db.get(User, session.user_id) if session else None
    if user is None:
        raise HTTPException(401, "Your session has expired. Please log in.")
    return user


AuthenticatedUser = Annotated[User, Depends(authenticated_user)]


def current_user(user: AuthenticatedUser) -> User:
    if user.must_change_password:
        raise HTTPException(403, "Change your temporary password before continuing.")
    return user


CurrentUser = Annotated[User, Depends(current_user)]

ROLE_AREAS = {"admin": "administrators", "teacher": "teachers", "student": "students"}


def require_role(*roles: str):
    areas = " and ".join(ROLE_AREAS[r] for r in roles)

    def dependency(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(403, f"Not allowed: this area is only for {areas}.")
        return user

    return dependency


CurrentAdmin = Annotated[User, Depends(require_role("admin"))]
CurrentTeacher = Annotated[User, Depends(require_role("teacher"))]
CurrentStudent = Annotated[User, Depends(require_role("student"))]
CurrentStaff = Annotated[User, Depends(require_role("teacher", "admin"))]
