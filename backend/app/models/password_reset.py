import uuid
from datetime import datetime

from sqlalchemy import CHAR, DateTime, ForeignKey, SmallInteger, Uuid, text
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.db.base import Base
from app.db.mixins import UUIDPrimaryKeyMixin


class PasswordResetToken(UUIDPrimaryKeyMixin, Base):
    """One forgot-password attempt (D126, D127): an emailed 6-digit code, then a reset token.

    1. Requested: ``code_hash`` holds the HMAC of the emailed code (never the
       code), ``expires_at`` is the code's deadline, ``token_hash`` is empty.
    2. Verified (the right code, within ``attempts`` limit): ``verified_at`` is
       set, ``token_hash`` holds the SHA-256 of a new 256-bit reset token that
       only the browser has, and ``expires_at`` becomes that token's deadline.
    3. Used: ``consumed_at``, set by the one UPDATE that changes the password.

    Asking for a new code expires the user's unused rows, so at most one works
    at a time. Old rows stay (they count towards the hourly limit) and go with
    the user (ON DELETE CASCADE).
    """

    __tablename__ = "password_reset_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str | None] = mapped_column(CHAR(64), unique=True)
    code_hash: Mapped[str | None] = mapped_column(CHAR(64))
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_ip: Mapped[str | None] = mapped_column(INET)
