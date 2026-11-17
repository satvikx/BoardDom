import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.api import auth, content, documents, workspaces
from app.core.config import Settings
from app.db.session import build_engine, session_factory
from app.services.extraction import ExtractionWorker
from app.services.storage import FileStorage

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    engine = build_engine(settings.resolved_database_url)

    @asynccontextmanager
    async def lifespan(app):
        app.state.worker.recover()
        yield
        app.state.worker.close()
        engine.dispose()

    app = FastAPI(title="Boardom", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.session_factory = session_factory(engine)
    app.state.storage = FileStorage(settings.resolved_upload_dir, settings.max_upload_bytes)

    app.state.worker = ExtractionWorker(app.state.session_factory, app.state.storage, settings)

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
        # Only the non-sensitive upload limit needed by the file picker.
        return {"max_upload_bytes": settings.max_upload_bytes}

    for router in (auth.router, workspaces.router, documents.router, content.router):
        app.include_router(router, prefix="/api/v1")
    return app


app = create_app()
