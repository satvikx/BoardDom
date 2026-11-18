"""Background jobs for slow AI work (syllabus and notes generation).

Single process, one worker thread, like ExtractionWorker. Job rows are the source of truth;
a restart marks unfinished jobs as failed so the teacher can simply run them again.
"""

import logging
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.ai import AIError
from app.models.entities import Job, utcnow
from app.services.usage import ai_actor

logger = logging.getLogger(__name__)
ACTIVE = ("queued", "running")

# (db, job, report_progress) -> optional final message
JobFn = Callable[[Session, Job, Callable[[int, int], None]], str | None]


class JobFailed(Exception):
    """Expected failure with a message that is safe to show the teacher."""


class JobRunner:
    def __init__(self, session_factory):
        self.factory = session_factory
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="boardom-job")
        self.futures: dict[UUID, Future] = {}

    def recover(self) -> None:
        with self.factory() as db:
            db.execute(
                update(Job)
                .where(Job.status.in_(ACTIVE))
                .values(
                    status="failed",
                    message="The server restarted before this finished. Run it again.",
                    finished_at=utcnow(),
                )
            )
            db.commit()

    def close(self) -> None:
        self.pool.shutdown(wait=True, cancel_futures=True)

    def start(self, db: Session, workspace_id, kind: str, user_id, fn: JobFn) -> Job:
        """Create a queued job (one active job per course and kind) and schedule it."""
        busy = db.scalar(
            select(Job.id).where(
                Job.workspace_id == workspace_id, Job.kind == kind, Job.status.in_(ACTIVE)
            )
        )
        if busy:
            raise HTTPException(409, "This is already running. Wait for it to finish.")
        job = Job(workspace_id=workspace_id, kind=kind, created_by_user_id=user_id)
        db.add(job)
        db.commit()
        self.futures[job.id] = self.pool.submit(self._run, job.id, fn)
        return job

    def wait(self, job_id: UUID, timeout: float = 30) -> None:
        """For tests and CLIs: block until the job finished."""
        future = self.futures.get(job_id)
        if future:
            future.result(timeout=timeout)

    def _run(self, job_id: UUID, fn: JobFn) -> None:
        with self.factory() as db:
            job = db.get(Job, job_id)
            if job is None:
                return
            job.status = "running"
            db.commit()

            def report(done: int, total: int) -> None:
                job.progress, job.total = done, total
                db.commit()

            try:
                with ai_actor(job.created_by_user_id, job.workspace_id):
                    message = fn(db, job, report)
                job.status, job.message = "succeeded", message
            except (JobFailed, AIError) as exc:
                db.rollback()
                job.status = "failed"
                job.message = exc.message if isinstance(exc, AIError) else str(exc)
            except Exception:
                logger.exception("Job %s (%s) crashed", job_id, job.kind)
                db.rollback()
                job.status, job.message = "failed", "Something went wrong. Please retry."
            job.finished_at = utcnow()
            try:
                db.commit()
            except Exception:  # Course deleted while running: nothing left to update.
                logger.warning("Job %s finished after its course was removed", job_id)
            self.futures.pop(job_id, None)
