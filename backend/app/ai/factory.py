import logging

from app.ai.fake_provider import FakeProvider
from app.ai.openai_provider import OpenAIProvider
from app.core.config import Settings

logger = logging.getLogger("boardom.ai")


def build_provider(settings: Settings):
    if settings.ai_provider == "fake":
        return FakeProvider(demo_mode=False)
    if settings.openai_api_key is None:
        if settings.environment == "production":
            raise RuntimeError("BOARDOM_OPENAI_API_KEY is required in production.")
        logger.warning("No BOARDOM_OPENAI_API_KEY: running AI features in offline demo mode.")
        return FakeProvider(demo_mode=True)
    if settings.environment == "production" and not settings.ai_verify_tls:
        raise RuntimeError("BOARDOM_AI_VERIFY_TLS=false is not allowed in production.")
    return OpenAIProvider(settings)
