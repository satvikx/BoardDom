"""Guardrails: prompt-injection screening, moderation, and PII scrubbing for logs.

The injection screen is a fast, offline pattern check. It flags text that tries to address
the AI model itself ("ignore previous instructions", fake system messages, requests to reveal
prompts or keys). It is deliberately conservative: flagged source passages are kept for the
teacher to review but never sent to a model.
"""

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

INJECTION_PATTERNS = [
    (
        r"\b(ignore|disregard|forget|override|bypass)\b[^.\n]{0,40}\b(previous|prior|above|"
        r"earlier|all|any|your|the)\b[^.\n]{0,30}\b(instructions?|prompts?|rules|directions|"
        r"guidelines)",
        "asks the AI to ignore its instructions",
    ),
    (r"\b(system|developer)\s+(prompt|message|instructions?)\b", "mentions a system prompt"),
    (r"\byou are now (a|an|the|in|no longer)\b", "tries to change the AI's role"),
    (
        r"\b(reveal|print|show|repeat|leak|output)\b[^.\n]{0,30}\b(system prompt|your "
        r"instructions|api[ _-]?key|secret|password)",
        "asks the AI to reveal secrets",
    ),
    (r"<\s*/?\s*(system|assistant|instructions?)\s*>", "contains fake role tags"),
    (r"(?m)^\s*(system|assistant)\s*:", "contains a fake system/assistant message"),
    (
        r"\bdo not (follow|obey)\b[^.\n]{0,30}\b(rules|instructions|guidelines)",
        "asks the AI to break its rules",
    ),
    (r"\b(jailbreak|dan mode|developer mode)\b", "contains a jailbreak phrase"),
    (r"\bnew instructions?\s*:", "contains new instructions for the AI"),
    (r"\bbegin (system|prompt|instructions)\b", "contains an instruction block"),
]
COMPILED = [(re.compile(p, re.IGNORECASE), reason) for p, reason in INJECTION_PATTERNS]


@dataclass
class Screen:
    flagged: bool
    reasons: list[str] = field(default_factory=list)

    @property
    def reason(self) -> str:
        return "Possible prompt injection: " + "; ".join(self.reasons) if self.reasons else ""


def screen_injection(text: str) -> Screen:
    reasons = [reason for pattern, reason in COMPILED if pattern.search(text or "")]
    return Screen(bool(reasons), list(dict.fromkeys(reasons)))


# ---- moderation -----------------------------------------------------------------------------

MODERATION_CHARS = 8000  # per provider call


class ModerationRejected(Exception):
    def __init__(self, categories: list[str]):
        self.categories = categories
        shown = ", ".join(c.replace("_", " ").replace("/", " / ") for c in categories[:3])
        super().__init__(
            "This text was flagged by the content filter"
            + (f" ({shown})" if shown else "")
            + ". Please rephrase it."
        )


def moderation_flags(provider, settings, text: str) -> list[str] | None:
    """Categories if flagged, [] if clean, None if the check could not run (fail open)."""
    from app.ai import AIError

    text = (text or "").strip()
    if not text:
        return []
    try:
        result = provider.moderate(text[:MODERATION_CHARS])
    except AIError as exc:
        if getattr(settings, "moderation_required", False):
            raise ModerationRejected([]) from exc
        logger.warning("Moderation unavailable (%s); allowing text", exc.code)
        return None
    return (result.categories or ["flagged"]) if result.flagged else []


def check_text(provider, settings, *texts) -> None:
    """Reject user text that the moderation model flags (raises ModerationRejected)."""
    joined = "\n".join(t for t in texts if t)
    for start in range(0, len(joined), MODERATION_CHARS):
        flags = moderation_flags(provider, settings, joined[start : start + MODERATION_CHARS])
        if flags:
            raise ModerationRejected(flags)


# ---- PII scrubbing for logs -----------------------------------------------------------------

PII_PATTERNS = [
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[email]"),
    (re.compile(r"\b(sk|pk|rk)-[A-Za-z0-9_-]{8,}"), "[key]"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"), "Bearer [token]"),
    (re.compile(r"\b\d(?:[ -]?\d){12,18}\b"), "[number]"),
    (re.compile(r"(?<!\w)\+?\d[\d ()-]{7,}\d(?!\w)"), "[phone]"),
]


def scrub(text: str) -> str:
    for pattern, replacement in PII_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def install_log_scrubber() -> None:
    """Scrub PII from every log record's final message, whichever handler formats it."""
    current = logging.getLogRecordFactory()
    if getattr(current, "boardom_scrubber", False):
        return

    def factory(*args, **kwargs):
        record = current(*args, **kwargs)
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - leave malformed records to logging itself
            return record
        cleaned = scrub(message)
        if cleaned != message:
            record.msg, record.args = cleaned, None
        return record

    factory.boardom_scrubber = True
    logging.setLogRecordFactory(factory)
