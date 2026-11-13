import re
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AliasChoices, Field, field_validator, SecretStr, model_validator
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


class EmailBackend(StrEnum):
    # Hand the message to an SMTP server; "sent" only once the server accepts it.
    smtp = "smtp"
    # Brevo's HTTPS email API (D125): for hosts that block outbound SMTP ports,
    # such as Render's free plan. "sent" once Brevo accepts it.
    brevo = "brevo"
    # Development only: write the message to a file under EMAIL_OUTBOX_DIR,
    # never to the log or an API response.
    outbox = "outbox"
    # No delivery: invitations are created but reported as not sent.
    none = "none"


class AiProvider(StrEnum):
    # Off: the assistant opens but says it is not configured (D96).
    none = "none"
    # Google Gemini through the official google-genai SDK (D100): text, images, PDFs, tools, streaming.
    gemini = "gemini"
    # Any OpenAI-compatible chat-completions API, e.g. Groq; text (images if the model supports them).
    openai_compatible = "openai_compatible"
    # Anthropic Claude through the official SDK: text, images, PDFs, tools, streaming (D97).
    anthropic = "anthropic"


class Environment(StrEnum):
    development = "development"
    staging = "staging"
    production = "production"


# Everything DOCTOR_APPROVAL_REQUIREMENTS may name: application fields and
# credential document types.
DOCTOR_APPROVAL_REQUIREMENT_NAMES = (
    "license_number",
    "registration_authority",
    "years_of_experience",
    "qualifications",
    "institution",
    "bio",
    "consultation_fee",
    "languages",
    "phone",
    "registration_certificate",
    "degree_certificate",
    "supporting_document",
)


