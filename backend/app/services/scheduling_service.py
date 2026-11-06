"""Doctors' scheduling policies (D117).

The doctor controls their own policy; administrators (schedule:manage_any
together with settings:manage) may set it for a doctor. Saving a policy
changes only how future free times are offered: every existing appointment
keeps its own start and end time.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.exceptions import ConflictError, NotFoundError, PermissionDeniedError
from app.core.permissions import Perm, Principal
from app.models.department import Department
from app.models.doctor import Doctor
from app.models.scheduling import SchedulingMode, SchedulingPolicy
from app.schemas.scheduling import (
    AffectedAppointment,
    PreviewSlot,
    SchedulePreview,
    SchedulePreviewRequest,
    SchedulingPolicyRead,
    SchedulingPolicyWrite,
)
from app.services import audit_service
from app.services.audit_service import AuditAction

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EffectivePolicy:
    """The rules in force for a doctor: their saved policy, or the clinic defaults
    for the queue (hybrid, 15 minutes, no buffer) when nothing is saved yet."""

    mode: SchedulingMode = SchedulingMode.hybrid
    consultation_minutes: int = 15
    buffer_minutes: int = 0
    accept_walk_ins: bool = True
    walk_in_capacity: int | None = None
    late_grace_minutes: int = 10
    max_overbook: int = 1
    allow_receptionist_overrides: bool = True
    configured: bool = False

    @property
    def walk_ins_open(self) -> bool:
        return self.accept_walk_ins and self.mode is not SchedulingMode.scheduled


FIELDS = tuple(SchedulingPolicyWrite.model_fields)


def effective(policy: SchedulingPolicy | None) -> EffectivePolicy:
    if policy is None:
        return EffectivePolicy()
    return EffectivePolicy(**{f: getattr(policy, f) for f in FIELDS}, configured=True)


async def effective_policy(db: AsyncSession, doctor_id: uuid.UUID) -> EffectivePolicy:
    return effective(await db.get(SchedulingPolicy, doctor_id))


def can_manage(principal: Principal, doctor_id: uuid.UUID) -> bool:
    if principal.has(Perm.schedule_manage_own) and principal.doctor_id == doctor_id:
        return True
    return principal.has(Perm.schedule_manage_any, Perm.settings_manage)


def _ensure_can_read(principal: Principal, doctor_id: uuid.UUID) -> None:
    if can_manage(principal, doctor_id) or principal.has(Perm.schedule_read):
        return
    raise PermissionDeniedError("You cannot view this doctor's scheduling policy")


async def _legacy_slot_minutes(db: AsyncSession, doctor_id: uuid.UUID) -> int | None:
    from sqlalchemy import select

    from app.models.schedule import ScheduleTemplate

    return await db.scalar(
        select(ScheduleTemplate.slot_minutes)
        .where(ScheduleTemplate.doctor_id == doctor_id, ScheduleTemplate.is_active.is_(True))
        .order_by(ScheduleTemplate.updated_at.desc())
        .limit(1)
    )


async def _read(db: AsyncSession, doctor_id: uuid.UUID, row: SchedulingPolicy | None) -> SchedulingPolicyRead:
    values = effective(row)
    return SchedulingPolicyRead(
        doctor_id=doctor_id,
        configured=row is not None,
        legacy_slot_minutes=None if row is not None else await _legacy_slot_minutes(db, doctor_id),
        updated_at=row.updated_at if row is not None else None,
        **{f: getattr(values, f) for f in FIELDS},
    )


async def get_policy(db: AsyncSession, principal: Principal, doctor_id: uuid.UUID) -> SchedulingPolicyRead:
    if await db.get(Doctor, doctor_id) is None:
        raise NotFoundError("Doctor not found")
    _ensure_can_read(principal, doctor_id)
    return await _read(db, doctor_id, await db.get(SchedulingPolicy, doctor_id))


# ---- what a new length would do (D120) ---------------------------------------------

AFFECTED_LIMIT = 20


async def _doctor_tz(db: AsyncSession, doctor_id: uuid.UUID) -> ZoneInfo:
    tz = await db.scalar(
        select(Department.timezone).join(Doctor, Doctor.department_id == Department.id).where(Doctor.id == doctor_id)
    )
    if tz is None:
        raise NotFoundError("Doctor not found")
    return ZoneInfo(tz)


async def misfits(db: AsyncSession, doctor_id: uuid.UUID, timing, tz: ZoneInfo) -> list:
    """Upcoming active appointments that are not exactly one of the times the
    proposed length/buffer would offer (different length, off the grid, or
    outside the hours). They are not touched; this only lists them."""
    from app.models.appointment import ACTIVE_STATUSES, Appointment
    from app.services import availability_service

    now = clock.utcnow()
    upcoming = (
        await db.scalars(
            select(Appointment)
            .where(
                Appointment.doctor_id == doctor_id,
                Appointment.status.in_(ACTIVE_STATUSES),
                Appointment.starts_at >= now,
            )
            .order_by(Appointment.starts_at, Appointment.id)
        )
    ).all()
    if not upcoming:
        return []
    first = now.astimezone(tz).date()
    last = max(a.starts_at.astimezone(tz).date() for a in upcoming)
    window_start = datetime.combine(first, time.min, tzinfo=tz)
    window_end = datetime.combine(last + timedelta(days=1), time.min, tzinfo=tz)
    templates, exceptions = await availability_service._schedule_rules(
        db, doctor_id, first, last, window_start, window_end
    )
    grid = {
        (s.starts_at, s.ends_at)
        for s in availability_service.working_slots(templates, exceptions, tz, first, last, timing)
    }
    return [a for a in upcoming if (a.starts_at, a.ends_at) not in grid]


def _affected(rows) -> list[AffectedAppointment]:
    return [
        AffectedAppointment(
            id=a.id,
            starts_at=a.starts_at,
            ends_at=a.ends_at,
            duration_minutes=int((a.ends_at - a.starts_at).total_seconds() // 60),
        )
        for a in rows[:AFFECTED_LIMIT]
    ]


async def preview(
    db: AsyncSession, principal: Principal, doctor_id: uuid.UUID, req: SchedulePreviewRequest
) -> SchedulePreview:
    """The times one date would offer with a proposed length and buffer, from
    the same engine as booking (weekly hours, custom hours, breaks, leave,
    blocks, existing bookings), and the upcoming bookings that would not fit.
    Saves nothing. Readable by whoever may read the policy (doctor, staff)."""
    from app.models.appointment import ACTIVE_STATUSES, Appointment
    from app.services import availability_service

    if await db.get(Doctor, doctor_id) is None:
        raise NotFoundError("Doctor not found")
    _ensure_can_read(principal, doctor_id)
    tz = await _doctor_tz(db, doctor_id)
    timing = availability_service.Timing(req.consultation_minutes, req.buffer_minutes)
    day: date = req.date
    start = datetime.combine(day, time.min, tzinfo=tz)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz)
    templates, exceptions = await availability_service._schedule_rules(db, doctor_id, day, day, start, end)
    slots = availability_service.working_slots(templates, exceptions, tz, day, day, timing)
    busy = (
        await db.execute(
            select(Appointment.starts_at, Appointment.ends_at).where(
                Appointment.doctor_id == doctor_id,
                Appointment.status.in_(ACTIVE_STATUSES),
                Appointment.starts_at < end,
                Appointment.ends_at > start,
            )
        )
    ).all()
    now = clock.utcnow()
    board = []
    for slot in sorted(set(slots)):
        if slot.starts_at < now:
            status = "past"
        elif any(slot.overlaps(a, b) for a, b in busy):
            status = "booked"
        else:
            status = "free"
        board.append(PreviewSlot(starts_at=slot.starts_at, ends_at=slot.ends_at, status=status))
    exact = availability_service.working_slots(templates, exceptions, tz, day, day, availability_service.FINE_GRID)
    hours = availability_service.merge_hours(exact, tz)
    affected = await misfits(db, doctor_id, timing, tz)
    return SchedulePreview(
        doctor_id=doctor_id,
        date=day,
        timezone=str(tz),
        consultation_minutes=timing.minutes,
        buffer_minutes=timing.buffer,
        working_hours=[(a.strftime("%H:%M"), b.strftime("%H:%M")) for a, b in hours],
        slots=board,
        free_count=sum(1 for b in board if b.status == "free"),
        booked_count=sum(1 for b in board if b.status == "booked"),
        affected_count=len(affected),
        affected=_affected(affected),
    )


async def update_policy(
    db: AsyncSession, principal: Principal, doctor_id: uuid.UUID, data: SchedulingPolicyWrite, *, ip: str | None = None
) -> SchedulingPolicyRead:
    if await db.get(Doctor, doctor_id) is None:
        raise NotFoundError("Doctor not found")
    if not can_manage(principal, doctor_id):
        raise PermissionDeniedError("Only the doctor (or an administrator) can change this scheduling policy")
    row = await db.get(SchedulingPolicy, doctor_id, with_for_update=True)
    before = None if row is None else {f: getattr(row, f) for f in FIELDS}

    # A new length or buffer must not silently strand upcoming bookings (D120):
    # list them and require the explicit choice to keep them at their times.
    from app.services import availability_service

    new_timing = availability_service.Timing(data.consultation_minutes, data.buffer_minutes)
    kept = 0
    if row is None or availability_service.timing_of(row) != new_timing:
        stranded = await misfits(db, doctor_id, new_timing, await _doctor_tz(db, doctor_id))
        if stranded and not getattr(data, "keep_existing_appointments", False):
            raise ConflictError(
                f"{len(stranded)} upcoming appointment(s) do not fit the new length. They keep their booked "
                "times: confirm to save, or reschedule them first.",
                code="SCHEDULE_CONFLICTS",
                details={
                    "count": len(stranded),
                    "appointments": [a.model_dump(mode="json") for a in _affected(stranded)],
                },
            )
        kept = len(stranded)
    if row is None:
        row = SchedulingPolicy(doctor_id=doctor_id)
        db.add(row)
    for field in FIELDS:
        setattr(row, field, getattr(data, field))
    row.updated_by_user_id = principal.user_id
    row.updated_at = clock.utcnow()
    after = {f: (v.value if hasattr(v, "value") else v) for f, v in data.model_dump(include=set(FIELDS)).items()}
    audit_service.record(
        db, AuditAction.scheduling_policy_changed, actor_id=principal.user_id, target_type="doctor", target_id=doctor_id,
        ip_address=ip,
        details={
            "before": {f: (v.value if hasattr(v, "value") else v) for f, v in before.items()} if before else None,
            "after": after,
            "kept_appointments": kept,
        },
    )
    await db.commit()
    logger.info("scheduling_policy_changed", extra={"doctor_id": str(doctor_id), "by": str(principal.user_id)})
    return await _read(db, doctor_id, row)
