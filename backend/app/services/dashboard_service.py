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
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.config import settings
from app.core.permissions import Perm, Principal
from app.models.appointment import ACTIVE_STATUSES, Appointment, AppointmentStatus, upcoming_condition
from app.models.department import Department
from app.models.doctor import Doctor
from app.models.patient import Patient
from app.models.rbac import Role, UserRole
from app.models.user import User
from app.schemas.dashboard import (
    AccountSummary,
    AdminDashboard,
    AdminKpi,
    AdminRecentUser,
    DashboardSummary,
    DoctorSummary,
    FrontDeskSummary,
    OverviewSummary,
    PatientSummary,
    TodayCounts,
)
from app.services import access

S = AppointmentStatus


def _count(condition: ColumnElement[bool] | None = None):
    counter = func.count()
    return counter.filter(condition) if condition is not None else counter


def _upcoming(now: datetime) -> ColumnElement[bool]:
    return upcoming_condition(now)


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
    # One round trip: the counts and the record's status together.
    profile_active = select(Patient.is_active).where(Patient.id == principal.patient_id).scalar_subquery()
    upcoming, total, doctors, profile_active = (
        await db.execute(
            select(
                _count(_upcoming(now)),
                _count(),
                func.count(distinct(Appointment.doctor_id)).filter(Appointment.status.in_(ACTIVE_STATUSES)),
                profile_active,
            )
            .select_from(Appointment)
            .where(access.own_appointments(principal))
        )
    ).one()
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
    """Every total the caller may see, in ONE query (each a scalar subquery):
    a round trip to the hosted database costs ~120 ms."""
    def total(model, condition=None):
        query = select(func.count()).select_from(model)
        return (query.where(condition) if condition is not None else query).scalar_subquery()

    wanted: dict[str, object] = {}
    if principal.has(Perm.user_read):
        wanted["users_total"] = total(User)
        wanted["users_active"] = total(User, User.is_active.is_(True))
    if principal.has(Perm.doctor_read):
        wanted["doctors_active"] = total(Doctor, Doctor.is_active.is_(True))
    if principal.has(Perm.department_manage):
        wanted["departments_active"] = total(Department, Department.is_active.is_(True))
    if principal.has(Perm.patient_read_any):
        wanted["patients_total"] = total(Patient)
        wanted["patients_active"] = total(Patient, Patient.is_active.is_(True))
    if principal.has(Perm.appointment_read_any):
        wanted["appointments_total"] = total(Appointment)
    # Nothing the caller may see: no section at all.
    if not wanted:
        return None
    row = (await db.execute(select(*(value.label(key) for key, value in wanted.items())))).one()
    return OverviewSummary(**row._mapping)


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


# ---- administrator dashboard (D85) -------------------------------------------------------

RECENT_USERS = 5
_KPI_TABLES = (
    ("users", User),
    # Doctor profiles exist only for approved doctors; applicants have none (D77).
    ("doctors", Doctor),
    ("patients", Patient),
    ("appointments", Appointment),
    ("departments", Department),
)


def growth(total: int, previous: int) -> tuple[float | None, str]:
    """Percent change and trend; 'new' when there was nothing to compare with."""
    if previous == 0:
        return (None, "new") if total > 0 else (0.0, "flat")
    percent = round((total - previous) / previous * 100, 1)
    return percent, "up" if percent > 0 else "down" if percent < 0 else "flat"


async def admin_dashboard(db: AsyncSession, day=None) -> AdminDashboard:
    """Clinic totals as of `day` (default today, in the clinic's timezone)
    against the end of the previous month, and the newest accounts.

    Totals are cumulative: every record created up to the end of `day`,
    whatever its current status (a deactivated department or a cancelled
    appointment still existed). Two queries: every table's counts as scalar
    subqueries of one SELECT, then the newest users with their role codes."""
    tz = ZoneInfo(settings.clinic_timezone)
    day = day or clock.utcnow().astimezone(tz).date()
    cutoff = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz)
    month_start = datetime.combine(day.replace(day=1), time.min, tzinfo=tz)

    counts = []
    for _, model in _KPI_TABLES:
        for since in (cutoff, month_start):
            counts.append(select(func.count()).select_from(model).where(model.created_at < since).scalar_subquery())
    row = (await db.execute(select(*counts))).one()
    kpis = []
    for i, (key, _) in enumerate(_KPI_TABLES):
        total, previous = row[2 * i], row[2 * i + 1]
        percent, trend = growth(total, previous)
        kpis.append(AdminKpi(key=key, total=total, previous=previous, change_percent=percent, trend=trend))

    role_codes = (
        select(func.array_agg(aggregate_order_by(Role.code, Role.code)))
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == User.id)
        .scalar_subquery()
    )
    rows = (
        await db.execute(
            select(User, role_codes)
            .where(User.created_at < cutoff)
            .order_by(User.created_at.desc(), User.id.desc())
            .limit(RECENT_USERS)
        )
    ).all()
    users = [u for u, _ in rows]
    roles = {u.id: list(codes or []) for u, codes in rows}
    return AdminDashboard(
        date=day,
        timezone=tz.key,
        compared_to=day.replace(day=1) - timedelta(days=1),
        kpis=kpis,
        recent_users=[
            AdminRecentUser(
                id=u.id, name=u.name, email=u.email, roles=roles[u.id], is_active=u.is_active, created_at=u.created_at
            )
            for u in users
        ],
    )
