import logging
import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError
from app.models.appointment import Appointment, AppointmentStatus
from app.models.department import Department
from app.models.doctor import Doctor
from app.models.stored_file import StoredFile
from app.models.user import User
from app.schemas.department import DepartmentCreate, DepartmentUpdate
from app.services.pagination import PageParams, paginate

logger = logging.getLogger(__name__)

PREVIEW_DOCTORS = 3
# Appointments still ahead of the patient: kept as they are when a
# department is deactivated, and counted in the warning.
UPCOMING = (AppointmentStatus.requested, AppointmentStatus.scheduled, AppointmentStatus.confirmed, AppointmentStatus.checked_in)


class DepartmentSort(StrEnum):
    name = "name"
    name_desc = "-name"
    timezone = "timezone"
    timezone_desc = "-timezone"
    doctors = "doctors"
    doctors_desc = "-doctors"
    status = "status"
    status_desc = "-status"


@dataclass(frozen=True)
class DoctorRow:
    id: uuid.UUID
    name: str
    title: str | None
    photo_key: str | None
    specialization: str = ""
    is_active: bool = True


@dataclass(frozen=True)
class DepartmentWithDoctors:
    department: Department
    doctor_count: int
    preview: list[DoctorRow]
    doctors: list[DoctorRow] = field(default_factory=list)
    upcoming_appointments: int = 0


def _practising():
    """A doctor who counts: active profile and active login. Doctor profiles
    only exist once an application is approved (D77)."""
    return and_(Doctor.is_active.is_(True), User.is_active.is_(True))


def _doctor_counts():
    return (
        select(Doctor.department_id.label("department_id"), func.count(Doctor.id).label("n"))
        .join(User, User.id == Doctor.user_id)
        .where(_practising())
        .group_by(Doctor.department_id)
        .subquery()
    )


async def _ensure_name_free(db: AsyncSession, name: str, exclude_id: uuid.UUID | None = None) -> None:
    # Case-insensitive: "Cardiology" and "cardiology" are the same department.
    query = select(Department.id).where(func.lower(Department.name) == name.lower())
    if exclude_id is not None:
        query = query.where(Department.id != exclude_id)
    if await db.scalar(query) is not None:
        raise ConflictError("Department already exists", code="DEPARTMENT_EXISTS")


async def create_department(db: AsyncSession, data: DepartmentCreate) -> Department:
    await _ensure_name_free(db, data.name)
    department = Department(
        name=data.name,
        description=data.description,
        timezone=data.timezone or settings.clinic_timezone,
        icon=data.icon,
        color=data.color,
        is_active=data.is_active,
    )
    db.add(department)
    await db.commit()
    await db.refresh(department)
    logger.info("department_created", extra={"department_id": str(department.id)})
    return department


async def list_departments(
    db: AsyncSession, params: PageParams, *, active_only: bool, q: str | None = None
) -> tuple[Sequence[Department], int]:
    """The plain list (public directory, pickers)."""
    query = select(Department).order_by(Department.name, Department.id)
    if active_only:
        query = query.where(Department.is_active.is_(True))
    if q:
        query = query.where(Department.name.ilike(f"%{q.strip()}%"))
    return await paginate(db, query, params)


async def _previews(db: AsyncSession, department_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[DoctorRow]]:
    """Up to PREVIEW_DOCTORS practising doctors per department, by name: one query."""
    if not department_ids:
        return {}
    ranked = (
        select(
            Doctor.department_id,
            Doctor.id,
            User.name,
            Doctor.title,
            StoredFile.object_key,
            func.row_number().over(partition_by=Doctor.department_id, order_by=(func.lower(User.name), Doctor.id)).label("rn"),
        )
        .join(User, User.id == Doctor.user_id)
        .outerjoin(StoredFile, StoredFile.id == Doctor.photo_file_id)
        .where(Doctor.department_id.in_(department_ids), _practising())
        .subquery()
    )
    rows = await db.execute(select(ranked).where(ranked.c.rn <= PREVIEW_DOCTORS).order_by(ranked.c.department_id, ranked.c.rn))
    grouped: dict[uuid.UUID, list[DoctorRow]] = defaultdict(list)
    for department_id, doctor_id, name, title, photo_key, _ in rows:
        grouped[department_id].append(DoctorRow(doctor_id, name, title, photo_key))
    return grouped


