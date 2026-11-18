"""AI call accounting (ai_calls table) and per-user daily limits.

Every provider call ends in `record()` (app.ai.base), which hands a Usage to the provider's
`usage_sink`. The sink stores one row per call, attributed to whoever is "acting" in this
context: a request handler or a background job sets that with `ai_actor(...)`.
"""

import contextvars
import logging
import queue
import threading
from contextlib import contextmanager
from datetime import UTC, datetime, time
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy import func, select

from app.core.security import CurrentUser, Db
from app.models.entities import AICall, User

logger = logging.getLogger(__name__)
_actor: contextvars.ContextVar = contextvars.ContextVar(
    "boardom_ai_actor", default=(None, None, "full")
)


@contextmanager
def ai_actor(user_id=None, workspace_id=None, pipeline: str = "full"):
    token = _actor.set((user_id, workspace_id, pipeline))
    try:
        yield
    finally:
        _actor.reset(token)


class UsageRecorder:
    """Queue AI-call rows and write them from one background thread.

    The caller may be inside an open write transaction (a job indexing sources), and SQLite
    allows one writer: writing inline would wait for our own transaction. Queuing keeps the
    AI call fast; the row lands as soon as the database is free.
    """

    def __init__(self, session_factory):
        self.factory = session_factory
        self.queue: queue.Queue = queue.Queue()
        self.thread = threading.Thread(target=self._loop, name="ai-calls", daemon=True)
        self.thread.start()

    def __call__(self, usage) -> None:
        user_id, workspace_id, pipeline = _actor.get()
        self.queue.put(
            dict(
                user_id=user_id,
                workspace_id=workspace_id,
                purpose=usage.purpose[:50],
                model=usage.model[:100],
                pipeline=pipeline,
                input_tokens=usage.input_tokens,
                cached_tokens=usage.cached_tokens,
                output_tokens=usage.output_tokens,
                latency_ms=usage.latency_ms,
                cost_usd=usage.cost_usd,
            )
        )

    def _loop(self) -> None:
        while True:
            row = self.queue.get()
            try:
                if row is None:
                    return
                for attempt in range(3):
                    try:
                        with self.factory() as db:
                            db.add(AICall(**row))
                            db.commit()
                        break
                    except Exception:  # noqa: BLE001 - e.g. locked, or course just deleted
                        if attempt == 2:
                            logger.exception("Could not record an AI call")
                        row["workspace_id"] = row["workspace_id"] if attempt == 0 else None
            finally:
                self.queue.task_done()

    def flush(self) -> None:
        """Wait until every queued row is written (tests, reports)."""
        self.queue.join()

    def close(self) -> None:
        self.queue.put(None)
        self.thread.join(timeout=10)


def make_sink(session_factory) -> UsageRecorder:
    return UsageRecorder(session_factory)


def usage_today(db, user_id) -> tuple[int, float]:
    start = datetime.combine(datetime.now(UTC).date(), time.min, tzinfo=UTC)
    count, cost = db.execute(
        select(func.count(), func.coalesce(func.sum(AICall.cost_usd), 0.0)).where(
            AICall.user_id == user_id, AICall.created_at >= start
        )
    ).one()
    return count, float(cost)


def check_quota(db, user: User, settings) -> None:
    count, cost = usage_today(db, user.id)
    if count >= settings.daily_ai_calls_per_user:
        raise HTTPException(
            429,
            f"You have reached today's AI limit ({settings.daily_ai_calls_per_user} AI calls). "
            "It resets at midnight UTC.",
        )
    if settings.daily_ai_cost_usd_per_user and cost >= settings.daily_ai_cost_usd_per_user:
        raise HTTPException(
            429,
            f"You have reached today's AI budget (${settings.daily_ai_cost_usd_per_user:.2f}). "
            "It resets at midnight UTC.",
        )


def ai_quota(request: Request, db: Db, user: CurrentUser) -> User:
    check_quota(db, user, request.app.state.settings)
    return user


# Use on any route that starts AI work: the user, after their daily limit is checked.
AIQuota = Annotated[User, Depends(ai_quota)]
