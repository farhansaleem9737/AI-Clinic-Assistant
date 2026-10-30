import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class AiConversation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One assistant conversation, owned by one user (D96). Never shared."""

    __tablename__ = "ai_conversations"
    __table_args__ = (Index("ix_ai_conversations_user_id_updated_at", "user_id", "updated_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(120))


class AiMessage(UUIDPrimaryKeyMixin, Base):
    """A turn in a conversation. `role` is user or assistant; tool calls and
    their results are not stored (they are re-derived, never trusted)."""

    __tablename__ = "ai_messages"
    __table_args__ = (
        Index("ix_ai_messages_conversation_id_created_at", "conversation_id", "created_at"),
        CheckConstraint("role IN ('user', 'assistant')", name="role"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("ai_conversations.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    # Document ids attached to a user message.
    document_ids: Mapped[list | None] = mapped_column(JSONB)
    # An action the assistant proposed and the user must confirm, e.g.
    # {"type": "book_appointment", "doctor_id", "starts_at", "status": "pending", ...}.
    action: Mapped[dict | None] = mapped_column(JSONB)
    # Structured results shown as cards (D100): doctors or appointments exactly
    # as the backend returned them, e.g. [{"kind": "doctors", "items": [...]}].
    results: Mapped[list | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AiDocument(UUIDPrimaryKeyMixin, Base):
    """A file uploaded to the assistant. The original is private object
    storage under a random key; the extracted text is kept for answering
    questions. Owned by one user; deleted with them."""

    __tablename__ = "ai_documents"
    __table_args__ = (
        Index("ix_ai_documents_user_id_created_at", "user_id", "created_at"),
        CheckConstraint("status IN ('ready', 'no_text', 'failed')", name="status"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("ai_conversations.id", ondelete="SET NULL")
    )
    # Display only, cleaned; never used to build a path or key.
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    object_key: Mapped[str] = mapped_column(String(512), unique=True)
    # ready: text extracted; no_text: nothing readable (image or scanned PDF,
    # needs a vision model); failed: could not be read.
    status: Mapped[str] = mapped_column(String(20))
    extracted_text: Mapped[str | None] = mapped_column(Text)
    page_count: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AiUsage(UUIDPrimaryKeyMixin, Base):
    """One message that reached the AI provider (D100): who, when, which model,
    tokens and tool calls. Never the prompt or the answer. Counted for the
    per-user and server-wide limits."""

    __tablename__ = "ai_usage"
    __table_args__ = (
        Index("ix_ai_usage_user_id_created_at", "user_id", "created_at"),
        Index("ix_ai_usage_created_at", "created_at"),
        CheckConstraint("status IN ('ok', 'failed')", name="status"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(30))
    model: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20))
    error_code: Mapped[str | None] = mapped_column(String(40))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    model_requests: Mapped[int] = mapped_column(Integer, default=0)
    tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
