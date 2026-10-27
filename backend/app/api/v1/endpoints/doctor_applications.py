import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import require_permission
from app.api.deps.pagination import page_params
from app.api.deps.uploads import read_document
from app.core.permissions import Perm, Principal
from app.core.storage import Storage, get_storage
from app.db.session import get_db
from app.models.doctor_application import ApplicationStatus, CredentialType, DoctorApplicationDocument
from app.schemas.common import Page
from app.schemas.doctor_application import (
    ApplicationApproval,
    ApplicationDocumentRead,
    ApplicationRejection,
    DoctorApplicationRead,
    DoctorApplicationSummary,
    DoctorApplicationUpdate,
)
from app.schemas.document import DocumentDownload
from app.services import doctor_application_service as service
from app.services.file_validation import display_filename
from app.services.pagination import PageParams

# The applicant works only on /me: there is no id to guess, so nobody can
# reach another applicant's application or documents. Reviewers use ids.
router = APIRouter(prefix="/doctor-applications", tags=["doctor applications"])

OWN = require_permission(Perm.doctor_application_manage_own)
REVIEW = require_permission(Perm.doctor_application_review)


def to_document(d: DoctorApplicationDocument) -> ApplicationDocumentRead:
    return ApplicationDocumentRead(
        id=d.id,
        document_type=d.document_type,
        filename=d.file.original_filename,
        content_type=d.file.content_type,
        size_bytes=d.file.size_bytes,
        uploaded_at=d.created_at,
    )


def to_read(view: service.ApplicationView) -> DoctorApplicationRead:
    a = view.application
    return DoctorApplicationRead(
        id=a.id,
        status=a.status,
        name=view.name,
        email=view.email,
        license_number=a.license_number,
        registration_authority=a.registration_authority,
        specialization=a.specialization,
        department_id=a.department_id,
        department_name=view.department_name,
        years_of_experience=a.years_of_experience,
        qualifications=a.qualifications,
        institution=a.institution,
        bio=a.bio,
        consultation_fee=a.consultation_fee,
        languages=a.languages,
        phone=a.phone,
        submitted_at=a.submitted_at,
        reviewed_at=a.reviewed_at,
        review_notes=a.review_notes,
        doctor_id=a.doctor_id,
        documents=[to_document(d) for d in view.documents],
        missing_for_approval=view.missing_for_approval,
    )


# ---- The applicant -----------------------------------------------------------
@router.get("/me", response_model=DoctorApplicationRead)
async def get_my_application(db: AsyncSession = Depends(get_db), principal: Principal = Depends(OWN)):
    return to_read(await service.get_own(db, principal))


@router.patch("/me", response_model=DoctorApplicationRead)
async def update_my_application(
    body: DoctorApplicationUpdate, db: AsyncSession = Depends(get_db), principal: Principal = Depends(OWN)
):
    return to_read(await service.update_own(db, principal, body))


@router.post("/me/documents", response_model=ApplicationDocumentRead, status_code=status.HTTP_201_CREATED)
async def upload_my_document(
    file: Annotated[UploadFile, File(description="PDF, JPEG or PNG, at most MAX_DOCUMENT_BYTES")],
    document_type: Annotated[CredentialType, Form()],
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(OWN),
    storage: Storage = Depends(get_storage),
):
    checked = await read_document(file)
    document = await service.add_document(
        db,
        storage,
        principal,
        document_type=document_type,
        checked=checked,
        original_filename=display_filename(file.filename),
    )
    return to_document(document)


@router.delete("/me/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_my_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(OWN),
    storage: Storage = Depends(get_storage),
):
    await service.remove_document(db, storage, principal, document_id)


# ---- Reviewers ---------------------------------------------------------------
@router.get("/", response_model=Page[DoctorApplicationSummary])
async def list_applications(
    status_filter: ApplicationStatus | None = Query(None, alias="status"),
    params: PageParams = Depends(page_params),
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(REVIEW),
):
    rows, total = await service.list_applications(db, params, status=status_filter)
    items = [
        DoctorApplicationSummary(
            id=row.application.id,
            status=row.application.status,
            name=row.name,
            email=row.email,
            specialization=row.application.specialization,
            department_name=row.department_name,
            document_count=row.document_count,
            submitted_at=row.application.submitted_at,
        )
        for row in rows
    ]
    return Page(items=items, total=total, page=params.page, page_size=params.page_size)


@router.get("/{application_id}", response_model=DoctorApplicationRead)
async def get_application(
    application_id: uuid.UUID, db: AsyncSession = Depends(get_db), _: Principal = Depends(REVIEW)
):
    return to_read(await service.get_application(db, application_id))


@router.get("/{application_id}/documents/{document_id}/download", response_model=DocumentDownload)
async def download_document(
    application_id: uuid.UUID,
    document_id: uuid.UUID,
    response: Response,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(REVIEW),
    storage: Storage = Depends(get_storage),
):
    """A link valid for a few minutes (DOCUMENT_URL_TTL_SECONDS)."""
    url, expires_at = await service.document_link(db, storage, principal, application_id, document_id)
    response.headers["Cache-Control"] = "no-store"
    return DocumentDownload(url=url, expires_at=expires_at)


@router.post("/{application_id}/approve", response_model=DoctorApplicationRead)
async def approve_application(
    application_id: uuid.UUID,
    body: ApplicationApproval,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(REVIEW),
):
    return to_read(await service.approve(db, principal, application_id, body.notes))


@router.post("/{application_id}/reject", response_model=DoctorApplicationRead)
async def reject_application(
    application_id: uuid.UUID,
    body: ApplicationRejection,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(REVIEW),
):
    return to_read(await service.reject(db, principal, application_id, body.notes))
