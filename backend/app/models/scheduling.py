"""Hybrid scheduling (D117): each doctor's scheduling policy, and the day's
queue of scheduled and walk-in patients with stable token numbers."""

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


def _enum(cls, name):
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])


class SchedulingMode(enum.StrEnum):
    # Patients book exact times; no walk-in tokens.
    scheduled = "scheduled"
    # No times: patients get a token for the day and are seen in arrival order.
    fifo = "fifo"
    # Booked times keep priority; walk-ins fill the capacity left over.
    hybrid = "hybrid"


class SchedulingPolicy(Base):
    """How one doctor runs their sessions. The doctor sets it (staff with
    schedule:manage_any may too). Saving it changes how *future* free times
    are offered; existing appointments keep their own start and end times.

    A doctor with no row keeps the legacy behaviour: slot length from each
    weekly template's ``slot_minutes`` (D117, legacy duration policy).
    """

    __tablename__ = "doctor_scheduling_policies"
    __table_args__ = (
        CheckConstraint("consultation_minutes BETWEEN 5 AND 240", name="consultation_minutes_range"),
        CheckConstraint("buffer_minutes BETWEEN 0 AND 120", name="buffer_minutes_range"),
        CheckConstraint("late_grace_minutes BETWEEN 0 AND 120", name="late_grace_minutes_range"),
        CheckConstraint("max_overbook BETWEEN 0 AND 5", name="max_overbook_range"),
        CheckConstraint("walk_in_capacity IS NULL OR walk_in_capacity BETWEEN 1 AND 500", name="walk_in_capacity_range"),
    )

    doctor_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("doctors.id", ondelete="CASCADE"), primary_key=True)
    mode: Mapped[SchedulingMode] = mapped_column(_enum(SchedulingMode, "scheduling_mode"), default=SchedulingMode.hybrid)
    consultation_minutes: Mapped[int] = mapped_column(SmallInteger, default=15)
    buffer_minutes: Mapped[int] = mapped_column(SmallInteger, default=0)
    accept_walk_ins: Mapped[bool] = mapped_column(Boolean, default=True)
    # Walk-in tokens per day; NULL = no limit beyond the working hours.
    walk_in_capacity: Mapped[int | None] = mapped_column(SmallInteger)
    late_grace_minutes: Mapped[int] = mapped_column(SmallInteger, default=10)
    # Extra patients staff may book into an already taken time (capacity lanes 1..max_overbook).
    max_overbook: Mapped[int] = mapped_column(SmallInteger, default=1)
    allow_receptionist_overrides: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))


class QueueKind(enum.StrEnum):
    scheduled = "scheduled"  # from an appointment, at its check-in
    walk_in = "walk_in"


class QueueState(enum.StrEnum):
    registered = "registered"  # token issued, not yet arrived (patient's own walk-in request)
    waiting = "waiting"  # checked in
    called = "called"  # asked to come in
    in_consultation = "in_consultation"
    completed = "completed"
    absent = "absent"  # called but not there; can check in again
    no_show = "no_show"
    cancelled = "cancelled"


OPEN_QUEUE_STATES = (QueueState.registered, QueueState.waiting, QueueState.called, QueueState.in_consultation, QueueState.absent)


class TokenCounter(Base):
    """Last token number issued per doctor and local date; incremented with one
    atomic INSERT ... ON CONFLICT DO UPDATE ... RETURNING, so two concurrent
    check-ins can never receive the same number."""

    __tablename__ = "queue_token_counters"

    doctor_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("doctors.id", ondelete="CASCADE"), primary_key=True)
    session_date: Mapped[date] = mapped_column(Date, primary_key=True)
    last_token: Mapped[int] = mapped_column(Integer, default=0)


class QueueEntry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One patient in one doctor's queue for one local date.

    ``token_number`` never changes once issued; the *position* is computed
    from the queue rules every time it is read (queue_service.order).
    """

    __tablename__ = "queue_entries"
    __table_args__ = (
        UniqueConstraint("doctor_id", "session_date", "token_number", name="uq_queue_entries_doctor_date_token"),
        # The database, not only the code: one called patient and one consultation per doctor at a time.
        Index("uq_queue_entries_one_called", "doctor_id", unique=True, postgresql_where=text("state = 'called'")),
        Index("uq_queue_entries_one_consultation", "doctor_id", unique=True, postgresql_where=text("state = 'in_consultation'")),
        # One open walk-in token per patient per doctor and day.
        Index(
            "uq_queue_entries_open_walk_in", "doctor_id", "session_date", "patient_id", unique=True,
            postgresql_where=text("kind = 'walk_in' AND state IN ('registered', 'waiting', 'called', 'in_consultation', 'absent')"),
        ),
        Index("ix_queue_entries_doctor_id_session_date", "doctor_id", "session_date"),
        Index("ix_queue_entries_patient_id", "patient_id"),
    )

    doctor_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("doctors.id", ondelete="RESTRICT"))
    session_date: Mapped[date] = mapped_column(Date)
    token_number: Mapped[int] = mapped_column(Integer)
    kind: Mapped[QueueKind] = mapped_column(_enum(QueueKind, "queue_kind"))
    state: Mapped[QueueState] = mapped_column(_enum(QueueState, "queue_state"))
    patient_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("patients.id", ondelete="RESTRICT"))
    appointment_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("appointments.id", ondelete="RESTRICT"), unique=True
    )
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    called_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Staff adjustments (audited): not callable before this time / called ahead of the rules.
    deferred_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    prioritized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    note: Mapped[str | None] = mapped_column(String(300))
