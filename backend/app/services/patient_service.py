import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BusinessRuleError, ConflictError, DomainError, NotFoundError
from app.core.permissions import Principal, RoleCode
from app.core.storage import Storage
from app.models.stored_file import FileCategory
from app.services.file_validation import CheckedFile
from app.models.appointment import Appointment
from app.models.patient import Patient, SexAtBirth
from app.models.user import User
from app.schemas.patient import (
    PatientSelfUpdate,
    PatientCreate,
    PatientRegistration,
    PatientUpdate,
)
from app.services import access, appointment_service, auth_service, rbac_service, file_service
from app.services.audit_service import AuditAction, record
from app.services.pagination import PageParams, paginate

logger = logging.getLogger(__name__)


class PatientSort(StrEnum):
    name = "name"
    registered_newest = "registered_newest"
    registered_oldest = "registered_oldest"
    # Admin > Patients columns (D91); "-" = descending.
    name_desc = "-name"
    mrn = "mrn"
    mrn_desc = "-mrn"
    email = "email"
    email_desc = "-email"
    phone = "phone"
    phone_desc = "-phone"
    status = "status"  # active first
    status_desc = "-status"


# The id breaks ties, so pages never repeat or skip a patient.
_SORTS = {
    PatientSort.name: (Patient.last_name, Patient.first_name),
    PatientSort.registered_newest: (Patient.created_at.desc(),),
    PatientSort.registered_oldest: (Patient.created_at.asc(),),
    PatientSort.name_desc: (Patient.last_name.desc(), Patient.first_name.desc()),
    PatientSort.mrn: (Patient.mrn.asc(),),
    PatientSort.mrn_desc: (Patient.mrn.desc(),),
    # Walk-ins without an email or phone sort last either way.
    PatientSort.email: (func.lower(Patient.email).asc().nulls_last(), Patient.last_name, Patient.first_name),
    PatientSort.email_desc: (func.lower(Patient.email).desc().nulls_last(), Patient.last_name, Patient.first_name),
    PatientSort.phone: (Patient.phone.asc().nulls_last(), Patient.last_name, Patient.first_name),
    PatientSort.phone_desc: (Patient.phone.desc().nulls_last(), Patient.last_name, Patient.first_name),
    PatientSort.status: (Patient.is_active.desc(), Patient.last_name, Patient.first_name),
    PatientSort.status_desc: (Patient.is_active.asc(), Patient.last_name, Patient.first_name),
}


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
    doctor_id: uuid.UUID | None = None,
    registered_from: date | None = None,
    registered_to: date | None = None,
    sex_at_birth: SexAtBirth | None = None,
    sort: PatientSort = PatientSort.name,
) -> tuple[list[Patient], int]:
    """Patients the caller may see, filtered in SQL and paged.

    `doctor_id`: patients who have (or had) an appointment with that doctor —
    the only doctor-patient relationship the data model has. An EXISTS test,
    so several appointments never repeat a patient. `registered_from/_to`:
    inclusive calendar dates of the record's creation, in the clinic's
    timezone."""
    if registered_from and registered_to and registered_from > registered_to:
        raise BusinessRuleError("The start date must not be after the end date", code="INVALID_RANGE")
    query = select(Patient).where(access.patient_visibility(principal)).order_by(*_SORTS[sort], Patient.id)
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
    if sex_at_birth is not None:
        query = query.where(Patient.sex_at_birth == sex_at_birth)
    if doctor_id is not None:
        query = query.where(
            exists().where(Appointment.patient_id == Patient.id, Appointment.doctor_id == doctor_id)
        )
    tz = ZoneInfo(settings.clinic_timezone)
    if registered_from is not None:
        query = query.where(Patient.created_at >= datetime.combine(registered_from, time.min, tzinfo=tz))
    if registered_to is not None:
        query = query.where(
            Patient.created_at < datetime.combine(registered_to + timedelta(days=1), time.min, tzinfo=tz)
        )
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


IDENTITY_FIELDS = ("first_name", "last_name", "date_of_birth", "sex_at_birth")


async def update_own_profile(db: AsyncSession, principal: Principal, data: PatientSelfUpdate) -> Patient:
    """A patient edits their own contact and personal details (D99). A
    change to the name, date of birth or gender is audited with the values
    it replaced, so the clinic can see and, if needed, reverse it."""
    patient = await get_own(db, principal)
    changes = data.model_dump(exclude_unset=True)
    for required in IDENTITY_FIELDS:
        if required in changes and changes[required] is None:
            del changes[required]
    previous = {
        field: str(getattr(patient, field))
        for field in IDENTITY_FIELDS
        if field in changes and changes[field] != getattr(patient, field)
    }
    for field, value in changes.items():
        setattr(patient, field, value)
    if previous:
        record(db, AuditAction.patient_identity_changed, actor_id=principal.user_id, target_type="patient",
               target_id=patient.id, details={"fields": sorted(previous), "previous": previous})
    await _commit_and_reload(db, patient)
    logger.info("patient_self_updated", extra={"patient_id": str(patient.id), "fields": sorted(changes)})
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
    record(db, AuditAction.patient_activated if active else AuditAction.patient_deactivated,
           actor_id=principal.user_id, target_type="patient", target_id=patient.id)
    await _commit_and_reload(db, patient)
    logger.info(
        "patient_activated" if active else "patient_deactivated",
        extra={"patient_id": str(patient.id), "by": str(principal.user_id)},
    )
    return patient


@dataclass(frozen=True)
class BulkOutcome:
    patient_id: uuid.UUID
    ok: bool
    code: str | None = None
    message: str | None = None


async def set_active_bulk(
    db: AsyncSession, principal: Principal, patient_ids: list[uuid.UUID], active: bool
) -> list[BulkOutcome]:
    """Each patient in its own transaction through ``set_active``: the same
    visibility, upcoming-appointment rule and audit apply, and one refusal
    does not undo the others."""
    outcomes = []
    for patient_id in dict.fromkeys(patient_ids):
        try:
            await set_active(db, principal, patient_id, active)
            outcomes.append(BulkOutcome(patient_id, True))
        except DomainError as exc:
            await db.rollback()
            await db.refresh(principal.user)  # the rollback expired it
            outcomes.append(BulkOutcome(patient_id, False, exc.code, exc.message))
    return outcomes


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
