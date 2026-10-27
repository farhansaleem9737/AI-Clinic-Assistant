import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Integer, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.stored_file import StoredFile


class ApplicationStatus(enum.StrEnum):
    pending_review = "pending_review"
    approved = "approved"
    rejected = "rejected"


class CredentialType(enum.StrEnum):
    registration_certificate = "registration_certificate"
    degree_certificate = "degree_certificate"
    supporting_document = "supporting_document"


class DoctorApplication(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A self-registered doctor's professional details, awaiting review.

    Choosing "Doctor" at registration is not verification: the login gets the
    doctor_applicant role only (no clinical access), and no Doctor profile
    exists until an administrator approves this application (D77). Every
    professional field is optional here; what approval needs is decided by
    the review policy, not by registration.
    """

    __tablename__ = "doctor_applications"
    __table_args__ = (
        CheckConstraint(
            "years_of_experience IS NULL OR years_of_experience BETWEEN 0 AND 80", name="experience_range"
        ),
        CheckConstraint("consultation_fee IS NULL OR consultation_fee >= 0", name="fee_not_negative"),
        CheckConstraint("(status = 'pending_review') = (reviewed_at IS NULL)", name="review_consistent"),
        CheckConstraint("(status = 'approved') = (doctor_id IS NOT NULL)", name="approval_has_profile"),
    )

    # One application per login.
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), unique=True)
    status: Mapped[ApplicationStatus] = mapped_column(
        Enum(ApplicationStatus, name="doctor_application_status", values_callable=lambda e: [m.value for m in e]),
        default=ApplicationStatus.pending_review,
        index=True,
    )

    # Professional details as the applicant gave them. Not unique: a licence
    # number is checked against existing doctors at approval, so nobody can
    # block a real doctor by registering their number first.
    license_number: Mapped[str | None] = mapped_column(String(50))
    registration_authority: Mapped[str | None] = mapped_column(String(150))
    specialization: Mapped[str | None] = mapped_column(String(150))
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("departments.id", ondelete="RESTRICT"), index=True
    )
    years_of_experience: Mapped[int | None] = mapped_column(Integer)
    qualifications: Mapped[str | None] = mapped_column(String(500))
    institution: Mapped[str | None] = mapped_column(String(200))
    bio: Mapped[str | None] = mapped_column(String(1000))
    consultation_fee: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    languages: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(30))

    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    # Shown to the applicant: the reason for a rejection, or a note on approval.
    review_notes: Mapped[str | None] = mapped_column(String(1000))
    # The profile created on approval.
    doctor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("doctors.id", ondelete="RESTRICT"), unique=True
    )


class DoctorApplicationDocument(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A credential (registration certificate, degree, ...) in private R2
    storage. Only administrators reviewing applications get a download link."""

    __tablename__ = "doctor_application_documents"

    application_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("doctor_applications.id", ondelete="RESTRICT"), index=True
    )
    document_type: Mapped[CredentialType] = mapped_column(
        Enum(CredentialType, name="credential_type", values_callable=lambda e: [m.value for m in e])
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("stored_files.id", ondelete="RESTRICT"), unique=True
    )

    file: Mapped[StoredFile] = relationship(lazy="joined")
