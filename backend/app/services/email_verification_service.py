"""One-time codes that prove a registering user owns their email address.

``send_code`` emails six digits and stores only their HMAC; ``consume`` checks
the code during registration and deletes it in the registration's own
transaction, so a code can create at most one account. Wrong guesses are
counted (and committed on their own), and a code stops working after
EMAIL_VERIFICATION_MAX_ATTEMPTS of them or EMAIL_VERIFICATION_CODE_MINUTES.

The code is emailed at once rather than queued: the outbox would have to
store it in plain text (the same reason invitations are sent at once, D87).
"""

import hashlib
import hmac
import logging
import secrets
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.config import settings
from app.core.exceptions import BusinessRuleError, ConflictError, EmailUnavailableError, RateLimitedError
from app.models.email_verification import EmailVerificationCode
from app.models.user import User
from app.services import email_service

logger = logging.getLogger(__name__)


def _hash(email: str, code: str) -> str:
    return hmac.new(settings.secret_key.encode(), f"{email}:{code}".encode(), hashlib.sha256).hexdigest()


def _email(to: str, code: str) -> email_service.Email:
    minutes = settings.email_verification_code_minutes
    text = (
        f"Your Clinic AI Assistant verification code is {code}.\n\n"
        f"Enter it on the Create account page within {minutes} minutes. "
        "If you did not try to create an account, you can ignore this email."
    )
    html = (
        '<div style="font-family:Arial,sans-serif;color:#172b4d;max-width:480px">'
        "<p>Use this code to verify your email address and create your Clinic AI Assistant account:</p>"
        f'<p style="font-size:28px;font-weight:700;letter-spacing:6px;color:#1677ff">{code}</p>'
        f"<p>It expires in {minutes} minutes. If you did not try to create an account, you can ignore this email.</p>"
        "</div>"
    )
    return email_service.Email(to=to, subject=f"{code} is your Clinic AI Assistant verification code", text=text, html=html)


async def send_code(db: AsyncSession, email: str) -> None:
    """Email a new code to an address that has no account yet."""
    if await db.scalar(select(User.id).where(User.email == email)) is not None:
        raise ConflictError("Email already registered", code="EMAIL_TAKEN")
    now = clock.utcnow()
    current = await db.scalar(select(EmailVerificationCode).where(EmailVerificationCode.email == email))
    if current is not None:
        wait = current.created_at + timedelta(seconds=settings.email_verification_resend_seconds) - now
        if wait.total_seconds() > 0:
            raise RateLimitedError(
                "A code was sent moments ago. Please wait before asking for another.",
                code="CODE_RECENTLY_SENT",
                details={"retry_after_seconds": int(wait.total_seconds()) + 1},
            )
        await db.delete(current)
        await db.flush()

    code = f"{secrets.randbelow(1_000_000):06d}"
    db.add(
        EmailVerificationCode(
            email=email,
            code_hash=_hash(email, code),
            attempts=0,
            created_at=now,
            expires_at=now + timedelta(minutes=settings.email_verification_code_minutes),
        )
    )
    await db.commit()
    delivery = await email_service.send(_email(email, code))
    if delivery not in (email_service.Delivery.sent, email_service.Delivery.outbox):
        # Let the user ask again straight away instead of waiting out the resend delay.
        await db.execute(delete(EmailVerificationCode).where(EmailVerificationCode.email == email))
        await db.commit()
        raise EmailUnavailableError("The verification code could not be sent. Please try again later.")
    logger.info("email_verification_code_sent")


async def consume(db: AsyncSession, email: str, code: str | None) -> None:
    """Check a code for registration and use it up (deleted when the caller commits)."""
    invalid = BusinessRuleError(
        "The verification code is incorrect or has expired. Request a new code.", code="INVALID_VERIFICATION_CODE"
    )
    if not code:
        raise BusinessRuleError("Enter the verification code sent to your email.", code="VERIFICATION_REQUIRED")
    row = await db.scalar(select(EmailVerificationCode).where(EmailVerificationCode.email == email).with_for_update())
    if row is None or row.expires_at <= clock.utcnow() or row.attempts >= settings.email_verification_max_attempts:
        raise invalid
    if not hmac.compare_digest(row.code_hash, _hash(email, code)):
        # Counted even though the registration fails: commit before raising.
        row.attempts += 1
        await db.commit()
        raise invalid
    await db.delete(row)
