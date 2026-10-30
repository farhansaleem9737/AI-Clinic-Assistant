"""Bookable slots, computed on demand (architecture §9, D9).

    weekly templates (local wall-clock, expanded in the department timezone)
    — replaced, on a date with a custom-hours exception, by that day's hours
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
from app.models.user import User

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


def by_local_date(slots: Iterable[Slot], tz: ZoneInfo) -> dict[date, list[Slot]]:
    """Group slots by the calendar date they start on in `tz`, in time order."""
    days: dict[date, list[Slot]] = defaultdict(list)
    for slot in sorted(slots):
        days[slot.starts_at.astimezone(tz).date()].append(slot)
    return dict(days)


def bookable_until(now: datetime, tz: ZoneInfo) -> date:
    """The last local date on which anything can still be booked."""
    return (now + timedelta(days=settings.booking_max_advance_days)).astimezone(tz).date()


def remove_busy(slots: Iterable[Slot], busy: Sequence[tuple[datetime, datetime]]) -> list[Slot]:
    return [s for s in slots if not any(s.overlaps(start, end) for start, end in busy)]


def slot_minutes_on(templates: Iterable[ScheduleTemplate], day: date) -> int:
    """Slot length a doctor uses on `day`: that weekday's template, else the default."""
    for t in templates:
        if t.weekday == day.weekday() and t.valid_from <= day and (t.valid_until is None or day <= t.valid_until):
            return t.slot_minutes
    return settings.default_slot_minutes


def working_slots(
    templates: Sequence[ScheduleTemplate],
    exceptions: Iterable[ScheduleException],
    tz: ZoneInfo,
    date_from: date,
    date_to: date,
) -> list[Slot]:
    """Every slot the doctor works in [date_from, date_to], before bookings.

    Precedence: a date's custom hours replace its weekly hours; extra
    availability adds time; leave, holidays and blocks remove time (from
    custom and extra hours too). The one rule used by booking, the public
    calendar and the directory badges.
    """
    exceptions = list(exceptions)
    custom = [e for e in exceptions if e.kind is ExceptionKind.custom_hours]
    overridden = {e.starts_at.astimezone(tz).date() for e in custom}
    slots = [s for s in expand_templates(templates, tz, date_from, date_to) if s.starts_at.astimezone(tz).date() not in overridden]
    for e in exceptions:
        start, end = e.starts_at.astimezone(tz), e.ends_at.astimezone(tz)
        if e.kind is ExceptionKind.extra_availability:
            slots.extend(slice_window(start, end, settings.default_slot_minutes))
        elif e.kind is ExceptionKind.custom_hours:
            slots.extend(slice_window(start, end, slot_minutes_on(templates, start.date())))
    blocking = [(e.starts_at, e.ends_at) for e in exceptions if e.kind.is_unavailable]
    return remove_busy(slots, blocking)


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
            .join(User, User.id == Doctor.user_id)
            .where(
                Doctor.id == doctor_id,
                Doctor.is_active.is_(True),
                Department.is_active.is_(True),
                User.is_active.is_(True),
            )
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
    """The bookable (free) slots in the range. Booking validation uses this."""
    bookable, free, _ = await slot_board(
        db, doctor_id, date_from, date_to, now=now, min_lead=min_lead, exclude_appointment_id=exclude_appointment_id
    )
    return bookable, free


async def _schedule_rules(
    db: AsyncSession, doctor_id: uuid.UUID, date_from: date, date_to: date, window_start: datetime, window_end: datetime
) -> tuple[list[ScheduleTemplate], list[ScheduleException]]:
    """The templates and exceptions that can affect [date_from, date_to]."""
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
    return list(templates), list(exceptions)


async def slot_board(
    db: AsyncSession,
    doctor_id: uuid.UUID,
    date_from: date,
    date_to: date,
    *,
    now: datetime,
    min_lead: timedelta,
    exclude_appointment_id: uuid.UUID | None = None,
) -> tuple[BookableDoctor, list[Slot], list[Slot]]:
    """``(doctor, free, unavailable)`` for the range.

    ``unavailable`` are slots inside the doctor's working hours (after leave
    and blocks) that cannot be booked: already taken, or too soon (booking
    notice, or already past). They let a calendar grey out a time instead of
    hiding it; they say nothing about who booked it.
    """
    if date_to < date_from:
        raise BusinessRuleError("date_to must not be before date_from", code="INVALID_RANGE")
    if (date_to - date_from).days + 1 > MAX_RANGE_DAYS:
        raise BusinessRuleError(f"At most {MAX_RANGE_DAYS} days per request", code="RANGE_TOO_LARGE")

    bookable = await bookable_doctor(db, doctor_id)
    tz = bookable.timezone
    window_start = datetime.combine(date_from, time.min, tzinfo=tz)
    window_end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=tz)
    templates, exceptions = await _schedule_rules(db, doctor_id, date_from, date_to, window_start, window_end)

    slots = working_slots(templates, exceptions, tz, date_from, date_to)
    booked = await _busy_appointments(db, doctor_id, window_start, window_end, exclude_appointment_id)

    earliest = now + min_lead
    latest = now + timedelta(days=settings.booking_max_advance_days)
    # Working slots in the window and the booking horizon (a set: extra
    # availability may repeat a template slot).
    working = {s for s in slots if s.starts_at <= latest and window_start <= s.starts_at < window_end}
    free = {s for s in remove_busy(working, booked) if s.starts_at >= earliest}
    return bookable, sorted(free), sorted(working - free)


