from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env", env_prefix="BOARDOM_", extra="ignore"
    )

    database_url: str = "sqlite:///data/boardom.db"
    upload_dir: Path = Path("data/uploads")
    max_upload_bytes: int = Field(default=10 * 1024 * 1024, gt=0)
    max_pdf_pages: int = Field(default=200, gt=0)
    max_extracted_characters: int = Field(default=500000, gt=0)
    extraction_timeout_seconds: float = Field(default=60, gt=0, le=600)
    session_lifetime_seconds: int = Field(default=7 * 24 * 60 * 60, gt=0)
    cookie_secure: bool = False
    frontend_origin: str = "http://localhost:3000"
    environment: Literal["development", "test", "production"] = "development"

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
    def resolved_upload_dir(self) -> Path:
        return (BACKEND_ROOT / self.upload_dir).resolve()
