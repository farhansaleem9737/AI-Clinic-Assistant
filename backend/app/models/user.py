from datetime import date

from sqlalchemy import Boolean, Date, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Authentication identity only. Roles live in ``user_roles``; domain data
    lives on profiles (Doctor, Patient)."""

    __tablename__ = "users"

    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    # Users are never deleted (audit and clinical records reference them).
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Personal details of doctors and staff, given at sign-up or by the admin
    # who creates the account. Patients keep theirs on the patient record.
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    gender: Mapped[str | None] = mapped_column(String(10))
