"""The day's queue: scheduled and walk-in patients of one doctor (D117).

One coordinator decides the order for everything (the staff board, "call
next", a patient's own position, the assistant):

  0. patients staff moved to the front (audited), in the order that was done;
  1. checked-in booked patients whose reserved time has come, by that time;
  2. everyone else waiting, by their time: a booked patient's reserved time,
     a walk-in's check-in time (FIFO, by eligible check-in);
  3. deferred patients, until their deferral ends.
  Ties: the token number (issued in check-in order) decides.

"Call next" takes the first of that order, with one rule for walk-ins: a
walk-in is called only when the consultation fits before the next booked
time; otherwise a booked patient who is already here goes first, and only if
none is here is the walk-in called anyway (flagged as possibly delaying the
booked patient). Nobody is marked absent or a no-show automatically.

Tokens are stable numbers per doctor and local date, issued by an atomic
counter; the position is computed each time it is read. The database allows
one called patient and one consultation per doctor at a time.
"""

import logging
import math
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.config import settings
from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError, PermissionDeniedError
from app.core.permissions import Perm, Principal
from app.models.appointment import Appointment, AppointmentStatus
from app.models.department import Department
from app.models.doctor import Doctor
from app.models.patient import Patient
from app.models.schedule import ScheduleException, ScheduleTemplate
from app.models.scheduling import OPEN_QUEUE_STATES, QueueEntry, QueueKind, QueueState, SchedulingMode, SchedulingPolicy
from app.models.user import User
from app.schemas.scheduling import (
    CallResult,
    MyQueueEntry,
    QueueBoard,
    QueueEntryRead,
    SessionSummary,
    UpcomingScheduled,
    WaitEstimate,
    WalkInCreate,
)
from app.services import audit_service, availability_service, scheduling_service
from app.services.audit_service import AuditAction
from app.services.scheduling_service import EffectivePolicy

logger = logging.getLogger(__name__)

S = AppointmentStatus
Q = QueueState


# ---- the coordinator (pure: no I/O) ------------------------------------------------------


@dataclass(frozen=True)
class Waiting:
    """A queue entry as the coordinator sees it."""

    entry: QueueEntry
    scheduled_at: datetime | None  # the appointment's reserved start; None for a walk-in


def _group(w: Waiting, now: datetime) -> int:
    e = w.entry
    if e.deferred_until is not None and e.deferred_until > now:
        return 3
    if e.prioritized_at is not None:
        return 0
    if w.scheduled_at is not None and w.scheduled_at <= now:
        return 1
    return 2


def queue_key(w: Waiting, now: datetime) -> tuple:
    group = _group(w, now)
    e = w.entry
    if group == 3:
        moment = e.deferred_until
    elif group == 0:
        moment = e.prioritized_at
    else:
        moment = w.scheduled_at if w.scheduled_at is not None else e.checked_in_at
    return (group, moment, e.token_number)


def order(waiting: Sequence[Waiting], now: datetime) -> list[Waiting]:
    """Checked-in patients in the order they should be seen."""
    return sorted(waiting, key=lambda w: queue_key(w, now))


def choose_next(
    waiting: Sequence[Waiting], now: datetime, consultation_minutes: int, next_reservation: datetime | None
) -> tuple[Waiting | None, bool]:
    """(who to call, whether calling them may delay a booked patient)."""
    ordered = [w for w in order(waiting, now) if _group(w, now) < 3]
    if not ordered:
        return None, False
    first = ordered[0]
    if _group(first, now) < 2 or first.scheduled_at is not None:
        return first, False
    # A walk-in: does a consultation fit before the next reserved time?
    if next_reservation is None or next_reservation - now >= timedelta(minutes=consultation_minutes):
        return first, False
    early = next((w for w in ordered if w.scheduled_at is not None), None)
    if early is not None:
        return early, False
    return first, True


def _round(minutes: float, up: bool) -> int:
    value = math.ceil(minutes / 5) * 5 if up else math.floor(minutes / 5) * 5
    return max(0, int(value))


def estimate(ahead: int, consultation_minutes: int, now: datetime, scheduled_at: datetime | None, overrun: int = 0) -> WaitEstimate:
    """A range for the wait, never one exact number: consultations vary."""
    low = ahead * consultation_minutes * 0.75
    high = ahead * consultation_minutes * 1.5 + overrun
    if scheduled_at is not None and scheduled_at > now:
        until = (scheduled_at - now).total_seconds() / 60
        low, high = max(low, until), max(high, until + consultation_minutes / 2)
    return WaitEstimate(min_minutes=_round(low, up=False), max_minutes=max(_round(high, up=True), 5))


