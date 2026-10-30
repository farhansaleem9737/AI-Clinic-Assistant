import logging
import uuid
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.config import settings
from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError, PermissionDeniedError
from app.core.permissions import Perm, Principal
from app.models.department import Department
from app.models.doctor import Doctor
from app.models.schedule import ExceptionKind, ScheduleException, ScheduleTemplate
from app.schemas.schedule import (
    DateExceptionRead,
    DateExceptionType,
    DateExceptionWrite,
    ScheduleExceptionCreate,
    ScheduleTemplateCreate,
    ScheduleTemplateUpdate,
    WeeklyDayRead,
    WeeklyScheduleRead,
    WeeklyScheduleUpdate,
    WorkingInterval,
)

logger = logging.getLogger(__name__)


def ensure_can_manage(principal: Principal, doctor_id: uuid.UUID) -> None:
    """Doctors manage their own schedule; staff with manage_any manage everyone's."""
    if principal.has(Perm.schedule_manage_any):
        return
    if principal.has(Perm.schedule_manage_own) and principal.doctor_id == doctor_id:
        return
    raise PermissionDeniedError("You cannot manage this doctor's schedule")


async def _doctor(db: AsyncSession, doctor_id: uuid.UUID) -> Doctor:
    doctor = await db.get(Doctor, doctor_id)
    if doctor is None:
        raise NotFoundError("Doctor not found")
    return doctor


async def doctor_timezone(db: AsyncSession, doctor_id: uuid.UUID) -> ZoneInfo:
    tz = await db.scalar(
        select(Department.timezone).join(Doctor, Doctor.department_id == Department.id).where(Doctor.id == doctor_id)
    )
    if tz is None:
        raise NotFoundError("Doctor not found")
    return ZoneInfo(tz)


async def _ensure_no_overlap(
    db: AsyncSession,
    *,
    doctor_id: uuid.UUID,
    weekday: int,
    start_time: time,
    end_time: time,
    valid_from: date,
    valid_until: date | None,
    exclude_id: uuid.UUID | None = None,
) -> None:
    """Two active templates may not cover the same weekday hours during
    overlapping validity periods — the slots would be ambiguous."""
    query = select(ScheduleTemplate.id).where(
        ScheduleTemplate.doctor_id == doctor_id,
        ScheduleTemplate.weekday == weekday,
        ScheduleTemplate.is_active.is_(True),
        ScheduleTemplate.start_time < end_time,
        ScheduleTemplate.end_time > start_time,
        or_(ScheduleTemplate.valid_until.is_(None), ScheduleTemplate.valid_until >= valid_from),
    )
    if valid_until is not None:
        query = query.where(ScheduleTemplate.valid_from <= valid_until)
    if exclude_id is not None:
        query = query.where(ScheduleTemplate.id != exclude_id)
    if await db.scalar(query.limit(1)) is not None:
        raise ConflictError("Overlaps an existing working block", code="SCHEDULE_OVERLAP")


async def list_templates(
    db: AsyncSession, doctor_id: uuid.UUID, *, include_inactive: bool = False
) -> list[ScheduleTemplate]:
    await _doctor(db, doctor_id)
    query = select(ScheduleTemplate).where(ScheduleTemplate.doctor_id == doctor_id)
    if not include_inactive:
        query = query.where(ScheduleTemplate.is_active.is_(True))
    query = query.order_by(ScheduleTemplate.weekday, ScheduleTemplate.start_time)
    return list((await db.scalars(query)).all())


async def create_template(db: AsyncSession, principal: Principal, data: ScheduleTemplateCreate) -> ScheduleTemplate:
    ensure_can_manage(principal, data.doctor_id)
    await _doctor(db, data.doctor_id)
    await _ensure_no_overlap(db, **data.model_dump(exclude={"slot_minutes"}))
    template = ScheduleTemplate(**data.model_dump())
    db.add(template)
    await db.commit()
    await db.refresh(template)
    logger.info("schedule_template_created", extra={"template_id": str(template.id), "doctor_id": str(data.doctor_id)})
    return template


async def _template(db: AsyncSession, template_id: uuid.UUID) -> ScheduleTemplate:
    template = await db.get(ScheduleTemplate, template_id)
    if template is None:
        raise NotFoundError("Schedule template not found")
    return template


