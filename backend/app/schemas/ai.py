import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AiStatus(BaseModel):
    """What the assistant can do on this server. Never the key or model secrets."""

    configured: bool
    provider: str
    documents_enabled: bool
    max_files: int
    max_file_bytes: int
    accepted_types: list[str]
    capabilities: list[str]
    # The model in use (not a secret), so staff can see what answers them.
    model: str | None = None
    # The caller's roles, so the panel suggests what fits them.
    roles: list[str] = []


class AiUsageRead(BaseModel):
    """The signed-in user's assistant usage today (D100). Limits of 0 mean none."""

    requests_today: int
    daily_limit: int
    remaining_today: int | None
    per_minute_limit: int
    input_tokens_today: int
    output_tokens_today: int
    resets_at: datetime


class SendMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: uuid.UUID | None = None
    text: str = Field(min_length=1, max_length=4000)
    document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=10)

    @field_validator("text")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Message must not be blank")
        return value.strip()


class ActionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: bool


class AiMessageRead(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    document_ids: list[uuid.UUID] = []
    action: dict | None = None
    results: list[dict] = []
    created_at: datetime


class ConversationRead(BaseModel):
    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationRead):
    messages: list[AiMessageRead]


class SendResultRead(BaseModel):
    conversation: ConversationRead
    user_message: AiMessageRead
    assistant_message: AiMessageRead


class AiDocumentRead(BaseModel):
    id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int
    status: str
    page_count: int | None
    conversation_id: uuid.UUID | None
    created_at: datetime
