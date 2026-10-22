import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import require_any_permission
from app.api.deps.uploads import read_document
from app.core.permissions import Perm,Principal
from app.core.storage import Storage, get_storage
from app.db.session import get_db
from app.models.patient_document import DocumentType, PatientDocument
from app.schemas.document import DocumentCreate,DocumentDownload, DocumentRead, DocumentRetract
from app.services import document_service
from app.services.file_validation import display_filename


# Nested under the patient: every route names the patient, and the service
# checks the document belongs to that patient *and* that the caller may see it.
router= APIRouter(prefix="/patients/{patient_id}/documents", tags=["documents"])

READ = (Perm.document_read_own, Perm.document_read_assigned)
UPLOAD = (Perm.document_upload_own, Perm.document_upload_assigned)
RETRACT = (Perm.document_retract_own, Perm.document_retract_assigned)

def to_read(d: PatientDocument, principal: Principal) -> DocumentRead:
    return DocumentRead(
        id=d.id,
        patient_id=d.patient_id,
        appointment_id=d.appointment_id,
        document_type=d.document_type,
        title=d.title,
        document_date=d.document_date,
        filename=d.file.original_filename,
        content_type=d.file.content_type,
        size_bytes=d.file.size_bytes,
        uploaded_by_me=d.uploaded_by_user_id == principal.user_id,
        created_at=d.created_at,
    )

@router.get("/", response_model=list[DocumentRead])
async def list_document(
    patient_id:uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_any_permission(*READ)),
):
    return [to_read(d, principal) for d in await document_service.list_document(db, principal, patient_id)]

@router.post("/", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def upload_document(
    patient_id: uuid.UUID,
    file: Annotated[UploadFile, File(description="PDF, JPEG or PNG, at most 20MB")],
    document_type: Annotated[DocumentType, Form()],
    title: Annotated[str, Form(min_length=1, max_length=200)],
    document_date: Annotated[date | None, Form()] = None,
    appointment_id: Annotated[uuid.UUID | None, Form()] = None,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_any_permission(*UPLOAD)),
    storage: Storage = Depends(get_storage),
):
    checked = await read_document(file)
    meta= DocumentCreate(
        document_type=document_type, title=title, document_date=document_date, appointment_id=appointment_id
    )
    document = await document_service.upload_document(
        db, storage, principal, patient_id,checked=checked, meta=meta, original_filename=display_filename(file.filename)
    )
    return to_read(document, principal)

@router.get("/{document_id}", response_model=DocumentRead)
async def get_document(
    patient_id: uuid.UUID,
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_any_permission(*READ)),
):
    return to_read(await document_service.get_document(db, principal, patient_id, document_id), principal)

@router.get("/{document_id}/download", response_model=DocumentDownload)
async def download_document(
    patient_id: uuid.UUID,
    document_id: uuid.UUID,
    response: Response,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_any_permission(*READ)),
    storage: Storage = Depends(get_storage),
):
    """A link valid for a few minutes. JSON rather than a redirect: browsers
    drop the Authorization header on cross-origin redirects, and the app
    decides when to open it."""
    url, expires_at= await document_service.download_link(db, storage, principal, patient_id, document_id)
    response.headers["Cache-Control"] = "no-store"
    return DocumentDownload(url=url, expires_at=expires_at)

@router.post("/{document_id}/retract", response_model=DocumentRead)
async def retract_document(
    patient_id: uuid.UUID,
    document_id: uuid.UUID,
    body: DocumentRetract,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_any_permission(*RETRACT)),
):
    document = await document_service.retract_document(db, principal, patient_id, document_id, body.reason)
    return to_read(document, principal)
