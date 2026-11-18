from pathlib import Path
from typing import Literal

from pydantic import EmailStr, Field, SecretStr, TypeAdapter, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ADMIN_PASSWORD = "BoardomAdmin#2026"
DEFAULT_ADMIN_RESET_PIN = "482916"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env", env_prefix="BOARDOM_", extra="ignore"
    )

    database_url: str = "sqlite:///data/boardom.db"
    upload_dir: Path = Path("data/uploads")
    chroma_dir: Path = Path("data/chroma")  # ChromaDB vector index
    max_ocr_pages: int = Field(default=20, ge=1, le=200)
    model_vision: str | None = None  # image/scan text recognition; defaults to model_smart
    max_upload_bytes: int = Field(default=10 * 1024 * 1024, gt=0)
    max_pdf_pages: int = Field(default=200, gt=0)
    max_extracted_characters: int = Field(default=500000, gt=0)
    extraction_timeout_seconds: float = Field(default=60, gt=0, le=600)
    session_lifetime_seconds: int = Field(default=7 * 24 * 60 * 60, gt=0)
    cookie_secure: bool = False
    frontend_origin: str = "http://localhost:3000"
    environment: Literal["development", "test", "production"] = "development"
    # Accounts. Public sign-up creates teachers; off by default (admins create teachers).
    allow_public_signup: bool = False
    admin_email: str = "admin@example.com"
    admin_password: str = Field(default=DEFAULT_ADMIN_PASSWORD, min_length=8, max_length=128)
    admin_reset_pin: str = Field(default=DEFAULT_ADMIN_RESET_PIN, min_length=6, max_length=64)
    default_student_limit: int = Field(default=4, ge=0)
    # AI. Without an API key the app runs AI features in offline demo mode (FakeProvider).
    ai_provider: Literal["openai", "fake"] = "openai"
    openai_api_key: SecretStr | None = None
    openai_base_url: str | None = None  # e.g. https://genailab.tcs.in/
    ai_verify_tls: bool = True  # false only for the hackathon gateway; refused in production
    model_smart: str = "gpt-6.1-sol"
    model_fast: str = "gpt-6-luna"
    model_embedding: str = "text-embedding-3-small"
    model_moderation: str = "omni-moderation-latest"
    model_tts: str = "gpt-4o-mini-tts"  # narration for study videos
    tts_voice: str = "alloy"
    video_tts: bool = True  # false: always make silent videos with captions
    # Coach answers only when the best source passage scores at least this (cosine), unless
    # the student names a course concept or asks a general "what should I study" question.
    coach_min_score: float = Field(default=0.2, ge=0, le=1)
    # Guardrails: per-user daily AI limits (model calls; cost only counts priced models).
    daily_ai_calls_per_user: int = Field(default=500, ge=1)
    daily_ai_cost_usd_per_user: float = Field(default=5.0, ge=0)  # 0 = no cost limit
    # true: reject text when the moderation service is unavailable (default: allow + log).
    moderation_required: bool = False
    # Research searches only these domains (and their subdomains). JSON list in .env.
    trusted_domains: list[str] = [
        "wikipedia.org",
        "britannica.com",
        "khanacademy.org",
        "openstax.org",
        "ocw.mit.edu",
        "nptel.ac.in",
        "ncert.nic.in",
        "bbc.co.uk",
        "nature.com",
        "nasa.gov",
    ]
    ai_timeout_seconds: float = Field(default=60, gt=0, le=600)
    ai_max_retries: int = Field(default=2, ge=0, le=5)
    model_prices: dict[str, tuple[float, float, float]] = {
        "gpt-6.1-sol": (2.00, 0.10, 10.00),
        "gpt-6-luna": (0.10, 0.01, 0.50),
    }

    @field_validator("openai_api_key", "openai_base_url", mode="before")
    @classmethod
    def blank_is_unset(cls, value):
        # `BOARDOM_OPENAI_API_KEY=` (as in .env.example) must mean "no key" -> demo mode.
        if isinstance(value, str) and not value.strip():
            return None
        return value.strip() if isinstance(value, str) else value

    @field_validator("admin_email")
    @classmethod
    def normalize_admin_email(cls, value: str) -> str:
        return str(TypeAdapter(EmailStr).validate_python(value.strip().lower()))

    @model_validator(mode="after")
    def no_default_secrets_in_production(self):
        if self.environment == "production" and (
            self.admin_password == DEFAULT_ADMIN_PASSWORD
            or self.admin_reset_pin == DEFAULT_ADMIN_RESET_PIN
        ):
            raise ValueError(
                "Refusing to start in production with the default admin password or reset PIN. "
                "Set BOARDOM_ADMIN_PASSWORD and BOARDOM_ADMIN_RESET_PIN."
            )
        return self

    @field_validator("frontend_origin")
    @classmethod
    def valid_origin(cls, value: str) -> str:
        from urllib.parse import urlsplit

        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
        ):
            raise ValueError("Use an explicit http(s) origin without a path")
        return value.rstrip("/")

    @property
    def resolved_database_url(self) -> str:
        url = make_url(self.database_url)
        if url.get_backend_name() == "sqlite" and url.database not in {None, "", ":memory:"}:
            path = Path(url.database)
            if not path.is_absolute():
                path = BACKEND_ROOT / path
            url = url.set(database=str(path.resolve()))
        return url.render_as_string(hide_password=False)

    @property
    def resolved_chroma_dir(self) -> Path:
        return (BACKEND_ROOT / self.chroma_dir).resolve()

    @property
    def resolved_upload_dir(self) -> Path:
        return (BACKEND_ROOT / self.upload_dir).resolve()
