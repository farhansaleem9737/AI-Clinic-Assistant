import uuid
from datetime import datetime

from sqlalchemy import DateTime, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow


class UUIDPrimaryKeyMixin:
    """UUIDv7 primary key: not guessable like a sequence, but time-ordered so
    B-tree inserts stay local. Generated in Python (``uuid.uuid7``, Python 3.14+)
    so the id is known before flush; the server default (PostgreSQL 18
    ``uuidv7()``) covers rows inserted by raw SQL and migrations."""

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid7, server_default=text("uuidv7()")
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
