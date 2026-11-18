from pydantic import BaseModel


class AIStatusOut(BaseModel):
    provider: str
    demo_mode: bool
    model_smart: str
    model_fast: str
    model_embedding: str


class AIPingOut(BaseModel):
    reply: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    cost_usd: float | None