async def update_template(
    db: AsyncSession, principal: Principal, template_id: uuid.UUID, data: ScheduleTemplateUpdate
) -> ScheduleTemplate:
    template = await _template(db, template_id)
    ensure_can_manage(principal, template.doctor_id)
    changes = data.model_dump(exclude_unset=True)
    start = changes.get("start_time") or template.start_time
    end = changes.get("end_time") or template.end_time
    valid_until = changes.get("valid_until", template.valid_until)
    if start >= end:
        raise BusinessRuleError("start_time must be before end_time", code="INVALID_TIMES")
    await _ensure_no_overlap(
        db,
        doctor_id=template.doctor_id,
        weekday=template.weekday,
        start_time=start,
        end_time=end,
        valid_from=template.valid_from,
        valid_until=valid_until,
        exclude_id=template.id,
    )
    for field, value in changes.items():
        if value is not None or field == "valid_until":
            setattr(template, field, value)
    await db.commit()
    await db.refresh(template)
    logger.info("schedule_template_updated", extra={"template_id": str(template.id), "fields": sorted(changes)})
    return template


async def deactivate_template(db: AsyncSession, principal: Principal, template_id: uuid.UUID) -> ScheduleTemplate:
    """Already-booked appointments inside the block are kept; only new
    bookings stop being offered."""
    template = await _template(db, template_id)
    ensure_can_manage(principal, template.doctor_id)
    template.is_active = False
    await db.commit()
    await db.refresh(template)
    logger.info("schedule_template_deactivated", extra={"template_id": str(template.id)})
    return template


async def list_exceptions(
    db: AsyncSession, doctor_id: uuid.UUID, *, start: datetime | None = None, end: datetime | None = None
) -> list[ScheduleException]:
    await _doctor(db, doctor_id)
    query = select(ScheduleException).where(ScheduleException.doctor_id == doctor_id)
    if start is not None:
        query = query.where(ScheduleException.ends_at > start)
    if end is not None:
        query = query.where(ScheduleException.starts_at < end)
    return list((await db.scalars(query.order_by(ScheduleException.starts_at))).all())


async def create_exception(db: AsyncSession, principal: Principal, data: ScheduleExceptionCreate) -> ScheduleException:
    ensure_can_manage(principal, data.doctor_id)
    await _doctor(db, data.doctor_id)
    if data.kind is not ExceptionKind.extra_availability:
        await _ensure_no_booked_appointments(db, data.doctor_id, data.starts_at, data.ends_at)
    exception = ScheduleException(**data.model_dump(), created_by_user_id=principal.user_id)
    db.add(exception)
    await db.commit()
    await db.refresh(exception)
    logger.info(
        "schedule_exception_created",
        extra={"exception_id": str(exception.id), "doctor_id": str(data.doctor_id), "kind": data.kind.value},
    )
    return exception


async def _ensure_no_booked_appointments(
    db: AsyncSession, doctor_id: uuid.UUID, start: datetime, end: datetime
) -> None:
    """Marking a doctor unavailable must not silently strand booked patients:
    those appointments have to be rescheduled or cancelled first."""
    from app.models.appointment import ACTIVE_STATUSES, Appointment

    count = await db.scalar(
        select(func.count(Appointment.id)).where(
            Appointment.doctor_id == doctor_id,
            Appointment.status.in_(ACTIVE_STATUSES),
            Appointment.starts_at < end,
            Appointment.ends_at > start,
        )
    )
    if count:
        raise ConflictError(
            "Booked appointments fall inside this period; reschedule or cancel them first",
            code="APPOINTMENTS_IN_PERIOD",
            details={"appointments": count},
        )


async def delete_exception(db: AsyncSession, principal: Principal, exception_id: uuid.UUID) -> None:
    exception = await db.get(ScheduleException, exception_id)
    if exception is None:
        raise NotFoundError("Schedule exception not found")
    ensure_can_manage(principal, exception.doctor_id)
    await _delete(db, exception)


