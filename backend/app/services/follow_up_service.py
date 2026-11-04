"""Follow-up visits recorded as due by a date (D108).

Only the appointment's doctor or staff who manage appointments record one, on
an appointment they can see. It is a date and nothing more: no reason, no
clinical note, no interval invented by the system or the AI, and never a
booking. The reminder run mentions it to the patient shortly before it is
due, unless they booked or it was dismissed.
"""

import logging
import uuid
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.exceptions import BusinessRuleError, NotFoundError, PermissionDeniedError
from app.core.permissions import Perm, Principal
from app.models.appointment import Appointment
from app.models.department import Department
from app.models.doctor import Doctor
from app.models.notification import FollowUp
from app.services import access

logger = logging.getLogger(__name__)

MAX_AHEAD_DAYS = 730


async def _visible_appointment(db: AsyncSession, principal: Principal, appointment_id: uuid.UUID) -> Appointment:
    appt = await db.scalar(
        select(Appointment).where(Appointment.id == appointment_id, access.appointment_visibility(principal))
    )
    if appt is None:
        raise NotFoundError("Appointment not found")
    return appt


def _may_record(principal: Principal, appt: Appointment) -> bool:
    return principal.has(Perm.appointment_manage) or (principal.doctor_id is not None and principal.doctor_id == appt.doctor_id)


async def _open_for(db: AsyncSession, appointment_id: uuid.UUID) -> FollowUp | None:
    return await db.scalar(
        select(FollowUp).where(FollowUp.appointment_id == appointment_id, FollowUp.dismissed_at.is_(None))
    )


async def get_for_appointment(db: AsyncSession, principal: Principal, appointment_id: uuid.UUID) -> tuple[FollowUp | None, bool]:
    """The open follow-up of a visible appointment, and whether the caller may change it."""
    appt = await _visible_appointment(db, principal, appointment_id)
    return await _open_for(db, appointment_id), _may_record(principal, appt)


async def record(db: AsyncSession, principal: Principal, appointment_id: uuid.UUID, due_date: date) -> FollowUp:
    """Record (or move) the follow-up of an appointment."""
    appt = await _visible_appointment(db, principal, appointment_id)
    if not _may_record(principal, appt):
        raise PermissionDeniedError("Only the doctor or the clinic can record a follow-up")
    tz = await db.scalar(
        select(Department.timezone).join(Doctor, Doctor.department_id == Department.id).where(Doctor.id == appt.doctor_id)
    )
    today = clock.utcnow().astimezone(ZoneInfo(tz)).date()
    if not today < due_date <= today + timedelta(days=MAX_AHEAD_DAYS):
        raise BusinessRuleError("The follow-up date must be in the future, within two years", code="INVALID_FOLLOW_UP_DATE")
    follow_up = await _open_for(db, appointment_id)
    if follow_up is None:
        follow_up = FollowUp(
            patient_id=appt.patient_id, doctor_id=appt.doctor_id, appointment_id=appt.id, created_by_user_id=principal.user_id
        )
        db.add(follow_up)
    follow_up.due_date = due_date
    # A moved date counts from now: it is reminded about again, and bookings made
    # before this change do not cancel it out.
    follow_up.created_at = clock.utcnow()
    await db.commit()
    await db.refresh(follow_up)
    logger.info("follow_up_recorded", extra={"follow_up_id": str(follow_up.id), "by": str(principal.user_id)})
    return follow_up


async def dismiss(db: AsyncSession, principal: Principal, follow_up_id: uuid.UUID) -> None:
    """The patient (their own) or the doctor/clinic (as for recording) closes it: no more reminders."""
    follow_up = await db.get(FollowUp, follow_up_id)
    if follow_up is None or follow_up.dismissed_at is not None:
        raise NotFoundError("Follow-up not found")
    own = principal.patient_id is not None and principal.patient_id == follow_up.patient_id
    if not own:
        appt = await db.scalar(
            select(Appointment).where(Appointment.id == follow_up.appointment_id, access.appointment_visibility(principal))
        )
        if appt is None:
            raise NotFoundError("Follow-up not found")
        if not _may_record(principal, appt):
            raise PermissionDeniedError("You cannot dismiss this follow-up")
    follow_up.dismissed_at = clock.utcnow()
    await db.commit()
    logger.info("follow_up_dismissed", extra={"follow_up_id": str(follow_up_id), "by": str(principal.user_id)})