class Settings(BaseSettings):
    environment: Environment = Environment.development

    database_url: str
    # Logs every SQL statement *with its parameters*. Keep off anywhere real
    # patient data exists.
    sql_echo: bool = False
    # Connection pool (see app/db/database.py). A pooled connection idle for
    # longer than db_ping_after_idle_seconds is checked (one round trip) before
    # reuse; connections older than db_pool_recycle_seconds are replaced. Keep
    # the recycle below Neon's 5-minute auto-suspend.
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_recycle_seconds: int = 240
    db_ping_after_idle_seconds: float = 30

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
    # Self-registration needs a one-time code sent to the email address first.
    email_verification_required: bool = True
    email_verification_code_minutes: int = 10
    email_verification_max_attempts: int = 5
    email_verification_resend_seconds: int = 60
    verification_code_requests_per_minute: int = 5
    # Changing the password without the current one is allowed only this soon
    # after signing in (D116); later the current password is asked for again.
    password_change_recent_auth_minutes: int = 10
    password_change_attempts_per_minute: int = 5
    # Header search (D119): typing is debounced, so this only stops scripted enumeration.
    search_requests_per_minute: int = 120

    refresh_cookie_name: str = "refresh_token"
    csrf_cookie_name: str = "csrf_token"
    csrf_header_name: str = "X-CSRF-Token"
    # None = decide from the environment: Secure everywhere except development,
    # where the app is served over plain http.
    cookie_secure: bool | None = None

    # Comma-separated in .env, e.g. CORS_ORIGINS=http://localhost:5173,https://app.example.com
    cors_origins: Annotated[list[str], NoDecode] = []

    # Live updates over a WebSocket (D122). Events only say *what changed*; the
    # page then re-reads it through the REST API, which stays the source of truth.
    realtime_enabled: bool = True
    # Browser origins allowed to open the socket. Empty = the CORS_ORIGINS list.
    # A page on the API's own origin is always allowed; development allows any
    # origin (the Vite proxy, a phone on the LAN). A ticket is required regardless.
    ws_allowed_origins: Annotated[list[str], NoDecode] = []
    ws_max_connections_per_user: int = 5  # tabs and devices of one account
    ws_max_connections: int = 500  # this process in total
    ws_ticket_ttl_seconds: int = 30  # a ticket is used once, right after it is issued
    ws_tickets_per_minute: int = 30  # per client IP
    ws_revalidate_seconds: int = 300  # re-read the account: deactivated or signed out everywhere → closed
    ws_send_timeout_seconds: float = 5  # a client that cannot take a message this fast is dropped
    ws_queue_size: int = 100  # messages waiting for one client before it counts as too slow

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

    # Appointment reminders (D108), sent by the reminder run (POST
    # /internal/reminders/run, called by Cloud Scheduler). Minutes before the
    # start; patients get each, the doctor the doctor list.
    reminder_offsets_minutes: Annotated[list[int], NoDecode] = [1440, 60]
    doctor_reminder_offsets_minutes: Annotated[list[int], NoDecode] = [60]
    # A recorded follow-up is mentioned to the patient this many days before it is due.
    follow_up_reminder_days: int = 7
    # Who may call the reminder run. In production: Cloud Scheduler's OIDC
    # token, checked for this audience (the run URL) and service-account e-mail.
    reminders_oidc_audience: str | None = None
    reminders_invoker_email: str | None = None
    # Development / other schedulers only: a shared secret in X-Reminders-Secret.
    reminders_cron_secret: SecretStr | None = None


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

    # What a doctor application must contain before an administrator can
    # approve it, on top of specialization and department (a doctor profile
    # cannot exist without those). Comma-separated in .env, e.g.
    # DOCTOR_APPROVAL_REQUIREMENTS=license_number,registration_certificate
    # Registration itself never requires any of these (D77).
    doctor_approval_requirements: Annotated[list[str], NoDecode] = []

    # Administrator invitations (D87). The link points at the frontend, with
    # the token in the URL fragment so it never reaches a server log.
    frontend_base_url: str = "http://localhost:5173"

    # "Continue with Google" (D123): OpenID Connect, Authorization Code + PKCE,
    # run by the backend. Off unless enabled; then the client id and secret are
    # required. The callback must be on the origin the browser uses for the app
    # (the Vite / Vercel origin that forwards /api), so its cookies are first-party:
    # by default FRONTEND_BASE_URL + API_V1_PREFIX + /auth/google/callback.
    google_oauth_enabled: bool = False
    google_oauth_client_id: str | None = None
    google_oauth_client_secret: SecretStr | None = None
    google_oauth_redirect_uri: str | None = None
    google_oauth_timeout_seconds: float = 10
    google_oauth_flow_minutes: int = 10  # Google sign-in must finish within this
    google_oauth_signup_minutes: int = 30  # a new user's time to complete the registration form
    google_oauth_attempts_per_minute: int = 20  # per client IP, at the start endpoints
    # Forgot password (D126, D127): an emailed 6-digit code, valid CODE_MINUTES and
    # for CODE_MAX_ATTEMPTS wrong guesses; the right code gives the browser a reset
    # token valid TOKEN_MINUTES. Per client IP per minute at the public endpoints;
    # per account at most PER_HOUR codes, at least RESEND_SECONDS apart (counted in
    # the database, so every API process agrees).
    password_reset_code_minutes: int = 10
    password_reset_code_max_attempts: int = 5
    password_reset_token_minutes: int = 10
    password_reset_requests_per_minute: int = 5
    password_reset_attempts_per_minute: int = 10
    password_reset_resend_seconds: int = 60
    password_reset_max_per_hour: int = 5
    admin_invite_expire_hours: int = 24
    # A doctor's invitation to a receptionist (D131): its link works this long.
    receptionist_invite_expire_hours: int = 72
    # Attempts per client IP per minute at the public invitation endpoints.
    invite_attempts_per_minute: int = 10

    # Outgoing email. None = outbox in development, otherwise SMTP if
    # SMTP_HOST is set, otherwise none.
    email_backend: EmailBackend | None = None
    email_from: str = "Clinic AI Assistant <no-reply@localhost>"
    email_outbox_dir: Path = Path(__file__).resolve().parents[2] / "var" / "outbox"
    # EMAIL_BACKEND=brevo (D125): a Brevo API key (SMTP & API → API keys), sent over
    # HTTPS port 443. EMAIL_FROM must be a sender verified in Brevo.
    brevo_api_key: SecretStr | None = None
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_starttls: bool = True
    # Implicit TLS from the first byte (usually port 465) instead of STARTTLS.
    smtp_ssl: bool = False
    smtp_timeout_seconds: int = 10
    # Unencrypted SMTP is refused unless set, and then only to this machine
    # (a local test server such as Mailpit). Never for a real provider.
    smtp_allow_plaintext_localhost: bool = False

    # Notification emails (D109): queued in the email_outbox table and sent
    # by the outbox run (also part of the reminder run). After a commit that
    # queued email, this process also starts sending at once, without waiting
    # for the next run. Reminder emails: these offsets only (minutes before);
    # by default every patient reminder (24 h and 1 h) also goes by email.
    email_send_after_commit: bool = True
    email_reminder_offsets_minutes: Annotated[list[int], NoDecode] = [1440, 60]
    email_max_attempts: int = 6

    # AI assistant (D96). Off unless a provider, model and key are all set.
    # AI_ENABLED=false switches it off whatever else is configured.
    ai_enabled: bool = True
    ai_provider: AiProvider = AiProvider.none
    ai_model: str | None = None
    ai_api_key: SecretStr | None = None
    # AI_PROVIDER=gemini (D100): GEMINI_API_KEY / GEMINI_MODEL, or AI_API_KEY / AI_MODEL.
    # The model is used exactly as configured: there is no automatic fallback
    # to another (possibly paid) model.
    gemini_api_key: SecretStr | None = None
    gemini_model: str | None = None
    # Optional Gemini thinking level (e.g. "low"); unset = the model's default.
    gemini_thinking_level: str | None = None
    # AI_PROVIDER=anthropic only: may come from ANTHROPIC_API_KEY instead of AI_API_KEY.
    anthropic_api_key: SecretStr | None = None
    # openai_compatible only, e.g. https://api.groq.com/openai/v1
    ai_base_url: str | None = None
    ai_max_output_tokens: int = 1024
    # Model round trips per message (each may call tools). AI_MAX_TOOL_CALLS also accepted.
    ai_max_tool_steps: int = Field(default=4, ge=1, le=10, validation_alias=AliasChoices("ai_max_tool_steps", "ai_max_tool_calls"))
    ai_timeout_seconds: int = Field(default=30, ge=5, validation_alias=AliasChoices("ai_timeout_seconds", "ai_request_timeout_seconds"))
    # Earlier messages sent with each request (a rolling window).
    ai_max_history_messages: int = Field(default=12, ge=2, le=50)
    # Usage limits (D100). 0 = no limit. Per user, then for the whole server;
    # a "day" is the clinic's calendar day.
    ai_daily_request_limit: int = Field(default=20, ge=0)
    ai_rate_limit_per_minute: int = Field(default=5, ge=0)
    ai_global_daily_request_limit: int = Field(default=500, ge=0)
    ai_global_rate_limit_per_minute: int = Field(default=15, ge=0)
    # Log token counts per request (never prompts or answers).
    ai_log_token_usage: bool = True
    # A proposed booking / cancellation / move must be confirmed within this time.
    ai_action_ttl_minutes: int = Field(default=15, ge=1, le=240)
    # Conversations untouched for longer are deleted by scripts.purge_ai_documents. 0 = keep.
    ai_conversation_retention_days: int = Field(default=90, ge=0)
    # Whether this provider may receive patient health information: the
    # signed-in user's appointments and uploaded documents. Keep False for
    # free tiers and any provider without a suitable agreement; then those
    # tools and document analysis are switched off (doctor search and booking
    # proposals still work). True only for synthetic test data or an approved provider.
    ai_phi_allowed: bool = False
    # Development (D102): documents whose own text declares them synthetic /
    # fictional test data may be explained by the AI provider even when
    # AI_PHI_ALLOWED is false. Real reports stay on the server. Keep false in production.
    ai_allow_synthetic_documents: bool = False
    # Uploading medical documents to the assistant. Needs AI_PHI_ALLOWED too;
    # off by default until privacy and clinical safeguards are approved.
    ai_enable_medical_document_upload: bool = False
    ai_max_file_bytes: int = 10 * 1024 * 1024
    ai_max_files_per_message: int = 5
    # Uploaded assistant documents older than this are deleted by
    # scripts.purge_ai_documents. 0 = keep until the user deletes them.
    ai_document_retention_days: int = 30
    # Responsiveness on a small instance (D130, docs/PERFORMANCE.md).
    # Gemini: no first chunk within this many seconds, or a pause longer than the
    # idle limit mid-answer, fails the step (each step is also capped by AI_TIMEOUT_SECONDS).
    ai_first_token_timeout_seconds: int = Field(default=25, ge=3)
    ai_stream_idle_timeout_seconds: int = Field(default=20, ge=3)
    # Assistant requests answered at once by this process; more get "busy" (503 AI_BUSY)
    # instead of queueing behind each other. 0 = no limit.
    ai_max_concurrent_requests: int = Field(default=3, ge=0)
    # Document reading (PDF parsing) runs outside the web process's event loop:
    # "process" = one low-priority worker process (no GIL shared with the web
    # server; production default), "thread" = one dedicated thread (development
    # and tests). Unset: process in production, thread elsewhere.
    ai_extraction_isolation: Literal["process", "thread"] | None = None
    ai_extraction_timeout_seconds: int = Field(default=60, ge=5)
    # Documents waiting or being read at once; more are refused as busy.
    ai_extraction_queue_limit: int = Field(default=4, ge=1)
    # Log a warning when the event loop is late by more than this (0 = off).
    event_loop_lag_warning_ms: int = Field(default=500, ge=0)

    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    @field_validator("ai_model", "ai_base_url", "gemini_model", "gemini_thinking_level", mode="before")
    @classmethod
    def blank_ai_setting_is_unset(cls, value: object) -> object:
        return None if isinstance(value, str) and (not value.strip() or "CHANGE_ME" in value) else value

    @field_validator("ai_api_key", "anthropic_api_key", "gemini_api_key", mode="before")
    @classmethod
    def blank_ai_key_is_unset(cls, value: object) -> object:
        return None if isinstance(value, str) and (not value.strip() or "CHANGE_ME" in value) else value

    @property
    def ai_key(self) -> SecretStr | None:
        if self.ai_provider is AiProvider.anthropic:
            return self.ai_api_key or self.anthropic_api_key
        if self.ai_provider is AiProvider.gemini:
            return self.gemini_api_key or self.ai_api_key
        return self.ai_api_key

    @property
    def ai_model_name(self) -> str | None:
        if self.ai_provider is AiProvider.gemini:
            return self.gemini_model or self.ai_model
        return self.ai_model

    @property
    def ai_configured(self) -> bool:
        if not self.ai_enabled or self.ai_provider is AiProvider.none or not self.ai_model_name or self.ai_key is None:
            return False
        return self.ai_provider is not AiProvider.openai_compatible or bool(self.ai_base_url)

    @property
    def ai_documents_enabled(self) -> bool:
        return self.ai_configured and self.ai_phi_allowed and self.ai_enable_medical_document_upload

    @property
    def extraction_in_process(self) -> bool:
        if self.ai_extraction_isolation is not None:
            return self.ai_extraction_isolation == "process"
        return self.environment is Environment.production

    @field_validator("frontend_base_url")
    @classmethod
    def plain_base_url(cls, value: str) -> str:
        value = value.rstrip("/")
        if not re.fullmatch(r"https?://[^/?#\s]+(/[^?#\s]*)?", value):
            raise ValueError("FRONTEND_BASE_URL must be an http(s) URL without a query or fragment")
        return value

    @field_validator("smtp_host", mode="before")
    @classmethod
    def blank_smtp_host_is_unset(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("smtp_username", "smtp_password", mode="before")
    @classmethod
    def blank_smtp_login_is_unset(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("email_reminder_offsets_minutes", mode="before")
    @classmethod
    def split_email_offsets(cls, value: object) -> object:
        if isinstance(value, str):
            return [int(v) for v in value.split(",") if v.strip()]
        return value

    @field_validator("email_from")
    @classmethod
    def valid_sender(cls, value: str) -> str:
        from email.headerregistry import Address
        from email.utils import parseaddr

        name, address = parseaddr(value)
        try:
            Address(display_name=name, addr_spec=address)
        except (ValueError, IndexError) as exc:
            raise ValueError("EMAIL_FROM must be an address, optionally with a name: Name <user@example.com>") from exc
        if "@" not in address:
            raise ValueError("EMAIL_FROM must be an address, optionally with a name: Name <user@example.com>")
        return value

    @field_validator("doctor_approval_requirements", mode="before")
    @classmethod
    def split_requirements(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("doctor_approval_requirements")
    @classmethod
    def known_requirements(cls, value: list[str]) -> list[str]:
        unknown = sorted(set(value) - set(DOCTOR_APPROVAL_REQUIREMENT_NAMES))
        if unknown:
            raise ValueError(f"Unknown DOCTOR_APPROVAL_REQUIREMENTS: {', '.join(unknown)}")
        return value

    @field_validator("cors_origins", "ws_allowed_origins", mode="before")
    @classmethod
    def split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip().rstrip("/") for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("cors_origins", "ws_allowed_origins")
    @classmethod
    def reject_wildcard(cls, value: list[str]) -> list[str]:
        # The API sends credentials cross-origin, which browsers refuse with "*"
        # anyway; an explicit list is also the only safe production setting.
        if "*" in value:
            raise ValueError("CORS_ORIGINS and WS_ALLOWED_ORIGINS must list explicit origins, not '*'")
        return value

    @field_validator("reminder_offsets_minutes", "doctor_reminder_offsets_minutes", mode="before")
    @classmethod
    def split_offsets(cls, value: object) -> object:
        # "1440,60" in the environment, like CORS_ORIGINS.
        if isinstance(value, str):
            return [int(v) for v in value.split(",") if v.strip()]
        return value

    @field_validator("reminder_offsets_minutes", "doctor_reminder_offsets_minutes")
    @classmethod
    def positive_offsets(cls, value: list[int]) -> list[int]:
        if any(v <= 0 for v in value):
            raise ValueError("Reminder offsets must be positive minutes")
        return sorted(set(value), reverse=True)

    @field_validator("brevo_api_key", mode="before")
    @classmethod
    def blank_brevo_key(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("reminders_oidc_audience", "reminders_invoker_email", "reminders_cron_secret", mode="before")
    @classmethod
    def blank_reminder_setting_is_unset(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

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
        if self.environment is Environment.production and (
            not self.frontend_base_url.startswith("https://") or re.search(r"//(localhost|127\.0\.0\.1)\b", self.frontend_base_url)
        ):
            # Every email link starts here (D124): never http or localhost in production.
            raise ValueError("FRONTEND_BASE_URL must be the public https address of the app in production")
        if self.environment is  Environment.production and not self.storage_configured:
            raise ValueError("R2 storage settings are required in production")
        if self.environment is not Environment.development and self.email_backend is EmailBackend.outbox:
            raise ValueError("EMAIL_BACKEND=outbox is for development only")
        if self.email_backend is EmailBackend.smtp and not self.smtp_host:
            raise ValueError("EMAIL_BACKEND=smtp needs SMTP_HOST")
        if self.email_backend is EmailBackend.brevo and not self.brevo_api_key:
            raise ValueError("EMAIL_BACKEND=brevo needs BREVO_API_KEY")
        if self.smtp_host:
            self._check_smtp_security()
        if self.google_oauth_enabled and not (self.google_oauth_client_id and self.google_oauth_client_secret):
            raise ValueError("GOOGLE_OAUTH_ENABLED needs GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET")
        if self.google_oauth_redirect_uri and not self.google_oauth_redirect_uri.startswith(("https://", "http://localhost", "http://127.0.0.1")):
            raise ValueError("GOOGLE_OAUTH_REDIRECT_URI must be https (http only for localhost)")
        return self

    def _check_smtp_security(self) -> None:
        """Never plaintext to a real server, never a half-configured login."""
        if self.smtp_ssl and self.smtp_starttls:
            raise ValueError("Choose one: SMTP_SSL=true (implicit TLS, port 465) or SMTP_STARTTLS=true (port 587)")
        if not (self.smtp_ssl or self.smtp_starttls):
            local = self.smtp_host in ("localhost", "127.0.0.1", "::1")
            if not (self.smtp_allow_plaintext_localhost and local):
                raise ValueError(
                    "SMTP without TLS is refused; set SMTP_STARTTLS=true or SMTP_SSL=true "
                    "(a local test server needs SMTP_ALLOW_PLAINTEXT_LOCALHOST=true)"
                )
        if self.smtp_port == 465 and self.smtp_starttls:
            raise ValueError("Port 465 uses implicit TLS: set SMTP_SSL=true and SMTP_STARTTLS=false")
        if bool(self.smtp_username) != bool(self.smtp_password):
            raise ValueError("SMTP_USERNAME and SMTP_PASSWORD go together")

    @property
    def effective_email_backend(self) -> EmailBackend:
        if self.email_backend is not None:
            return self.email_backend
        if self.environment is Environment.development:
            return EmailBackend.outbox
        if self.brevo_api_key:
            return EmailBackend.brevo
        return EmailBackend.smtp if self.smtp_host else EmailBackend.none

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
    def google_redirect_uri(self) -> str:
        """The exact callback registered in Google Cloud Console."""
        return self.google_oauth_redirect_uri or f"{self.frontend_base_url}{self.api_v1_prefix}/auth/google/callback"

    @property
    def google_cookie_path(self) -> str:
        # The short-lived Google sign-in cookies go only to these endpoints.
        return f"{self.api_v1_prefix}/auth/google"

    @property
    def auth_cookie_path(self) -> str:
        # The refresh cookie is only ever sent to the auth endpoints.
        return f"{self.api_v1_prefix}/auth"


settings = Settings()