async def _delete(db: AsyncSession, exception: ScheduleException) -> None:
    await lock_doctor_schedule(db, exception.doctor_id)
    if exception.kind is ExceptionKind.custom_hours:
        # The weekly hours come back for that date: appointments booked inside
        # the custom hours must still fit them.
        tz = await doctor_timezone(db, exception.doctor_id)
        day = exception.starts_at.astimezone(tz).date()
        await _ensure_appointments_fit(db, exception.doctor_id, tz, day, await _weekly_windows_on(db, exception.doctor_id, day, tz))
    exception_id = exception.id
    await db.delete(exception)
    await db.commit()
    logger.info("schedule_exception_deleted", extra={"exception_id": str(exception_id)})


# ---- My Schedule: the whole week, and single dates (D78) ------------------------------

SCHEDULE_CONFLICT_MESSAGE = (
    "This schedule change conflicts with existing appointments. "
    "Please reschedule or cancel those appointments before continuing."
)
# How far ahead a date exception may be set.
MAX_EXCEPTION_AHEAD_DAYS = 730


async def lock_doctor_schedule(db: AsyncSession, doctor_id: uuid.UUID) -> None:
    """The lock bookings take on a doctor (appointment_service._serialize_bookings,
    namespace 1). A schedule change and a booking for the same doctor run one
    after the other, so a booking cannot slip in after the conflict check."""
    await db.execute(text("SELECT pg_advisory_xact_lock(1, hashtext(:key))"), {"key": str(doctor_id)})


def _today(tz: ZoneInfo) -> date:
    return clock.utcnow().astimezone(tz).date()


def _day_bounds(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    return datetime.combine(day, time.min, tzinfo=tz), datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz)


async def _templates_from(db: AsyncSession, doctor_id: uuid.UUID, today: date) -> list[ScheduleTemplate]:
    """Active templates still in force today or later: the regular week."""
    query = (
        select(ScheduleTemplate)
        .where(
            ScheduleTemplate.doctor_id == doctor_id,
            ScheduleTemplate.is_active.is_(True),
            or_(ScheduleTemplate.valid_until.is_(None), ScheduleTemplate.valid_until >= today),
        )
        .order_by(ScheduleTemplate.weekday, ScheduleTemplate.start_time)
    )
    return list((await db.scalars(query)).all())


def _week(templates: list[ScheduleTemplate]) -> dict[int, list[ScheduleTemplate]]:
    week: dict[int, list[ScheduleTemplate]] = defaultdict(list)
    for t in templates:
        week[t.weekday].append(t)
    return week


def _intervals(templates: list[ScheduleTemplate]) -> list[tuple[time, time]]:
    return sorted({(t.start_time, t.end_time) for t in templates})


async def get_weekly(db: AsyncSession, principal: Principal, doctor_id: uuid.UUID) -> WeeklyScheduleRead:
    ensure_can_manage(principal, doctor_id)
    await _doctor(db, doctor_id)
    tz = await doctor_timezone(db, doctor_id)
    week = _week(await _templates_from(db, doctor_id, _today(tz)))
    days = []
    for weekday in range(7):
        templates = week.get(weekday, [])
        days.append(
            WeeklyDayRead(
                weekday=weekday,
                enabled=bool(templates),
                intervals=[WorkingInterval(start_time=s, end_time=e) for s, e in _intervals(templates)],
                slot_minutes=templates[0].slot_minutes if templates else settings.default_slot_minutes,
            )
        )
    return WeeklyScheduleRead(doctor_id=doctor_id, timezone=tz.key, days=days)


async def _active_appointments(
    db: AsyncSession, doctor_id: uuid.UUID, start: datetime, end: datetime | None = None
) -> list[tuple[datetime, datetime]]:
    from app.models.appointment import ACTIVE_STATUSES, Appointment

    query = select(Appointment.starts_at, Appointment.ends_at).where(
        Appointment.doctor_id == doctor_id,
        Appointment.status.in_(ACTIVE_STATUSES),
        Appointment.ends_at > start,
    )
    if end is not None:
        query = query.where(Appointment.starts_at < end)
    return [tuple(row) for row in (await db.execute(query.order_by(Appointment.starts_at))).all()]


def _fits(start: datetime, end: datetime, windows: list[tuple[datetime, datetime]]) -> bool:
    return any(w_start <= start and end <= w_end for w_start, w_end in windows)


