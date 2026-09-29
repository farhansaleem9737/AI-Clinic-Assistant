from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Department(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "departments"

    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(String(500))
    # IANA name. Recurring schedules of this department's doctors are expanded
    # in this timezone.
    timezone: Mapped[str] = mapped_column(String(64))
    # Retired, never deleted: doctors and appointments reference it.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
