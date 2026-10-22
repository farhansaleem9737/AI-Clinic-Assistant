import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.models.patient_document import DocumentType

class DocumentCreate(BaseModel):
    """Form fields sent with an uploaded document. """

    document_type: DocumentType
    title: str = Field(min_length=1,max_length=200)
    document_date: date | None = None
    appointment_id: uuid.UUID | None =None


class DocumentRead(BaseModel):
    """Metadata only. The file itself is fetched through /download."""

    id: uuid.UUID
    patient_id: uuid.UUID
    appointment_id: uuid.UUID | None
    document_type: DocumentType
    title: str
    document_date: date | None
    filename: str | None
    content_type: str
    size_bytes: int
    uploaded_by_me: bool
    created_at: datetime

class DocumentDownload(BaseModel):
    """A presigned link: anyone holding it can download the file until expires_at."""
    url: str
    expires_at: datetime

class DocumentRetract(BaseModel):
    reason: str = Field(min_length=3, max_length=500)