"""A patient's allergies, diagnoses and medications (D112).

Structured entries typed in by people, never read out of documents or made up
by the AI. Who records what:

- allergies and medications: the patient (self-reported) or a treating doctor;
- diagnoses: a treating doctor only.

`source` says which, so a self-reported entry is always shown as such. An entry
is never deleted: removing it (a mistake, or an allergy that was wrong) sets
`removed_at` and hides it, and the row stays for the medical record.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, String, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin

SOURCES = ("patient", "clinician")
ALLERGY_SEVERITIES = ("mild", "moderate", "severe", "unknown")
DIAGNOSIS_STATUSES = ("active", "resolved")
MEDICATION_STATUSES = ("active", "stopped")


def _one_of(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class HealthRecordMixin(UUIDPrimaryKeyMixin, TimestampMixin):
    patient_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("patients.id", ondelete="RESTRICT"))
    # "patient": reported by the patient; "clinician": recorded by a treating doctor.
    source: Mapped[str] = mapped_column(String(10))
    recorded_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"))
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    removed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"))


class PatientAllergy(HealthRecordMixin, Base):
    __tablename__ = "patient_allergies"
    __table_args__ = (
        Index("ix_patient_allergies_patient_id", "patient_id"),
        # One current entry per substance and patient (case-insensitive).
        Index(
            "uq_patient_allergies_current_substance", "patient_id", func.lower(text("substance")),
            unique=True, postgresql_where=text("removed_at IS NULL"),
        ),
        CheckConstraint(_one_of("source", SOURCES), name="source_known"),
        CheckConstraint(_one_of("severity", ALLERGY_SEVERITIES), name="severity_known"),
    )

    # PHI: shown to authorised users, never logged.
    substance: Mapped[str] = mapped_column(String(120))
    reaction: Mapped[str | None] = mapped_column(String(200))
    severity: Mapped[str] = mapped_column(String(10), default="unknown")


class PatientDiagnosis(HealthRecordMixin, Base):
    __tablename__ = "patient_diagnoses"
    __table_args__ = (
        Index("ix_patient_diagnoses_patient_id", "patient_id"),
        CheckConstraint("source = 'clinician'", name="source_clinician"),
        CheckConstraint(_one_of("status", DIAGNOSIS_STATUSES), name="status_known"),
    )

    condition: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(10), default="active")
    diagnosed_on: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(String(1000))


class PatientMedication(HealthRecordMixin, Base):
    __tablename__ = "patient_medications"
    __table_args__ = (
        Index("ix_patient_medications_patient_id", "patient_id"),
        CheckConstraint(_one_of("source", SOURCES), name="source_known"),
        CheckConstraint(_one_of("status", MEDICATION_STATUSES), name="status_known"),
        CheckConstraint("end_date IS NULL OR start_date IS NULL OR end_date >= start_date", name="dates_ordered"),
    )

    name: Mapped[str] = mapped_column(String(200))
    dosage: Mapped[str | None] = mapped_column(String(100))
    frequency: Mapped[str | None] = mapped_column(String(100))
    instructions: Mapped[str | None] = mapped_column(String(500))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(10), default="active")
