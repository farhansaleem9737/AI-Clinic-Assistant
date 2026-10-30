import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, SmallInteger, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.db.base import Base
from app.db.mixins import UUIDPrimaryKeyMixin


class Notification(UUIDPrimaryKeyMixin, Base):
    """A message for one user, created by a real event in the same
    transaction as that event (D86). Read in-app only; no e-mail or push."""

    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_user_id_created_at", "user_id", "created_at"),
        # Only internal paths: never an external URL.
        CheckConstraint("link IS NULL OR (link LIKE '/%' AND link NOT LIKE '//%')", name="internal_link"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    # e.g. doctor_application, appointment_booked, appointment_cancelled
    type: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(150))
    # No clinical details: dates, times and what happened, nothing more.
    message: Mapped[str] = mapped_column(String(500))
    link: Mapped[str | None] = mapped_column(String(255))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ClinicSettings(Base):
    """The clinic's own details, edited by administrators (D86). One row
    (id = 1). Operational rules (timezone, slot length, booking limits) stay in
    server configuration: changing them here could break existing bookings."""

    __tablename__ = "clinic_settings"
    __table_args__ = (CheckConstraint("id = 1", name="single_row"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1)
    clinic_name: Mapped[str | None] = mapped_column(String(120))
    contact_phone: Mapped[str | None] = mapped_column(String(30))
    contact_email: Mapped[str | None] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(String(500))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
