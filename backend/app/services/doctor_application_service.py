"""Doctor self-registration and credential review (D77).

Registering as a doctor is a *claim*, not a verification:

1. ``register`` creates the login with the doctor_applicant role (no
   clinical permission) and a pending application holding whatever
   professional details were given. All of them are optional.
2. The applicant completes details and uploads credentials later
   (``update_own`` / ``add_document``) while the application is pending.
3. An administrator approves (``approve``): only then is the Doctor profile
   created and the doctor role granted. Or rejects, with a reason.

Approval requirements are a policy (``missing_for_approval``), separate from
registration validation, so they can be tightened through settings without
making sign-up impossible.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.config import settings
from app.core.exceptions import (
    BusinessRuleError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    StorageUnavailableError,
)
from app.core.permissions import Principal, RoleCode
from app.core.storage import Storage, StorageError
from app.models.department import Department
from app.models.doctor import Doctor
from app.models.doctor_application import (
    ApplicationStatus,
    CredentialType,
    DoctorApplication,
    DoctorApplicationDocument,
)
from app.models.rbac import Role, UserRole
from app.models.stored_file import FileCategory, FileStatus
from app.models.user import User
from app.schemas.doctor_application import DoctorApplicationUpdate, DoctorRegistration, ProfessionalDetails
from app.services import auth_service, doctor_service, file_service, rbac_service
from app.services.file_validation import CheckedFile
from app.services.pagination import PageParams, paginate

logger = logging.getLogger(__name__)

# A doctor profile cannot exist without these, whatever the settings say.
ALWAYS_REQUIRED = ("specialization", "department_id")
# Enough for a certificate, a degree and a few supporting pages.
MAX_DOCUMENTS = 10

_DETAIL_FIELDS = tuple(ProfessionalDetails.model_fields)


@dataclass(frozen=True)
class ApplicationView:
    application: DoctorApplication
    name: str
    email: str
    department_name: str | None
    documents: list[DoctorApplicationDocument]
    missing_for_approval: list[str]


@dataclass(frozen=True)
class ApplicationSummaryRow:
    application: DoctorApplication
    name: str
    email: str
    department_name: str | None
    document_count: int


def missing_for_approval(
    application: DoctorApplication, documents: list[DoctorApplicationDocument]
) -> list[str]:
    """Field and document-type names still needed before approval. The
    review policy, kept apart from registration validation."""
    have_documents = {d.document_type.value for d in documents}
    missing = []
    for name in (*ALWAYS_REQUIRED, *settings.doctor_approval_requirements):
        if name in CredentialType.__members__:
            present = name in have_documents
        else:
            present = getattr(application, name) is not None
        if not present and name not in missing:
            missing.append(name)
    return missing


async def _check_department(db: AsyncSession, department_id: uuid.UUID | None) -> None:
    if department_id is None:
        return
    department = await db.get(Department, department_id)
    if department is None or not department.is_active:
        raise BusinessRuleError(
            "Choose one of the clinic's departments", code="DEPARTMENT_UNAVAILABLE", details={"field": "department_id"}
        )


async def register(db: AsyncSession, data: DoctorRegistration) -> User:
    """Login + doctor_applicant role + pending application, one transaction.
    Nothing is committed if any step fails."""
    await _check_department(db, data.department_id)
    user = await auth_service.create_user(db, name=data.name, email=data.email, password=data.password)
    await rbac_service.grant_roles(db, user.id, [RoleCode.doctor_applicant])
    db.add(
        DoctorApplication(
            user_id=user.id,
            status=ApplicationStatus.pending_review,
            submitted_at=clock.utcnow(),
            **data.model_dump(include=set(_DETAIL_FIELDS)),
        )
    )
    await db.commit()
    logger.info("doctor_applicant_registered", extra={"user_id": str(user.id)})
    return user


# ---- Reading -----------------------------------------------------------------
def _view_query() -> Select:
    return (
        select(DoctorApplication, User.name, User.email, Department.name)
        .join(User, User.id == DoctorApplication.user_id)
        .outerjoin(Department, Department.id == DoctorApplication.department_id)
    )


async def _documents(db: AsyncSession, application_id: uuid.UUID) -> list[DoctorApplicationDocument]:
    query = (
        select(DoctorApplicationDocument)
        .where(DoctorApplicationDocument.application_id == application_id)
        .order_by(DoctorApplicationDocument.created_at, DoctorApplicationDocument.id)
    )
    return list((await db.scalars(query)).all())


async def _view(db: AsyncSession, condition) -> ApplicationView:
    row = (await db.execute(_view_query().where(condition))).one_or_none()
    if row is None:
        raise NotFoundError("Doctor application not found", code="NO_DOCTOR_APPLICATION")
    application, name, email, department_name = row
    documents = await _documents(db, application.id)
    return ApplicationView(
        application, name, email, department_name, documents, missing_for_approval(application, documents)
    )


async def get_own(db: AsyncSession, principal: Principal) -> ApplicationView:
    return await _view(db, DoctorApplication.user_id == principal.user_id)


async def get_application(db: AsyncSession, application_id: uuid.UUID) -> ApplicationView:
    return await _view(db, DoctorApplication.id == application_id)


async def list_applications(
    db: AsyncSession, params: PageParams, *, status: ApplicationStatus | None = None
) -> tuple[list[ApplicationSummaryRow], int]:
    document_count = (
        select(func.count(DoctorApplicationDocument.id))
        .where(DoctorApplicationDocument.application_id == DoctorApplication.id)
        .scalar_subquery()
    )
    query = (
        select(DoctorApplication, User.name, User.email, Department.name, document_count)
        .join(User, User.id == DoctorApplication.user_id)
        .outerjoin(Department, Department.id == DoctorApplication.department_id)
        .order_by(DoctorApplication.submitted_at, DoctorApplication.id)
    )
    if status is not None:
        query = query.where(DoctorApplication.status == status)
    rows, total = await paginate(db, query, params)
    return [ApplicationSummaryRow(*row) for row in rows], total


# ---- The applicant -----------------------------------------------------------
async def _own_open_application(db: AsyncSession, principal: Principal) -> DoctorApplication:
    application = await db.scalar(
        select(DoctorApplication).where(DoctorApplication.user_id == principal.user_id).with_for_update()
    )
    if application is None:
        raise NotFoundError("Doctor application not found", code="NO_DOCTOR_APPLICATION")
    if application.status != ApplicationStatus.pending_review:
        raise ConflictError(
            "This application has already been reviewed and can no longer be changed", code="APPLICATION_CLOSED"
        )
    return application


async def update_own(db: AsyncSession, principal: Principal, data: DoctorApplicationUpdate) -> ApplicationView:
    application = await _own_open_application(db, principal)
    changes = data.model_dump(exclude_unset=True)
    if "department_id" in changes:
        await _check_department(db, changes["department_id"])
    for field, value in changes.items():
        setattr(application, field, value)
    await db.commit()
    logger.info("doctor_application_updated", extra={"application_id": str(application.id), "fields": sorted(changes)})
    return await get_own(db, principal)


async def add_document(
    db: AsyncSession,
    storage: Storage,
    principal: Principal,
    *,
    document_type: CredentialType,
    checked: CheckedFile,
    original_filename: str | None,
) -> DoctorApplicationDocument:
    # Authorize and check limits before anything reaches R2.
    application = await _own_open_application(db, principal)
    count = await db.scalar(
        select(func.count(DoctorApplicationDocument.id)).where(
            DoctorApplicationDocument.application_id == application.id
        )
    )
    if count >= MAX_DOCUMENTS:
        raise BusinessRuleError(
            f"An application can hold at most {MAX_DOCUMENTS} documents; remove one first",
            code="TOO_MANY_DOCUMENTS",
        )
    stored = await file_service.upload(
        db,
        storage,
        category=FileCategory.doctor_credential,
        owner_id=application.id,
        checked=checked,
        uploaded_by=principal.user_id,
        original_filename=original_filename,
    )
    document = DoctorApplicationDocument(application_id=application.id, document_type=document_type, file=stored)
    db.add(document)
    await file_service.commit_or_discard(db, storage, stored)
    # Ids, type and size only: never the file name.
    logger.info(
        "doctor_credential_uploaded",
        extra={
            "application_id": str(application.id),
            "document_id": str(document.id),
            "content_type": stored.content_type,
            "size_bytes": stored.size_bytes,
        },
    )
    return document


async def remove_document(db: AsyncSession, storage: Storage, principal: Principal, document_id: uuid.UUID) -> None:
    """Withdraw an uploaded credential while the application is pending."""
    application = await _own_open_application(db, principal)
    # Both ids must match: another applicant's document is simply "not found".
    document = await db.scalar(
        select(DoctorApplicationDocument).where(
            DoctorApplicationDocument.id == document_id,
            DoctorApplicationDocument.application_id == application.id,
        )
    )
    if document is None:
        raise NotFoundError("Document not found")
    file = document.file
    await db.delete(document)
    file.status = FileStatus.pending_deletion
    await db.commit()
    await file_service.finish_deletion(db, storage, file)
    logger.info("doctor_credential_removed", extra={"application_id": str(application.id), "document_id": str(document_id)})


# ---- The reviewer ------------------------------------------------------------
async def document_link(
    db: AsyncSession, storage: Storage, principal: Principal, application_id: uuid.UUID, document_id: uuid.UUID
) -> tuple[str, datetime]:
    document = await db.scalar(
        select(DoctorApplicationDocument).where(
            DoctorApplicationDocument.id == document_id,
            DoctorApplicationDocument.application_id == application_id,
        )
    )
    if document is None:
        raise NotFoundError("Document not found")
    try:
        info = await storage.head(document.file.object_key)
    except StorageError as exc:
        raise StorageUnavailableError("File storage is temporarily unavailable, please try again") from exc
    if info is None:
        logger.error("doctor_credential_file_missing", extra={"document_id": str(document.id)})
        raise NotFoundError("The file for this document is missing", code="FILE_MISSING")

    ttl = settings.document_url_ttl_seconds
    extension = document.file.object_key.rsplit(".", 1)[-1]
    url = storage.presigned_get_url(
        document.file.object_key,
        expires_in=ttl,
        download_name=f"{document.document_type.value}.{extension}",
        content_type=document.file.content_type,
    )
    # Stand-in for an AuditLog row (architecture §21).
    logger.info(
        "doctor_credential_url_issued",
        extra={"application_id": str(application_id), "document_id": str(document.id), "by": str(principal.user_id)},
    )
    return url, clock.utcnow() + timedelta(seconds=ttl)


async def _pending_for_review(db: AsyncSession, principal: Principal, application_id: uuid.UUID) -> DoctorApplication:
    application = await db.scalar(
        select(DoctorApplication).where(DoctorApplication.id == application_id).with_for_update()
    )
    if application is None:
        raise NotFoundError("Doctor application not found", code="NO_DOCTOR_APPLICATION")
    if application.user_id == principal.user_id:
        raise PermissionDeniedError("You cannot review your own application", code="SELF_REVIEW")
    if application.status != ApplicationStatus.pending_review:
        raise ConflictError("This application has already been reviewed", code="APPLICATION_ALREADY_REVIEWED")
    return application


def _mark_reviewed(
    application: DoctorApplication, principal: Principal, status: ApplicationStatus, notes: str | None
) -> None:
    application.status = status
    application.reviewed_at = clock.utcnow()
    application.reviewed_by_user_id = principal.user_id
    application.review_notes = notes


async def approve(
    db: AsyncSession, principal: Principal, application_id: uuid.UUID, notes: str | None
) -> ApplicationView:
    """Create the Doctor profile from the application and swap the
    doctor_applicant role for doctor, in one transaction."""
    application = await _pending_for_review(db, principal, application_id)
    missing = missing_for_approval(application, await _documents(db, application.id))
    if missing:
        raise BusinessRuleError(
            "The application is missing information required for approval",
            code="APPLICATION_INCOMPLETE",
            details={"missing": missing},
        )
    user = await db.get(User, application.user_id)
    if not user.is_active:
        raise BusinessRuleError("The applicant's account is inactive", code="USER_INACTIVE")
    if await db.scalar(select(Doctor.id).where(Doctor.user_id == user.id)) is not None:
        raise ConflictError("A doctor profile already exists for this account", code="DOCTOR_PROFILE_EXISTS")
    await doctor_service.ensure_active_department(db, application.department_id)
    await doctor_service.ensure_license_free(db, application.license_number)

    doctor = Doctor(
        user_id=user.id,
        department_id=application.department_id,
        specialization=application.specialization,
        license_number=application.license_number,
        qualifications=application.qualifications,
        bio=application.bio,
        languages=application.languages,
        years_of_experience=application.years_of_experience or 0,
        consultation_fee=application.consultation_fee,
        phone=application.phone,
    )
    db.add(doctor)
    await db.flush()
    await rbac_service.grant_roles(db, user.id, [RoleCode.doctor], granted_by=principal.user_id)
    applicant_role = await db.scalar(select(Role.id).where(Role.code == RoleCode.doctor_applicant))
    applicant_link = await db.get(UserRole, (user.id, applicant_role))
    if applicant_link is not None:
        await db.delete(applicant_link)
    _mark_reviewed(application, principal, ApplicationStatus.approved, notes)
    application.doctor_id = doctor.id
    await db.commit()
    logger.info(
        "doctor_application_approved",
        extra={"application_id": str(application.id), "doctor_id": str(doctor.id), "by": str(principal.user_id)},
    )
    return await get_application(db, application.id)


async def reject(db: AsyncSession, principal: Principal, application_id: uuid.UUID, notes: str) -> ApplicationView:
    """The login keeps the doctor_applicant role (no clinical access) and can
    read the reason; the application can no longer be changed."""
    application = await _pending_for_review(db, principal, application_id)
    _mark_reviewed(application, principal, ApplicationStatus.rejected, notes)
    await db.commit()
    logger.info(
        "doctor_application_rejected", extra={"application_id": str(application.id), "by": str(principal.user_id)}
    )
    return await get_application(db, application.id)
