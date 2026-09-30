"""Bookable slots, computed on demand (architecture §9, D9).

    weekly templates (local wall-clock, expanded in the department timezone)
  + extra-availability exceptions
  − leave / holiday / block exceptions
  − existing active appointments
  bounded by the booking lead time and maximum advance

Nothing here is stored: a slot is free exactly when this computation says so,
and the database's overlap constraint on appointments is the final arbiter
under concurrency.
"""

import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BusinessRuleError, NotFoundError
from app.models.department import Department
from app.models.doctor import Doctor
from app.models.schedule import ExceptionKind, ScheduleException, ScheduleTemplate

MAX_RANGE_DAYS = 31


@dataclass(frozen=True, order=True)
class Slot:
    starts_at: datetime
    ends_at: datetime

    def overlaps(self, start: datetime, end: datetime) -> bool:
        return self.starts_at < end and start < self.ends_at


# ---- pure functions (no I/O) -------------------------------------------------


def slice_window(start: datetime, end: datetime, minutes: int) -> list[Slot]:
    """Cut [start, end) into consecutive slots; a trailing partial slot is dropped."""
    step = timedelta(minutes=minutes)
    slots, cursor = [], start
    while cursor + step <= end:
        slots.append(Slot(cursor.astimezone(UTC), (cursor + step).astimezone(UTC)))
        cursor += step
    return slots


def expand_templates(
    templates: Iterable[ScheduleTemplate], tz: ZoneInfo, date_from: date, date_to: date
) -> list[Slot]:
    """Materialise template slots for each local calendar date in [date_from, date_to].

    Arithmetic happens on local wall-clock datetimes, so a 09:00 template is
    09:00 local on both sides of a DST change.
    """
    slots: list[Slot] = []
    day = date_from
    while day <= date_to:
        for t in templates:
            if t.weekday != day.weekday() or day < t.valid_from or (t.valid_until and day > t.valid_until):
                continue
            start = datetime.combine(day, t.start_time, tzinfo=tz)
            end = datetime.combine(day, t.end_time, tzinfo=tz)
            slots.extend(slice_window(start, end, t.slot_minutes))
        day += timedelta(days=1)
    return slots


def remove_busy(slots: Iterable[Slot], busy: Sequence[tuple[datetime, datetime]]) -> list[Slot]:
    return [s for s in slots if not any(s.overlaps(start, end) for start, end in busy)]


# ---- database-backed -----------------------------------------------------------


@dataclass(frozen=True)
class BookableDoctor:
    doctor: Doctor
    timezone: ZoneInfo


async def bookable_doctor(db: AsyncSession, doctor_id: uuid.UUID) -> BookableDoctor:
    """The doctor, if they can currently receive appointments."""
    row = (
        await db.execute(
            select(Doctor, Department.timezone)
            .join(Department, Department.id == Doctor.department_id)
            .where(Doctor.id == doctor_id, Doctor.is_active.is_(True), Department.is_active.is_(True))
        )
    ).one_or_none()
    if row is None:
        raise NotFoundError("Doctor not found or not accepting appointments", code="DOCTOR_UNAVAILABLE")
    return BookableDoctor(row[0], ZoneInfo(row[1]))


async def _busy_appointments(
    db: AsyncSession, doctor_id: uuid.UUID, start: datetime, end: datetime, exclude_id: uuid.UUID | None
) -> list[tuple[datetime, datetime]]:
    # Imported here: appointments depend on availability, not the other way round.
    from app.models.appointment import ACTIVE_STATUSES, Appointment

    query = select(Appointment.starts_at, Appointment.ends_at).where(
        Appointment.doctor_id == doctor_id,
        Appointment.status.in_(ACTIVE_STATUSES),
        Appointment.starts_at < end,
        Appointment.ends_at > start,
    )
    if exclude_id is not None:
        query = query.where(Appointment.id != exclude_id)
    return [tuple(r) for r in (await db.execute(query)).all()]


async def available_slots(
    db: AsyncSession,
    doctor_id: uuid.UUID,
    date_from: date,
    date_to: date,
    *,
    now: datetime,
    min_lead: timedelta,
    exclude_appointment_id: uuid.UUID | None = None,
) -> tuple[BookableDoctor, list[Slot]]:
    if date_to < date_from:
        raise BusinessRuleError("date_to must not be before date_from", code="INVALID_RANGE")
    if (date_to - date_from).days + 1 > MAX_RANGE_DAYS:
        raise BusinessRuleError(f"At most {MAX_RANGE_DAYS} days per request", code="RANGE_TOO_LARGE")

    bookable = await bookable_doctor(db, doctor_id)
    tz = bookable.timezone
    window_start = datetime.combine(date_from, time.min, tzinfo=tz)
    window_end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=tz)

    templates = (
        await db.scalars(
            select(ScheduleTemplate).where(
                ScheduleTemplate.doctor_id == doctor_id,
                ScheduleTemplate.is_active.is_(True),
                ScheduleTemplate.valid_from <= date_to,
                or_(ScheduleTemplate.valid_until.is_(None), ScheduleTemplate.valid_until >= date_from),
            )
        )
    ).all()
    exceptions = (
        await db.scalars(
            select(ScheduleException).where(
                ScheduleException.doctor_id == doctor_id,
                ScheduleException.starts_at < window_end,
                ScheduleException.ends_at > window_start,
            )
        )
    ).all()

    slots = expand_templates(templates, tz, date_from, date_to)
    for exc in exceptions:
        if exc.kind is ExceptionKind.extra_availability:
            slots.extend(slice_window(exc.starts_at.astimezone(tz), exc.ends_at.astimezone(tz), settings.default_slot_minutes))

    blocking = [(e.starts_at, e.ends_at) for e in exceptions if e.kind is not ExceptionKind.extra_availability]
    blocking += await _busy_appointments(db, doctor_id, window_start, window_end, exclude_appointment_id)

    earliest = now + min_lead
    latest = now + timedelta(days=settings.booking_max_advance_days)
    free = {
        s
        for s in remove_busy(slots, blocking)
        if s.starts_at >= earliest and s.starts_at <= latest and window_start <= s.starts_at < window_end
    }
    return bookable, sorted(free)