async def manage_list(
    db: AsyncSession,
    params: PageParams,
    *,
    q: str | None = None,
    is_active: bool | None = None,
    sort: DepartmentSort = DepartmentSort.name,
) -> tuple[list[DepartmentWithDoctors], int]:
    """Admin > Departments (D89): search name and description, filter by
    status, sort on the server (stable by id), with each department's
    practising-doctor count and avatar preview. Two queries per page."""
    counts = _doctor_counts()
    n = func.coalesce(counts.c.n, 0)
    name = func.lower(Department.name)
    order = {
        DepartmentSort.name: [name.asc()],
        DepartmentSort.name_desc: [name.desc()],
        DepartmentSort.timezone: [Department.timezone.asc(), name.asc()],
        DepartmentSort.timezone_desc: [Department.timezone.desc(), name.asc()],
        DepartmentSort.doctors: [n.asc(), name.asc()],
        DepartmentSort.doctors_desc: [n.desc(), name.asc()],
        DepartmentSort.status: [Department.is_active.desc(), name.asc()],  # Active first
        DepartmentSort.status_desc: [Department.is_active.asc(), name.asc()],
    }[sort]
    query = (
        select(Department, n)
        .outerjoin(counts, counts.c.department_id == Department.id)
        .order_by(*order, Department.id)
    )
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        query = query.where(or_(Department.name.ilike(pattern), Department.description.ilike(pattern)))
    if is_active is not None:
        query = query.where(Department.is_active.is_(is_active))
    rows, total = await paginate(db, query, params)
    previews = await _previews(db, [d.id for d, _ in rows])
    return [DepartmentWithDoctors(d, count, previews.get(d.id, [])) for d, count in rows], total


@dataclass(frozen=True)
class DepartmentSummary:
    total: int
    active: int
    inactive: int
    # Practising doctors (same rule as each department's doctor_count), clinic-wide.
    doctors: int


async def summary(db: AsyncSession) -> DepartmentSummary:
    """Clinic-wide totals for Admin > Departments (D93): not affected by the
    page's search or status filter. Two aggregate queries."""
    total, active = (
        await db.execute(select(func.count(Department.id), func.count(Department.id).filter(Department.is_active.is_(True))))
    ).one()
    doctors = await db.scalar(select(func.count(Doctor.id)).join(User, User.id == Doctor.user_id).where(_practising()))
    return DepartmentSummary(total=total, active=active, inactive=total - active, doctors=doctors)


async def get_department(db: AsyncSession, department_id: uuid.UUID, *, active_only: bool = False) -> Department:
    department = await db.get(Department, department_id)
    if department is None or (active_only and not department.is_active):
        raise NotFoundError("Department not found")
    return department


async def get_detail(db: AsyncSession, department_id: uuid.UUID) -> DepartmentWithDoctors:
    department = await get_department(db, department_id)
    rows = await db.execute(
        select(Doctor.id, User.name, Doctor.title, StoredFile.object_key, Doctor.specialization, Doctor.is_active, User.is_active)
        .join(User, User.id == Doctor.user_id)
        .outerjoin(StoredFile, StoredFile.id == Doctor.photo_file_id)
        .where(Doctor.department_id == department.id)
        .order_by(func.lower(User.name), Doctor.id)
    )
    doctors = [DoctorRow(i, nm, t, k, spec, active and login) for i, nm, t, k, spec, active, login in rows]
    practising = [d for d in doctors if d.is_active]
    upcoming = await db.scalar(
        select(func.count(Appointment.id))
        .join(Doctor, Doctor.id == Appointment.doctor_id)
        .where(Doctor.department_id == department.id, Appointment.status.in_(UPCOMING), Appointment.starts_at >= clock.utcnow())
    )
    return DepartmentWithDoctors(department, len(practising), practising[:PREVIEW_DOCTORS], doctors, upcoming)


async def update_department(db: AsyncSession, department_id: uuid.UUID, data: DepartmentUpdate) -> Department:
    department = await get_department(db, department_id)
    changes = data.model_dump(exclude_unset=True)
    # Name and timezone cannot be emptied; description, icon and colour can.
    for required in ("name", "timezone"):
        if changes.get(required, "") is None:
            changes.pop(required)
    if "name" in changes:
        await _ensure_name_free(db, changes["name"], exclude_id=department.id)
    for name, value in changes.items():
        setattr(department, name, value)
    await db.commit()
    await db.refresh(department)
    logger.info("department_updated", extra={"department_id": str(department.id), "fields": sorted(changes)})
    return department


async def set_active(db: AsyncSession, department_id: uuid.UUID, active: bool) -> Department:
    """Deactivation keeps everything (D89): doctors stay assigned, existing
    appointments stay as they are and can still be attended. What stops is
    new business: the public directory hides the department and its doctors,
    no slots are offered, booking and rescheduling refuse
    (availability_service.bookable_doctor), and no doctor can be moved into it."""
    department = await get_department(db, department_id)
    department.is_active = active
    await db.commit()
    await db.refresh(department)
    logger.info(
        "department_activated" if active else "department_deactivated",
        extra={"department_id": str(department.id)},
    )
    return department