# ---- one doctor's day, for the staff schedule view (D83) ----------------------------


class SlotStatus(StrEnum):
    available = "available"
    # An active appointment overlaps it. Who and why is never part of this view.
    booked = "booked"
    # Inside the scheduled hours but blocked by leave or a block exception.
    blocked = "blocked"
    # Between two working blocks of the day (e.g. lunch).
    break_ = "break"
    # Already started, or inside the booking notice.
    past = "past"
    # Beyond the booking horizon.
    beyond_horizon = "beyond_horizon"


class DayStatus(StrEnum):
    available = "available"
    # Working hours, but every bookable slot is taken.
    fully_booked = "fully_booked"
    # No working hours that day.
    off = "off"
    # Leave or another exception removed the working hours.
    unavailable = "unavailable"
    # Nothing can be booked any more (the day or its hours are over).
    past = "past"


@dataclass(frozen=True)
class BoardSlot:
    starts_at: datetime
    ends_at: datetime
    status: SlotStatus


@dataclass(frozen=True)
class DaySummary:
    day: date
    status: DayStatus
    available: int


@dataclass(frozen=True)
class DaySchedule:
    doctor: Doctor
    timezone: ZoneInfo
    day: date
    today: date
    slot_minutes: int
    hours: tuple[tuple[time, time], ...]
    breaks: tuple[tuple[time, time], ...]
    slots: list[BoardSlot]
    total_slots: int
    available_slots: int
    week: list[DaySummary]


def _gaps(ranges: tuple[tuple[datetime, datetime], ...]) -> list[tuple[datetime, datetime]]:
    return [(ranges[i][1], ranges[i + 1][0]) for i in range(len(ranges) - 1) if ranges[i][1] < ranges[i + 1][0]]


def _ranges(slots: Iterable[Slot]) -> tuple[tuple[datetime, datetime], ...]:
    """Consecutive slots joined into (start, end) instants."""
    merged: list[list[datetime]] = []
    for slot in sorted(slots):
        if merged and merged[-1][1] == slot.starts_at:
            merged[-1][1] = slot.ends_at
        else:
            merged.append([slot.starts_at, slot.ends_at])
    return tuple((a, b) for a, b in merged)


