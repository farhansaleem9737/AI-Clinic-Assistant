import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.db.base import Base
from app.db.mixins import UUIDPrimaryKeyMixin


class DocumentExtraction(UUIDPrimaryKeyMixin, Base):
    """The server's reading of one stored file, kept so a document is parsed
    once per content and extractor version instead of on every question (D130).

    Not an access path: it is looked up only after document_service has
    authorized the caller for the document that owns `file_id`, so the
    record's rules apply unchanged. It holds the same findings the patient
    record already implies (values, conditions, short source lines), never
    the file. Deleted with the file (ON DELETE CASCADE, and when the object
    is deleted from storage); a new extractor version writes a new row and
    older versions are never read.
    """

    __tablename__ = "document_extractions"
    __table_args__ = (UniqueConstraint("file_id", "version"),)

    file_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stored_files.id", ondelete="CASCADE"))
    # The file's content hash when it was read: a mismatch is never served.
    sha256: Mapped[str] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(20))
    payload: Mapped[dict] = mapped_column(JSONB)
    duration_ms: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
