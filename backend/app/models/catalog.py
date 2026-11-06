"""The medical catalog (D118): specializations under departments, which
doctors practise them, and the conditions and symptoms they are suited to.

    Department -< DepartmentSpecialization >- Specialization -< DoctorSpecialization >- Doctor
    MedicalTopic -< MedicalTopicSpecialization >- Specialization

A specialization may belong to more than one department (Pediatric Cardiology
is under Pediatrics and Cardiology). `Doctor.specialization` (free text, as
shown on profiles) and `Doctor.department_id` (the primary department) are
unchanged; the links here add structure next to them.

Topic links are routing guidance for the assistant and the directory, never a
diagnosis. Each one carries review metadata: rows seeded from the curated
catalog start as "curated" until a clinician marks them "reviewed".
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin

TOPIC_TYPES = ("disease", "condition", "symptom")
RELEVANCE = ("primary", "secondary")
REVIEW_STATUSES = ("curated", "reviewed")


class Specialization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "specializations"

    name: Mapped[str] = mapped_column(String(120), unique=True)
    # Stable key for links and seeding; never changes once created.
    slug: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str | None] = mapped_column(String(500))
    # Other names for the same thing ("cardiologist", "heart rhythm specialist"),
    # lower case. Unique across specializations (checked in the service).
    aliases: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class DepartmentSpecialization(Base):
    __tablename__ = "department_specializations"
    __table_args__ = (Index("ix_department_specializations_specialization_id", "specialization_id"),)

    department_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("departments.id", ondelete="CASCADE"), primary_key=True)
    specialization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("specializations.id", ondelete="CASCADE"), primary_key=True
    )


class DoctorSpecialization(Base):
    """Set only by authorised staff (doctor:update) or from catalog evidence
    in the doctor's approved profile; never inferred from free text alone."""

    __tablename__ = "doctor_specializations"
    __table_args__ = (Index("ix_doctor_specializations_specialization_id", "specialization_id"),)

    doctor_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("doctors.id", ondelete="CASCADE"), primary_key=True)
    specialization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("specializations.id", ondelete="RESTRICT"), primary_key=True
    )


class MedicalTopic(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "medical_topics"
    __table_args__ = (CheckConstraint("topic_type IN ('disease', 'condition', 'symptom')", name="topic_type_known"),)

    canonical_name: Mapped[str] = mapped_column(String(150), unique=True)
    slug: Mapped[str] = mapped_column(String(150), unique=True)
    topic_type: Mapped[str] = mapped_column(String(20))
    aliases: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    # Can be an emergency ("chest pain", "stroke"): the assistant points to
    # emergency care first and does not offer routine booking alone.
    urgent: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class MedicalTopicSpecialization(Base):
    __tablename__ = "medical_topic_specializations"
    __table_args__ = (
        CheckConstraint("relevance IN ('primary', 'secondary')", name="relevance_known"),
        CheckConstraint("review_status IN ('curated', 'reviewed')", name="review_status_known"),
        Index("ix_medical_topic_specializations_specialization_id", "specialization_id"),
    )

    topic_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("medical_topics.id", ondelete="CASCADE"), primary_key=True)
    specialization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("specializations.id", ondelete="CASCADE"), primary_key=True
    )
    relevance: Mapped[str] = mapped_column(String(10), default="primary")
    review_status: Mapped[str] = mapped_column(String(10), default="curated", server_default="curated")
    # Where the link came from ("catalog v1"), and who reviewed it, when.
    source: Mapped[str | None] = mapped_column(String(100))
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