async def day_schedule(
    db: AsyncSession, doctor_id: uuid.UUID, day: date | None, *, now: datetime, min_lead: timedelta
) -> DaySchedule:
    """Every slot of `day` with its status, plus the Sunday-to-Saturday week
    around it, for the staff schedule view. The same rules as booking:
    weekly hours, custom hours, extra availability, leave and blocks, active
    appointments, the booking notice and the booking horizon. Booked slots
    carry no appointment or patient data."""
    bookable = await bookable_doctor(db, doctor_id)
    tz = bookable.timezone
    today = now.astimezone(tz).date()
    day = day or today
    if not today - timedelta(days=366) <= day <= today + timedelta(days=settings.booking_max_advance_days + 7):
        raise BusinessRuleError("That date is outside the schedule that can be shown", code="DATE_OUT_OF_RANGE")
    week_start = day - timedelta(days=day.isoweekday() % 7)
    week_end = week_start + timedelta(days=6)
    window_start = datetime.combine(week_start, time.min, tzinfo=tz)
    window_end = datetime.combine(week_end + timedelta(days=1), time.min, tzinfo=tz)
    templates, exceptions = await _schedule_rules(db, doctor_id, week_start, week_end, window_start, window_end)
    blocking = [e for e in exceptions if e.kind.is_unavailable]
    # Scheduled = the hours before leave and blocks; working = what remains.
    scheduled = working_slots(templates, [e for e in exceptions if not e.kind.is_unavailable], tz, week_start, week_end)
    booked = await _busy_appointments(db, doctor_id, window_start, window_end, None)
    earliest = now + min_lead
    latest = now + timedelta(days=settings.booking_max_advance_days)

    def status_of(slot: Slot) -> SlotStatus:
        if any(slot.overlaps(e.starts_at, e.ends_at) for e in blocking):
            return SlotStatus.blocked
        if any(slot.overlaps(start, end) for start, end in booked):
            return SlotStatus.booked
        if slot.starts_at < earliest:
            return SlotStatus.past
        if slot.starts_at > latest:
            return SlotStatus.beyond_horizon
        return SlotStatus.available

    by_day: dict[date, list[Slot]] = defaultdict(list)
    for slot in sorted(set(scheduled)):
        by_day[slot.starts_at.astimezone(tz).date()].append(slot)

    week = []
    for offset in range(7):
        d = week_start + timedelta(days=offset)
        statuses = [status_of(s) for s in by_day.get(d, [])]
        free = statuses.count(SlotStatus.available)
        if free:
            state = DayStatus.available
        elif not statuses:
            day_start, day_end = datetime.combine(d, time.min, tzinfo=tz), datetime.combine(d + timedelta(days=1), time.min, tzinfo=tz)
            on_leave = any(e.starts_at < day_end and e.ends_at > day_start for e in blocking)
            state = DayStatus.unavailable if on_leave else DayStatus.off
        else:
            # Slots that could still have been booked, if nobody had.
            open_ = [s for s in statuses if s not in (SlotStatus.blocked, SlotStatus.past)]
            if all(s is SlotStatus.blocked for s in statuses):
                state = DayStatus.unavailable
            elif d < today or not open_:
                state = DayStatus.past
            elif SlotStatus.booked in open_:
                state = DayStatus.fully_booked
            else:
                state = DayStatus.unavailable  # beyond the booking horizon
        week.append(DaySummary(d, state, free))

    day_slots = by_day.get(day, [])
    board = [BoardSlot(s.starts_at, s.ends_at, status_of(s)) for s in day_slots]
    ranges = _ranges(day_slots)
    minutes = slot_minutes_on(templates, day)
    for gap_start, gap_end in _gaps(ranges):
        board += [BoardSlot(s.starts_at, s.ends_at, SlotStatus.break_) for s in slice_window(gap_start, gap_end, minutes)]
    board.sort(key=lambda b: b.starts_at)
    local = lambda pairs: tuple((a.astimezone(tz).time(), b.astimezone(tz).time()) for a, b in pairs)  # noqa: E731
    return DaySchedule(
        doctor=bookable.doctor,
        timezone=tz,
        day=day,
        today=today,
        slot_minutes=minutes,
        hours=local(ranges),
        breaks=local(_gaps(ranges)),
        slots=board,
        total_slots=len(day_slots),
        available_slots=sum(1 for b in board if b.status is SlotStatus.available),
        week=week,
    )


# ---- directory status (many doctors at once) ---------------------------------------


class AvailabilityStatus(StrEnum):
    # At least one bookable slot in the coming days.
    available = "available"
    # Working in the coming days, but every slot is taken.
    busy = "busy"
    # No working hours in the coming days (no schedule, or on leave).
    unavailable = "unavailable"


# At or below this many free slots in the window, availability is "limited".
LIMITED_AVAILABILITY_SLOTS = 3


@dataclass(frozen=True)
class DoctorAvailability:
    status: AvailabilityStatus
    next_available: datetime | None = None
    # A free slot remains today, in the doctor's department timezone.
    available_today: bool = False
    # Few free slots left in the window (LIMITED_AVAILABILITY_SLOTS or fewer).
    limited: bool = False
    # Today's working hours (local wall-clock ranges, after exceptions, before
    # bookings), e.g. ((09:00, 13:00), (14:00, 17:00)). Empty: not working today.
    today_hours: tuple[tuple[time, time], ...] = ()


def merge_hours(slots: Iterable[Slot], tz: ZoneInfo) -> tuple[tuple[time, time], ...]:
    """Consecutive slots joined into local (start, end) ranges."""
    return tuple((s.astimezone(tz).time(), e.astimezone(tz).time()) for s, e in _ranges(slots))


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
            # The whole days, not just [now, horizon]: a custom-hours day must
            # replace that day's weekly hours even where its own hours have
            # already ended or start after the horizon.
            ScheduleException.starts_at < datetime.combine(last_day + timedelta(days=1), time.min, tzinfo=UTC),
            ScheduleException.ends_at > datetime.combine(first_day, time.min, tzinfo=UTC),
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
        slots = working_slots(templates[doctor_id], exceptions[doctor_id], tz, first_day, last_day)
        today = now.astimezone(tz).date()
        hours = merge_hours((s for s in slots if s.starts_at.astimezone(tz).date() == today), tz)
        working = [s for s in slots if earliest <= s.starts_at <= horizon]
        free = remove_busy(working, booked[doctor_id])
        if free:
            first = min(free).starts_at
            result[doctor_id] = DoctorAvailability(
                AvailabilityStatus.available,
                first,
                available_today=first.astimezone(tz).date() == today,
                limited=len(free) <= LIMITED_AVAILABILITY_SLOTS,
                today_hours=hours,
            )
        elif working:
            result[doctor_id] = DoctorAvailability(AvailabilityStatus.busy, today_hours=hours)
        else:
            result[doctor_id] = DoctorAvailability(AvailabilityStatus.unavailable, today_hours=hours)
    return result
