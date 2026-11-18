import hashlib
import math
import re

from app.ai.base import (
    AIError,
    ModerationResult,
    TextResult,
    Usage,
    WebResult,
    WebSource,
    record,
)

DIMENSIONS = 1024  # few collisions for course-sized vocabularies
TOKEN = re.compile(r"[a-z0-9]+")
STOPWORDS = frozenset(
    "a an and are as at be been but by can do does for from has have how i in into is it its "
    "know me my need no not of on or so than that the their them then there these they this "
    "to was we what when where which while who why will with you your about also each else "
    "more most other some such very".split()
)


class FakeProvider:
    """Deterministic, offline stand-in: used by tests and by demo mode without an API key."""

    name = "fake"
    embedding_id = f"fake-bow-{DIMENSIONS}"

    def __init__(self, demo_mode: bool = False):
        self.demo_mode = demo_mode
        self.usage_sink = None
        self.structured_responses: dict[str, object] = {}  # schema name -> instance or dict
        # schema name -> fn(instructions, prompt) -> instance or dict (demo-mode generators)
        self.structured_builders: dict[str, object] = {}
        self.moderation_marker = "[flag]"

    def _usage(self, purpose, fast, size):
        usage = Usage(
            purpose,
            "fake-fast" if fast else "fake-smart",
            input_tokens=size,
            output_tokens=size // 2,
            cost_usd=0.0,
        )
        record(self, usage)
        return usage

    def text(self, instructions, prompt, *, purpose, fast=False, max_output_tokens=None):
        return TextResult(f"[demo] {prompt[:80]}", self._usage(purpose, fast, len(prompt)))

    def structured(self, instructions, prompt, schema, *, purpose, fast=False):
        canned = self.structured_responses.get(schema.__name__)
        builder = self.structured_builders.get(schema.__name__)
        if canned is None and builder is not None:
            canned = builder(instructions, prompt)
        if canned is None:
            raise AIError("fake_unconfigured", f"No fake response set for {schema.__name__}.", 500)
        parsed = canned if isinstance(canned, schema) else schema.model_validate(canned)
        return parsed, self._usage(purpose, fast, len(prompt))

    def embed(self, texts, *, purpose):
        record(self, Usage(purpose, "fake-embedding", input_tokens=sum(len(t) for t in texts)))
        return [self._vector(t) for t in texts]

    @staticmethod
    def _vector(text):
        """Bag-of-words hashing: shared words -> higher cosine, so offline search is topical."""
        values = [0.0] * DIMENSIONS
        words = [w for w in TOKEN.findall(text.lower()) if len(w) > 1 and w not in STOPWORDS]
        for word in words or [text.lower().strip() or "empty"]:
            stem = word[:-1] if len(word) > 4 and word.endswith("s") else word
            bucket = int.from_bytes(hashlib.sha256(stem.encode()).digest()[:4], "big")
            values[bucket % DIMENSIONS] += 1.0
        norm = math.sqrt(sum(v * v for v in values)) or 1.0
        return [v / norm for v in values]

    def read_image(self, data, media_type):
        """No offline text recognition: images and scanned PDFs wait for a real provider."""
        raise AIError(
            "ocr_unavailable",
            "Reading text from images needs the AI service (set BOARDOM_OPENAI_API_KEY).",
            503,
        )

    def speech(self, text):
        """No offline voice: callers fall back to silent videos with captions."""
        raise AIError("tts_unavailable", "Narration is not available in demo mode.", 503)

    def moderate(self, text):
        flagged = self.moderation_marker in text
        return ModerationResult(flagged, ["fake"] if flagged else [])

    def web_search(self, query, *, purpose, allowed_domains=None):
        if self.demo_mode:
            raise AIError("web_unavailable", "web search is not available in demo mode.", 503)
        domain = (allowed_domains or ["example.com"])[0]
        source = WebSource(f"https://{domain}/demo", "Demo source")
        return WebResult(
            f"[demo] results for {query[:60]}", [source], self._usage(purpose, False, len(query))
        )
