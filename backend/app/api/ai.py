from fastapi import APIRouter, Request

from app.core.security import CurrentStaff
from app.schemas.ai import AIPingOut, AIStatusOut
from app.services.usage import AIQuota, ai_actor

# Teachers and admins only: students get 403, anonymous users 401.
router = APIRouter(prefix="/ai", tags=["AI"])


@router.get("/status", response_model=AIStatusOut)
def status(request: Request, user: CurrentStaff):
    settings, provider = request.app.state.settings, request.app.state.ai
    return AIStatusOut(
        provider=provider.name,
        demo_mode=provider.demo_mode,
        model_smart=settings.model_smart,
        model_fast=settings.model_fast,
        model_embedding=settings.model_embedding,
    )


@router.post("/ping", response_model=AIPingOut)
def ping(request: Request, user: CurrentStaff, quota: AIQuota):
    """One tiny real call on the fast model, to confirm key, model name and network work."""
    with ai_actor(user.id):
        result = request.app.state.ai.text(
            "Reply with the single word: ok",
            "ping",
            purpose="ping",
            fast=True,
            max_output_tokens=16,
        )
    usage = result.usage
    return AIPingOut(
        reply=result.text.strip(),
        model=usage.model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        latency_ms=usage.latency_ms,
        cost_usd=usage.cost_usd,
    )
