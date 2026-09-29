from enum import StrEnum
from pathlib import Path
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# backend/.env, resolved from this file so the app, Alembic and pytest all find
# it regardless of the working directory they were started from.
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Environment(StrEnum):
    development = "development"
    staging = "staging"
    production = "production"


class Settings(BaseSettings):
    environment: Environment = Environment.development

    database_url: str
    # Logs every SQL statement *with its parameters*. Keep off anywhere real
    # patient data exists.
    sql_echo: bool = False

    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # Comma-separated in .env, e.g. CORS_ORIGINS=http://localhost:5173,https://app.example.com
    cors_origins: Annotated[list[str], NoDecode] = []

    log_level: str = "INFO"

    api_v1_prefix: str = "/api/v1"

    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("cors_origins")
    @classmethod
    def reject_wildcard(cls, value: list[str]) -> list[str]:
        # The API sends credentials cross-origin, which browsers refuse with "*"
        # anyway; an explicit list is also the only safe production setting.
        if "*" in value:
            raise ValueError("CORS_ORIGINS must list explicit origins, not '*'")
        return value


settings = Settings()
