import logging
import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError
from app.core.permissions import Principal, RoleCode
from app.models.department import Department
from app.models.doctor import Doctor
from app.models.user import User
from app.schemas.doctor import DoctorCreate, DoctorSelfUpdate, DoctorUpdate
from app.services import appointment_service, auth_service, rbac_service
from app.services.pagination import PageParams, paginate

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DoctorRow:
    """A Doctor plus the fields that live on related rows (User, Department)."""

    doctor: Doctor
    name: str
    email: str
    department_name: str


@dataclass(frozen=True)
class DoctorFilters:
    department_id: uuid.UUID | None = None
    specialization: str | None = None
    q: str | None = None
    min_experience: int | None = None
    fee_min: Decimal | None = None
    fee_max: Decimal | None = None
    is_active: bool | None = None


def _base_query() -> Select:
    return (
        select(Doctor, User.name, User.email, Department.name)
        .join(User, User.id == Doctor.user_id)
        .join(Department, Department.id == Doctor.department_id)
    )


def _visible_publicly(query: Select) -> Select:
    # The public directory shows only doctors who can actually be seen:
    # active profile, active login, active department.
    return query.where(Doctor.is_active.is_(True), User.is_active.is_(True), Department.is_active.is_(True))


def _row(row) -> DoctorRow:
    doctor, name, email, department_name = row
    return DoctorRow(doctor, name, email, department_name)


async def list_doctors(
    db: AsyncSession, params: PageParams, filters: DoctorFilters, *, public: bool
) -> tuple[list[DoctorRow], int]:
    query = _base_query().order_by(User.name, Doctor.id)
    if public:
        query = _visible_publicly(query)
    elif filters.is_active is not None:
        query = query.where(Doctor.is_active.is_(filters.is_active))
    if filters.department_id:
        query = query.where(Doctor.department_id == filters.department_id)
    if filters.specialization:
        query = query.where(Doctor.specialization.ilike(f"%{filters.specialization.strip()}%"))
    if filters.q:
        query = query.where(User.name.ilike(f"%{filters.q.strip()}%"))
    if filters.min_experience is not None:
        query = query.where(Doctor.years_of_experience >= filters.min_experience)
    if filters.fee_min is not None:
        query = query.where(Doctor.consultation_fee >= filters.fee_min)
    if filters.fee_max is not None:
        query = query.where(Doctor.consultation_fee <= filters.fee_max)
    rows, total = await paginate(db, query, params)
    return [_row(r) for r in rows], total


async def get_doctor(db: AsyncSession, doctor_id: uuid.UUID, *, public: bool = False) -> DoctorRow:
    query = _base_query().where(Doctor.id == doctor_id)
    if public:
        query = _visible_publicly(query)
    row = (await db.execute(query)).one_or_none()
    if row is None:
        raise NotFoundError("Doctor not found")
    return _row(row)


async def get_own_profile(db: AsyncSession, principal: Principal) -> DoctorRow:
    if principal.doctor_id is None:
        raise NotFoundError("You do not have a doctor profile", code="NO_DOCTOR_PROFILE")
    return await get_doctor(db, principal.doctor_id)


async def _active_department(db: AsyncSession, department_id: uuid.UUID) -> Department:
    department = await db.get(Department, department_id)
    if department is None:
        raise NotFoundError("Department not found")
    if not department.is_active:
        raise BusinessRuleError("Department is inactive", code="DEPARTMENT_INACTIVE")
    return department


async def _ensure_license_free(db: AsyncSession, license_number: str | None, exclude_id: uuid.UUID | None = None):
    if not license_number:
        return
    query = select(Doctor.id).where(Doctor.license_number == license_number)
    if exclude_id is not None:
        query = query.where(Doctor.id != exclude_id)
    if await db.scalar(query) is not None:
        raise ConflictError("License number already registered", code="LICENSE_TAKEN")


async def create_doctor(db: AsyncSession, principal: Principal, data: DoctorCreate) -> DoctorRow:
    await _active_department(db, data.department_id)
    await _ensure_license_free(db, data.license_number)

    if data.account is not None:
        user = await auth_service.create_user(
            db, name=data.account.name, email=data.account.email, password=data.account.password
        )
        await rbac_service.grant_roles(db, user.id, [RoleCode.doctor], granted_by=principal.user_id)
    else:
        user = await db.get(User, data.user_id)
        if user is None:
            raise NotFoundError("User not found")
        if not user.is_active:
            raise BusinessRuleError("User account is inactive", code="USER_INACTIVE")
        if not await rbac_service.user_has_role(db, user.id, RoleCode.doctor):
            raise BusinessRuleError(
                "User must have the 'doctor' role before a Doctor profile can be created",
                code="USER_NOT_DOCTOR",
            )
        if await db.scalar(select(Doctor.id).where(Doctor.user_id == user.id)) is not None:
            raise ConflictError("Doctor profile already exists for this user", code="DOCTOR_PROFILE_EXISTS")

    doctor = Doctor(user_id=user.id, **data.model_dump(exclude={"user_id", "account"}))
    db.add(doctor)
    await db.commit()
    logger.info("doctor_created", extra={"doctor_id": str(doctor.id), "by": str(principal.user_id)})
    return await get_doctor(db, doctor.id)


async def _apply(db: AsyncSession, doctor: Doctor, changes: dict) -> DoctorRow:
    for field, value in changes.items():
        setattr(doctor, field, value)
    await db.commit()
    await db.refresh(doctor)
    logger.info("doctor_updated", extra={"doctor_id": str(doctor.id), "fields": sorted(changes)})
    return await get_doctor(db, doctor.id)


async def update_doctor(db: AsyncSession, doctor_id: uuid.UUID, data: DoctorUpdate) -> DoctorRow:
    doctor = await db.get(Doctor, doctor_id)
    if doctor is None:
        raise NotFoundError("Doctor not found")
    changes = data.model_dump(exclude_unset=True)
    if changes.get("department_id") is not None:
        await _active_department(db, changes["department_id"])
    if "license_number" in changes:
        await _ensure_license_free(db, changes["license_number"], exclude_id=doctor.id)
    for required in ("department_id", "specialization", "years_of_experience"):
        if required in changes and changes[required] is None:
            del changes[required]
    return await _apply(db, doctor, changes)


async def update_own_profile(db: AsyncSession, principal: Principal, data: DoctorSelfUpdate) -> DoctorRow:
    if principal.doctor_id is None:
        raise NotFoundError("You do not have a doctor profile", code="NO_DOCTOR_PROFILE")
    doctor = await db.get(Doctor, principal.doctor_id)
    return await _apply(db, doctor, data.model_dump(exclude_unset=True))


async def set_active(db: AsyncSession, doctor_id: uuid.UUID, active: bool) -> DoctorRow:
    doctor = await db.get(Doctor, doctor_id)
    if doctor is None:
        raise NotFoundError("Doctor not found")
    if active:
        await _active_department(db, doctor.department_id)
    elif upcoming := await appointment_service.count_upcoming(db, doctor_id=doctor.id):
        raise ConflictError(
            "This doctor has upcoming appointments; reschedule or cancel them first",
            code="HAS_UPCOMING_APPOINTMENTS",
            details={"appointments": upcoming},
        )
    doctor.is_active = active
    await db.commit()
    logger.info("doctor_activated" if active else "doctor_deactivated", extra={"doctor_id": str(doctor.id)})
    return await get_doctor(db, doctor.id)
