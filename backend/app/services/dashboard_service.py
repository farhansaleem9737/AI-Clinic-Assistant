"""Role-aware dashboard figures.

Which sections a caller receives is decided by their *permissions*, not by
role names, and every appointment count is scoped with the same conditions
(``services/access.py``) that guard the appointment list — so the dashboard
can never count a record the caller could not open.

Each section is one aggregate query (``COUNT(*) FILTER (WHERE ...)``); no rows
are loaded and nothing is filtered in Python.
"""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.config import settings
from app.core.permissions import Perm, Principal
from app.models.appointment import ACTIVE_STATUSES, Appointment, AppointmentStatus
from app.models.department import Department
from app.models.doctor import Doctor
from app.models.patient import Patient
from app.models.user import User
from app.schemas.dashboard import (
    AccountSummary,
    DashboardSummary,
    DoctorSummary,
    FrontDeskSummary,
    OverviewSummary,
    PatientSummary,
    TodayCounts,
)
from app.services import access

S = AppointmentStatus

# Booked and not finished: what "upcoming" means on every dashboard.
_OPEN = (S.requested, S.scheduled, S.confirmed, S.checked_in, S.in_progress)


def _count(condition: ColumnElement[bool] | None = None):
    counter = func.count()
    return counter.filter(condition) if condition is not None else counter


def _upcoming(now: datetime) -> ColumnElement[bool]:
    return Appointment.status.in_(_OPEN) & (Appointment.ends_at > now)


async def _today_counts(db: AsyncSession, scope: ColumnElement[bool], now: datetime, tz: ZoneInfo) -> TodayCounts:
    today = now.astimezone(tz).date()
    start = datetime.combine(today, time.min, tzinfo=tz)
    end = start + timedelta(days=1)
    row = (
        await db.execute(
            select(
                _count(),
                _count(Appointment.status.in_((S.requested, S.scheduled, S.confirmed))),
                _count(Appointment.status == S.checked_in),
                _count(Appointment.status == S.in_progress),
                _count(Appointment.status == S.completed),
                _count(Appointment.status == S.cancelled),
                _count(Appointment.status == S.no_show),
            )
            .select_from(Appointment)
            .where(scope, Appointment.starts_at >= start, Appointment.starts_at < end)
        )
    ).one()
    return TodayCounts(
        date=today,
        timezone=tz.key,
        total=row[0],
        awaiting_check_in=row[1],
        checked_in=row[2],
        in_progress=row[3],
        completed=row[4],
        cancelled=row[5],
        no_show=row[6],
    )


async def _patient_section(db: AsyncSession, principal: Principal, now: datetime) -> PatientSummary:
    if principal.patient_id is None:
        return PatientSummary(
            has_profile=False, profile_active=False, upcoming_appointments=0, total_appointments=0, my_doctors=0
        )
    upcoming, total, doctors = (
        await db.execute(
            select(
                _count(_upcoming(now)),
                _count(),
                func.count(distinct(Appointment.doctor_id)).filter(Appointment.status.in_(ACTIVE_STATUSES)),
            )
            .select_from(Appointment)
            .where(access.own_appointments(principal))
        )
    ).one()
    profile_active = await db.scalar(select(Patient.is_active).where(Patient.id == principal.patient_id))
    return PatientSummary(
        has_profile=True,
        profile_active=bool(profile_active),
        upcoming_appointments=upcoming,
        total_appointments=total,
        my_doctors=doctors,
    )


async def _doctor_section(db: AsyncSession, principal: Principal, now: datetime) -> DoctorSummary:
    if principal.doctor_id is None:
        return DoctorSummary(has_profile=False, today=None, upcoming_appointments=0, my_patients=0)
    scope = access.assigned_appointments(principal)
    # "Today" is the doctor's working day: their department's local date.
    tz_name = await db.scalar(
        select(Department.timezone)
        .join(Doctor, Doctor.department_id == Department.id)
        .where(Doctor.id == principal.doctor_id)
    )
    upcoming, patients = (
        await db.execute(
            select(
                _count(_upcoming(now)),
                func.count(distinct(Appointment.patient_id)).filter(Appointment.status.in_(ACTIVE_STATUSES)),
            )
            .select_from(Appointment)
            .where(scope)
        )
    ).one()
    return DoctorSummary(
        has_profile=True,
        today=await _today_counts(db, scope, now, ZoneInfo(tz_name)),
        upcoming_appointments=upcoming,
        my_patients=patients,
    )


async def _front_desk_section(db: AsyncSession, principal: Principal, now: datetime) -> FrontDeskSummary:
    scope = access.appointment_visibility(principal)  # true() for read_any
    upcoming = await db.scalar(select(_count(_upcoming(now))).select_from(Appointment).where(scope))
    return FrontDeskSummary(
        today=await _today_counts(db, scope, now, ZoneInfo(settings.clinic_timezone)),
        upcoming_appointments=upcoming or 0,
    )


async def _overview_section(db: AsyncSession, principal: Principal) -> OverviewSummary | None:
    overview = OverviewSummary()
    if principal.has(Perm.user_read):
        overview.users_total, overview.users_active = (
            await db.execute(select(_count(), _count(User.is_active.is_(True))).select_from(User))
        ).one()
    if principal.has(Perm.doctor_read):
        overview.doctors_active = await db.scalar(
            select(func.count()).select_from(Doctor).where(Doctor.is_active.is_(True))
        )
    if principal.has(Perm.department_manage):
        overview.departments_active = await db.scalar(
            select(func.count()).select_from(Department).where(Department.is_active.is_(True))
        )
    if principal.has(Perm.patient_read_any):
        overview.patients_total, overview.patients_active = (
            await db.execute(select(_count(), _count(Patient.is_active.is_(True))).select_from(Patient))
        ).one()
    if principal.has(Perm.appointment_read_any):
        overview.appointments_total = await db.scalar(select(func.count()).select_from(Appointment))
    # Nothing the caller may see: no section at all.
    return overview if overview.model_dump(exclude_none=True) else None


async def get_summary(db: AsyncSession, principal: Principal) -> DashboardSummary:
    now = clock.utcnow()
    summary = DashboardSummary(
        account=AccountSummary(is_active=principal.user.is_active, roles=sorted(principal.roles))
    )
    if principal.has(Perm.appointment_read_own):
        summary.patient = await _patient_section(db, principal, now)
    if principal.has(Perm.appointment_read_assigned):
        summary.doctor = await _doctor_section(db, principal, now)
    if principal.has(Perm.appointment_read_any):
        summary.front_desk = await _front_desk_section(db, principal, now)
    summary.overview = await _overview_section(db, principal)
    return summary
