from sqlalchemy import Boolean, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Department(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "departments"

    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    # Catalog key (D118), e.g. "cardiology"; set when the department is the
    # catalog's entry (created by it, or matched by name or alias). NULL for
    # clinic-specific departments outside the catalog.
    slug: Mapped[str | None] = mapped_column(String(120), unique=True)
    # Other names people use ("ENT", "Otolaryngology"), lower case.
    aliases: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    description: Mapped[str | None] = mapped_column(String(500))
    # IANA name. Recurring schedules of this department's doctors are expanded
    # in this timezone.
    timezone: Mapped[str] = mapped_column(String(64))
    # Retired, never deleted: doctors and appointments reference it.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Display only (D89): an icon key and colour key from a fixed list
    # (schemas/department.py). NULL = chosen from the name in the UI.
    icon: Mapped[str | None] = mapped_column(String(30))
    color: Mapped[str | None] = mapped_column(String(20))
