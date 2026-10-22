import logging
import uuid
from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError
from app.core.permissions import Principal, RoleCode
from app.core.storage import Storage
from app.models.stored_file import FileCategory
from app.services.file_validation import CheckedFile
from app.models.patient import Patient
from app.models.user import User
from app.schemas.patient import (
    PatientContactUpdate,
    PatientCreate,
    PatientRegistration,
    PatientUpdate,
)
from app.services import access, appointment_service, auth_service, rbac_service, file_service
from app.services.pagination import PageParams, paginate

logger = logging.getLogger(__name__)


async def _commit_and_reload(db: AsyncSession, patient: Patient) -> Patient:
    await db.commit()
    await db.refresh(patient)
    return patient


async def register_self(db: AsyncSession, data: PatientRegistration) -> User:
    """Self-registration: login, patient role and patient profile in one transaction."""
    user = await auth_service.create_user(
        db, name=f"{data.first_name} {data.last_name}", email=data.email, password=data.password
    )
    await rbac_service.grant_roles(db, user.id, [RoleCode.patient])
    db.add(
        Patient(
            user_id=user.id,
            first_name=data.first_name,
            last_name=data.last_name,
            date_of_birth=data.date_of_birth,
            sex_at_birth=data.sex_at_birth,
            phone=data.phone,
            email=data.email,
        )
    )
    await db.commit()
    logger.info("patient_self_registered", extra={"user_id": str(user.id)})
    return user


async def create_patient(db: AsyncSession, principal: Principal, data: PatientCreate) -> Patient:
    """Staff registration of a (possibly walk-in, account-less) patient."""
    patient = Patient(**data.model_dump(), registered_by_user_id=principal.user_id)
    db.add(patient)
    await _commit_and_reload(db, patient)
    logger.info("patient_registered", extra={"patient_id": str(patient.id), "by": str(principal.user_id)})
    return patient


async def create_own_profile(db: AsyncSession, principal: Principal, data: PatientCreate) -> Patient:
    """For a patient login that has no profile yet (e.g. accounts created
    before profiles existed)."""
    if principal.patient_id is not None:
        raise ConflictError("You already have a patient profile", code="PATIENT_PROFILE_EXISTS")
    values = data.model_dump()
    values["email"] = values.get("email") or principal.user.email
    patient = Patient(**values, user_id=principal.user_id, registered_by_user_id=principal.user_id)
    db.add(patient)
    await _commit_and_reload(db, patient)
    logger.info("patient_profile_completed", extra={"patient_id": str(patient.id)})
    return patient


async def get_own(db: AsyncSession, principal: Principal) -> Patient:
    if principal.patient_id is None:
        raise NotFoundError("You do not have a patient profile yet", code="NO_PATIENT_PROFILE")
    return await db.get(Patient, principal.patient_id)


async def get_patient(db: AsyncSession, principal: Principal, patient_id: uuid.UUID) -> Patient:
    return await access.get_readable_patient(db, principal, patient_id)


async def list_patients(
    db: AsyncSession,
    principal: Principal,
    params: PageParams,
    *,
    q: str | None = None,
    date_of_birth: date | None = None,
    is_active: bool | None = None,
) -> tuple[list[Patient], int]:
    query = (
        select(Patient)
        .where(access.patient_visibility(principal))
        .order_by(Patient.last_name, Patient.first_name, Patient.id)
    )
    if q:
        term = q.strip()
        pattern = f"%{term}%"
        query = query.where(
            or_(
                func.concat(Patient.first_name, " ", Patient.last_name).ilike(pattern),
                Patient.mrn.ilike(pattern),
                Patient.phone.ilike(pattern),
                Patient.email.ilike(pattern),
            )
        )
    if date_of_birth is not None:
        query = query.where(Patient.date_of_birth == date_of_birth)
    if is_active is not None:
        query = query.where(Patient.is_active.is_(is_active))
    return await paginate(db, query, params)


async def _get_for_update(db: AsyncSession, patient_id: uuid.UUID) -> Patient:
    patient = await db.get(Patient, patient_id)
    if patient is None:
        raise NotFoundError("Patient not found")
    return patient


async def update_patient(db: AsyncSession, principal: Principal, patient_id: uuid.UUID, data: PatientUpdate) -> Patient:
    patient = await _get_for_update(db, patient_id)
    changes = data.model_dump(exclude_unset=True)
    for required in ("first_name", "last_name", "date_of_birth", "sex_at_birth"):
        if required in changes and changes[required] is None:
            del changes[required]
    for field, value in changes.items():
        setattr(patient, field, value)
    await _commit_and_reload(db, patient)
    logger.info(
        "patient_updated",
        extra={"patient_id": str(patient.id), "by": str(principal.user_id), "fields": sorted(changes)},
    )
    return patient


