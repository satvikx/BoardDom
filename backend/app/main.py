import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.ai import AIError, build_provider
from app.api import (
    admin,
    ai,
    auth,
    content,
    course_content,
    documents,
    enrollments,
    student,
    teacher,
    workspaces,
)
from app.core.config import Settings
from app.core.ratelimit import FailureLimiter
from app.db.session import build_engine, session_factory
from app.services import demo_ai
from app.services.accounts import ensure_admin
from app.services.extraction import ExtractionWorker
from app.services.guardrails import ModerationRejected, install_log_scrubber
from app.services.jobs import JobRunner
from app.services.storage import FileStorage
from app.services.usage import make_sink
from app.services.vector_index import ChromaIndex

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    install_log_scrubber()
    engine = build_engine(settings.resolved_database_url)

    @asynccontextmanager
    async def lifespan(app):
        ensure_admin(app.state.session_factory, settings)
        app.state.worker.recover()
        app.state.jobs.recover()
        yield
        app.state.jobs.close()
        app.state.usage.close()
        app.state.worker.close()
        engine.dispose()

    app = FastAPI(title="Boardom", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.vector_index = ChromaIndex(settings.resolved_chroma_dir)
    app.state.session_factory = session_factory(engine, app.state.vector_index)
    app.state.storage = FileStorage(settings.resolved_upload_dir, settings.max_upload_bytes)
    # Real provider with a key; offline FakeProvider (demo mode) without one.
    app.state.ai = build_provider(settings)
    demo_ai.install(app.state.ai)  # No-op for the real provider.
    app.state.usage = make_sink(app.state.session_factory)
    app.state.ai.usage_sink = app.state.usage
    app.state.jobs = JobRunner(app.state.session_factory)

    app.state.worker = ExtractionWorker(
        app.state.session_factory, app.state.storage, settings, app.state.ai
    )
    # 5 failures per email in 15 minutes locks that email's logins for 15 minutes.
    app.state.login_limiter = FailureLimiter(5, window_seconds=900, lockout_seconds=900)
    # 5 wrong PINs (any email) lock every PIN reset for 15 minutes.
    app.state.pin_limiter = FailureLimiter(5, window_seconds=900, lockout_seconds=900)

    @app.middleware("http")
    async def browser_security(request: Request, call_next):
        if request.method in {"POST", "PATCH", "PUT", "DELETE"}:
            if request.headers.get("origin") != settings.frontend_origin:
                return JSONResponse(
                    status_code=403, content={"detail": "Untrusted request origin."}
                )
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        messages = [f"{'.'.join(str(p) for p in e['loc'][1:])}: {e['msg']}" for e in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": "; ".join(messages)})

    @app.exception_handler(ModerationRejected)
    async def moderation_rejected(request: Request, exc: ModerationRejected):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(AIError)
    async def ai_error(request: Request, exc: AIError):
        logger.error("AI call failed: %s", exc.code)
        return JSONResponse(status_code=exc.status, content={"detail": exc.message})

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, exc: SQLAlchemyError):
        logger.error("Database operation failed: %s", type(exc).__name__)
        return JSONResponse(
            status_code=503, content={"detail": "Database unavailable. Please retry."}
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        logger.error("Unexpected request error: %s", type(exc).__name__)
        return JSONResponse(
            status_code=500, content={"detail": "Something went wrong. Please retry."}
        )

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/v1/config")
    def public_config():
        # Only non-sensitive values the UI needs (file picker limit, Register link).
        return {
            "max_upload_bytes": settings.max_upload_bytes,
            "allow_public_signup": settings.allow_public_signup,
        }

    for router in (
        auth.router,
        workspaces.router,
        documents.router,
        content.router,
        enrollments.router,
        admin.router,
        teacher.router,
        student.router,
        ai.router,
        course_content.router,
    ):
        app.include_router(router, prefix="/api/v1")
    return app


app = create_app()
