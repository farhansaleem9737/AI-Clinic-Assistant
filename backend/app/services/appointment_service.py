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
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, Select, and_, func, or_, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core import clock
from app.core.config import settings
from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError, PermissionDeniedError
from app.core.permissions import Perm, Principal, RoleCode
from app.models.appointment import (
    ACTIVE_STATUSES,
    Appointment,
    AppointmentStatus,
    AppointmentStatusHistory,
    CancellationReason,
    upcoming_condition,
)
from app.models.department import Department
from app.models.doctor import Doctor
from app.models.patient import Patient
from app.models.scheduling import QueueEntry, SchedulingMode
from app.models.stored_file import StoredFile
from app.models.user import User
from app.schemas.appointment import AppointmentCreate, AppointmentUpdate, Reschedule, StatusChange
from app.services import (
    access,
    appointment_state,
    audit_service,
    availability_service,
    email_outbox_service,
    notification_service,
    scheduling_service,
)
from app.services.audit_service import AuditAction
from app.services.appointment_state import Context
from app.services.pagination import PageParams, paginate
from app.services.search_text import NameMatch, contains_pattern

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
    years_of_experience: int
    doctor_verified: bool
    department_id: uuid.UUID
    department_name: str
    timezone: str
    patient_mrn: str
    patient_name: str
    patient_dob: date
    rescheduled_to_id: uuid.UUID | None
    allowed_transitions: list[str]
    can_reschedule: bool
    # Object key of the doctor's profile photo, if any (signed by the endpoint).
    doctor_photo_key: str | None = None
    # The same for the patient's photo.
    patient_photo_key: str | None = None
    patient_sex: str | None = None
    token_number: int | None = None
    queue_state: str | None = None
    # D120: the n-th active appointment of the doctor's local day, by time.
    queue_position: int | None = None


class AppointmentScope(StrEnum):
    """Upcoming: open and not yet ended (the dashboards' definition).
    Past: everything else (finished, cancelled, missed or over)."""

    upcoming = "upcoming"
    past = "past"
    all = "all"


class AppointmentSort(StrEnum):
    """Columns the appointment table may sort by (D84). Never a raw column name."""

    time_asc = "time_asc"
    time_desc = "time_desc"
    patient_asc = "patient_asc"
    patient_desc = "patient_desc"
    doctor_asc = "doctor_asc"
    doctor_desc = "doctor_desc"
    department_asc = "department_asc"
    department_desc = "department_desc"
    # Lifecycle order (requested, scheduled, confirmed, ...), as the enum is declared.
    status_asc = "status_asc"
    status_desc = "status_desc"


@dataclass(frozen=True)
class AppointmentFilters:
    patient_id: uuid.UUID | None = None
    doctor_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    statuses: tuple[AppointmentStatus, ...] = ()
    date_from: date | None = None
    date_to: date | None = None
    # Free text: the doctor's name, specialization or department.
    q: str | None = None
    scope: AppointmentScope = AppointmentScope.all
    newest_first: bool = False
    # When set, overrides newest_first; time and id always break ties.
    sort: AppointmentSort | None = None


_Successor = aliased(Appointment)
_PatientPhoto = aliased(StoredFile)


def appointment_department():
    """The department an appointment belongs to: the one recorded at booking
    (D92), else, for older rows, the doctor's current one. Needs Doctor joined."""
    return func.coalesce(Appointment.department_id, Doctor.department_id)


def _view_query(doctor_user=None) -> Select:
    doctor_user = doctor_user if doctor_user is not None else aliased(User)
    return (
        select(
            Appointment,
            doctor_user.name,
            Doctor.title,
            Doctor.room_number,
            Doctor.specialization,
            Doctor.years_of_experience,
            Doctor.license_number,
            Department.id,
            Department.name,
            Department.timezone,
            Patient.mrn,
            Patient.first_name,
            Patient.last_name,
            Patient.date_of_birth,
            Patient.sex_at_birth,
            _Successor.id,
            StoredFile.object_key,
            _PatientPhoto.object_key,
            QueueEntry.token_number,
            QueueEntry.state,
        )
        .join(Doctor, Doctor.id == Appointment.doctor_id)
        .join(doctor_user, doctor_user.id == Doctor.user_id)
        .join(Department, Department.id == appointment_department())
        .join(Patient, Patient.id == Appointment.patient_id)
        .outerjoin(_Successor, _Successor.rescheduled_from_id == Appointment.id)
        .outerjoin(StoredFile, StoredFile.id == Doctor.photo_file_id)
        .outerjoin(_PatientPhoto, _PatientPhoto.id == Patient.photo_file_id)
        .outerjoin(QueueEntry, QueueEntry.appointment_id == Appointment.id)
    )