# ---- directory status (many doctors at once) ---------------------------------------


class AvailabilityStatus(StrEnum):
    # At least one bookable slot in the coming days.
    available = "available"
    # Working in the coming days, but every slot is taken.
    busy = "busy"
    # No working hours in the coming days (no schedule, or on leave).
    unavailable = "unavailable"


@dataclass(frozen=True)
class DoctorAvailability:
    status: AvailabilityStatus
    next_available: datetime | None = None


async def availability_status(
    db: AsyncSession, doctor_ids: Sequence[uuid.UUID], *, now: datetime
) -> dict[uuid.UUID, DoctorAvailability]:
    """Availability badge for each doctor, over the next
    ``settings.availability_status_days`` days.

    Uses the same templates, exceptions and bookings as ``available_slots`` (so
    the badge and the bookable slots cannot disagree), but in four queries for
    the whole list instead of several per doctor. Judged from a patient's
    point of view: the booking lead time applies.
    """
    from app.models.appointment import ACTIVE_STATUSES, Appointment

    result = {doctor_id: DoctorAvailability(AvailabilityStatus.unavailable) for doctor_id in doctor_ids}
    if not doctor_ids:
        return result

    timezones = dict(
        (
            await db.execute(
                select(Doctor.id, Department.timezone)
                .join(Department, Department.id == Doctor.department_id)
                .where(Doctor.id.in_(doctor_ids), Doctor.is_active.is_(True), Department.is_active.is_(True))
            )
        ).all()
    )
    earliest = now + timedelta(minutes=settings.booking_min_lead_minutes)
    horizon = now + timedelta(days=settings.availability_status_days)
    # One day either side covers every department timezone.
    first_day, last_day = (now - timedelta(days=1)).date(), (horizon + timedelta(days=1)).date()

    templates: dict[uuid.UUID, list[ScheduleTemplate]] = defaultdict(list)
    for template in await db.scalars(
        select(ScheduleTemplate).where(
            ScheduleTemplate.doctor_id.in_(timezones),
            ScheduleTemplate.is_active.is_(True),
            ScheduleTemplate.valid_from <= last_day,
            or_(ScheduleTemplate.valid_until.is_(None), ScheduleTemplate.valid_until >= first_day),
        )
    ):
        templates[template.doctor_id].append(template)

    exceptions: dict[uuid.UUID, list[ScheduleException]] = defaultdict(list)
    for exception in await db.scalars(
        select(ScheduleException).where(
            ScheduleException.doctor_id.in_(timezones),
            ScheduleException.starts_at < horizon,
            ScheduleException.ends_at > now,
        )
    ):
        exceptions[exception.doctor_id].append(exception)

    booked: dict[uuid.UUID, list[tuple[datetime, datetime]]] = defaultdict(list)
    for doctor_id, starts_at, ends_at in await db.execute(
        select(Appointment.doctor_id, Appointment.starts_at, Appointment.ends_at).where(
            Appointment.doctor_id.in_(timezones),
            Appointment.status.in_(ACTIVE_STATUSES),
            Appointment.starts_at < horizon,
            Appointment.ends_at > now,
        )
    ):
        booked[doctor_id].append((starts_at, ends_at))

    for doctor_id, tz_name in timezones.items():
        tz = ZoneInfo(tz_name)
        slots = expand_templates(templates[doctor_id], tz, first_day, last_day)
        blocking = []
        for exception in exceptions[doctor_id]:
            if exception.kind is ExceptionKind.extra_availability:
                slots.extend(
                    slice_window(
                        exception.starts_at.astimezone(tz), exception.ends_at.astimezone(tz), settings.default_slot_minutes
                    )
                )
            else:
                blocking.append((exception.starts_at, exception.ends_at))
        working = [s for s in remove_busy(slots, blocking) if earliest <= s.starts_at <= horizon]
        free = remove_busy(working, booked[doctor_id])
        if free:
            result[doctor_id] = DoctorAvailability(AvailabilityStatus.available, min(free).starts_at)
        elif working:
            result[doctor_id] = DoctorAvailability(AvailabilityStatus.busy)
    return result
