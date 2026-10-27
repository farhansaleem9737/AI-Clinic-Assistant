import logging
import uuid
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import Select, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.storage import Storage
from app.models.stored_file import FileCategory
from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError
from app.core.permissions import Principal, RoleCode
from app.models.department import Department
from app.models.doctor import Doctor, DoctorEducation, DoctorExperience
from app.models.user import User
from app.schemas.doctor import DoctorCareerUpdate, DoctorCreate, DoctorSelfUpdate, DoctorUpdate
from app.services import appointment_service, auth_service, availability_service, rbac_service, file_service
from app.services.availability_service import AvailabilityStatus, DoctorAvailability
from app.services.pagination import PageParams, paginate
from app.services.file_validation import CheckedFile


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DoctorRow:
    """A Doctor plus the fields that live on related rows (User, Department)."""

    doctor: Doctor
    name: str
    email: str
    department_name: str
    availability: DoctorAvailability = DoctorAvailability(AvailabilityStatus.unavailable)


class DoctorSort(StrEnum):
    name_asc = "name_asc"
    name_desc = "name_desc"
    experience_asc = "experience_asc"
    experience_desc = "experience_desc"
    fee_asc = "fee_asc"
    fee_desc = "fee_desc"


# Doctors without a listed fee sort last either way; name and id break ties so
# pages are stable.
_ORDER_BY = {
    DoctorSort.name_asc: (User.name.asc(),),
    DoctorSort.name_desc: (User.name.desc(),),
    DoctorSort.experience_asc: (Doctor.years_of_experience.asc(), User.name.asc()),
    DoctorSort.experience_desc: (Doctor.years_of_experience.desc(), User.name.asc()),
    DoctorSort.fee_asc: (Doctor.consultation_fee.asc().nulls_last(), User.name.asc()),
    DoctorSort.fee_desc: (Doctor.consultation_fee.desc().nulls_last(), User.name.asc()),
}


@dataclass(frozen=True)
class DoctorFilters:
    department_id: uuid.UUID | None = None
    specialization: str | None = None
    # Free text: matches the doctor's name, specialization or department.
    q: str | None = None
    min_experience: int | None = None
    fee_min: Decimal | None = None
    fee_max: Decimal | None = None
    is_active: bool | None = None
    sort: DoctorSort = DoctorSort.name_asc


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


async def _rows(db: AsyncSession, rows) -> list[DoctorRow]:
    """Attach each doctor's availability (one batch computation for the list)."""
    availability = await availability_service.availability_status(
        db, [row[0].id for row in rows], now=clock.utcnow()
    )
    return [
        DoctorRow(doctor, name, email, department_name, availability[doctor.id])
        for doctor, name, email, department_name in rows
    ]


async def list_doctors(
    db: AsyncSession, params: PageParams, filters: DoctorFilters, *, public: bool
) -> tuple[list[DoctorRow], int]:
    query = _base_query().order_by(*_ORDER_BY[filters.sort], Doctor.id)
    if public:
        query = _visible_publicly(query)
    elif filters.is_active is not None:
        query = query.where(Doctor.is_active.is_(filters.is_active))
    if filters.department_id:
        query = query.where(Doctor.department_id == filters.department_id)
    if filters.specialization:
        query = query.where(Doctor.specialization.ilike(f"%{filters.specialization.strip()}%"))
    if filters.q and filters.q.strip():
        pattern = f"%{filters.q.strip()}%"
        query = query.where(
            or_(User.name.ilike(pattern), Doctor.specialization.ilike(pattern), Department.name.ilike(pattern))
        )
    if filters.min_experience is not None:
        query = query.where(Doctor.years_of_experience >= filters.min_experience)
    if filters.fee_min is not None:
        query = query.where(Doctor.consultation_fee >= filters.fee_min)
    if filters.fee_max is not None:
        query = query.where(Doctor.consultation_fee <= filters.fee_max)
    rows, total = await paginate(db, query, params)
    return await _rows(db, rows), total