# ---- helpers ------------------------------------------------------------------------------


@dataclass(frozen=True)
class DoctorInfo:
    doctor_id: uuid.UUID
    name: str
    timezone: ZoneInfo
    department_name: str | None
    user_id: uuid.UUID


async def _doctor(db: AsyncSession, doctor_id: uuid.UUID) -> DoctorInfo:
    row = (
        await db.execute(
            select(Doctor.id, Doctor.title, User.name, Department.timezone, Department.name, User.id)
            .join(User, User.id == Doctor.user_id)
            .join(Department, Department.id == Doctor.department_id)
            .where(Doctor.id == doctor_id)
        )
    ).one_or_none()
    if row is None:
        raise NotFoundError("Doctor not found")
    return DoctorInfo(row[0], " ".join(filter(None, [row[1], row[2]])), ZoneInfo(row[3]), row[4], row[5])


def _today(tz: ZoneInfo) -> date:
    return clock.utcnow().astimezone(tz).date()


def _is_staff(principal: Principal) -> bool:
    return principal.has(Perm.appointment_check_in)


def _is_the_doctor(principal: Principal, doctor_id: uuid.UUID) -> bool:
    return principal.has(Perm.appointment_consult) and principal.doctor_id == doctor_id


def _ensure_staff_or_doctor(principal: Principal, doctor_id: uuid.UUID) -> None:
    if not (_is_staff(principal) or _is_the_doctor(principal, doctor_id)):
        raise PermissionDeniedError("You cannot manage this doctor's queue")


async def _lock_session(db: AsyncSession, doctor_id: uuid.UUID, day: date) -> None:
    """Serialize changes to one doctor's queue for one day (released at commit)."""
    await db.execute(text("SELECT pg_advisory_xact_lock(3, hashtext(:key))"), {"key": f"{doctor_id}:{day.isoformat()}"})


async def next_token(db: AsyncSession, doctor_id: uuid.UUID, day: date) -> int:
    """The next token number for this doctor and day: one atomic statement, so
    concurrent requests always get different numbers."""
    return await db.scalar(
        text(
            "INSERT INTO queue_token_counters (doctor_id, session_date, last_token) VALUES (:d, :s, 1) "
            "ON CONFLICT (doctor_id, session_date) DO UPDATE SET last_token = queue_token_counters.last_token + 1 "
            "RETURNING last_token"
        ),
        {"d": doctor_id, "s": day},
    )


async def _flush(db: AsyncSession) -> None:
    """Flush in a savepoint: a unique-index race becomes a clean 409."""
    try:
        async with db.begin_nested():
            await db.flush()
    except IntegrityError as exc:
        name = str(getattr(getattr(exc.orig, "__cause__", None), "constraint_name", "") or exc)
        if "one_consultation" in name:
            raise ConflictError("This doctor already has a patient in consultation", code="CONSULTATION_IN_PROGRESS") from None
        if "one_called" in name:
            raise ConflictError("A patient has already been called and is not in yet", code="ALREADY_CALLED") from None
        if "open_walk_in" in name:
            raise ConflictError("This patient already has a token for this doctor today", code="ALREADY_IN_QUEUE") from None
        raise ConflictError("The queue changed at the same time; please try again", code="QUEUE_RACE") from None


def _audit(db: AsyncSession, principal: Principal, action: AuditAction, entry: QueueEntry, **details) -> None:
    audit_service.record(
        db, action, actor_id=principal.user_id, target_type="queue_entry", target_id=entry.id,
        details={"doctor_id": str(entry.doctor_id), "session_date": entry.session_date.isoformat(),
                 "token": entry.token_number, **details},
    )


async def _active_consultation(db: AsyncSession, doctor_id: uuid.UUID, exclude: uuid.UUID | None = None) -> bool:
    query = select(QueueEntry.id).where(QueueEntry.doctor_id == doctor_id, QueueEntry.state == Q.in_consultation)
    if exclude is not None:
        query = query.where(QueueEntry.id != exclude)
    return await db.scalar(query.limit(1)) is not None


# ---- hooks from the appointment state machine ------------------------------------------------