async def update_own_contact(db: AsyncSession, principal: Principal, data: PatientContactUpdate) -> Patient:
    patient = await get_own(db, principal)
    changes = data.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(patient, field, value)
    await _commit_and_reload(db, patient)
    logger.info("patient_contact_updated", extra={"patient_id": str(patient.id), "fields": sorted(changes)})
    return patient


async def set_active(db: AsyncSession, principal: Principal, patient_id: uuid.UUID, active: bool) -> Patient:
    patient = await _get_for_update(db, patient_id)
    if not active and (upcoming := await appointment_service.count_upcoming(db, patient_id=patient.id)):
        raise ConflictError(
            "This patient has upcoming appointments; cancel them first",
            code="HAS_UPCOMING_APPOINTMENTS",
            details={"appointments": upcoming},
        )
    patient.is_active = active
    await _commit_and_reload(db, patient)
    logger.info(
        "patient_activated" if active else "patient_deactivated",
        extra={"patient_id": str(patient.id), "by": str(principal.user_id)},
    )
    return patient


async def _ensure_unlinked(db: AsyncSession, patient: Patient) -> None:
    if patient.user_id is not None:
        raise ConflictError("Patient already has a login", code="PATIENT_ALREADY_LINKED")


async def link_account(db: AsyncSession, principal: Principal, patient_id: uuid.UUID, user_id: uuid.UUID) -> Patient:
    patient = await _get_for_update(db, patient_id)
    await _ensure_unlinked(db, patient)
    user = await db.get(User, user_id)
    if user is None:
        raise NotFoundError("User not found")
    if not user.is_active:
        raise BusinessRuleError("User account is inactive", code="USER_INACTIVE")
    if not await rbac_service.user_has_role(db, user.id, RoleCode.patient):
        raise BusinessRuleError("Only accounts with the patient role can be linked", code="USER_NOT_PATIENT")
    if await db.scalar(select(Patient.id).where(Patient.user_id == user.id)) is not None:
        raise ConflictError("This login already belongs to another patient", code="ACCOUNT_ALREADY_LINKED")
    patient.user_id = user.id
    await _commit_and_reload(db, patient)
    logger.info("patient_account_linked", extra={"patient_id": str(patient.id), "by": str(principal.user_id)})
    return patient


async def create_account(
    db: AsyncSession, principal: Principal, patient_id: uuid.UUID, *, email: str, password: str
) -> Patient:
    """Give an existing (walk-in) patient a portal login."""
    patient = await _get_for_update(db, patient_id)
    await _ensure_unlinked(db, patient)
    user = await auth_service.create_user(db, name=patient.full_name, email=email, password=password)
    await rbac_service.grant_roles(db, user.id, [RoleCode.patient], granted_by=principal.user_id)
    patient.user_id = user.id
    await _commit_and_reload(db, patient)
    logger.info("patient_account_created", extra={"patient_id": str(patient.id), "by": str(principal.user_id)})
    return patient

# ---- Profile photo ---------------------------------------------------------

async def _set_photo(db:AsyncSession, storage:Storage, principal: Principal, patient: Patient, checked:CheckedFile) -> Patient:
    await file_service.replace_photo(
        db, storage, patient, category=FileCategory.patient_photo, checked=checked, uploaded_by=principal.user_id
    )
    logger.info("patient_photo_updated", extra={"patient_id": str(patient.id),"by": str(principal.user_id)})
    return patient

async def _remove_photo(db: AsyncSession, storage: Storage, principal:Principal, patient: Patient) ->Patient:
    await file_service.remove_photo(db, storage, patient)
    logger.info("patient_photo_removed", extra={"patient_id": str(patient.id), "by":str(principal.user_id)})
    return patient

async def set_patient_photo(
        db: AsyncSession, storage: Storage, principal: Principal, patient_id: uuid.UUID, checked: CheckedFile
) -> Patient:
    return await _set_photo(db, storage, principal, await _get_for_update(db, patient_id), checked)

async def remove_patient_photo(db:AsyncSession, storage: Storage, principal:Principal, patient_id: uuid.UUID) -> Patient:
    return await _remove_photo(db, storage, principal, await _get_for_update(db, patient_id))

async def set_own_photo(db: AsyncSession, storage: Storage, principal: Principal, checked: CheckedFile) -> Patient:
    return await _set_photo(db, storage, principal, await get_own(db, principal), checked)


async def remove_own_photo(db: AsyncSession, storage: Storage, principal: Principal) -> Patient:
    return await _remove_photo(db, storage, principal, await get_own(db, principal))
