import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol, TypeVar

from pydantic import BaseModel

logger = logging.getLogger("boardom.ai")
T = TypeVar("T", bound=BaseModel)


class AIError(Exception):
    """A failure safe to show users: never carries keys, prompts or raw provider bodies."""

    def __init__(self, code: str, message: str, status: int = 502):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


@dataclass
class Usage:
    purpose: str
    model: str
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    cost_usd: float | None = None


@dataclass
class TextResult:
    text: str
    usage: Usage


@dataclass
class WebSource:
    url: str
    title: str


@dataclass
class WebResult:
    text: str
    sources: list[WebSource]
    usage: Usage


@dataclass
class ModerationResult:
    flagged: bool
    categories: list[str] = field(default_factory=list)


class AIProvider(Protocol):
    name: str
    demo_mode: bool
    usage_sink: Callable[[Usage], None] | None

    def text(
        self,
        instructions: str,
        prompt: str,
        *,
        purpose: str,
        fast: bool = False,
        max_output_tokens: int | None = None,
    ) -> TextResult: ...

    def structured(
        self, instructions: str, prompt: str, schema: type[T], *, purpose: str, fast: bool = False
    ) -> tuple[T, Usage]: ...

    def embed(self, texts: list[str], *, purpose: str) -> list[list[float]]: ...

    def moderate(self, text: str) -> ModerationResult: ...

    def speech(self, text: str) -> bytes: ...

    def read_image(self, data: bytes, media_type: str) -> str: ...

    def web_search(
        self, query: str, *, purpose: str, allowed_domains: list[str] | None = None
    ) -> WebResult: ...


def price(prices: dict, usage: Usage) -> float | None:
    rates = prices.get(usage.model)
    if rates is None:
        return None
    rate_in, rate_cached, rate_out = rates
    fresh = max(usage.input_tokens - usage.cached_tokens, 0)
    return (
        fresh * rate_in + usage.cached_tokens * rate_cached + usage.output_tokens * rate_out
    ) / 1e6


def record(provider, usage: Usage) -> None:
    """Single exit point for call accounting; a later ai_calls table plugs in as the sink."""
    logger.info(
        "ai_call purpose=%s model=%s in=%d cached=%d out=%d ms=%d cost=%s",
        usage.purpose,
        usage.model,
        usage.input_tokens,
        usage.cached_tokens,
        usage.output_tokens,
        usage.latency_ms,
        usage.cost_usd,
    )
    if provider.usage_sink:
        provider.usage_sink(usage)
