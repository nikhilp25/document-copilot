"""Single source of truth for backend configuration.

Import `settings` from this module. Never read `os.environ` or call
`load_dotenv` elsewhere in app code.
"""

from pathlib import Path
from typing import Annotated

from pydantic import Field, HttpUrl, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Environment configuration, validated at import time."""

    # Absolute path so imports work from uvicorn, pytest, notebooks, and scripts
    # regardless of the current working directory.
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Supabase (Auth + API) ---

    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str

    # --- Postgres (Alembic + direct DB access) ---

    # Must be the direct/session connection. The transaction pooler cannot run
    # migrations, extension setup, or index creation.
    database_url: PostgresDsn

    # --- OpenAI ---

    openai_api_key: str

    # The answering model. Not a `KnownModelName` literal in the pinned
    # pydantic-ai, but its reasoning profile is — the name reaches OpenAI as
    # written, so a typo surfaces as a 404 on the first turn.
    openai_chat_model: str = "gpt-5.5"

    openai_embedding_model: str = "text-embedding-3-small"
    openai_embedding_dimensions: int = 1536

    # --- Server ---

    allowed_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )

    @field_validator("supabase_url")
    @classmethod
    def _validate_supabase_url(cls, value: str) -> str:
        # Stored as a plain string because the Supabase SDK builds paths by
        # concatenation; a trailing slash produces doubled separators.
        return str(HttpUrl(value)).rstrip("/")

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _split_allowed_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


settings = Settings()