async def on_appointment_status(db: AsyncSession, appt: Appointment, status: AppointmentStatus, principal: Principal) -> None:
    """Keep the queue in step with an appointment's status (called inside the
    status change's transaction, before it commits)."""
    entry = await db.scalar(select(QueueEntry).where(QueueEntry.appointment_id == appt.id).with_for_update())
    now = clock.utcnow()
    if status in (S.checked_in, S.in_progress) and entry is None:
        tz = (await _doctor(db, appt.doctor_id)).timezone
        day = appt.starts_at.astimezone(tz).date()
        await _lock_session(db, appt.doctor_id, day)
        entry = QueueEntry(
            doctor_id=appt.doctor_id, session_date=day, token_number=await next_token(db, appt.doctor_id, day),
            kind=QueueKind.scheduled, state=Q.waiting, patient_id=appt.patient_id, appointment_id=appt.id,
            checked_in_at=now, created_by_user_id=principal.user_id,
        )
        db.add(entry)
    if entry is None:
        return
    if status is S.in_progress:
        if await _active_consultation(db, appt.doctor_id, exclude=entry.id):
            raise ConflictError("Finish the current consultation before starting another", code="CONSULTATION_IN_PROGRESS")
        entry.state, entry.started_at = Q.in_consultation, now
        entry.called_at = entry.called_at or now
    elif status is S.completed:
        entry.state, entry.completed_at = Q.completed, now
    elif status is S.cancelled:
        entry.state = Q.cancelled
    elif status is S.no_show:
        entry.state = Q.no_show
    await _flush(db)


# ---- reading ---------------------------------------------------------------------------------


async def _entries(db: AsyncSession, doctor_id: uuid.UUID, day: date) -> list[tuple[QueueEntry, datetime | None, str]]:
    rows = await db.execute(
        select(QueueEntry, Appointment.starts_at, Patient.first_name, Patient.last_name)
        .join(Patient, Patient.id == QueueEntry.patient_id)
        .outerjoin(Appointment, Appointment.id == QueueEntry.appointment_id)
        .where(QueueEntry.doctor_id == doctor_id, QueueEntry.session_date == day)
        .order_by(QueueEntry.token_number)
    )
    return [(e, starts, f"{first} {last}") for e, starts, first, last in rows]


async def _next_reservation(db: AsyncSession, doctor_id: uuid.UUID, now: datetime, grace: int) -> datetime | None:
    """The earliest reserved time still ahead (or within its grace): booked patients
    not yet seen, who keep priority for their time even before they arrive."""
    return await db.scalar(
        select(func.min(Appointment.starts_at))
        .outerjoin(QueueEntry, QueueEntry.appointment_id == Appointment.id)
        .where(
            Appointment.doctor_id == doctor_id,
            Appointment.status.in_((S.scheduled, S.confirmed, S.checked_in)),
            Appointment.starts_at >= now - timedelta(minutes=grace),
            Appointment.starts_at < now + timedelta(hours=12),
            (QueueEntry.id.is_(None)) | (QueueEntry.state.in_((Q.waiting, Q.absent))),
        )
    )


def _late(scheduled_at: datetime | None, arrived: datetime | None, now: datetime, grace: int) -> bool:
    if scheduled_at is None:
        return False
    return (arrived or now) > scheduled_at + timedelta(minutes=grace)


def _read(
    entry: QueueEntry, scheduled_at: datetime | None, name: str | None, policy: EffectivePolicy, now: datetime,
    position: int | None = None, wait: WaitEstimate | None = None,
) -> QueueEntryRead:
    return QueueEntryRead(
        id=entry.id, token_number=entry.token_number, kind=entry.kind, state=entry.state, session_date=entry.session_date,
        doctor_id=entry.doctor_id, patient_id=entry.patient_id, patient_name=name, appointment_id=entry.appointment_id,
        scheduled_at=scheduled_at, checked_in_at=entry.checked_in_at, called_at=entry.called_at, started_at=entry.started_at,
        completed_at=entry.completed_at, deferred_until=entry.deferred_until if entry.deferred_until and entry.deferred_until > now else None,
        prioritized=entry.prioritized_at is not None, late=_late(scheduled_at, entry.checked_in_at, now, policy.late_grace_minutes),
        position=position, estimated_wait=wait, note=entry.note,
    )


@dataclass
class _Snapshot:
    rows: list[tuple[QueueEntry, datetime | None, str]]
    waiting: list[Waiting]
    current: tuple | None
    called: tuple | None
    overrun: int


def _snapshot(rows, policy: EffectivePolicy, now: datetime) -> _Snapshot:
    waiting = [Waiting(e, starts) for e, starts, _ in rows if e.state is Q.waiting]
    current = next(((e, s, n) for e, s, n in rows if e.state is Q.in_consultation), None)
    called = next(((e, s, n) for e, s, n in rows if e.state is Q.called), None)
    overrun = 0
    if current is not None and current[0].started_at is not None:
        elapsed = (now - current[0].started_at).total_seconds() / 60
        overrun = max(0, int(elapsed - policy.consultation_minutes))
    return _Snapshot(rows, waiting, current, called, overrun)


