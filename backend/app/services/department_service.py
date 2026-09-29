import logging
import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.models.department import Department
from app.schemas.department import DepartmentCreate

logger = logging.getLogger(__name__)


async def create_department(db: AsyncSession, data: DepartmentCreate) -> Department:
    existing = await db.scalar(select(Department.id).where(Department.name == data.name))
    if existing is not None:
        raise ConflictError("Department already exists", code="DEPARTMENT_EXISTS")

    department = Department(name=data.name, description=data.description)
    db.add(department)
    await db.commit()
    await db.refresh(department)
    logger.info("department_created", extra={"department_id": str(department.id)})
    return department


async def list_departments(db: AsyncSession) -> Sequence[Department]:
    result = await db.scalars(select(Department).order_by(Department.name))
    return result.all()


async def get_department(db: AsyncSession, department_id: uuid.UUID) -> Department:
    department = await db.get(Department, department_id)
    if department is None:
        raise NotFoundError("Department not found")
    return department
