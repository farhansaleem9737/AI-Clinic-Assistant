import re
from enum import StrEnum
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import field_validator, SecretStr, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# backend/.env, resolved from this file so the app, Alembic and pytest all find
# it regardless of the working directory they were started from.
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

# R2's account-level S3 endpoint (plain, EU or FedRAMP jurisdiction). The bucket
# is passed per request, so the endpoint never contains a bucket or a path.

R2_ENDPOINT_PATTERN=re.compile(
    r"https://(?P<account>[0-9a-f]{32})\.(?:(?:eu|fedramp)\.)?r2\.cloudflarestorage\.com"
)
_R2_FIELDS=("r2_account_id","r2_endpoint_url","r2_access_key_id","r2_secret_access_key","r2_bucket_name")


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
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 14
    # Lifetime of a session signed in *without* "Remember me". Its cookie also
    # disappears when the browser closes; this bounds it if the browser
    # restores session cookies or is simply never closed.
    session_token_expire_hours: int = 12
    # Two requests presenting the same refresh token within this many seconds
    # (e.g. two tabs opening at once) are treated as a race, not as theft.
    refresh_reuse_grace_seconds: int = 10

    refresh_cookie_name: str = "refresh_token"
    csrf_cookie_name: str = "csrf_token"
    csrf_header_name: str = "X-CSRF-Token"
    # None = decide from the environment: Secure everywhere except development,
    # where the app is served over plain http.
    cookie_secure: bool | None = None

    # Comma-separated in .env, e.g. CORS_ORIGINS=http://localhost:5173,https://app.example.com
    cors_origins: Annotated[list[str], NoDecode] = []

    log_level: str = "INFO"

    api_v1_prefix: str = "/api/v1"

    # IANA name. Default for new departments and for interpreting calendar
    # dates in API filters ("appointments on 2026-10-01").
    clinic_timezone: str = "UTC"

    # Appointment booking policy.
    booking_min_lead_minutes: int = 60
    booking_max_advance_days: int = 90
    patient_cancellation_cutoff_minutes: int = 120
    no_show_grace_minutes: int = 15
    # Length of slots opened by an "extra availability" schedule exception.
    default_slot_minutes: int = 30
    # How far ahead the directory looks when labelling a doctor Available / Busy / Unavailable.
    availability_status_days: int = 7


    # Cloudflare R2 object storage, through its S3-compatible API. Optional in
    # development and tests (file features answer 503 without it); required in
    # production. The bucket must stay private: files are reached only through
    # short-lived presigned URLs issued after an authorization check.
    r2_account_id:str | None = None
    r2_endpoint_url:str | None = None
    r2_access_key_id:str | None = None
    r2_secret_access_key:SecretStr | None = None
    r2_bucket_name:str | None = None
    r2_region:str = "auto"
    # Connect and read timeout for each request to R2.
    r2_timeout_seconds:int = 10
    # Presigned link lifetimes. Anyone holding a link can use it until then.
    photo_url_ttl_seconds:int=3600
    document_url_ttl_seconds:int=300
    max_photo_bytes:int = 5 * 1024 * 1024
    max_document_bytes:int = 20 * 1024 * 1024

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

    @field_validator("clinic_timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"Unknown IANA timezone: {value}") from exc
        return value

    @field_validator(*_R2_FIELDS, mode="before")
    @classmethod
    def blank_or_placeholder_is_unset(cls, value: object)->object:
        # An empty value, or a CHANGE_ME placeholder copied from .env.example,
        # means "not configured" rather than "configured with a bad value"
        if isinstance(value,str) and (not value.strip() or "CHANGE_ME" in value):
            return None
        return value

    @field_validator("r2_endpoint_url")
    @classmethod
    def valid_r2_endpoint(cls,value : str | None)->str | None:
        if value is None:
            return None
        value = value.rstrip("/")
        if not R2_ENDPOINT_PATTERN.fullmatch(value):
            raise ValueError(
                "R2_ENDPOINT_URL must be https://<account_id>.r2.cloudflarestorage.com, without a bucket or path"
            )
        return value

    @model_validator(mode="after")
    def check_storage(self)->"Settings":
        if self.r2_account_id and self.r2_endpoint_url:
            account=R2_ENDPOINT_PATTERN.fullmatch(self.r2_endpoint_url)["account"]
            if account!=self.r2_account_id.strip().lower():
                raise ValueError("R2_ENDPOINT_URL does not belong to R2_ACCOUNT_ID")
        if self.environment is  Environment.production and not self.storage_configured:
            raise ValueError("R2 storage settings are required in production")
        return self

    @property
    def storage_configured(self) -> bool:
        return all(
            (self.r2_endpoint_url, self.r2_access_key_id, self.r2_secret_access_key, self.r2_bucket_name)
        )

    @property
    def secure_cookies(self) -> bool:
        if self.cookie_secure is not None:
            return self.cookie_secure
        return self.environment is not Environment.development

    @property
    def auth_cookie_path(self) -> str:
        # The refresh cookie is only ever sent to the auth endpoints.
        return f"{self.api_v1_prefix}/auth"


settings = Settings()