def _positions(snap: _Snapshot, policy: EffectivePolicy, now: datetime) -> dict[uuid.UUID, tuple[int, WaitEstimate]]:
    busy = (1 if snap.current else 0) + (1 if snap.called else 0)
    result = {}
    for index, w in enumerate(order(snap.waiting, now)):
        ahead = index + busy
        result[w.entry.id] = (index + 1, estimate(ahead, policy.consultation_minutes, now, w.scheduled_at, snap.overrun))
    return result


async def board(db: AsyncSession, principal: Principal, doctor_id: uuid.UUID, day: date | None = None) -> QueueBoard:
    _ensure_staff_or_doctor(principal, doctor_id)
    doctor = await _doctor(db, doctor_id)
    day = day or _today(doctor.timezone)
    policy_row = await db.get(SchedulingPolicy, doctor_id)
    policy = scheduling_service.effective(policy_row)
    now = clock.utcnow()
    rows = await _entries(db, doctor_id, day)
    snap = _snapshot(rows, policy, now)
    positions = _positions(snap, policy, now)

    def read(row, with_position=False):
        e, s, n = row
        pos = positions.get(e.id) if with_position else None
        return _read(e, s, n, policy, now, *(pos or (None, None)))

    waiting_rows = {w.entry.id: (w.entry, w.scheduled_at) for w in snap.waiting}
    names = {e.id: n for e, _, n in rows}
    waiting = [read((waiting_rows[i][0], waiting_rows[i][1], names[i]), True) for i in sorted(positions, key=lambda i: positions[i][0])]

    day_start = datetime.combine(day, time.min, tzinfo=doctor.timezone)
    seen = {e.appointment_id for e, _, _ in rows if e.appointment_id}
    pending = await db.execute(
        select(Appointment.id, Appointment.patient_id, Appointment.starts_at, Appointment.status, Patient.first_name, Patient.last_name)
        .join(Patient, Patient.id == Appointment.patient_id)
        .where(
            Appointment.doctor_id == doctor_id,
            Appointment.status.in_((S.scheduled, S.confirmed)),
            Appointment.starts_at >= day_start,
            Appointment.starts_at < day_start + timedelta(days=1),
        )
        .order_by(Appointment.starts_at)
    )
    not_arrived = [
        UpcomingScheduled(
            appointment_id=a_id, patient_id=p_id, patient_name=f"{first} {last}", scheduled_at=starts, status=status.value,
            late=_late(starts, None, now, policy.late_grace_minutes),
        )
        for a_id, p_id, starts, status, first, last in pending
        if a_id not in seen
    ]
    from app.services.scheduling_service import _read as read_policy

    return QueueBoard(
        doctor_id=doctor_id, doctor_name=doctor.name, session_date=day, timezone=str(doctor.timezone),
        policy=await read_policy(db, doctor_id, policy_row),
        current=read(snap.current) if snap.current else None,
        called=read(snap.called) if snap.called else None,
        waiting=waiting,
        registered=[read(r) for r in rows if r[0].state is Q.registered],
        finished=[read(r) for r in rows if r[0].state in (Q.completed, Q.absent, Q.no_show, Q.cancelled)],
        not_arrived=not_arrived,
        running_late_minutes=snap.overrun,
    )


