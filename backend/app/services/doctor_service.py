import logging
import uuid
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError
from app.models.department import Department
from app.models.doctor import Doctor
from app.core.permissions import RoleCode
from app.models.user import User
from app.services import rbac_service
from app.schemas.doctor import DoctorCreate, DoctorUpdate

logger = logging.getLogger(__name__)


class DoctorWithName(NamedTuple):
    """A Doctor row plus the display name, which lives on the related User row."""

    doctor: Doctor
    name: str


async def _ensure_department_exists(db: AsyncSession, department_id: uuid.UUID) -> None:
    if await db.get(Department, department_id) is None:
        raise NotFoundError("Department not found")


async def create_doctor(db: AsyncSession, data: DoctorCreate) -> DoctorWithName:
    user = await db.get(User, data.user_id)
    if user is None:
        raise NotFoundError("User not found")
    if not await rbac_service.user_has_role(db, user.id, RoleCode.doctor):
        raise BusinessRuleError(
            "User must have the 'doctor' role before a Doctor profile can be created",
            code="USER_NOT_DOCTOR",
        )

    await _ensure_department_exists(db, data.department_id)

    existing = await db.scalar(select(Doctor.id).where(Doctor.user_id == data.user_id))
    if existing is not None:
        raise ConflictError("Doctor profile already exists for this user", code="DOCTOR_PROFILE_EXISTS")

    doctor = Doctor(**data.model_dump())
    db.add(doctor)
    await db.commit()
    await db.refresh(doctor)
    logger.info("doctor_created", extra={"doctor_id": str(doctor.id)})
    return DoctorWithName(doctor, user.name)


async def list_doctors(db: AsyncSession) -> list[DoctorWithName]:
    result = await db.execute(
        select(Doctor, User.name).join(User, Doctor.user_id == User.id).order_by(User.name)
    )
    return [DoctorWithName(doctor, name) for doctor, name in result.all()]


async def get_doctor(db: AsyncSession, doctor_id: uuid.UUID) -> DoctorWithName:
    result = await db.execute(
        select(Doctor, User.name).join(User, Doctor.user_id == User.id).where(Doctor.id == doctor_id)
    )
    row = result.one_or_none()
    if row is None:
        raise NotFoundError("Doctor not found")
    return DoctorWithName(*row)


async def update_doctor(db: AsyncSession, doctor_id: uuid.UUID, data: DoctorUpdate) -> DoctorWithName:
    doctor = await db.get(Doctor, doctor_id)
    if doctor is None:
        raise NotFoundError("Doctor not found")

    changes = data.model_dump(exclude_unset=True)
    if "department_id" in changes:
        await _ensure_department_exists(db, changes["department_id"])

    for field, value in changes.items():
        setattr(doctor, field, value)
    await db.commit()
    await db.refresh(doctor)
    logger.info("doctor_updated", extra={"doctor_id": str(doctor.id), "fields": sorted(changes)})
    return await get_doctor(db, doctor_id)


async def delete_doctor(db: AsyncSession, doctor_id: uuid.UUID) -> None:
    # Hard delete is existing behaviour; Stage 5 replaces it with deactivation.
    doctor = await db.get(Doctor, doctor_id)
    if doctor is None:
        raise NotFoundError("Doctor not found")
    await db.delete(doctor)
    await db.commit()
    logger.info("doctor_deleted", extra={"doctor_id": str(doctor_id)})
