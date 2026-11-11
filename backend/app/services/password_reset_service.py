"""Forgot password: a 6-digit code by email, then a new password (D126, D127).

    request_reset(email) ── emails a code ──▶ verify_code(email, code) ── reset token ──▶ reset_password(token, password)

* ``request_reset`` always gives the caller the same answer. For an active
  account it stores the HMAC of a new random 6-digit code (expiring any unused
  earlier one) and returns the email to send; the endpoint sends it after the
  response, so the response time does not reveal whether the account exists.
  Codes per account are bounded in the database (RESEND_SECONDS apart, at most
  PER_HOUR an hour), which holds across API processes.
* An account that signs in only with Google (D123) gets an email saying so,
  not a code: its password is set after signing in with Google.
* ``verify_code`` checks the code under a row lock, so concurrent guesses are
  counted one by one; after CODE_MAX_ATTEMPTS wrong ones, or CODE_MINUTES, the
  code stops working. The right code is used up at once and exchanged for a
  256-bit reset token, valid TOKEN_MINUTES, that can only set a password: it
  is not a sign-in token. Every refusal reads the same, whether the address
  has an account or not.
* ``reset_password`` uses the token up with one conditional UPDATE, so two
  submissions cannot both succeed. It sets the password (hashed as
  everywhere else), expires the user's other codes, ends every session
  (refresh tokens now, access tokens through ``users.password_changed_at``)
  and commits; nobody is signed in.

Codes are sent at once, not through the email outbox, which would store them
in plain text (as for invitations, D87). Codes, tokens and passwords are never
logged or returned.
"""

import hashlib
import hmac
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.config import settings
from app.core.exceptions import BusinessRuleError
from app.core.security import hash_password, hash_token
from app.models.password_reset import PasswordResetToken
from app.models.user import User
from app.services import audit_service, auth_service, email_service, email_templates
from app.services.audit_service import AuditAction

logger = logging.getLogger(__name__)


class TokenState(StrEnum):
    invalid = "RESET_TOKEN_INVALID"
    expired = "RESET_TOKEN_EXPIRED"
    used = "RESET_TOKEN_USED"


_MESSAGES = {
    TokenState.invalid: "This password reset is not valid. Request a new code.",
    TokenState.expired: "This password reset has expired. Request a new code.",
    TokenState.used: "This password reset was already completed. Request a new code if you still need it.",
}
CODE_REFUSED = "RESET_CODE_INVALID"
CODE_MESSAGE = "That code is incorrect or has expired. Check the email, or request a new code."


def _refused(state: TokenState) -> BusinessRuleError:
    return BusinessRuleError(_MESSAGES[state], code=state.value)


def _code_hash(row_id: uuid.UUID, code: str) -> str:
    # Keyed and bound to its row: a database copy alone cannot test the 10^6 codes.
    return hmac.new(settings.secret_key.encode(), f"password-reset:{row_id}:{code}".encode(), hashlib.sha256).hexdigest()


def new_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"  # the OS CSPRNG


@dataclass(frozen=True)
class PendingEmail:
    """An email to send once the response has gone out. ``expires_at``: do not send it after this."""

    email: email_service.Email
    expires_at: datetime | None = None


@dataclass(frozen=True)
class ResetGrant:
    token: str
    expires_at: datetime


async def request_reset(db: AsyncSession, email: str, *, ip_address: str | None) -> PendingEmail | None:
    """None when nothing is to be sent (no such account, inactive, or over the limits). Commits."""
    # Row lock: concurrent requests for one account run one after the other, so
    # the limits below hold and the account ends up with exactly one live code.
    user = await db.scalar(select(User).where(User.email == email).with_for_update())
    if user is None or not user.is_active:
        logger.info("password_reset_requested", extra={"outcome": "no_eligible_account"})
        return None
    # Read before any rollback below expires the loaded row.
    user_id, address, has_password = user.id, user.email, user.password_hash is not None
    now = clock.utcnow()
    recent = (
        await db.execute(
            select(func.count(), func.max(PasswordResetToken.created_at)).where(
                PasswordResetToken.user_id == user_id, PasswordResetToken.created_at > now - timedelta(hours=1)
            )
        )
    ).one()
    count, latest = recent
    if count >= settings.password_reset_max_per_hour or (
        latest is not None and now - latest < timedelta(seconds=settings.password_reset_resend_seconds)
    ):
        await db.rollback()
        logger.info("password_reset_requested", extra={"outcome": "throttled", "user_id": str(user_id)})
        return None

    if not has_password:
        # Google-only account: nothing to reset. Tell the owner how to sign in.
        await db.rollback()
        logger.info("password_reset_requested", extra={"outcome": "google_only", "user_id": str(user_id)})
        rendered = email_templates.password_reset_google_only()
        return PendingEmail(email_service.Email(to=address, subject=rendered.subject, text=rendered.text, html=rendered.html))

    code = new_code()
    row_id = uuid.uuid7()
    expires_at = now + timedelta(minutes=settings.password_reset_code_minutes)
    # The new code replaces every unused one (and any verified, unused reset token).
    await db.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == user_id, PasswordResetToken.consumed_at.is_(None), PasswordResetToken.expires_at > now)
        .values(expires_at=now)
    )
    db.add(PasswordResetToken(
        id=row_id, user_id=user_id, code_hash=_code_hash(row_id, code), attempts=0, created_at=now,
        expires_at=expires_at, requested_ip=ip_address,
    ))
    await db.commit()
    logger.info("password_reset_requested", extra={"outcome": "code_created", "user_id": str(user_id)})
    rendered = email_templates.password_reset_code(code, settings.password_reset_code_minutes)
    return PendingEmail(
        email_service.Email(to=address, subject=rendered.subject, text=rendered.text, html=rendered.html),
        expires_at=expires_at,
    )


