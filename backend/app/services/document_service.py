"""Patient documents: lab reports, imaging reports, referrals and similar.

Clinical content, so access is relationship-based (access.document_*_scope):
the patient, and doctors who have an appointment with them. Nobody else by
default — not reception, not admins (architecture §1, §5). A denial is a
404: even confirming that a document exists is a disclosure.

Documents are never deleted. A wrong upload is retracted (entered_in_error);
its file stays in R2 for the retention period.
"""

import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.config import settings
from app.core.exceptions import NotFoundError, PermissionDeniedError, StorageUnavailableError
from app.core.permissions import Principal
from app.core.storage import Storage, StorageError
from app.models.appointment import Appointment
from app.models.patient import Patient
from app.models.patient_document import PatientDocument, DocumentStatus
from app.models.stored_file import FileCategory
from app.schemas.document import DocumentCreate
from app.services import access, file_service
from app.services.file_validation import CheckedFile

logger = logging.getLogger(__name__)

async def list_document(db: AsyncSession, principal: Principal, patient_id: uuid.UUID) -> list[PatientDocument]:
    await access.get_patient_in_scope(db, patient_id, access.document_read_scope(principal, Patient.id))
    query=(
        select(PatientDocument)
        .where(
            PatientDocument.patient_id == patient_id,
            PatientDocument.status == DocumentStatus.active,
            access.document_read_scope(principal, PatientDocument.patient_id),
        )
        .order_by(PatientDocument.created_at.desc(), PatientDocument.id.desc())
    )
    return list((await db.scalars(query)).all())

async def get_document(
        db: AsyncSession, principal: Principal,  patient_id: uuid.UUID, document_id: uuid.UUID
) -> PatientDocument:
    # Both ids must match: a document of patient B is never reachable through
    # patient A's URL, even for someone allowed to see both.
    document= await db.scalar(
        select(PatientDocument).where(
            PatientDocument.id == document_id,
            PatientDocument.patient_id== patient_id,
            PatientDocument.status == DocumentStatus.active,
            access.document_read_scope(principal, PatientDocument.patient_id),
        )
    )
    if document is None:
        raise NotFoundError("Document not found")
    return document

async def upload_document(
        db: AsyncSession,
        storage: Storage,
        principal: Principal,
        patient_id: uuid.UUID,
        *,
        checked: CheckedFile,
        meta: DocumentCreate,
        original_filename: str | None,
) -> PatientDocument:
    # authorize before anything reaches R2
    patient= await access.get_patient_in_scope(
        db, patient_id,  access.document_upload_scope(principal, Patient.id)
    )
    if meta.appointment_id is not None:
        belongs = await db.scalar(
            select(Appointment.id).where(Appointment.id == meta.appointment_id, Appointment.patient_id == patient.id)
        )
        if belongs is None:
            raise NotFoundError("Appointment not found")

    stored = await file_service.upload(
        db,
        storage,
        category=FileCategory.patient_document,
        owner_id=patient.id,
        checked=checked,
        uploaded_by=principal.user_id,
        original_filename=original_filename,
    )
    document= PatientDocument(
        patient_id= patient.id,
        file=stored,
        appointment_id=meta.appointment_id,
        document_type=meta.document_type,
        title=meta.title,
        document_date=meta.document_date,
        uploaded_by_user_id=principal.user_id,
    )
    db.add(document)
    await file_service.commit_or_discard(db, storage, stored)
    # Ids, type and size only: never the title or the filename (PHI).
    logger.info(
        "patient_document_uploaded",
        extra={
            "document_id": str(document.id),
            "patient_id": str(patient.id),
            "by": str(principal.user_id),
            "content_type": stored.content_type,
            "size_bytes": stored.size_bytes,
        }
    )
    return document

def _download_name(document: PatientDocument) -> str:
    """No PHI in the saved file's name: document type and date only."""
    day= document.document_date or document.created_at.date()
    extension= document.file.object_key.rsplit(".",1)[-1]
    return f"{document.document_type.value}-{day.isoformat()}.{extension}"

async def download_link(
        db: AsyncSession, storage: Storage, principal: Principal, patient_id:uuid.UUID, document_id:uuid.UUID
) -> tuple[str, datetime]:
    document = await get_document(db, principal, patient_id, document_id)
    try:
        info = await storage.head(document.file.object_key)
    except StorageError as exc:
        raise StorageUnavailableError("File storage is temporarily unavailable, please try again") from exc
    if info is None:
        logger.error("document_file_missing", extra={"document_id" : str(document.id), "file_id": str(document.file_id)})
        raise NotFoundError("The file for this document is missing; please contact the clinic", code= "FILE_MISSING")

    ttl=settings.document_url_ttl_seconds
    url=storage.presigned_get_url(
        document.file.object_key,
        expires_in=ttl,
        download_name=_download_name(document),
        content_type=document.file.content_type,
    )
    # Stand-in for an AuditLog row (architecture §21) until that table exists.
    logger.info(
        "document_download_url_issued",
        extra={"document_id":str(document.id), "patient_id":str(document.patient_id), "by": str(principal.user_id)},
    )
    return url, clock.utcnow() + timedelta(seconds=ttl)

async def retract_document(
        db:AsyncSession, principal: Principal, patient_id: uuid.UUID, document_id: uuid.UUID, reason: str
) -> PatientDocument:
    document= await get_document(db, principal, patient_id, document_id)
    allowed= await db.scalar(
        select(PatientDocument.id).where(PatientDocument.id == document.id, access.document_retract_scope(principal))
    )
    if allowed is None:
        # They can already see the document, so a 403 discloses nothing new.
        raise PermissionDeniedError("You cannot retract this document", code="CANNOT_RETRACT")
    document.status = DocumentStatus.entered_in_error
    document.retracted_by_user_id = principal.user_id
    document.retracted_at = clock.utcnow()
    document.retraction_reason = reason
    await db.commit()
    logger.info("patient_document_retracted", extra={"documnet_id": str(document.id), "by": str(principal.user_id)})
    return document