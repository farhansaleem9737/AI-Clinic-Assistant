import logging
import uuid
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError, PermissionDeniedError
from app.core.permissions import Perm, Principal
from app.models.department import Department
from app.models.doctor import Doctor
from app.models.schedule import ExceptionKind, ScheduleException, ScheduleTemplate
from app.schemas.schedule import ScheduleExceptionCreate, ScheduleTemplateCreate, ScheduleTemplateUpdate

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
    await db.delete(exception)
    await db.commit()
    logger.info("schedule_exception_deleted", extra={"exception_id": str(exception_id)})
