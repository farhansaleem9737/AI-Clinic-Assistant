import uuid
from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


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
    bio: Mapped[str | None] = mapped_column(String(1000))
    years_of_experience: Mapped[int] = mapped_column(Integer, default=0)
    consultation_fee: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    # Internal contact details: never part of the public directory.
    phone: Mapped[str | None] = mapped_column(String(30))
    room_number: Mapped[str | None] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
