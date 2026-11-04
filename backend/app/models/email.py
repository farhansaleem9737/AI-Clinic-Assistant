import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, SmallInteger, String, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.db.base import Base
from app.db.mixins import UUIDPrimaryKeyMixin

EMAIL_STATUSES = ("pending", "sending", "sent", "written", "failed", "expired")


class EmailOutbox(UUIDPrimaryKeyMixin, Base):
    """An email waiting to be sent, or what became of it (D109).

    Queued in the same transaction as its event, sent later by the outbox run
    outside any transaction, so a booking never waits for (or is undone by)
    an SMTP server. Status: pending → sending → sent (accepted by the SMTP
    server), written (development file), failed (gave up) or expired (too late
    to matter, e.g. a reminder after the appointment). Delivery is at least
    once: a run that dies mid-send may send that one email again.

    Bodies are kept only until sent; the address is the recipient account's
    own, and nothing clinical is ever in them.
    """

    __tablename__ = "email_outbox"
    __table_args__ = (
        CheckConstraint(f"status IN {EMAIL_STATUSES}", name="status"),
        # What the run picks up: due, unsent work.
        Index("ix_email_outbox_due", "next_attempt_at", postgresql_where=text("status IN ('pending', 'sending')")),
        # One email per event and user, however often the event's code runs.
        Index("uq_email_outbox_user_id_dedupe_key", "user_id", "dedupe_key", unique=True),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    to_address: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(50))
    subject: Mapped[str] = mapped_column(String(200))
    text_body: Mapped[str] = mapped_column(Text)
    html_body: Mapped[str] = mapped_column(Text)
    dedupe_key: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(10), default="pending", server_default=text("'pending'"))
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0, server_default=text("0"))
    # When it may be tried (again); for "sending", when an abandoned claim may be taken over.
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Not worth sending after this (a reminder once the appointment started).
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # An error class and SMTP code, never server text, addresses or secrets.
    last_error: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