def _conflict(dates: set[date]) -> ConflictError:
    # The doctor's own dates only: nothing about the patients.
    return ConflictError(
        SCHEDULE_CONFLICT_MESSAGE,
        code="SCHEDULE_CONFLICT",
        details={"dates": [d.isoformat() for d in sorted(dates)][:10]},
    )


async def update_weekly(
    db: AsyncSession, principal: Principal, doctor_id: uuid.UUID, data: WeeklyScheduleUpdate
) -> WeeklyScheduleRead:
    """Replace the regular week. Only weekdays that actually change get new
    templates (valid from today); past dates keep their history. Refused if
    an upcoming appointment would fall outside the new hours."""
    ensure_can_manage(principal, doctor_id)
    await _doctor(db, doctor_id)
    tz = await doctor_timezone(db, doctor_id)
    await lock_doctor_schedule(db, doctor_id)
    today = _today(tz)
    week = _week(await _templates_from(db, doctor_id, today))

    changed: dict[int, tuple[list[tuple[time, time]], int]] = {}
    for day in data.days:
        current = week.get(day.weekday, [])
        wanted = [(i.start_time, i.end_time) for i in day.intervals] if day.enabled else []
        slot = day.slot_minutes or (current[0].slot_minutes if current else settings.default_slot_minutes)
        same_hours = wanted == _intervals(current)
        same_slot = all(t.slot_minutes == slot for t in current)
        if not (same_hours and same_slot):
            changed[day.weekday] = (wanted, slot)
    if not changed:
        return await get_weekly(db, principal, doctor_id)

    await _ensure_week_keeps_appointments(db, doctor_id, tz, changed)

    for weekday, (wanted, slot) in changed.items():
        for template in week.get(weekday, []):
            if template.valid_from < today:
                template.valid_until = today - timedelta(days=1)  # history stays as it was
            else:
                template.is_active = False
        for start, end in wanted:
            db.add(
                ScheduleTemplate(
                    doctor_id=doctor_id,
                    weekday=weekday,
                    start_time=start,
                    end_time=end,
                    slot_minutes=slot,
                    valid_from=today,
                )
            )
    await db.commit()
    logger.info(
        "weekly_schedule_updated",
        extra={"doctor_id": str(doctor_id), "weekdays": sorted(changed), "by": str(principal.user_id)},
    )
    return await get_weekly(db, principal, doctor_id)


async def _ensure_week_keeps_appointments(
    db: AsyncSession, doctor_id: uuid.UUID, tz: ZoneInfo, changed: dict[int, tuple[list[tuple[time, time]], int]]
) -> None:
    """Every upcoming appointment on a changed weekday must still fit the new
    hours, unless its date is governed by an exception (custom hours or
    extra availability), which this change does not touch."""
    now = clock.utcnow()
    appointments = [
        (start, end)
        for start, end in await _active_appointments(db, doctor_id, now)
        if start.astimezone(tz).weekday() in changed
    ]
    if not appointments:
        return
    exceptions = (
        await db.scalars(
            select(ScheduleException).where(
                ScheduleException.doctor_id == doctor_id,
                ScheduleException.kind.in_([ExceptionKind.custom_hours, ExceptionKind.extra_availability]),
                ScheduleException.ends_at > now - timedelta(days=1),
            )
        )
    ).all()
    custom_dates = {e.starts_at.astimezone(tz).date() for e in exceptions if e.kind is ExceptionKind.custom_hours}
    extra = [(e.starts_at, e.ends_at) for e in exceptions if e.kind is ExceptionKind.extra_availability]

    conflicts: set[date] = set()
    for start, end in appointments:
        day = start.astimezone(tz).date()
        if day in custom_dates or _fits(start, end, extra):
            continue
        wanted, _ = changed[day.weekday()]
        windows = [(datetime.combine(day, s, tzinfo=tz), datetime.combine(day, e, tzinfo=tz)) for s, e in wanted]
        if not _fits(start, end, windows):
            conflicts.add(day)
    if conflicts:
        raise _conflict(conflicts)


