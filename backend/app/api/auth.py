from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.security import (
    COOKIE_NAME,
    DUMMY_HASH,
    CurrentUser,
    Db,
    create_session,
    password_hasher,
    token_digest,
    verify_password,
)
from app.models.entities import SessionToken, User
from app.schemas.api import Credentials, Register, UserOut

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=UserOut, status_code=201)
def register(data: Register, request: Request, response: Response, db: Db):
    user = User(
        email=str(data.email),
        display_name=data.display_name,
        password_hash=password_hasher.hash(data.password),
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "An account with this email already exists.") from None
    create_session(db, user, request, response)
    return user


@router.post("/login", response_model=UserOut)
def login(data: Credentials, request: Request, response: Response, db: Db):
    user = db.scalar(select(User).where(User.email == str(data.email)))
    valid = verify_password(user.password_hash if user else DUMMY_HASH, data.password)
    if not user or not valid:
        raise HTTPException(401, "Invalid email or password.")
    if password_hasher.check_needs_rehash(user.password_hash):
        user.password_hash = password_hasher.hash(data.password)
    create_session(db, user, request, response)
    return user


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser):
    return user


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Db):
    token = request.cookies.get(COOKIE_NAME)
    if token:
        session = db.scalar(
            select(SessionToken).where(SessionToken.token_hash == token_digest(token))
        )
        if session:
            db.delete(session)
            db.commit()
    response.delete_cookie(
        COOKIE_NAME,
        path="/",
        httponly=True,
        secure=request.app.state.settings.cookie_secure,
        samesite="lax",
    )