async def list_specializations(db: AsyncSession, *, department_id: uuid.UUID | None = None) -> list[str]:
    """Distinct specializations among publicly listed doctors (filter options),
    optionally limited to one department."""
    query = _visible_publicly(
        select(Doctor.specialization)
        .join(User, User.id == Doctor.user_id)
        .join(Department, Department.id == Doctor.department_id)
    )
    if department_id is not None:
        query = query.where(Doctor.department_id == department_id)
    return list((await db.scalars(query.distinct().order_by(Doctor.specialization))).all())


async def get_doctor(db: AsyncSession, doctor_id: uuid.UUID, *, public: bool = False) -> DoctorRow:
    query = _base_query().where(Doctor.id == doctor_id)
    if public:
        query = _visible_publicly(query)
    row = (await db.execute(query)).one_or_none()
    if row is None:
        raise NotFoundError("Doctor not found")
    return (await _rows(db, [row]))[0]


@dataclass(frozen=True)
class PublicProfile:
    row: DoctorRow
    experience: list[DoctorExperience]
    education: list[DoctorEducation]


@dataclass(frozen=True)
class Career:
    experience: list[DoctorExperience]
    education: list[DoctorEducation]


async def _career(db: AsyncSession, doctor_id: uuid.UUID) -> Career:
    """Career history, newest first (current positions and in-progress
    studies before finished ones). Two queries, whatever the length."""
    experience = await db.scalars(
        select(DoctorExperience)
        .where(DoctorExperience.doctor_id == doctor_id)
        .order_by(
            DoctorExperience.end_year.desc().nulls_first(),
            DoctorExperience.start_year.desc(),
            DoctorExperience.id,
        )
    )
    education = await db.scalars(
        select(DoctorEducation)
        .where(DoctorEducation.doctor_id == doctor_id)
        .order_by(
            DoctorEducation.end_year.desc().nulls_first(),
            DoctorEducation.start_year.desc().nulls_last(),
            DoctorEducation.id,
        )
    )
    return Career(list(experience.all()), list(education.all()))


async def get_public_profile(db: AsyncSession, doctor_id: uuid.UUID) -> PublicProfile:
    """A publicly listed doctor with their career history, newest first."""
    row = await get_doctor(db, doctor_id, public=True)
    career = await _career(db, doctor_id)
    return PublicProfile(row, career.experience, career.education)


async def ensure_publicly_listed(db: AsyncSession, doctor_id: uuid.UUID) -> None:
    """404 unless the doctor appears in the public directory."""
    query = _visible_publicly(
        select(Doctor.id)
        .join(User, User.id == Doctor.user_id)
        .join(Department, Department.id == Doctor.department_id)
        .where(Doctor.id == doctor_id)
    )
    if await db.scalar(query) is None:
        raise NotFoundError("Doctor not found")


async def get_own_profile(db: AsyncSession, principal: Principal) -> DoctorRow:
    if principal.doctor_id is None:
        raise NotFoundError("You do not have a doctor profile", code="NO_DOCTOR_PROFILE")
    return await get_doctor(db, principal.doctor_id)


async def ensure_active_department(db: AsyncSession, department_id: uuid.UUID) -> Department:
    department = await db.get(Department, department_id)
    if department is None:
        raise NotFoundError("Department not found")
    if not department.is_active:
        raise BusinessRuleError("Department is inactive", code="DEPARTMENT_INACTIVE")
    return department


async def ensure_license_free(db: AsyncSession, license_number: str | None, exclude_id: uuid.UUID | None = None):
    if not license_number:
        return
    query = select(Doctor.id).where(Doctor.license_number == license_number)
    if exclude_id is not None:
        query = query.where(Doctor.id != exclude_id)
    if await db.scalar(query) is not None:
        raise ConflictError("License number already registered", code="LICENSE_TAKEN")