async def sessions(db: AsyncSession, principal: Principal, day: date | None = None) -> list[SessionSummary]:
    """Today's (or `day`'s) working doctors with their queue counts, for the front desk."""
    if not _is_staff(principal):
        raise PermissionDeniedError("Only the front desk can see every doctor's session")
    doctors = (
        await db.execute(
            select(Doctor.id, Doctor.title, User.name, Department.name, Department.timezone)
            .join(User, User.id == Doctor.user_id)
            .join(Department, Department.id == Doctor.department_id)
            .where(Doctor.is_active.is_(True), Department.is_active.is_(True), User.is_active.is_(True))
            .order_by(User.name)
        )
    ).all()
    if not doctors:
        return []
    ids = [d[0] for d in doctors]
    some_tz = ZoneInfo(doctors[0][4])
    day = day or _today(some_tz)
    templates: dict = {i: [] for i in ids}
    for t in await db.scalars(
        select(ScheduleTemplate).where(
            ScheduleTemplate.doctor_id.in_(ids), ScheduleTemplate.is_active.is_(True), ScheduleTemplate.weekday == day.weekday(),
            ScheduleTemplate.valid_from <= day, (ScheduleTemplate.valid_until.is_(None)) | (ScheduleTemplate.valid_until >= day),
        )
    ):
        templates[t.doctor_id].append(t)
    window = (datetime.combine(day - timedelta(days=1), time.min, tzinfo=some_tz), datetime.combine(day + timedelta(days=2), time.min, tzinfo=some_tz))
    exceptions: dict = {i: [] for i in ids}
    for e in await db.scalars(
        select(ScheduleException).where(
            ScheduleException.doctor_id.in_(ids), ScheduleException.starts_at < window[1], ScheduleException.ends_at > window[0]
        )
    ):
        exceptions[e.doctor_id].append(e)
    policies = {p.doctor_id: p for p in await db.scalars(select(SchedulingPolicy).where(SchedulingPolicy.doctor_id.in_(ids)))}
    counts = {
        (d, s): n
        for d, s, n in await db.execute(
            select(QueueEntry.doctor_id, QueueEntry.state, func.count())
            .where(QueueEntry.doctor_id.in_(ids), QueueEntry.session_date == day)
            .group_by(QueueEntry.doctor_id, QueueEntry.state)
        )
    }
    result = []
    for doctor_id, title, name, dept, tz_name in doctors:
        tz = ZoneInfo(tz_name)
        windows = availability_service.working_windows(templates[doctor_id], exceptions[doctor_id], tz, day)
        if not windows:
            continue
        result.append(
            SessionSummary(
                doctor_id=doctor_id, doctor_name=" ".join(filter(None, [title, name])), department_name=dept,
                mode=scheduling_service.effective(policies.get(doctor_id)).mode,
                hours=[(a.astimezone(tz).strftime("%H:%M"), b.astimezone(tz).strftime("%H:%M")) for a, b in windows],
                waiting=counts.get((doctor_id, Q.waiting), 0) + counts.get((doctor_id, Q.called), 0),
                in_consultation=counts.get((doctor_id, Q.in_consultation), 0) > 0,
            )
        )
    return result


async def my_queue(db: AsyncSession, principal: Principal) -> list[MyQueueEntry]:
    """The signed-in patient's own tokens from today on, with their place and an
    estimated wait. Nothing about other patients is returned."""
    if principal.patient_id is None:
        return []
    mine = (
        await db.scalars(
            select(QueueEntry)
            .where(QueueEntry.patient_id == principal.patient_id, QueueEntry.state.in_(OPEN_QUEUE_STATES))
            .order_by(QueueEntry.session_date, QueueEntry.token_number)
        )
    ).all()
    result = []
    now = clock.utcnow()
    for entry in mine:
        doctor = await _doctor(db, entry.doctor_id)
        if entry.session_date < _today(doctor.timezone):
            continue
        policy = await scheduling_service.effective_policy(db, entry.doctor_id)
        rows = await _entries(db, entry.doctor_id, entry.session_date)
        snap = _snapshot(rows, policy, now)
        position, wait = _positions(snap, policy, now).get(entry.id, (None, None))
        scheduled_at = next((s for e, s, _ in rows if e.id == entry.id), None)
        result.append(
            MyQueueEntry(
                id=entry.id, token_number=entry.token_number, kind=entry.kind, state=entry.state, session_date=entry.session_date,
                doctor_id=entry.doctor_id, doctor_name=doctor.name, timezone=str(doctor.timezone), scheduled_at=scheduled_at,
                position=position, estimated_wait=wait,
            )
        )
    return result


# ---- changing the queue ----------------------------------------------------------------------


async def _locked_entry(db: AsyncSession, entry_id: uuid.UUID) -> QueueEntry:
    entry = await db.scalar(select(QueueEntry).where(QueueEntry.id == entry_id).with_for_update())
    if entry is None:
        raise NotFoundError("Queue entry not found")
    return entry


async def _entry_read(db: AsyncSession, principal: Principal, entry: QueueEntry) -> QueueEntryRead:
    policy = await scheduling_service.effective_policy(db, entry.doctor_id)
    rows = await _entries(db, entry.doctor_id, entry.session_date)
    now = clock.utcnow()
    position, wait = _positions(_snapshot(rows, policy, now), policy, now).get(entry.id, (None, None))
    _, scheduled_at, name = next(r for r in rows if r[0].id == entry.id)
    return _read(entry, scheduled_at, name, policy, now, position, wait)


