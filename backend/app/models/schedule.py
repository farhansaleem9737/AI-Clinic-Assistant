import enum
import uuid
from datetime import date, datetime, time

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Time,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ScheduleTemplate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A doctor's recurring weekly working block, e.g. Monday 09:00–13:00 in
    30-minute slots.

    Times are *local wall-clock* times in the doctor's department timezone,
    expanded per date at read time — so 09:00 stays 09:00 across a DST change.
    """

    __tablename__ = "schedule_templates"
    __table_args__ = (
        CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday_range"),
        CheckConstraint("start_time < end_time", name="start_before_end"),
        CheckConstraint("slot_minutes BETWEEN 5 AND 240", name="slot_minutes_range"),
        CheckConstraint("valid_until IS NULL OR valid_until >= valid_from", name="valid_range"),
        Index("ix_schedule_templates_doctor_id_weekday", "doctor_id", "weekday"),
    )

    doctor_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("doctors.id", ondelete="RESTRICT"))
    # ISO weekday minus one: Monday = 0 … Sunday = 6 (Python's date.weekday()).
    weekday: Mapped[int] = mapped_column(SmallInteger)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    slot_minutes: Mapped[int] = mapped_column(SmallInteger)
    valid_from: Mapped[date] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class ExceptionKind(enum.StrEnum):
    leave = "leave"
    holiday = "holiday"
    block = "block"
    # Adds bookable time outside the weekly templates.
    extra_availability = "extra_availability"


class ScheduleException(UUIDPrimaryKeyMixin, Base):
    """A one-off change to a doctor's availability over an exact interval."""

    __tablename__ = "schedule_exceptions"
    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="ends_after_starts"),
        Index("ix_schedule_exceptions_doctor_id_starts_at", "doctor_id", "starts_at"),
    )

    doctor_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("doctors.id", ondelete="RESTRICT"))
    kind: Mapped[ExceptionKind] = mapped_column(
        Enum(ExceptionKind, name="schedule_exception_kind", values_callable=lambda e: [m.value for m in e])
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Internal note (e.g. "conference"); shown to staff, never to patients.
    reason: Mapped[str | None] = mapped_column(String(255))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
