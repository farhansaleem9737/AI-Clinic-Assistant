import uuid
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, Numeric, SmallInteger, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.stored_file import StoredFile


class Doctor(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Professional profile. Name and credentials live on User; schedules and
    appointments are separate tables that reference this one."""

    __tablename__ = "doctors"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), unique=True)
    department_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("departments.id", ondelete="RESTRICT"), index=True
    )
    title: Mapped[str | None] = mapped_column(String(20))
    specialization: Mapped[str] = mapped_column(String(150))
    license_number: Mapped[str | None] = mapped_column(String(50), unique=True)
    # Degrees and certifications as shown to patients, e.g. "MBBS, FCPS (Cardiology)".
    qualifications: Mapped[str | None] = mapped_column(String(500))
    bio: Mapped[str | None] = mapped_column(String(1000))
    # Languages the doctor consults in, as shown to patients, e.g. "English, Urdu".
    languages: Mapped[str | None] = mapped_column(String(200))
    years_of_experience: Mapped[int] = mapped_column(Integer, default=0)
    consultation_fee: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    # Internal contact details: never part of the public directory.
    phone: Mapped[str | None] = mapped_column(String(30))
    room_number: Mapped[str | None] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Profile photo in R2; NULL shows the initials/illustration avatar.
    photo_file_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("stored_files.id", ondelete="RESTRICT"), unique=True
    )

    # Joined into every load of the profile, so responses can sign the photo
    # URL without another query. (A future SELECT ... FOR UPDATE on this
    # table must use with_for_update(of=<Model>): PostgreSQL refuses to lock
    # the nullable side of an outer join.)
    photo: Mapped[StoredFile | None] = relationship(lazy="joined")




class DoctorExperience(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One position in a doctor's public career history."""

    __tablename__ = "doctor_experiences"
    __table_args__ = (
        CheckConstraint("start_year BETWEEN 1940 AND 2100", name="start_year_range"),
        CheckConstraint("end_year IS NULL OR end_year >= start_year", name="end_after_start"),
    )

    doctor_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("doctors.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(150))
    organization: Mapped[str] = mapped_column(String(200))
    location: Mapped[str | None] = mapped_column(String(150))
    start_year: Mapped[int] = mapped_column(SmallInteger)
    # NULL means the doctor still holds the position ("Present").
    end_year: Mapped[int | None] = mapped_column(SmallInteger)
    description: Mapped[str | None] = mapped_column(String(1000))


class DoctorEducation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One degree, fellowship or certification on a doctor's public profile."""

    __tablename__ = "doctor_education"
    __table_args__ = (
        CheckConstraint("start_year IS NULL OR start_year BETWEEN 1940 AND 2100", name="start_year_range"),
        CheckConstraint("end_year IS NULL OR end_year BETWEEN 1940 AND 2100", name="end_year_range"),
        CheckConstraint(
            "start_year IS NULL OR end_year IS NULL OR end_year >= start_year", name="end_after_start"
        ),
    )

    doctor_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("doctors.id", ondelete="CASCADE"), index=True)
    qualification: Mapped[str] = mapped_column(String(150))
    institution: Mapped[str] = mapped_column(String(200))
    field_of_study: Mapped[str | None] = mapped_column(String(150))
    start_year: Mapped[int | None] = mapped_column(SmallInteger)
    # Year of completion; NULL while still in progress or when not recorded.
    end_year: Mapped[int | None] = mapped_column(SmallInteger)
