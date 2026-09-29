import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Doctor(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "doctors"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    department_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("departments.id", ondelete="RESTRICT"))
    specialization: Mapped[str] = mapped_column(String(150))
    bio: Mapped[str | None] = mapped_column(String(1000))
    years_of_experience: Mapped[int] = mapped_column(Integer, default=0)
    consultation_fee: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
