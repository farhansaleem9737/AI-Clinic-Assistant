import uuid
from datetime import datetime

from sqlalchemy import CHAR, DateTime, ForeignKey, Uuid
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.db.base import Base
from app.db.mixins import UUIDPrimaryKeyMixin


class PasswordResetToken(UUIDPrimaryKeyMixin, Base):
    """A one-time "reset your password" link sent by email (D126).

    Only the SHA-256 of the 256-bit token is stored; the raw value exists in the
    email alone. A token works once (``consumed_at``) and only until
    ``expires_at``. Asking for a new link expires the user's unused ones, so at
    most one link works at a time. Old rows stay (they count towards the hourly
    limit) and go with the user (ON DELETE CASCADE).
    """

    __tablename__ = "password_reset_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(CHAR(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_ip: Mapped[str | None] = mapped_column(INET)
