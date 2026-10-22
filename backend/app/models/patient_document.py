import enum
import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, Enum, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.stored_file import StoredFile


class DocumentType(enum.StrEnum):
    lab_report = "lab_report"
    imaging = "imaging"
    prescription = "prescription"
    referral = "referral"
    discharge_summary = "discharge_summary"
    other = "other"


class DocumentStatus(enum.StrEnum):
    active = "active"
    # Uploaded by mistake (wrong patient, wrong file). Hidden, never deleted.
    entered_in_error = "entered_in_error"


class PatientDocument(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A report or other clinical document in a patient's record.

    Never deleted (architecture §20): a wrong upload is retracted, and the
    file is kept for the medical-records retention period.
    """

    __tablename__ = "patient_documents"
    __table_args__ = (
        Index("ix_patient_documents_patient_id_created_at", "patient_id", "created_at"),
        CheckConstraint("(status = 'active') = (retracted_at IS NULL)", name="retraction_consistent"),
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("patients.id", ondelete="RESTRICT"))
    file_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("stored_files.id", ondelete="RESTRICT"), unique=True
    )
    # Optional: the visit this document belongs to. Later: encounter_id.
    appointment_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("appointments.id", ondelete="RESTRICT"), index=True
    )
    document_type: Mapped[DocumentType] = mapped_column(
        Enum(DocumentType, name="document_type", values_callable=lambda e: [m.value for m in e])
    )
    # PHI: shown to authorised users, never logged or used in file names.
    title: Mapped[str] = mapped_column(String(200))
    # When the test or report was done, not when it was uploaded.
    document_date: Mapped[date | None] = mapped_column(Date)
    uploaded_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"))
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, name="document_status", values_callable=lambda e: [m.value for m in e]),
        default=DocumentStatus.active,
    )
    retracted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT")
    )
    retracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retraction_reason: Mapped[str | None] = mapped_column(String(500))

    # Loaded in the same query (LEFT OUTER JOIN): every use needs the key/type.
    file: Mapped[StoredFile] = relationship(lazy="joined")
