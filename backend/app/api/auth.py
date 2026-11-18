import hmac

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.core.ratelimit import minutes_text
from app.core.security import (
    COOKIE_NAME,
    DUMMY_HASH,
    AuthenticatedUser,
    Db,
    create_session,
    password_hasher,
    token_digest,
    verify_password,
)
from app.models.entities import SessionToken, User, utcnow
from app.schemas.api import AdminPasswordReset, ChangePassword, Credentials, Register, UserOut

router = APIRouter(prefix="/auth", tags=["Authentication"])
PIN_RESET_KEY = "admin-pin-reset"  # Global: every PIN attempt counts toward one lockout.
PIN_RESET_ERROR = "Invalid PIN or account."


def too_many(seconds: int, what: str) -> HTTPException:
    return HTTPException(
        429,
        f"Too many {what}. Try again in {minutes_text(seconds)}.",
        headers={"Retry-After": str(seconds)},
    )


@router.post("/register", response_model=UserOut, status_code=201)
def register(data: Register, request: Request, response: Response, db: Db):
    if not request.app.state.settings.allow_public_signup:
        raise HTTPException(403, "Public sign-up is turned off. Ask an administrator for access.")
    user = User(
        email=str(data.email),
        display_name=data.display_name,
        password_hash=password_hasher.hash(data.password),
        role="teacher",
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "An account with this email already exists.") from None
    user.last_login_at = utcnow()
    create_session(db, user, request, response)
    return user


@router.post("/login", response_model=UserOut)
def login(data: Credentials, request: Request, response: Response, db: Db):
    limiter = request.app.state.login_limiter
    key = str(data.email)  # Already trimmed and lowercased; never the (proxied) client IP.
    if wait := limiter.retry_after(key):
        raise too_many(wait, "failed login attempts for this account")
    user = db.scalar(select(User).where(User.email == key))
    valid = verify_password(user.password_hash if user else DUMMY_HASH, data.password)
    if not user or not valid:
        if wait := limiter.record_failure(key):
            raise too_many(wait, "failed login attempts for this account")
        raise HTTPException(401, "Invalid email or password.")
    limiter.reset(key)
    if password_hasher.check_needs_rehash(user.password_hash):
        user.password_hash = password_hasher.hash(data.password)
    user.last_login_at = utcnow()
    create_session(db, user, request, response)
    return user


@router.get("/me", response_model=UserOut)
def me(user: AuthenticatedUser):
    return user


@router.post("/change-password", response_model=UserOut)
def change_password(data: ChangePassword, request: Request, db: Db, user: AuthenticatedUser):
    limiter = request.app.state.login_limiter
    if wait := limiter.retry_after(user.email):
        raise too_many(wait, "failed password attempts for this account")
    if not verify_password(user.password_hash, data.current_password):
        if wait := limiter.record_failure(user.email):
            raise too_many(wait, "failed password attempts for this account")
        raise HTTPException(400, "Your current password is incorrect.")
    if data.new_password == data.current_password:
        raise HTTPException(422, "Choose a new password that differs from the current one.")
    user.password_hash = password_hasher.hash(data.new_password)
    user.must_change_password = False
    # Sign out every other browser; keep this one.
    current = token_digest(request.cookies.get(COOKIE_NAME, ""))
    db.execute(
        delete(SessionToken).where(
            SessionToken.user_id == user.id, SessionToken.token_hash != current
        )
    )
    db.commit()
    return user


@router.post("/admin/reset-password")
def admin_reset_password(data: AdminPasswordReset, request: Request, db: Db):
    """Reset the admin password with the configured PIN. The PIN is never exposed or editable."""
    settings = request.app.state.settings
    limiter = request.app.state.pin_limiter
    if wait := limiter.retry_after(PIN_RESET_KEY):
        raise too_many(wait, "PIN attempts. PIN reset is locked")
    # Same work for every failure: one lookup and one constant-time comparison.
    user = db.scalar(select(User).where(User.email == str(data.email)))
    pin_ok = hmac.compare_digest(data.pin.encode(), settings.admin_reset_pin.encode())
    if not (pin_ok and user is not None and user.role == "admin"):
        if wait := limiter.record_failure(PIN_RESET_KEY):
            raise too_many(wait, "PIN attempts. PIN reset is locked")
        raise HTTPException(400, PIN_RESET_ERROR)
    limiter.reset(PIN_RESET_KEY)
    request.app.state.login_limiter.reset(user.email)
    user.password_hash = password_hasher.hash(data.new_password)
    user.must_change_password = False
    db.execute(delete(SessionToken).where(SessionToken.user_id == user.id))
    db.commit()
    return {"detail": "Password updated. Log in with your new password."}


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
