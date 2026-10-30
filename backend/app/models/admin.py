import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.db.base import Base
from app.db.mixins import UUIDPrimaryKeyMixin


class AdminInvitation(UUIDPrimaryKeyMixin, Base):
    """An invitation to become an administrator (D87).

    Only the SHA-256 of the token is stored: the token itself exists only in
    the email. Single use: ``accepted_at`` or ``revoked_at`` ends it, and so
    does ``expires_at``. Status is derived from those, never stored twice.
    """

    __tablename__ = "admin_invitations"
    __table_args__ = (
        Index("ix_admin_invitations_email", "email"),
        # The workflow grants exactly one role. A wider invitation would need
        # its own review, not a different value in this column.
        CheckConstraint("role_code = 'admin'", name="admin_role_only"),
        CheckConstraint("NOT (accepted_at IS NOT NULL AND revoked_at IS NOT NULL)", name="single_outcome"),
    )

    email: Mapped[str] = mapped_column(String(255))
    name: Mapped[str | None] = mapped_column(String(100))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    role_code: Mapped[str] = mapped_column(String(50), default="admin")
    invited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    # What the email provider said the last time the link was sent:
    # sent (accepted by SMTP), outbox (development file), failed, not_configured.
    delivery_status: Mapped[str | None] = mapped_column(String(20))
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(UUIDPrimaryKeyMixin, Base):
    """Append-only record of sensitive actions (architecture §21, D87).

    ``details`` holds non-secret context only: never passwords, tokens or
    token hashes.
    """

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_created_at", "created_at"),
        Index("ix_audit_logs_target", "target_type", "target_id"),
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # None for the command-line bootstrap, which has no signed-in actor.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(60))
    target_type: Mapped[str] = mapped_column(String(40))
    target_id: Mapped[str | None] = mapped_column(String(64))
    ip_address: Mapped[str | None] = mapped_column(String(45))
    details: Mapped[dict | None] = mapped_column(JSONB)
