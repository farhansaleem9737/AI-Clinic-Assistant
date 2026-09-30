"""Appointment booking, lifecycle and rescheduling.

Every rule lives here, not in the router:
- who may book for whom, and only into a slot that is actually free;
- record-level visibility (others' appointments are 404);
- status changes only through the state machine (appointment_state);
- double-booking is finally prevented by the database's EXCLUDE constraints,
  whose violations are translated into clear 409s.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import Select, func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core import clock
from app.core.config import settings
from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError, PermissionDeniedError
from app.core.permissions import Perm, Principal
from app.models.appointment import (
    ACTIVE_STATUSES,
    Appointment,
    AppointmentStatus,
    AppointmentStatusHistory,
    CancellationReason,
)
from app.models.department import Department
from app.models.doctor import Doctor
from app.models.patient import Patient
from app.models.user import User
from app.schemas.appointment import AppointmentCreate, AppointmentUpdate, Reschedule, StatusChange
from app.services import access, appointment_state, availability_service
from app.services.appointment_state import Context
from app.services.pagination import PageParams, paginate

logger = logging.getLogger(__name__)
S = AppointmentStatus


@dataclass(frozen=True)
class AppointmentView:
    """An appointment plus the related fields its responses need."""

    appointment: Appointment
    doctor_name: str
    doctor_title: str | None
    doctor_room: str | None
    specialization: str
    department_id: uuid.UUID
    department_name: str
    timezone: str
    patient_mrn: str
    patient_name: str
    patient_dob: date
    rescheduled_to_id: uuid.UUID | None
    allowed_transitions: list[str]
    can_reschedule: bool


@dataclass(frozen=True)
class AppointmentFilters:
    patient_id: uuid.UUID | None = None
    doctor_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    statuses: tuple[AppointmentStatus, ...] = ()
    date_from: date | None = None
    date_to: date | None = None
    newest_first: bool = False


_Successor = aliased(Appointment)


def _view_query() -> Select:
    doctor_user = aliased(User)
    return (
        select(
            Appointment,
            doctor_user.name,
            Doctor.title,
            Doctor.room_number,
            Doctor.specialization,
            Department.id,
            Department.name,
            Department.timezone,
            Patient.mrn,
            Patient.first_name,
            Patient.last_name,
            Patient.date_of_birth,
            _Successor.id,
        )
        .join(Doctor, Doctor.id == Appointment.doctor_id)
        .join(doctor_user, doctor_user.id == Doctor.user_id)
        .join(Department, Department.id == Doctor.department_id)
        .join(Patient, Patient.id == Appointment.patient_id)
        .outerjoin(_Successor, _Successor.rescheduled_from_id == Appointment.id)
    )


def _to_view(row, principal: Principal, now: datetime) -> AppointmentView:
    (appt, doctor_name, title, room, specialization, dept_id, dept_name, tz, mrn, first, last, dob, successor_id) = row
    ctx = Context(principal=principal, appointment=appt, now=now, timezone=ZoneInfo(tz))
    allowed, can_reschedule = appointment_state.allowed_actions(ctx)
    return AppointmentView(
        appointment=appt,
        doctor_name=doctor_name,
        doctor_title=title,
        doctor_room=room,
        specialization=specialization,
        department_id=dept_id,
        department_name=dept_name,
        timezone=tz,
        patient_mrn=mrn,
        patient_name=f"{first} {last}",
        patient_dob=dob,
        rescheduled_to_id=successor_id,
        allowed_transitions=allowed,
        can_reschedule=can_reschedule,
    )


# ---- reads ------------------------------------------------------------------------


async def get_view(db: AsyncSession, principal: Principal, appointment_id: uuid.UUID) -> AppointmentView:
    row = (
        await db.execute(
            _view_query().where(Appointment.id == appointment_id, access.appointment_visibility(principal))
        )
    ).one_or_none()
    if row is None:
        raise NotFoundError("Appointment not found")
    return _to_view(row, principal, clock.utcnow())


def _local_day_start(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=ZoneInfo(settings.clinic_timezone))


async def list_appointments(
    db: AsyncSession, principal: Principal, params: PageParams, filters: AppointmentFilters
) -> tuple[list[AppointmentView], int]:
    query = _view_query().where(access.appointment_visibility(principal))
    if filters.patient_id:
        query = query.where(Appointment.patient_id == filters.patient_id)
    if filters.doctor_id:
        query = query.where(Appointment.doctor_id == filters.doctor_id)
    if filters.department_id:
        query = query.where(Doctor.department_id == filters.department_id)
    if filters.statuses:
        query = query.where(Appointment.status.in_(filters.statuses))
    # Calendar dates are interpreted in the clinic's timezone.
    if filters.date_from:
        query = query.where(Appointment.starts_at >= _local_day_start(filters.date_from))
    if filters.date_to:
        query = query.where(Appointment.starts_at < _local_day_start(filters.date_to + timedelta(days=1)))
    order = Appointment.starts_at.desc() if filters.newest_first else Appointment.starts_at.asc()
    query = query.order_by(order, Appointment.id)

    rows, total = await paginate(db, query, params)
    now = clock.utcnow()
    return [_to_view(r, principal, now) for r in rows], total


async def history(db: AsyncSession, principal: Principal, appointment_id: uuid.UUID) -> list[AppointmentStatusHistory]:
    await get_view(db, principal, appointment_id)  # visibility check
    result = await db.scalars(
        select(AppointmentStatusHistory)
        .where(AppointmentStatusHistory.appointment_id == appointment_id)
        .order_by(AppointmentStatusHistory.changed_at, AppointmentStatusHistory.id)
    )
    return list(result.all())


# ---- booking ------------------------------------------------------------------------


def _record(db: AsyncSession, appt: Appointment, from_status, to_status, by: uuid.UUID | None, reason=None) -> None:
    db.add(
        AppointmentStatusHistory(
            appointment_id=appt.id, from_status=from_status, to_status=to_status, changed_by_user_id=by, reason=reason
        )
    )


def booking_lead(principal: Principal) -> timedelta:
    """Staff may book any future slot; patients need notice."""
    if principal.has(Perm.appointment_create):
        return timedelta(0)
    return timedelta(minutes=settings.booking_min_lead_minutes)


async def _find_free_slot(
    db: AsyncSession,
    principal: Principal,
    doctor_id: uuid.UUID,
    starts_at: datetime,
    exclude_appointment_id: uuid.UUID | None = None,
) -> availability_service.Slot:
    bookable = await availability_service.bookable_doctor(db, doctor_id)
    local_day = starts_at.astimezone(bookable.timezone).date()
    _, slots = await availability_service.available_slots(
        db,
        doctor_id,
        local_day,
        local_day,
        now=clock.utcnow(),
        min_lead=booking_lead(principal),
        exclude_appointment_id=exclude_appointment_id,
    )
    for slot in slots:
        if slot.starts_at == starts_at:
            return slot
    raise ConflictError("That time is not available", code="SLOT_UNAVAILABLE")


async def _resolve_patient(db: AsyncSession, principal: Principal, requested: uuid.UUID | None) -> Patient:
    if principal.has(Perm.appointment_create):
        if requested is None:
            raise BusinessRuleError("patient_id is required", code="PATIENT_REQUIRED")
        patient = await db.get(Patient, requested)
    else:
        if principal.patient_id is None:
            raise BusinessRuleError("Complete your patient profile before booking", code="NO_PATIENT_PROFILE")
        if requested is not None and requested != principal.patient_id:
            # Same answer as a non-existent patient: no disclosure.
            raise NotFoundError("Patient not found")
        patient = await db.get(Patient, principal.patient_id)
    if patient is None:
        raise NotFoundError("Patient not found")
    if not patient.is_active:
        raise BusinessRuleError("Patient record is inactive", code="PATIENT_INACTIVE")
    return patient


async def _ensure_patient_free(
    db: AsyncSession, patient_id: uuid.UUID, slot: availability_service.Slot, exclude_id: uuid.UUID | None = None
) -> None:
    query = select(Appointment.id).where(
        Appointment.patient_id == patient_id,
        Appointment.status.in_(ACTIVE_STATUSES),
        Appointment.starts_at < slot.ends_at,
        Appointment.ends_at > slot.starts_at,
    )
    if exclude_id is not None:
        query = query.where(Appointment.id != exclude_id)
    if await db.scalar(query.limit(1)) is not None:
        raise ConflictError("The patient already has an appointment at that time", code="PATIENT_DOUBLE_BOOKED")


def _conflict_from(exc: IntegrityError) -> ConflictError:
    constraint = getattr(getattr(exc.orig, "__cause__", None), "constraint_name", None) or ""
    if "doctor_overlap" in constraint:
        return ConflictError("That time was just booked by someone else", code="SLOT_TAKEN")
    if "patient_overlap" in constraint:
        return ConflictError("The patient already has an appointment at that time", code="PATIENT_DOUBLE_BOOKED")
    if "idempotency_key" in constraint:
        return ConflictError("This booking request was already submitted", code="DUPLICATE_REQUEST")
    return ConflictError("The request conflicts with existing data")


# PostgreSQL deadlock_detected / serialization_failure: the request lost a
# race with another one and can simply be retried.
_RETRYABLE_SQLSTATES = {"40P01", "40001"}


async def _flush_or_conflict(db: AsyncSession) -> None:
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise _conflict_from(exc) from None
    except DBAPIError as exc:
        if getattr(getattr(exc.orig, "__cause__", None), "sqlstate", None) not in _RETRYABLE_SQLSTATES:
            raise
        await db.rollback()
        raise ConflictError("Another booking was being made at the same time; please try again", code="BOOKING_RACE") from None


async def _serialize_bookings(db: AsyncSession, doctor_id: uuid.UUID, patient_id: uuid.UUID) -> None:
    """Take transaction-scoped advisory locks on the doctor and the patient.

    Without them, two requests for one slot can both pass the availability
    check and insert at the same moment; each insert's EXCLUDE check then
    waits on the other's uncommitted row and PostgreSQL aborts one as a
    deadlock. With them, the second request waits until the first commits,
    re-checks availability and gets a clean 409. The EXCLUDE constraints
    remain the final guarantee.

    Always doctor first, then patient, so these locks cannot deadlock each other.
    """
    for namespace, key in ((1, doctor_id), (2, patient_id)):
        await db.execute(text("SELECT pg_advisory_xact_lock(:ns, hashtext(:key))"), {"ns": namespace, "key": str(key)})


def _new_appointment(
    db: AsyncSession,
    principal: Principal,
    *,
    patient_id: uuid.UUID,
    doctor_id: uuid.UUID,
    slot: availability_service.Slot,
    reason: str | None,
    staff_notes: str | None = None,
    idempotency_key: str | None = None,
    rescheduled_from_id: uuid.UUID | None = None,
) -> Appointment:
    """Add a new booking (not yet flushed). Its history is written by
    ``_record_booking`` once the insert has succeeded."""
    appt = Appointment(
        patient_id=patient_id,
        doctor_id=doctor_id,
        starts_at=slot.starts_at,
        ends_at=slot.ends_at,
        status=S.scheduled,
        reason=reason,
        staff_notes=staff_notes,
        booked_by_user_id=principal.user_id,
        idempotency_key=idempotency_key,
        rescheduled_from_id=rescheduled_from_id,
    )
    db.add(appt)
    return appt


def _record_booking(db: AsyncSession, appt: Appointment, principal: Principal) -> None:
    """A booking is *requested* and — the slot having been verified free —
    immediately *scheduled* by the system (architecture §8). Both steps are
    kept in the history."""
    _record(db, appt, None, S.requested, principal.user_id)
    _record(db, appt, S.requested, S.scheduled, None, "Slot available; scheduled automatically")


async def book(
    db: AsyncSession, principal: Principal, data: AppointmentCreate, idempotency_key: str | None
) -> tuple[AppointmentView, bool]:
    """Returns (appointment, replayed). A repeated Idempotency-Key returns the
    original appointment instead of booking again."""
    if idempotency_key:
        existing = await db.scalar(
            select(Appointment).where(
                Appointment.booked_by_user_id == principal.user_id, Appointment.idempotency_key == idempotency_key
            )
        )
        if existing is not None:
            if existing.doctor_id != data.doctor_id or existing.starts_at != data.starts_at:
                raise ConflictError(
                    "This Idempotency-Key was used for a different booking", code="IDEMPOTENCY_KEY_REUSED"
                )
            return await get_view(db, principal, existing.id), True

    patient = await _resolve_patient(db, principal, data.patient_id)
    await _serialize_bookings(db, data.doctor_id, patient.id)
    slot = await _find_free_slot(db, principal, data.doctor_id, data.starts_at)
    await _ensure_patient_free(db, patient.id, slot)

    appt = _new_appointment(
        db,
        principal,
        patient_id=patient.id,
        doctor_id=data.doctor_id,
        slot=slot,
        reason=data.reason,
        idempotency_key=idempotency_key,
    )
    await _flush_or_conflict(db)
    _record_booking(db, appt, principal)
    await db.commit()
    logger.info(
        "appointment_booked",
        extra={"appointment_id": str(appt.id), "doctor_id": str(appt.doctor_id), "by": str(principal.user_id)},
    )
    return await get_view(db, principal, appt.id), False


# ---- changes ------------------------------------------------------------------------


async def _locked_context(db: AsyncSession, principal: Principal, appointment_id: uuid.UUID) -> Context:
    """Visible appointment, row-locked so concurrent changes serialize."""
    appt = await db.scalar(
        select(Appointment)
        .where(Appointment.id == appointment_id, access.appointment_visibility(principal))
        .with_for_update()
    )
    if appt is None:
        raise NotFoundError("Appointment not found")
    tz = await db.scalar(
        select(Department.timezone).join(Doctor, Doctor.department_id == Department.id).where(Doctor.id == appt.doctor_id)
    )
    return Context(principal=principal, appointment=appt, now=clock.utcnow(), timezone=ZoneInfo(tz))


def _cancel(ctx: Context, reason: CancellationReason, note: str | None) -> None:
    appt = ctx.appointment
    appt.status = S.cancelled
    appt.cancellation_reason = reason
    appt.cancellation_note = note
    appt.cancelled_at = ctx.now
    appt.cancelled_by_user_id = ctx.principal.user_id


async def change_status(
    db: AsyncSession, principal: Principal, appointment_id: uuid.UUID, change: StatusChange
) -> AppointmentView:
    ctx = await _locked_context(db, principal, appointment_id)
    appt = ctx.appointment
    appointment_state.authorize_transition(ctx, change.status)

    previous = appt.status
    if change.status is S.cancelled:
        _cancel(ctx, change.cancellation_reason, change.note)
    else:
        appt.status = change.status
    _record(db, appt, previous, change.status, principal.user_id, change.note)
    await db.commit()
    logger.info(
        "appointment_status_changed",
        extra={
            "appointment_id": str(appt.id),
            "from": previous.value,
            "to": change.status.value,
            "by": str(principal.user_id),
        },
    )
    return await get_view(db, principal, appt.id)


async def reschedule(
    db: AsyncSession, principal: Principal, appointment_id: uuid.UUID, data: Reschedule
) -> AppointmentView:
    """Cancel-and-rebook in one transaction (architecture D12): the old row is
    cancelled with reason ``rescheduled`` and the new one points back to it."""
    ctx = await _locked_context(db, principal, appointment_id)
    old = ctx.appointment
    appointment_state.authorize_reschedule(ctx)

    doctor_id = data.doctor_id or old.doctor_id
    await _serialize_bookings(db, doctor_id, old.patient_id)
    # The old appointment's own time does not count as busy: moving it by
    # fifteen minutes within its current slot is allowed.
    slot = await _find_free_slot(db, principal, doctor_id, data.starts_at, exclude_appointment_id=old.id)
    await _ensure_patient_free(db, old.patient_id, slot, exclude_id=old.id)

    previous = old.status
    _cancel(ctx, CancellationReason.rescheduled, data.note)
    _record(db, old, previous, S.cancelled, principal.user_id, data.note or "Rescheduled")
    # Release the old slot before claiming the new one, or the overlap
    # constraint would see both.
    await _flush_or_conflict(db)

    new = _new_appointment(
        db,
        principal,
        patient_id=old.patient_id,
        doctor_id=doctor_id,
        slot=slot,
        reason=old.reason,
        staff_notes=old.staff_notes,
        rescheduled_from_id=old.id,
    )
    await _flush_or_conflict(db)
    _record_booking(db, new, principal)
    await db.commit()
    logger.info(
        "appointment_rescheduled",
        extra={"from_appointment_id": str(old.id), "to_appointment_id": str(new.id), "by": str(principal.user_id)},
    )
    return await get_view(db, principal, new.id)


async def update(
    db: AsyncSession, principal: Principal, appointment_id: uuid.UUID, data: AppointmentUpdate
) -> AppointmentView:
    ctx = await _locked_context(db, principal, appointment_id)
    if not principal.has(Perm.appointment_manage):
        raise PermissionDeniedError("You are not allowed to edit appointments")
    changes = data.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(ctx.appointment, field, value)
    await db.commit()
    logger.info("appointment_updated", extra={"appointment_id": str(appointment_id), "fields": sorted(changes)})
    return await get_view(db, principal, appointment_id)


async def count_upcoming(
    db: AsyncSession, *, doctor_id: uuid.UUID | None = None, patient_id: uuid.UUID | None = None
) -> int:
    """Active appointments that have not started yet."""
    query = select(func.count(Appointment.id)).where(
        Appointment.status.in_((S.requested, S.scheduled, S.confirmed, S.checked_in)),
        Appointment.starts_at >= clock.utcnow(),
    )
    if doctor_id is not None:
        query = query.where(Appointment.doctor_id == doctor_id)
    if patient_id is not None:
        query = query.where(Appointment.patient_id == patient_id)
    return await db.scalar(query) or 0