async def register_walk_in(db: AsyncSession, principal: Principal, data: WalkInCreate) -> QueueEntryRead:
    """Staff: a walk-in who is here (checked in now). Patient: their own token,
    checked in by reception on arrival. Both within the doctor's policy."""
    staff = _is_staff(principal)
    if staff:
        if data.patient_id is None:
            raise BusinessRuleError("Choose the patient", code="PATIENT_REQUIRED")
        from app.services import access

        patient = await db.scalar(select(Patient).where(Patient.id == data.patient_id, access.patient_visibility(principal)))
    else:
        if not principal.has(Perm.appointment_create_own) or principal.patient_id is None:
            raise PermissionDeniedError("You cannot request a token")
        if data.patient_id not in (None, principal.patient_id):
            raise NotFoundError("Patient not found")
        patient = await db.get(Patient, principal.patient_id)
    if patient is None:
        raise NotFoundError("Patient not found")
    if not patient.is_active:
        raise BusinessRuleError("Patient record is inactive", code="PATIENT_INACTIVE")

    bookable = await availability_service.bookable_doctor(db, data.doctor_id)
    tz = bookable.timezone
    today = _today(tz)
    day = data.session_date or today
    if staff and day != today:
        raise BusinessRuleError("Walk-ins are registered for today", code="WALK_IN_TODAY_ONLY")
    if not today <= day <= today + timedelta(days=settings.booking_max_advance_days):
        raise BusinessRuleError("Choose a date from today within the booking horizon", code="DATE_OUT_OF_RANGE")
    policy = await scheduling_service.effective_policy(db, data.doctor_id)
    if not policy.walk_ins_open:
        raise BusinessRuleError("This doctor sees booked appointments only", code="WALK_INS_NOT_ACCEPTED")
    templates, exceptions = await availability_service._schedule_rules(
        db, data.doctor_id, day, day, datetime.combine(day, time.min, tzinfo=tz), datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz)
    )
    windows = availability_service.working_windows(templates, exceptions, tz, day)
    now = clock.utcnow()
    if not windows or (day == today and windows[-1][1] <= now):
        raise BusinessRuleError("The doctor is not seeing patients then", code="DOCTOR_NOT_WORKING")

    await _lock_session(db, data.doctor_id, day)
    if policy.walk_in_capacity is not None:
        taken = await db.scalar(
            select(func.count()).select_from(QueueEntry).where(
                QueueEntry.doctor_id == data.doctor_id, QueueEntry.session_date == day, QueueEntry.kind == QueueKind.walk_in,
                QueueEntry.state.not_in((Q.cancelled,)),
            )
        )
        if taken >= policy.walk_in_capacity:
            raise ConflictError("No walk-in places are left for this session", code="WALK_IN_CAPACITY_REACHED")
    existing = await db.scalar(
        select(QueueEntry.id).where(
            QueueEntry.doctor_id == data.doctor_id, QueueEntry.session_date == day, QueueEntry.patient_id == patient.id,
            QueueEntry.kind == QueueKind.walk_in, QueueEntry.state.in_(OPEN_QUEUE_STATES),
        )
    )
    if existing is not None:
        raise ConflictError("This patient already has a token for this doctor that day", code="ALREADY_IN_QUEUE")
    entry = QueueEntry(
        doctor_id=data.doctor_id, session_date=day, token_number=await next_token(db, data.doctor_id, day),
        kind=QueueKind.walk_in, state=Q.waiting if staff else Q.registered, patient_id=patient.id,
        checked_in_at=now if staff else None, created_by_user_id=principal.user_id, note=data.note if staff else None,
    )
    db.add(entry)
    await _flush(db)
    _audit(db, principal, AuditAction.queue_walk_in_registered, entry, by_patient=not staff)
    await db.commit()
    logger.info("queue_walk_in_registered", extra={"entry_id": str(entry.id), "doctor_id": str(entry.doctor_id)})
    return await _entry_read(db, principal, entry)


async def check_in(db: AsyncSession, principal: Principal, entry_id: uuid.UUID) -> QueueEntryRead:
    """A registered (or absent) walk-in arrives: they join the order by this check-in time."""
    if not _is_staff(principal):
        raise PermissionDeniedError("Only the front desk can check patients in")
    entry = await _locked_entry(db, entry_id)
    tz = (await _doctor(db, entry.doctor_id)).timezone
    if entry.session_date != _today(tz):
        raise BusinessRuleError("Patients can only be checked in on the day of their token", code="NOT_SESSION_DAY")
    if entry.state not in (Q.registered, Q.absent):
        raise ConflictError("This patient is already in the queue", code="INVALID_QUEUE_STATE")
    entry.state, entry.checked_in_at, entry.deferred_until = Q.waiting, clock.utcnow(), None
    await _flush(db)
    _audit(db, principal, AuditAction.queue_checked_in, entry)
    await db.commit()
    return await _entry_read(db, principal, entry)


