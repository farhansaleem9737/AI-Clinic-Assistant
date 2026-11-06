"""Hybrid scheduling (D117): doctor policies and the day's queue."""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.scheduling import QueueKind, QueueState, SchedulingMode

# The lengths the doctor's settings offer (D120). A length saved earlier
# outside these (5-240) keeps working and is shown as the current value.
STANDARD_DURATIONS = (15, 20, 30)


class SchedulingPolicyWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: SchedulingMode = SchedulingMode.hybrid
    consultation_minutes: int = Field(default=15, ge=5, le=240)
    buffer_minutes: int = Field(default=0, ge=0, le=120)
    accept_walk_ins: bool = True
    walk_in_capacity: int | None = Field(default=None, ge=1, le=500)
    late_grace_minutes: int = Field(default=10, ge=0, le=120)
    max_overbook: int = Field(default=1, ge=0, le=5)
    allow_receptionist_overrides: bool = True


class SchedulingPolicyRead(SchedulingPolicyWrite):
    doctor_id: uuid.UUID
    # False: nothing saved yet; free times still use the weekly hours' own
    # slot length (`legacy_slot_minutes`) until the doctor saves a policy.
    configured: bool
    legacy_slot_minutes: int | None = None
    standard_durations: tuple[int, ...] = STANDARD_DURATIONS
    updated_at: datetime | None = None


class SchedulingPolicyUpdate(SchedulingPolicyWrite):
    """The PUT body (D120): the policy plus the explicit choice needed when a new
    length or buffer does not fit upcoming bookings. Those always keep their
    booked times; nothing is moved or cancelled by saving."""

    keep_existing_appointments: bool = False


class SchedulePreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: date
    consultation_minutes: int = Field(ge=5, le=240)
    buffer_minutes: int = Field(default=0, ge=0, le=120)


class PreviewSlot(BaseModel):
    starts_at: datetime
    ends_at: datetime
    # free; booked = overlaps an existing appointment; past = already started.
    status: Literal["free", "booked", "past"]


class AffectedAppointment(BaseModel):
    """An upcoming booking that does not match the proposed length/grid. It
    keeps its time; listed so the doctor can decide (no patient details)."""

    id: uuid.UUID
    starts_at: datetime
    ends_at: datetime
    duration_minutes: int


class SchedulePreview(BaseModel):
    doctor_id: uuid.UUID
    date: date
    timezone: str
    consultation_minutes: int
    buffer_minutes: int
    # The day's working time after breaks, leave and blocks, local "HH:MM".
    working_hours: list[tuple[str, str]]
    slots: list[PreviewSlot]
    free_count: int
    booked_count: int
    affected_count: int
    affected: list[AffectedAppointment]


class WalkInCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doctor_id: uuid.UUID
    # Staff register someone who is here (checked in at once); a patient asks for
    # their own token (checked in by reception on arrival).
    patient_id: uuid.UUID | None = None
    session_date: date | None = None
    note: str | None = Field(default=None, max_length=300)


class DeferBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minutes: int = Field(ge=5, le=240)
    note: str | None = Field(default=None, max_length=300)


class QueueActionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, max_length=300)


class WaitEstimate(BaseModel):
    """A range, never a promise: consultations vary."""

    min_minutes: int
    max_minutes: int


class QueueEntryRead(BaseModel):
    id: uuid.UUID
    token_number: int
    kind: QueueKind
    state: QueueState
    session_date: date
    doctor_id: uuid.UUID
    # Staff and the doctor only (None on a patient's own view of others: never sent).
    patient_id: uuid.UUID | None = None
    patient_name: str | None = None
    appointment_id: uuid.UUID | None = None
    scheduled_at: datetime | None = None
    checked_in_at: datetime | None = None
    called_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    deferred_until: datetime | None = None
    prioritized: bool = False
    late: bool = False
    position: int | None = None  # 1 = next; None when not waiting
    estimated_wait: WaitEstimate | None = None
    note: str | None = None


class UpcomingScheduled(BaseModel):
    """Today's booked patients who have not checked in yet."""

    appointment_id: uuid.UUID
    patient_id: uuid.UUID
    patient_name: str
    scheduled_at: datetime
    status: str
    late: bool


class QueueBoard(BaseModel):
    doctor_id: uuid.UUID
    doctor_name: str
    session_date: date
    timezone: str
    policy: SchedulingPolicyRead
    current: QueueEntryRead | None = None
    called: QueueEntryRead | None = None
    waiting: list[QueueEntryRead] = []
    registered: list[QueueEntryRead] = []
    finished: list[QueueEntryRead] = []
    not_arrived: list[UpcomingScheduled] = []
    # Doctor is in consultation past the expected length: everyone may wait longer.
    running_late_minutes: int = 0


class SessionSummary(BaseModel):
    doctor_id: uuid.UUID
    doctor_name: str
    department_name: str | None
    mode: SchedulingMode
    hours: list[tuple[str, str]]
    waiting: int
    in_consultation: bool


class CallResult(BaseModel):
    entry: QueueEntryRead
    # Set when a walk-in was called although a booked patient is due within the
    # consultation length (no other patient was here).
    may_delay_scheduled: bool = False


class MyQueueEntry(BaseModel):
    """A patient's own place: no other patient's details."""

    id: uuid.UUID
    token_number: int
    kind: QueueKind
    state: QueueState
    session_date: date
    doctor_id: uuid.UUID
    doctor_name: str
    timezone: str
    scheduled_at: datetime | None = None
    position: int | None = None
    estimated_wait: WaitEstimate | None = None