async def create_doctor(db: AsyncSession, principal: Principal, data: DoctorCreate) -> DoctorRow:
    await ensure_active_department(db, data.department_id)
    await ensure_license_free(db, data.license_number)

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
        await ensure_active_department(db, changes["department_id"])
    if "license_number" in changes:
        await ensure_license_free(db, changes["license_number"], exclude_id=doctor.id)
    for required in ("department_id", "specialization", "years_of_experience"):
        if required in changes and changes[required] is None:
            del changes[required]
    return await _apply(db, doctor, changes)


async def update_own_profile(db: AsyncSession, principal: Principal, data: DoctorSelfUpdate) -> DoctorRow:
    if principal.doctor_id is None:
        raise NotFoundError("You do not have a doctor profile", code="NO_DOCTOR_PROFILE")
    doctor = await db.get(Doctor, principal.doctor_id)
    changes = data.model_dump(exclude_unset=True)
    if changes.get("years_of_experience", 0) is None:
        del changes["years_of_experience"]  # required column: "no value" means "leave it"
    return await _apply(db, doctor, changes)


async def set_active(db: AsyncSession, doctor_id: uuid.UUID, active: bool) -> DoctorRow:
    doctor = await db.get(Doctor, doctor_id)
    if doctor is None:
        raise NotFoundError("Doctor not found")
    if active:
        await ensure_active_department(db, doctor.department_id)
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


# ---- Profile photo ---------------------------------------------------------
def own_doctor_id(principal: Principal) -> uuid.UUID:
    if principal.doctor_id is None:
        raise NotFoundError("You do not have a doctor profile", code="NO_DOCTOR_PROFILE")
    return principal.doctor_id


async def _doctor(db: AsyncSession, doctor_id: uuid.UUID) -> Doctor:
    doctor= await db.get(Doctor, doctor_id)
    if doctor is None:
        raise NotFoundError("Doctor not found")
    return doctor

async def set_photo(
        db: AsyncSession, storage: Storage, principal: Principal, doctor_id:uuid.UUID, checked:CheckedFile
) -> DoctorRow:
    doctor= await _doctor(db, doctor_id)
    await file_service.replace_photo(
        db, storage, doctor, category=FileCategory.doctor_photo, checked=checked, uploaded_by=principal.user_id
    )
    logger.info("doctor_photo_updated", extra={"doctor_id": str(doctor.id), "by" : str(principal.user_id)})
    return await get_doctor(db, doctor.id)

async def remove_photo(db: AsyncSession, storage: Storage, principal: Principal,doctor_id: uuid.UUID) -> DoctorRow:
    doctor=await _doctor(db, doctor_id)
    await file_service.remove_photo(db, storage, doctor)
    logger.info("doctor_photo_removed", extra={"doctor_id": str(doctor.id), "by": str(principal.user_id)})
    return await get_doctor(db, doctor.id)


# ---- Career history ----------------------------------------------------------------


async def get_career(db: AsyncSession, doctor_id: uuid.UUID) -> Career:
    await _doctor(db, doctor_id)
    return await _career(db, doctor_id)


async def replace_career(
    db: AsyncSession, principal: Principal, doctor_id: uuid.UUID, data: DoctorCareerUpdate
) -> Career:
    """Replace the doctor's experience and education with `data`, in one
    transaction. Who may do this is decided by the endpoint: the doctor for
    their own profile (doctor:update_own), or staff with doctor:update."""
    doctor = await _doctor(db, doctor_id)
    await db.execute(delete(DoctorExperience).where(DoctorExperience.doctor_id == doctor.id))
    await db.execute(delete(DoctorEducation).where(DoctorEducation.doctor_id == doctor.id))
    db.add_all(DoctorExperience(doctor_id=doctor.id, **item.model_dump()) for item in data.experience)
    db.add_all(DoctorEducation(doctor_id=doctor.id, **item.model_dump()) for item in data.education)
    await db.commit()
    logger.info(
        "doctor_career_updated",
        extra={
            "doctor_id": str(doctor.id),
            "by": str(principal.user_id),
            "experience": len(data.experience),
            "education": len(data.education),
        },
    )
    return await _career(db, doctor.id)