async def _call(db: AsyncSession, principal: Principal, entry: QueueEntry, *, override: bool, may_delay: bool) -> CallResult:
    entry.state, entry.called_at, entry.deferred_until = Q.called, clock.utcnow(), None
    entry.prioritized_at = None
    await _flush(db)
    _audit(db, principal, AuditAction.queue_called, entry, override=override, may_delay_scheduled=may_delay)
    await db.commit()
    return CallResult(entry=await _entry_read(db, principal, entry), may_delay_scheduled=may_delay)


async def call_next(db: AsyncSession, principal: Principal, doctor_id: uuid.UUID) -> CallResult:
    _ensure_staff_or_doctor(principal, doctor_id)
    doctor = await _doctor(db, doctor_id)
    day = _today(doctor.timezone)
    await _lock_session(db, doctor_id, day)
    policy = await scheduling_service.effective_policy(db, doctor_id)
    now = clock.utcnow()
    rows = await _entries(db, doctor_id, day)
    if any(e.state is Q.called for e, _, _ in rows):
        raise ConflictError("A patient has already been called and is not in yet", code="ALREADY_CALLED")
    waiting = [Waiting(e, s) for e, s, _ in rows if e.state is Q.waiting]
    chosen, may_delay = choose_next(waiting, now, policy.consultation_minutes, await _next_reservation(db, doctor_id, now, policy.late_grace_minutes))
    if chosen is None:
        raise BusinessRuleError("Nobody is waiting", code="QUEUE_EMPTY")
    entry = await _locked_entry(db, chosen.entry.id)
    return await _call(db, principal, entry, override=False, may_delay=may_delay)


async def call_entry(db: AsyncSession, principal: Principal, entry_id: uuid.UUID) -> CallResult:
    """Call one particular patient out of order (staff or the doctor; audited)."""
    entry = await _locked_entry(db, entry_id)
    _ensure_staff_or_doctor(principal, entry.doctor_id)
    await _lock_session(db, entry.doctor_id, entry.session_date)
    if entry.state is not Q.waiting:
        raise ConflictError("Only a waiting patient can be called", code="INVALID_QUEUE_STATE")
    return await _call(db, principal, entry, override=True, may_delay=False)


async def start(db: AsyncSession, principal: Principal, entry_id: uuid.UUID) -> QueueEntryRead:
    """The doctor starts the consultation (booked patients: the appointment moves to in progress)."""
    entry = await _locked_entry(db, entry_id)
    if not _is_the_doctor(principal, entry.doctor_id):
        raise PermissionDeniedError("Only the patient's doctor can start the consultation")
    if entry.state not in (Q.waiting, Q.called):
        raise ConflictError("This patient is not waiting", code="INVALID_QUEUE_STATE")
    if entry.appointment_id is not None:
        from app.schemas.appointment import StatusChange
        from app.services import appointment_service

        await appointment_service.change_status(db, principal, entry.appointment_id, StatusChange(status=S.in_progress))
        entry = await db.get(QueueEntry, entry_id, populate_existing=True)
    else:
        if await _active_consultation(db, entry.doctor_id, exclude=entry.id):
            raise ConflictError("Finish the current consultation before starting another", code="CONSULTATION_IN_PROGRESS")
        now = clock.utcnow()
        entry.state, entry.started_at, entry.called_at = Q.in_consultation, now, entry.called_at or now
        await _flush(db)
    _audit(db, principal, AuditAction.queue_started, entry)
    await db.commit()
    return await _entry_read(db, principal, entry)


async def complete(db: AsyncSession, principal: Principal, entry_id: uuid.UUID) -> QueueEntryRead:
    entry = await _locked_entry(db, entry_id)
    if not _is_the_doctor(principal, entry.doctor_id):
        raise PermissionDeniedError("Only the patient's doctor can complete the consultation")
    if entry.state is not Q.in_consultation:
        raise ConflictError("This consultation has not started", code="INVALID_QUEUE_STATE")
    if entry.appointment_id is not None:
        from app.schemas.appointment import StatusChange
        from app.services import appointment_service

        await appointment_service.change_status(db, principal, entry.appointment_id, StatusChange(status=S.completed))
        entry = await db.get(QueueEntry, entry_id, populate_existing=True)
    else:
        entry.state, entry.completed_at = Q.completed, clock.utcnow()
        await _flush(db)
    _audit(db, principal, AuditAction.queue_completed, entry)
    await db.commit()
    return await _entry_read(db, principal, entry)


