import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class AppointmentStatus(enum.StrEnum):
    """Lifecycle (architecture §8). ``rescheduled`` is deliberately *not* a
    status: rescheduling cancels this row and creates a new one (D12)."""

    requested = "requested"
    scheduled = "scheduled"
    confirmed = "confirmed"
    checked_in = "checked_in"
    in_progress = "in_progress"
    completed = "completed"
    cancelled = "cancelled"
    no_show = "no_show"


# Statuses that hold the time slot. Cancelled and no-show appointments free it.
ACTIVE_STATUSES = (
    AppointmentStatus.requested,
    AppointmentStatus.scheduled,
    AppointmentStatus.confirmed,
    AppointmentStatus.checked_in,
    AppointmentStatus.in_progress,
    AppointmentStatus.completed,
)

# Booked and not finished: what "upcoming" means everywhere (dashboards and
# the appointment list's `upcoming` filter).
OPEN_STATUSES = (
    AppointmentStatus.requested,
    AppointmentStatus.scheduled,
    AppointmentStatus.confirmed,
    AppointmentStatus.checked_in,
    AppointmentStatus.in_progress,
)


def upcoming_condition(now):
    """Open appointments that have not ended yet."""
    return Appointment.status.in_(OPEN_STATUSES) & (Appointment.ends_at > now)


class CancellationReason(enum.StrEnum):
    patient_request = "patient_request"
    doctor_unavailable = "doctor_unavailable"
    clinic_decision = "clinic_decision"
    rescheduled = "rescheduled"
    other = "other"


def _enum(cls, name):
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])


_SLOT_HELD = "status NOT IN ('cancelled', 'no_show')"
_DURING = text("tstzrange(starts_at, ends_at, '[)')")


class Appointment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "appointments"
    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="ends_after_starts"),
        CheckConstraint(
            "(status = 'cancelled') = (cancellation_reason IS NOT NULL)", name="cancellation_reason_iff_cancelled"
        ),
        # Double-booking is impossible, not merely checked (architecture D10):
        # the database rejects any second active appointment overlapping in
        # time for the same doctor, or for the same patient — even when two
        # requests race.
        ExcludeConstraint(
            ("doctor_id", "="), (_DURING, "&&"), using="gist", where=text(_SLOT_HELD),
            name="ex_appointments_doctor_overlap",
        ),
        ExcludeConstraint(
            ("patient_id", "="), (_DURING, "&&"), using="gist", where=text(_SLOT_HELD),
            name="ex_appointments_patient_overlap",
        ),
        UniqueConstraint("booked_by_user_id", "idempotency_key", name="uq_appointments_booked_by_idempotency_key"),
        Index("ix_appointments_doctor_id_starts_at", "doctor_id", "starts_at"),
        Index("ix_appointments_patient_id_starts_at", "patient_id", "starts_at"),
    )
    __mapper_args__ = {"eager_defaults": True}

    patient_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("patients.id", ondelete="RESTRICT"))
    doctor_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("doctors.id", ondelete="RESTRICT"))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[AppointmentStatus] = mapped_column(_enum(AppointmentStatus, "appointment_status"))

    # The patient's own words. Visible to the patient.
    reason: Mapped[str | None] = mapped_column(String(500))
    # Front-desk notes (e.g. "needs wheelchair access"). Staff and doctors only.
    staff_notes: Mapped[str | None] = mapped_column(String(1000))

    # Who made the booking — not necessarily the patient.
    booked_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"))
    # Client-supplied key: retrying the same booking request cannot double-book.
    idempotency_key: Mapped[str | None] = mapped_column(String(100))

    cancellation_reason: Mapped[CancellationReason | None] = mapped_column(
        _enum(CancellationReason, "appointment_cancellation_reason")
    )
    cancellation_note: Mapped[str | None] = mapped_column(String(500))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))

    # Rescheduling chain: the new appointment points at the one it replaced.
    rescheduled_from_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("appointments.id", ondelete="RESTRICT"), unique=True
    )


class AppointmentStatusHistory(Base):
    """Append-only record of every status change: who, when, from, to, why."""

    __tablename__ = "appointment_status_history"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    appointment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("appointments.id", ondelete="RESTRICT"), index=True
    )
    from_status: Mapped[AppointmentStatus | None] = mapped_column(_enum(AppointmentStatus, "appointment_status"))
    to_status: Mapped[AppointmentStatus] = mapped_column(_enum(AppointmentStatus, "appointment_status"))
    # NULL = the system itself (e.g. automatic scheduling of a free slot).
    changed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    reason: Mapped[str | None] = mapped_column(String(500))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
