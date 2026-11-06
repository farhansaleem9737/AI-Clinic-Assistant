from datetime import datetime

from sqlalchemy import DateTime, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.db.base import Base
from app.db.mixins import UUIDPrimaryKeyMixin


class EmailVerificationCode(UUIDPrimaryKeyMixin, Base):
    """A one-time code emailed to an address before an account is created on it.

    Only an HMAC of the code is stored. A code is single use, expires after
    EMAIL_VERIFICATION_CODE_MINUTES and stops working after
    EMAIL_VERIFICATION_MAX_ATTEMPTS wrong guesses. Sending a new code replaces
    the old one, so an address has at most one live code.
    """

    __tablename__ = "email_verification_codes"

    email: Mapped[str] = mapped_column(String(255), unique=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