async def send(pending: PendingEmail) -> None:
    """Send a reset email (after the response). Failures are logged by class only, never with the code."""
    if pending.expires_at is not None and clock.utcnow() >= pending.expires_at:
        logger.warning("password_reset_email_skipped_expired")
        return
    delivery = await email_service.send(pending.email)
    if delivery not in (email_service.Delivery.sent, email_service.Delivery.outbox):
        logger.warning("password_reset_email_not_sent", extra={"delivery": delivery.value})


async def verify_code(db: AsyncSession, email: str, code: str) -> ResetGrant:
    """Exchange the emailed code for a reset token (not a sign-in). Commits, also on a wrong guess."""
    refused = BusinessRuleError(CODE_MESSAGE, code=CODE_REFUSED)
    now = clock.utcnow()
    # The newest live, unverified code of an active account, locked: guesses are counted one at a time.
    row = await db.scalar(
        select(PasswordResetToken)
        .join(User, User.id == PasswordResetToken.user_id)
        .where(
            User.email == email,
            User.is_active.is_(True),
            PasswordResetToken.code_hash.is_not(None),
            PasswordResetToken.verified_at.is_(None),
            PasswordResetToken.consumed_at.is_(None),
            PasswordResetToken.expires_at > now,
        )
        .order_by(PasswordResetToken.created_at.desc())
        .limit(1)
        .with_for_update(of=PasswordResetToken)
    )
    if row is None:
        hmac.compare_digest(_code_hash(uuid.uuid7(), code), "0" * 64)  # about the same work as a real check
        await db.rollback()
        raise refused
    if row.attempts >= settings.password_reset_code_max_attempts:
        await db.rollback()
        raise refused
    if not hmac.compare_digest(_code_hash(row.id, code), row.code_hash):
        row.attempts += 1
        if row.attempts >= settings.password_reset_code_max_attempts:
            row.expires_at = now  # used up: a new code is needed
        user_id = row.user_id
        await db.commit()
        logger.info("password_reset_code_rejected", extra={"user_id": str(user_id)})
        raise refused

    raw = secrets.token_urlsafe(32)  # 256 bits
    expires_at = now + timedelta(minutes=settings.password_reset_token_minutes)
    row.verified_at = now
    row.token_hash = hash_token(raw)
    row.expires_at = expires_at
    user_id = row.user_id
    await db.commit()
    logger.info("password_reset_code_verified", extra={"user_id": str(user_id)})
    return ResetGrant(token=raw, expires_at=expires_at)


async def _state_of(db: AsyncSession, token_hash: str) -> TokenState:
    row = await db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash))
    if row is None:
        return TokenState.invalid
    if row.consumed_at is not None:
        return TokenState.used
    return TokenState.expired


async def reset_password(db: AsyncSession, raw_token: str, new_password: str, *, ip_address: str | None) -> None:
    """Set a new password with a reset token from ``verify_code``. Ends every session; nobody is signed in. Commits."""
    token_hash = hash_token(raw_token)
    now = clock.utcnow()
    # Atomic: of two submissions of one token, exactly one gets a row back.
    # Only tokens earned with a verified code count (D127): old emailed links no longer work.
    user_id: uuid.UUID | None = await db.scalar(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.verified_at.is_not(None),
            PasswordResetToken.consumed_at.is_(None),
            PasswordResetToken.expires_at > now,
        )
        .values(consumed_at=now)
        .returning(PasswordResetToken.user_id)
    )
    if user_id is None:
        state = await _state_of(db, token_hash)
        await db.rollback()
        raise _refused(state)
    user = await db.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None or not user.is_active:
        await db.rollback()  # the token stays unused; it cannot help an inactive account anyway
        raise _refused(TokenState.invalid)

    user.password_hash = hash_password(new_password)
    user.password_changed_at = now
    # Every other unused code or token of this account stops working.
    await db.execute(
        delete(PasswordResetToken).where(
            PasswordResetToken.user_id == user.id, PasswordResetToken.consumed_at.is_(None)
        )
    )
    await auth_service.revoke_all_sessions(db, user.id)
    audit_service.record(
        db, AuditAction.user_password_reset, actor_id=user.id, target_type="user", target_id=user.id,
        ip_address=ip_address, details={"verified_with": "email_code"},
    )
    await db.commit()
    logger.info("password_reset_completed", extra={"user_id": str(user.id)})
