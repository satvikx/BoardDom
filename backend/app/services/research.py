"""Web research agent: plan searches, search trusted domains, screen, store findings.

The teacher accepts or ignores each finding; only accepted, unflagged findings reach the
syllabus generator, where they are cited as [W n]. Web text is screened for prompt injection
before it is stored; flagged findings are kept (for transparency) but cannot be accepted.
"""

import logging
from urllib.parse import urlsplit

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai import AIError
from app.models.entities import CourseProfile, Job, ResearchFinding, Workspace
from app.services.course_content import DATA_NOT_INSTRUCTIONS, course_header, profile_block
from app.services.guardrails import moderation_flags, screen_injection

logger = logging.getLogger(__name__)
MAX_QUERIES = 4


class ResearchPlan(BaseModel):
    queries: list[str]


PLAN_INSTRUCTIONS = (
    "You plan web research for a teacher building a course. Propose 2 to 4 short, specific "
    "search queries (a few words each) that would find authoritative teaching material, "
    "syllabi or recent developments for this course and its required topics. Return only the "
    f"queries. {DATA_NOT_INSTRUCTIONS}"
)


def trusted(url: str, domains: list[str]) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return bool(host) and any(host == d or host.endswith("." + d) for d in domains)


def research(provider, settings):
    def run(db: Session, job: Job, report) -> str:
        workspace = db.get(Workspace, job.workspace_id)
        profile = db.get(CourseProfile, workspace.id)
        domains = [d.lower().strip() for d in settings.trusted_domains if d.strip()]
        report(0, 1)
        prompt = "\n\n".join(p for p in (course_header(workspace), profile_block(profile)) if p)
        plan, _ = provider.structured(
            PLAN_INSTRUCTIONS, prompt, ResearchPlan, purpose="research_plan"
        )
        queries = list(dict.fromkeys(q.strip()[:200] for q in plan.queries if q.strip()))
        queries = queries[:MAX_QUERIES]
        if not queries:
            return "The AI proposed no searches. Try again."
        known = set(
            db.scalars(
                select(ResearchFinding.url).where(ResearchFinding.workspace_id == workspace.id)
            )
        )
        ordinal = (
            db.scalar(
                select(func.max(ResearchFinding.ordinal)).where(
                    ResearchFinding.workspace_id == workspace.id
                )
            )
            or 0
        )
        found = flagged = off_domain = 0
        report(0, len(queries))
        for done, query in enumerate(queries, start=1):
            try:
                result = provider.web_search(query, purpose="research", allowed_domains=domains)
            except AIError as exc:
                if done == 1:  # unavailable rather than one bad query: skip the whole step
                    return f"Web search is unavailable ({exc.message}) Research was skipped."
                logger.info("Research query failed: %s", exc.code)
                continue
            summary = result.text.strip()[:1500]
            for source in result.sources:
                if source.url in known:
                    continue
                if domains and not trusted(source.url, domains):
                    off_domain += 1
                    continue
                known.add(source.url)
                screen = screen_injection(f"{source.title}\n{summary}")
                if not screen.flagged and moderation_flags(provider, settings, summary):
                    screen.flagged, screen.reasons = True, ["flagged by the content filter"]
                ordinal += 1
                db.add(
                    ResearchFinding(
                        workspace_id=workspace.id,
                        ordinal=ordinal,
                        query=query,
                        title=(source.title or source.url)[:300],
                        url=source.url[:2000],
                        summary=summary,
                        status="ignored" if screen.flagged else "pending",
                        flagged=screen.flagged,
                        flag_reason=screen.reason[:300] or None,
                    )
                )
                found += 1
                flagged += screen.flagged
            db.commit()
            report(done, len(queries))
        parts = [f"Found {found} new finding(s) from {len(queries)} search(es)."]
        if flagged:
            parts.append(f"{flagged} looked like prompt injection and were set aside.")
        if off_domain:
            parts.append(f"{off_domain} result(s) outside the trusted domains were dropped.")
        if found - flagged:
            parts.append("Accept the useful ones; accepted findings are cited as [W n].")
        return " ".join(parts)

    return run
