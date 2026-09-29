import logging
import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError
from app.models.department import Department
from app.models.doctor import Doctor
from app.schemas.department import DepartmentCreate, DepartmentUpdate
from app.services.pagination import PageParams, paginate

logger = logging.getLogger(__name__)


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
    )
    db.add(department)
    await db.commit()
    await db.refresh(department)
    logger.info("department_created", extra={"department_id": str(department.id)})
    return department


async def list_departments(
    db: AsyncSession, params: PageParams, *, active_only: bool, q: str | None = None
) -> tuple[Sequence[Department], int]:
    query = select(Department).order_by(Department.name, Department.id)
    if active_only:
        query = query.where(Department.is_active.is_(True))
    if q:
        query = query.where(Department.name.ilike(f"%{q.strip()}%"))
    return await paginate(db, query, params)


async def get_department(db: AsyncSession, department_id: uuid.UUID, *, active_only: bool = False) -> Department:
    department = await db.get(Department, department_id)
    if department is None or (active_only and not department.is_active):
        raise NotFoundError("Department not found")
    return department


async def update_department(db: AsyncSession, department_id: uuid.UUID, data: DepartmentUpdate) -> Department:
    department = await get_department(db, department_id)
    changes = data.model_dump(exclude_unset=True, exclude_none=True)
    if "name" in changes:
        await _ensure_name_free(db, changes["name"], exclude_id=department.id)
    for field, value in changes.items():
        setattr(department, field, value)
    await db.commit()
    await db.refresh(department)
    logger.info("department_updated", extra={"department_id": str(department.id), "fields": sorted(changes)})
    return department


async def set_active(db: AsyncSession, department_id: uuid.UUID, active: bool) -> Department:
    department = await get_department(db, department_id)
    if not active:
        doctors = await db.scalar(
            select(func.count(Doctor.id)).where(Doctor.department_id == department.id, Doctor.is_active.is_(True))
        )
        if doctors:
            raise BusinessRuleError(
                "Move or deactivate this department's doctors first",
                code="DEPARTMENT_HAS_ACTIVE_DOCTORS",
                details={"active_doctors": doctors},
            )
    department.is_active = active
    await db.commit()
    await db.refresh(department)
    logger.info(
        "department_activated" if active else "department_deactivated",
        extra={"department_id": str(department.id)},
    )
    return department