async def defer(db: AsyncSession, principal: Principal, entry_id: uuid.UUID, minutes: int, note: str | None) -> QueueEntryRead:
    """Not callable for `minutes` (e.g. gone for a test); keeps their token."""
    entry = await _locked_entry(db, entry_id)
    _ensure_staff_or_doctor(principal, entry.doctor_id)
    if entry.state not in (Q.waiting, Q.called):
        raise ConflictError("Only a waiting or called patient can be deferred", code="INVALID_QUEUE_STATE")
    entry.state, entry.deferred_until, entry.prioritized_at = Q.waiting, clock.utcnow() + timedelta(minutes=minutes), None
    entry.note = note or entry.note
    await _flush(db)
    _audit(db, principal, AuditAction.queue_deferred, entry, minutes=minutes)
    await db.commit()
    return await _entry_read(db, principal, entry)


async def prioritize(db: AsyncSession, principal: Principal, entry_id: uuid.UUID, note: str | None) -> QueueEntryRead:
    """Move a waiting patient to the front (e.g. urgent need). Audited; it does not
    change anyone's appointment time."""
    entry = await _locked_entry(db, entry_id)
    _ensure_staff_or_doctor(principal, entry.doctor_id)
    if entry.state is not Q.waiting:
        raise ConflictError("Only a waiting patient can be moved", code="INVALID_QUEUE_STATE")
    entry.prioritized_at, entry.deferred_until = clock.utcnow(), None
    entry.note = note or entry.note
    await _flush(db)
    _audit(db, principal, AuditAction.queue_prioritized, entry)
    await db.commit()
    return await _entry_read(db, principal, entry)


async def mark_absent(db: AsyncSession, principal: Principal, entry_id: uuid.UUID) -> QueueEntryRead:
    """Called but not there. They can check in again later (and rejoin by that time)."""
    entry = await _locked_entry(db, entry_id)
    _ensure_staff_or_doctor(principal, entry.doctor_id)
    if entry.state not in (Q.waiting, Q.called):
        raise ConflictError("Only a waiting or called patient can be marked absent", code="INVALID_QUEUE_STATE")
    entry.state, entry.prioritized_at = Q.absent, None
    await _flush(db)
    _audit(db, principal, AuditAction.queue_marked_absent, entry)
    await db.commit()
    return await _entry_read(db, principal, entry)


async def mark_no_show(db: AsyncSession, principal: Principal, entry_id: uuid.UUID) -> QueueEntryRead:
    """Recorded by staff only, never automatically (booked patients: after the
    appointment's no-show grace, through the appointment's own rules)."""
    entry = await _locked_entry(db, entry_id)
    _ensure_staff_or_doctor(principal, entry.doctor_id)
    if entry.state not in (Q.registered, Q.waiting, Q.called, Q.absent):
        raise ConflictError("This patient can no longer be marked a no-show", code="INVALID_QUEUE_STATE")
    if entry.appointment_id is not None:
        raise BusinessRuleError(
            "A booked patient who checked in cannot be a no-show; mark them absent instead", code="CHECKED_IN_NOT_NO_SHOW"
        )
    entry.state = Q.no_show
    await _flush(db)
    _audit(db, principal, AuditAction.queue_marked_no_show, entry)
    await db.commit()
    return await _entry_read(db, principal, entry)


async def cancel(db: AsyncSession, principal: Principal, entry_id: uuid.UUID) -> QueueEntryRead:
    """A walk-in token is withdrawn (by staff, or by the patient for their own)."""
    entry = await _locked_entry(db, entry_id)
    own = principal.patient_id is not None and principal.patient_id == entry.patient_id
    if not (own or _is_staff(principal) or _is_the_doctor(principal, entry.doctor_id)):
        raise NotFoundError("Queue entry not found")
    if entry.kind is not QueueKind.walk_in:
        raise BusinessRuleError("Cancel the appointment itself instead", code="USE_APPOINTMENT_CANCEL")
    if entry.state not in (Q.registered, Q.waiting, Q.absent):
        raise ConflictError("This token can no longer be cancelled", code="INVALID_QUEUE_STATE")
    entry.state = Q.cancelled
    await _flush(db)
    _audit(db, principal, AuditAction.queue_cancelled, entry, by_patient=own)
    await db.commit()
    return await _entry_read(db, principal, entry)