async def _weekly_windows_on(
    db: AsyncSession, doctor_id: uuid.UUID, day: date, tz: ZoneInfo
) -> list[tuple[datetime, datetime]]:
    """The doctor's regular hours on one date, plus any extra availability."""
    templates = (
        await db.scalars(
            select(ScheduleTemplate).where(
                ScheduleTemplate.doctor_id == doctor_id,
                ScheduleTemplate.is_active.is_(True),
                ScheduleTemplate.weekday == day.weekday(),
                ScheduleTemplate.valid_from <= day,
                or_(ScheduleTemplate.valid_until.is_(None), ScheduleTemplate.valid_until >= day),
            )
        )
    ).all()
    windows = [
        (datetime.combine(day, t.start_time, tzinfo=tz), datetime.combine(day, t.end_time, tzinfo=tz))
        for t in templates
    ]
    day_start, day_end = _day_bounds(day, tz)
    extra = await db.execute(
        select(ScheduleException.starts_at, ScheduleException.ends_at).where(
            ScheduleException.doctor_id == doctor_id,
            ScheduleException.kind == ExceptionKind.extra_availability,
            ScheduleException.starts_at < day_end,
            ScheduleException.ends_at > day_start,
        )
    )
    return windows + [tuple(row) for row in extra.all()]


async def _ensure_appointments_fit(
    db: AsyncSession, doctor_id: uuid.UUID, tz: ZoneInfo, day: date, windows: list[tuple[datetime, datetime]]
) -> None:
    """Appointments still to come on `day` must lie inside `windows`."""
    day_start, day_end = _day_bounds(day, tz)
    since = max(day_start, clock.utcnow())
    for start, end in await _active_appointments(db, doctor_id, since, day_end):
        if not _fits(start, end, windows):
            raise _conflict({day})


def to_date_exception(exception: ScheduleException, tz: ZoneInfo) -> DateExceptionRead:
    start, end = exception.starts_at.astimezone(tz), exception.ends_at.astimezone(tz)
    first, last = start.date(), (end - timedelta(microseconds=1)).date()
    whole_days = start.time() == time.min and end.time() == time.min
    if exception.kind is ExceptionKind.custom_hours:
        kind = DateExceptionType.custom_hours
    elif exception.kind is ExceptionKind.extra_availability:
        kind = DateExceptionType.extra_hours
    else:
        kind = DateExceptionType.unavailable
    return DateExceptionRead(
        id=exception.id,
        type=kind,
        kind=exception.kind,
        date=first,
        end_date=last,
        start_time=None if whole_days else start.time(),
        end_time=None if whole_days else end.time(),
        reason=exception.reason,
        editable=first == last
        and (kind is DateExceptionType.custom_hours or (kind is DateExceptionType.unavailable and whole_days)),
    )


async def list_date_exceptions(
    db: AsyncSession, principal: Principal, doctor_id: uuid.UUID
) -> list[DateExceptionRead]:
    """Exceptions from today on, in date order."""
    ensure_can_manage(principal, doctor_id)
    await _doctor(db, doctor_id)
    tz = await doctor_timezone(db, doctor_id)
    today_start, _ = _day_bounds(_today(tz), tz)
    query = (
        select(ScheduleException)
        .where(ScheduleException.doctor_id == doctor_id, ScheduleException.ends_at > today_start)
        .order_by(ScheduleException.starts_at, ScheduleException.id)
        .limit(200)
    )
    return [to_date_exception(e, tz) for e in await db.scalars(query)]


async def _prepare_date_exception(
    db: AsyncSession, doctor_id: uuid.UUID, tz: ZoneInfo, data: DateExceptionWrite, exclude_id: uuid.UUID | None
) -> tuple[datetime, datetime]:
    today = _today(tz)
    if data.date < today:
        raise BusinessRuleError("Choose today or a later date", code="PAST_DATE")
    if data.date > today + timedelta(days=MAX_EXCEPTION_AHEAD_DAYS):
        raise BusinessRuleError("Choose a date within the next two years", code="DATE_TOO_FAR")
    day_start, day_end = _day_bounds(data.date, tz)
    # One exception per date: a second one would make the day ambiguous.
    clash = select(ScheduleException.id).where(
        ScheduleException.doctor_id == doctor_id,
        ScheduleException.starts_at < day_end,
        ScheduleException.ends_at > day_start,
    )
    if exclude_id is not None:
        clash = clash.where(ScheduleException.id != exclude_id)
    if await db.scalar(clash.limit(1)) is not None:
        raise ConflictError("This date already has an exception; edit that one instead", code="EXCEPTION_EXISTS")

    if data.type is DateExceptionType.custom_hours:
        start = datetime.combine(data.date, data.start_time, tzinfo=tz)
        end = datetime.combine(data.date, data.end_time, tzinfo=tz)
        await _ensure_appointments_fit(db, doctor_id, tz, data.date, [(start, end)])
        return start, end
    await _ensure_appointments_fit(db, doctor_id, tz, data.date, [])
    return day_start, day_end


