import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, SmallInteger, String, Uuid, text
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
        # The unread count reads only these rows.
        Index("ix_notifications_unread", "user_id", postgresql_where=text("read_at IS NULL")),
        # A scheduled notification (a reminder) exists at most once per user,
        # however often or concurrently the reminder run repeats (D108).
        Index("uq_notifications_user_id_dedupe_key", "user_id", "dedupe_key", unique=True),
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
    # Set for scheduled notifications, e.g. "reminder:<appointment id>:1440"; NULL for events.
    dedupe_key: Mapped[str | None] = mapped_column(String(120))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class NotificationPreference(Base):
    """Optional notification categories a user has switched off (D108). No row
    means everything on. Essential notifications (a doctor's new booking, an
    application to review) cannot be switched off."""

    __tablename__ = "notification_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    appointment_updates: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    reminders: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    follow_ups: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    # Also by email (D109), for the categories above that are on.
    emails: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class FollowUp(UUIDPrimaryKeyMixin, Base):
    """A follow-up visit a doctor or the clinic has recorded as due by a date
    (D108). Only a date: never a reason or clinical note, and never a booking.
    The patient is reminded shortly before it is due, unless they booked or
    it was dismissed."""

    __tablename__ = "follow_ups"
    __table_args__ = (
        Index("ix_follow_ups_patient_id", "patient_id"),
        Index("ix_follow_ups_open_due_date", "due_date", postgresql_where=text("dismissed_at IS NULL")),
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("patients.id", ondelete="CASCADE"))
    doctor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("doctors.id", ondelete="SET NULL"))
    # The visit it follows, if recorded from one.
    appointment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("appointments.id", ondelete="SET NULL"))
    # A date in the clinic's (the doctor's department's) timezone.
    due_date: Mapped[date] = mapped_column(Date)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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