def _to_view(row, principal: Principal, now: datetime) -> AppointmentView:
    (
        appt, doctor_name, title, room, specialization, experience, license_number,
        dept_id, dept_name, tz, mrn, first, last, dob, sex, successor_id, photo_key, patient_photo_key,
        token, queue_state,
    ) = row
    ctx = Context(principal=principal, appointment=appt, now=now, timezone=ZoneInfo(tz))
    allowed, can_reschedule = appointment_state.allowed_actions(ctx)
    return AppointmentView(
        appointment=appt,
        doctor_name=doctor_name,
        doctor_title=title,
        doctor_room=room,
        specialization=specialization,
        years_of_experience=experience,
        # Same rule as the public directory (D58); the number is never exposed.
        doctor_verified=bool(license_number),
        department_id=dept_id,
        department_name=dept_name,
        timezone=tz,
        patient_mrn=mrn,
        patient_name=f"{first} {last}",
        patient_dob=dob,
        rescheduled_to_id=successor_id,
        allowed_transitions=allowed,
        can_reschedule=can_reschedule,
        doctor_photo_key=photo_key,
        patient_photo_key=patient_photo_key,
        patient_sex=sex.value if sex is not None else None,
        token_number=token,
        queue_state=queue_state.value if queue_state is not None else None,
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
    view = _to_view(row, principal, clock.utcnow())
    a = view.appointment
    if a.status in ACTIVE_STATUSES:
        position = await queue_position(db, a.doctor_id, a.starts_at, ZoneInfo(view.timezone), appointment_id=a.id)
        view = replace(view, queue_position=position)
    return view


@dataclass(frozen=True)
class AppointmentDetail:
    view: AppointmentView
    # None when the caller may see the appointment but not the patient record.
    patient: Patient | None


async def get_detail(db: AsyncSession, principal: Principal, appointment_id: uuid.UUID) -> AppointmentDetail:
    """One appointment plus the patient's profile for the detail page. The
    profile goes through the patient visibility rule, not the appointment's:
    seeing a booking does not by itself grant reading the patient record."""
    view = await get_view(db, principal, appointment_id)
    patient = await db.scalar(
        select(Patient).where(Patient.id == view.appointment.patient_id, access.patient_visibility(principal))
    )
    return AppointmentDetail(view=view, patient=patient)


def _local_day_start(day: date, tz: ZoneInfo | None = None) -> datetime:
    return datetime.combine(day, time.min, tzinfo=tz or ZoneInfo(settings.clinic_timezone))


async def filter_timezone(db: AsyncSession, principal: Principal, filters: AppointmentFilters) -> ZoneInfo:
    """Which calendar the list's dates mean: the chosen doctor's department,
    else a doctor's own department, else the clinic's timezone."""
    doctor_id = filters.doctor_id
    if doctor_id is None and principal.doctor_id is not None and not principal.has(Perm.appointment_read_any):
        doctor_id = principal.doctor_id
    if doctor_id is not None:
        tz = await db.scalar(
            select(Department.timezone).join(Doctor, Doctor.department_id == Department.id).where(Doctor.id == doctor_id)
        )
        if tz:
            return ZoneInfo(tz)
    return ZoneInfo(settings.clinic_timezone)


def _scope_condition(scope: AppointmentScope, now: datetime) -> ColumnElement[bool] | None:
    if scope is AppointmentScope.upcoming:
        return upcoming_condition(now)
    if scope is AppointmentScope.past:
        return ~upcoming_condition(now)
    return None


def _filtered(
    query: Select,
    filters: AppointmentFilters,
    doctor_user,
    principal: Principal,
    tz: ZoneInfo,
    *,
    with_dates: bool = True,
) -> Select:
    """Every list filter except the scope, shared by the list and its counts.
    The query must already join Doctor, the doctor's User, Department and Patient."""
    if filters.date_from and filters.date_to and filters.date_from > filters.date_to:
        raise BusinessRuleError("date_from must not be after date_to", code="INVALID_RANGE")
    if filters.patient_id:
        query = query.where(Appointment.patient_id == filters.patient_id)
    if filters.doctor_id:
        query = query.where(Appointment.doctor_id == filters.doctor_id)
    if filters.department_id:
        query = query.where(appointment_department() == filters.department_id)
    if filters.statuses:
        query = query.where(Appointment.status.in_(filters.statuses))
    # Calendar dates are interpreted in `tz` (see filter_timezone).
    if with_dates and filters.date_from:
        query = query.where(Appointment.starts_at >= _local_day_start(filters.date_from, tz))
    if with_dates and filters.date_to:
        query = query.where(Appointment.starts_at < _local_day_start(filters.date_to + timedelta(days=1), tz))
    if filters.q and filters.q.strip():
        pattern = contains_pattern(filters.q)
        like = lambda column: column.ilike(pattern, escape="\\")  # noqa: E731
        # The doctor's name however it is typed ("dr sarah khan"; D114).
        doctor_name = NameMatch(doctor_user.name, filters.q)
        fields = [like(doctor_user.name), like(Doctor.specialization), like(Department.name)]
        if doctor_name.usable:
            fields.append(doctor_name.condition())
        if principal.has_any(Perm.appointment_read_any, Perm.appointment_read_assigned):
            # Doctors and staff look for patients: name, MRN or the reason
            # for the visit. Only within appointments they can already see.
            fields += [
                like(Patient.first_name + " " + Patient.last_name),
                like(Patient.mrn),
                like(Appointment.reason),
            ]
        query = query.where(or_(*fields))
    return query


def _order(filters: AppointmentFilters, doctor_user) -> tuple:
    if filters.sort is None:
        time_order = Appointment.starts_at.desc() if filters.newest_first else Appointment.starts_at.asc()
        return time_order, Appointment.id
    column, direction = filters.sort.value.rsplit("_", 1)
    keys = {
        "time": (Appointment.starts_at,),
        "patient": (Patient.last_name, Patient.first_name),
        "doctor": (doctor_user.name,),
        "department": (Department.name,),
        "status": (Appointment.status,),
    }[column]
    ordered = tuple(k.desc() if direction == "desc" else k.asc() for k in keys)
    return (*ordered, Appointment.starts_at, Appointment.id)


async def list_appointments(
    db: AsyncSession, principal: Principal, params: PageParams, filters: AppointmentFilters
) -> tuple[list[AppointmentView], int]:
    doctor_user = aliased(User)
    tz = await filter_timezone(db, principal, filters)
    query = _filtered(
        _view_query(doctor_user).where(access.appointment_visibility(principal)), filters, doctor_user, principal, tz
    )
    now = clock.utcnow()
    scope = _scope_condition(filters.scope, now)
    if scope is not None:
        query = query.where(scope)
    query = query.order_by(*_order(filters, doctor_user))

    rows, total = await paginate(db, query, params)
    return [_to_view(r, principal, now) for r in rows], total


@dataclass(frozen=True)
class ScopeCounts:
    upcoming: int
    past: int
    all: int
    # Only when asked for (include_today): appointments starting today in the
    # list's timezone, and that date.
    today: int | None = None
    today_date: date | None = None


async def count_by_scope(
    db: AsyncSession, principal: Principal, filters: AppointmentFilters, *, include_today: bool = False
) -> ScopeCounts:
    """How many visible appointments fall in each tab, under the same filters
    as the list (one aggregate query; no rows are loaded)."""
    doctor_user = aliased(User)
    now = clock.utcnow()
    upcoming = upcoming_condition(now)
    tz = await filter_timezone(db, principal, filters)
    today = now.astimezone(tz).date()
    on_today = (Appointment.starts_at >= _local_day_start(today, tz)) & (
        Appointment.starts_at < _local_day_start(today + timedelta(days=1), tz)
    )
    query = _counting(
        select(func.count().filter(upcoming), func.count().filter(~upcoming), func.count(), func.count().filter(on_today)),
        doctor_user,
        principal,
    )
    up, past, total, today_count = (await db.execute(_filtered(query, filters, doctor_user, principal, tz))).one()
    if not include_today:
        return ScopeCounts(upcoming=up, past=past, all=total)
    return ScopeCounts(upcoming=up, past=past, all=total, today=today_count, today_date=today)


def _counting(query: Select, doctor_user, principal: Principal) -> Select:
    return (
        query.select_from(Appointment)
        .join(Doctor, Doctor.id == Appointment.doctor_id)
        .join(doctor_user, doctor_user.id == Doctor.user_id)
        .join(Department, Department.id == appointment_department())
        .join(Patient, Patient.id == Appointment.patient_id)
        .where(access.appointment_visibility(principal))
    )


@dataclass(frozen=True)
class DayCounts:
    timezone: str
    today: date
    day: date
    on_day: int
    upcoming: int
    past: int


async def count_by_day(
    db: AsyncSession, principal: Principal, filters: AppointmentFilters, day: date | None
) -> DayCounts:
    """Counts for a calendar view (the doctor's My Appointments, D79):
    appointments on `day`, after today and before today, in the doctor's
    timezone. Status and search filters apply; date filters do not (the
    three ranges are the dates). Statuses are counted as stored: a cancelled
    appointment tomorrow is still in "upcoming"."""
    doctor_user = aliased(User)
    tz = await filter_timezone(db, principal, filters)
    today = clock.utcnow().astimezone(tz).date()
    day = day or today
    day_start, day_end = _local_day_start(day, tz), _local_day_start(day + timedelta(days=1), tz)
    today_start, tomorrow_start = _local_day_start(today, tz), _local_day_start(today + timedelta(days=1), tz)
    query = _counting(
        select(
            func.count().filter(Appointment.starts_at >= day_start, Appointment.starts_at < day_end),
            func.count().filter(Appointment.starts_at >= tomorrow_start),
            func.count().filter(Appointment.starts_at < today_start),
        ),
        doctor_user,
        principal,
    )
    on_day, upcoming, past = (
        await db.execute(_filtered(query, filters, doctor_user, principal, tz, with_dates=False))
    ).one()
    return DayCounts(timezone=tz.key, today=today, day=day, on_day=on_day, upcoming=upcoming, past=past)


async def history(db: AsyncSession, principal: Principal, appointment_id: uuid.UUID) -> list[AppointmentStatusHistory]:
    await get_view(db, principal, appointment_id)  # visibility check
    result = await db.scalars(
        select(AppointmentStatusHistory)
        .where(AppointmentStatusHistory.appointment_id == appointment_id)
        .order_by(AppointmentStatusHistory.changed_at, AppointmentStatusHistory.id)
    )
    return list(result.all())


# ---- the day's order and the next free time (D120) ---------------------------------


def _local_day_bounds(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    return datetime.combine(day, time.min, tzinfo=tz), datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz)


async def queue_position(
    db: AsyncSession, doctor_id: uuid.UUID, starts_at: datetime, tz: ZoneInfo, *, appointment_id: uuid.UUID | None = None
) -> int:
    """The estimated place in the doctor's local day: 1 + the active
    appointments that start earlier (ties, i.e. double bookings, by creation:
    ids are time-ordered). Derived, never stored, so a cancellation or a move
    earlier in the day moves everyone after it up. One indexed count
    (doctor_id, starts_at) over one day."""
    start, end = _local_day_bounds(starts_at.astimezone(tz).date(), tz)
    earlier = Appointment.starts_at < starts_at
    if appointment_id is not None:
        earlier = or_(earlier, and_(Appointment.starts_at == starts_at, Appointment.id < appointment_id))
    ahead = await db.scalar(
        select(func.count())
        .select_from(Appointment)
        .where(
            Appointment.doctor_id == doctor_id,
            Appointment.status.in_(ACTIVE_STATUSES),
            Appointment.starts_at >= start,
            Appointment.starts_at < end,
            earlier,
        )
    )
    return int(ahead or 0) + 1


@dataclass(frozen=True)
class NextAvailableResult:
    doctor_id: uuid.UUID
    day: date
    timezone: str
    slot: availability_service.Slot | None
    queue_position: int | None
    consultation_minutes: int
    booked_count: int
    free_count: int
    next_date: date | None

    def as_details(self) -> dict:
        return {
            "date": self.day.isoformat(),
            "starts_at": self.slot.starts_at.isoformat() if self.slot else None,
            "ends_at": self.slot.ends_at.isoformat() if self.slot else None,
            "queue_position": self.queue_position,
            "next_date": self.next_date.isoformat() if self.next_date else None,
        }


async def next_available(
    db: AsyncSession,
    principal: Principal,
    doctor_id: uuid.UUID,
    day: date,
    *,
    patient_id: uuid.UUID | None = None,
) -> NextAvailableResult:
    """Automatic token booking (D120): the earliest free time with the doctor
    on ``day``, from the same engine and rules as every other booking (working
    hours, breaks/leave, the doctor's consultation length, existing bookings,
    notice, horizon). Times the patient is already booked elsewhere are
    skipped. Nothing is reserved; the booking re-checks the time.

    Computed from the actual free intervals, not "bookings + 1", so cancelled,
    moved and custom-time bookings are all accounted for."""
    policy = await scheduling_service.effective_policy(db, doctor_id)
    if policy.mode is SchedulingMode.fifo and not principal.has(Perm.appointment_create):
        raise BusinessRuleError(
            "This doctor sees patients in arrival order: ask for a token for the day instead", code="FIFO_ONLY"
        )
    lead = booking_lead(principal)
    now = clock.utcnow()
    bookable, free, _ = await availability_service.slot_board(db, doctor_id, day, day, now=now, min_lead=lead)
    tz = bookable.timezone
    start, end = _local_day_bounds(day, tz)

    if patient_id is not None and free:
        own = (
            await db.execute(
                select(Appointment.starts_at, Appointment.ends_at).where(
                    Appointment.patient_id == patient_id,
                    Appointment.status.in_(ACTIVE_STATUSES),
                    Appointment.starts_at < end,
                    Appointment.ends_at > start,
                )
            )
        ).all()
        free = [s for s in free if not any(a < s.ends_at and s.starts_at < b for a, b in own)]

    booked = await db.scalar(
        select(func.count())
        .select_from(Appointment)
        .where(
            Appointment.doctor_id == doctor_id,
            Appointment.status.in_(ACTIVE_STATUSES),
            Appointment.starts_at >= start,
            Appointment.starts_at < end,
        )
    )
    slot = free[0] if free else None
    position = await queue_position(db, doctor_id, slot.starts_at, tz) if slot else None

    next_date = None
    if slot is None:
        last = min(day + timedelta(days=availability_service.MAX_RANGE_DAYS - 1), availability_service.bookable_until(now, tz))
        if last > day:
            _, later = await availability_service.available_slots(
                db, doctor_id, day + timedelta(days=1), last, now=now, min_lead=lead
            )
            next_date = later[0].starts_at.astimezone(tz).date() if later else None

    minutes = int((slot.ends_at - slot.starts_at).total_seconds() // 60) if slot else policy.consultation_minutes
    return NextAvailableResult(
        doctor_id=doctor_id,
        day=day,
        timezone=str(tz),
        slot=slot,
        queue_position=position,
        consultation_minutes=minutes,
        booked_count=int(booked or 0),
        free_count=len(free),
        next_date=next_date,
    )


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


def _ensure_may_override(principal: Principal, policy) -> None:
    """Only staff with appointment:override, and a receptionist only when the doctor allows it (D117)."""
    if not principal.has(Perm.appointment_override):
        raise PermissionDeniedError("You are not allowed to book outside the normal rules")
    receptionist_only = "receptionist" in principal.roles and "admin" not in principal.roles
    if receptionist_only and not policy.allow_receptionist_overrides:
        raise PermissionDeniedError("This doctor does not allow front-desk overrides", code="OVERRIDES_NOT_ALLOWED")


async def _override_slot(db: AsyncSession, data: AppointmentCreate, policy) -> tuple[availability_service.Slot, int]:
    """The interval and capacity lane for a staff override: inside the doctor's
    working hours, never in the past, and either free (lane 0) or an authorized
    double booking in the lowest free lane up to the doctor's limit (D117).
    The overlap constraint per lane stays the final guarantee."""
    bookable = await availability_service.bookable_doctor(db, data.doctor_id)
    tz = bookable.timezone
    starts_at = data.starts_at
    day = starts_at.astimezone(tz).date()
    window = (datetime.combine(day, time.min, tzinfo=tz), datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz))
    templates, exceptions = await availability_service._schedule_rules(db, data.doctor_id, day, day, *window)
    timing = availability_service.timing_of(await availability_service.scheduling_policy(db, data.doctor_id))
    minutes = data.duration_minutes or (timing.minutes if timing else availability_service.slot_minutes_on(templates, day))
    slot = availability_service.Slot(starts_at, starts_at + timedelta(minutes=minutes))
    now = clock.utcnow()
    if starts_at < now - timedelta(minutes=5) or starts_at > now + timedelta(days=settings.booking_max_advance_days):
        raise BusinessRuleError("Choose a time from now within the booking horizon", code="TIME_OUT_OF_RANGE")
    if data.custom_time:
        if starts_at.astimezone(tz).minute % 5 or starts_at.second or starts_at.microsecond:
            raise BusinessRuleError("Custom times are on 5-minute marks", code="INVALID_CUSTOM_TIME")
    else:
        listed = availability_service.working_slots(templates, exceptions, tz, day, day, timing)
        if not any(s.starts_at == starts_at for s in listed):
            raise ConflictError("That is not one of the doctor's appointment times", code="SLOT_UNAVAILABLE")
    windows = availability_service.working_windows(templates, exceptions, tz, day)
    if not any(a <= slot.starts_at and slot.ends_at <= b for a, b in windows):
        raise ConflictError("That time is outside the doctor's working hours", code="OUTSIDE_WORKING_HOURS")

    async def lane_taken(lane: int) -> bool:
        return await db.scalar(
            select(Appointment.id).where(
                Appointment.doctor_id == data.doctor_id, Appointment.capacity_lane == lane,
                Appointment.status.in_(ACTIVE_STATUSES), Appointment.starts_at < slot.ends_at, Appointment.ends_at > slot.starts_at,
            ).limit(1)
        ) is not None

    if not await lane_taken(0):
        return slot, 0
    if not data.double_booking:
        raise ConflictError("That time is already booked", code="SLOT_TAKEN")
    if not data.override_reason or len(data.override_reason.strip()) < 3:
        raise BusinessRuleError("Give a reason for the double booking", code="OVERRIDE_REASON_REQUIRED")
    if policy.max_overbook == 0:
        raise ConflictError("This doctor does not accept double bookings", code="OVERBOOKING_DISABLED")
    for lane in range(1, policy.max_overbook + 1):
        if not await lane_taken(lane):
            return slot, lane
    raise ConflictError(
        f"The doctor's limit of {policy.max_overbook} extra patient(s) at that time is reached", code="OVERBOOK_CAPACITY_REACHED"
    )


async def resolve_patient(db: AsyncSession, principal: Principal, requested: uuid.UUID | None) -> Patient:
    if principal.has(Perm.appointment_create):
        if requested is None:
            raise BusinessRuleError("patient_id is required", code="PATIENT_REQUIRED")
        # Booking permission is not patient access: the patient must also be
        # one the caller may see (reception: any), or it is "not found".
        patient = await db.scalar(
            select(Patient).where(Patient.id == requested, access.patient_visibility(principal))
        )
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
    booking_mode: str | None = None,
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
        booking_mode=booking_mode,
        # Evaluated in the INSERT itself: the department at the moment of booking.
        department_id=select(Doctor.department_id).where(Doctor.id == doctor_id).scalar_subquery(),
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

    patient = await resolve_patient(db, principal, data.patient_id)
    policy = await scheduling_service.effective_policy(db, data.doctor_id)
    if data.is_override:
        _ensure_may_override(principal, policy)
    elif policy.mode is SchedulingMode.fifo and not principal.has(Perm.appointment_create):
        raise BusinessRuleError(
            "This doctor sees patients in arrival order: ask for a token for the day instead", code="FIFO_ONLY"
        )
    await _serialize_bookings(db, data.doctor_id, patient.id)
    lane = 0
    if data.is_override:
        slot, lane = await _override_slot(db, data, policy)
    else:
        try:
            slot = await _find_free_slot(db, principal, data.doctor_id, data.starts_at)
        except ConflictError as exc:
            if data.booking_mode != "auto":
                raise
            # Taken between the preview and the confirmation: never book another
            # time silently; name the next one so the user can confirm it (D120).
            bookable = await availability_service.bookable_doctor(db, data.doctor_id)
            nxt = await next_available(
                db, principal, data.doctor_id, data.starts_at.astimezone(bookable.timezone).date(), patient_id=patient.id
            )
            raise ConflictError(
                "That time was just taken. Please review the next available time.",
                code=exc.code,
                details={"next_available": nxt.as_details()},
            ) from exc
    await _ensure_patient_free(db, patient.id, slot)

    appt = _new_appointment(
        db,
        principal,
        patient_id=patient.id,
        doctor_id=data.doctor_id,
        slot=slot,
        reason=data.reason,
        idempotency_key=idempotency_key,
        booking_mode="override" if data.is_override else data.booking_mode,
    )
    if data.is_override:
        appt.capacity_lane = lane
        appt.override_reason = data.override_reason
    await _flush_or_conflict(db)
    _record_booking(db, appt, principal)
    if data.is_override:
        audit_service.record(
            db, AuditAction.appointment_override_booked, actor_id=principal.user_id, target_type="appointment",
            target_id=appt.id,
            details={
                "doctor_id": str(appt.doctor_id), "double_booking": lane > 0, "capacity_lane": lane,
                "custom_time": data.custom_time, "duration_minutes": int((slot.ends_at - slot.starts_at).total_seconds() // 60),
                "reason": data.override_reason,
            },
        )
    await _notify_doctor_of_booking(db, appt, principal)
    await _notify_patient_of_booking(db, appt, principal)
    # The patient's receipt by email, however it was booked (D109).
    await email_outbox_service.appointment_email(db, appt, "appointment_booked")
    await db.commit()
    logger.info(
        "appointment_booked",
        extra={"appointment_id": str(appt.id), "doctor_id": str(appt.doctor_id), "by": str(principal.user_id)},
    )
    return await get_view(db, principal, appt.id), False


# ---- notifications (D86): dates and times only, never who or why ----------------------


async def _doctor_user_and_tz(db: AsyncSession, doctor_id: uuid.UUID) -> tuple[uuid.UUID, ZoneInfo]:
    user_id, tz = (
        await db.execute(
            select(Doctor.user_id, Department.timezone)
            .join(Department, Department.id == Doctor.department_id)
            .where(Doctor.id == doctor_id)
        )
    ).one()
    return user_id, ZoneInfo(tz)


async def _notify_doctor_of_booking(db: AsyncSession, appt: Appointment, principal: Principal) -> None:
    doctor_user, tz = await _doctor_user_and_tz(db, appt.doctor_id)
    if doctor_user == principal.user_id:
        return
    notification_service.notify(
        db,
        [doctor_user],
        type="appointment_booked",
        title="New appointment",
        message=f"An appointment was booked for {notification_service.when(appt.starts_at, tz)}.",
        link=f"/appointments/{appt.id}",
    )


async def _patient_user(db: AsyncSession, patient_id: uuid.UUID) -> uuid.UUID | None:
    """The patient's login, if they have one (walk-in records have none)."""
    return await db.scalar(select(Patient.user_id).where(Patient.id == patient_id))


async def _front_desk_if_patient_acted(db: AsyncSession, principal: Principal, patient_user: uuid.UUID | None) -> list[uuid.UUID]:
    """The front desk hears about changes a patient made online, not about their own (D108)."""
    if patient_user is None or principal.user_id != patient_user:
        return []
    return await notification_service.with_role(db, RoleCode.receptionist)


async def _notify_patient_of_booking(db: AsyncSession, appt: Appointment, principal: Principal) -> None:
    """Booked on the patient's behalf (front desk, doctor): the patient hears about it."""
    patient_user = await _patient_user(db, appt.patient_id)
    if patient_user is None or patient_user == principal.user_id:
        return
    _, tz = await _doctor_user_and_tz(db, appt.doctor_id)
    await notification_service.notify_optional(
        db,
        [patient_user],
        type="appointment_booked_for_you",
        title="Appointment booked",
        message=f"An appointment was booked for you on {notification_service.when(appt.starts_at, tz)}.",
        link=f"/appointments/{appt.id}",
    )


async def _notify_cancellation(db: AsyncSession, ctx: Context) -> None:
    """The doctor and the patient (if they have a login) hear about it,
    except whoever cancelled; the front desk when the patient cancelled online."""
    appt = ctx.appointment
    doctor_user, _ = await _doctor_user_and_tz(db, appt.doctor_id)
    patient_user = await _patient_user(db, appt.patient_id)
    desk = await _front_desk_if_patient_acted(db, ctx.principal, patient_user)
    await notification_service.notify_optional(
        db,
        [u for u in (doctor_user, patient_user, *desk) if u is not None and u != ctx.principal.user_id],
        type="appointment_cancelled",
        title="Appointment cancelled",
        message=f"The appointment on {notification_service.when(appt.starts_at, ctx.timezone)} was cancelled.",
        link=f"/appointments/{appt.id}",
    )


async def _notify_status(db: AsyncSession, ctx: Context, status: S) -> None:
    """Confirmed: the patient hears about it. Checked in: the doctor."""
    appt = ctx.appointment
    if status is S.confirmed:
        recipients = [await _patient_user(db, appt.patient_id)]
        title, message = "Appointment confirmed", f"Your appointment on {notification_service.when(appt.starts_at, ctx.timezone)} is confirmed."
        type_ = "appointment_confirmed"
    elif status is S.checked_in:
        recipients = [(await _doctor_user_and_tz(db, appt.doctor_id))[0]]
        title, message = "Patient checked in", f"The patient for {notification_service.when(appt.starts_at, ctx.timezone)} has arrived."
        type_ = "patient_checked_in"
    else:
        return
    await notification_service.notify_optional(
        db, [u for u in recipients if u != ctx.principal.user_id], type=type_, title=title, message=message,
        link=f"/appointments/{appt.id}",
    )


async def _notify_reschedule(db: AsyncSession, principal: Principal, old: Appointment, new: Appointment) -> None:
    """Patient and doctor(s), except whoever moved it; the front desk if the patient did."""
    new_doctor, tz = await _doctor_user_and_tz(db, new.doctor_id)
    old_doctor = new_doctor if old.doctor_id == new.doctor_id else (await _doctor_user_and_tz(db, old.doctor_id))[0]
    patient_user = await _patient_user(db, new.patient_id)
    desk = await _front_desk_if_patient_acted(db, principal, patient_user)
    await notification_service.notify_optional(
        db,
        [u for u in (patient_user, new_doctor, old_doctor, *desk) if u is not None and u != principal.user_id],
        type="appointment_rescheduled",
        title="Appointment rescheduled",
        message=(
            f"The appointment on {notification_service.when(old.starts_at, tz)} "
            f"was moved to {notification_service.when(new.starts_at, tz)}."
        ),
        link=f"/appointments/{new.id}",
    )


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
    # The day's queue follows the appointment (D117): check-in issues a token, and only
    # one consultation per doctor can be in progress.
    from app.services import queue_service

    await queue_service.on_appointment_status(db, appt, change.status, principal)
    if change.status is S.cancelled:
        _cancel(ctx, change.cancellation_reason, change.note)
        await _notify_cancellation(db, ctx)
        await email_outbox_service.appointment_email(db, appt, "appointment_cancelled")
    else:
        appt.status = change.status
        await _notify_status(db, ctx, change.status)
        if change.status is S.confirmed and await _patient_user(db, appt.patient_id) != principal.user_id:
            await email_outbox_service.appointment_email(db, appt, "appointment_confirmed")
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
    from app.services import queue_service

    await queue_service.on_appointment_status(db, old, S.cancelled, principal)
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
        booking_mode="custom",  # a time the user chose (D120)
    )
    await _flush_or_conflict(db)
    _record_booking(db, new, principal)
    await _notify_reschedule(db, principal, old, new)
    await email_outbox_service.appointment_email(db, new, "appointment_rescheduled", old=old)
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