async def create_date_exception(
    db: AsyncSession, principal: Principal, doctor_id: uuid.UUID, data: DateExceptionWrite
) -> DateExceptionRead:
    ensure_can_manage(principal, doctor_id)
    await _doctor(db, doctor_id)
    tz = await doctor_timezone(db, doctor_id)
    await lock_doctor_schedule(db, doctor_id)
    starts_at, ends_at = await _prepare_date_exception(db, doctor_id, tz, data, None)
    exception = ScheduleException(
        doctor_id=doctor_id,
        kind=ExceptionKind.custom_hours if data.type is DateExceptionType.custom_hours else ExceptionKind.leave,
        starts_at=starts_at,
        ends_at=ends_at,
        reason=data.reason,
        created_by_user_id=principal.user_id,
    )
    db.add(exception)
    await db.commit()
    await db.refresh(exception)
    logger.info(
        "schedule_exception_created",
        extra={"exception_id": str(exception.id), "doctor_id": str(doctor_id), "kind": exception.kind.value},
    )
    return to_date_exception(exception, tz)


async def _own_exception(db: AsyncSession, doctor_id: uuid.UUID, exception_id: uuid.UUID) -> ScheduleException:
    # Both ids must match: another doctor's exception is simply not found.
    exception = await db.scalar(
        select(ScheduleException).where(ScheduleException.id == exception_id, ScheduleException.doctor_id == doctor_id)
    )
    if exception is None:
        raise NotFoundError("Schedule exception not found")
    return exception


async def update_date_exception(
    db: AsyncSession, principal: Principal, doctor_id: uuid.UUID, exception_id: uuid.UUID, data: DateExceptionWrite
) -> DateExceptionRead:
    ensure_can_manage(principal, doctor_id)
    exception = await _own_exception(db, doctor_id, exception_id)
    tz = await doctor_timezone(db, doctor_id)
    current = to_date_exception(exception, tz)
    if not current.editable:
        raise BusinessRuleError(
            "This exception cannot be edited here; delete it and add a new one", code="NOT_EDITABLE"
        )
    if current.end_date < _today(tz):
        raise BusinessRuleError("Past exceptions are kept as they were", code="PAST_DATE")
    await lock_doctor_schedule(db, doctor_id)
    if exception.kind is ExceptionKind.custom_hours and data.date != current.date:
        # Moving custom hours away gives the old date its weekly hours back.
        await _ensure_appointments_fit(
            db, doctor_id, tz, current.date, await _weekly_windows_on(db, doctor_id, current.date, tz)
        )
    starts_at, ends_at = await _prepare_date_exception(db, doctor_id, tz, data, exception.id)
    if data.type is DateExceptionType.custom_hours:
        exception.kind = ExceptionKind.custom_hours
    elif not exception.kind.is_unavailable:
        exception.kind = ExceptionKind.leave  # an existing leave/holiday/block keeps its kind
    exception.starts_at, exception.ends_at, exception.reason = starts_at, ends_at, data.reason
    await db.commit()
    await db.refresh(exception)
    logger.info("schedule_exception_updated", extra={"exception_id": str(exception.id), "kind": exception.kind.value})
    return to_date_exception(exception, tz)


async def delete_date_exception(
    db: AsyncSession, principal: Principal, doctor_id: uuid.UUID, exception_id: uuid.UUID
) -> None:
    ensure_can_manage(principal, doctor_id)
    exception = await _own_exception(db, doctor_id, exception_id)
    if exception.ends_at <= clock.utcnow():
        raise BusinessRuleError("Past exceptions are kept as they were", code="PAST_DATE")
    await _delete(db, exception)
