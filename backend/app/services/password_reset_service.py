"""Forgot password: a one-time link by email (D126).

* ``request_reset`` always gives the caller the same answer. For an active
  account it stores the SHA-256 of a new 256-bit token (replacing any unused
  one) and returns the email to send; the endpoint sends it after the response,
  so the response time does not reveal whether the account exists either.
  Links per account are bounded in the database (RESEND_SECONDS apart, at most
  PER_HOUR an hour), which holds across API processes.
* An account that signs in only with Google (D123) gets an email saying so,
  not a link: its password is set after signing in with Google.
* ``reset_password`` uses a token up with one conditional UPDATE, so two
  submissions of one link cannot both succeed. It sets the password, deletes
  the user's other links, ends every session (refresh tokens now, access
  tokens through ``users.password_changed_at``) and does not sign anyone in.

The link is sent at once, not through the email outbox: the outbox would have
to store it, and with it a working credential, in plain text (as for
invitations, D87). Neither the token nor a password is ever logged.
"""

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
    TokenState.invalid: "This password reset link is not valid. Request a new one.",
    TokenState.expired: "This password reset link has expired. Request a new one.",
    TokenState.used: "This password reset link has already been used. Request a new one if you still need it.",
}


def _refused(state: TokenState) -> BusinessRuleError:
    return BusinessRuleError(_MESSAGES[state], code=state.value)


def reset_link(raw_token: str) -> str:
    # In the fragment: browsers never send it to a server or in a Referer header,
    # so it stays out of Vercel, Render and proxy logs.
    return f"{settings.frontend_base_url}/reset-password#token={raw_token}"


@dataclass(frozen=True)
class PendingEmail:
    """An email to send once the response has gone out. ``expires_at``: do not send it after this."""

    email: email_service.Email
    expires_at: datetime | None = None


async def request_reset(db: AsyncSession, email: str, *, ip_address: str | None) -> PendingEmail | None:
    """None when nothing is to be sent (no such account, inactive, or over the limits). Commits."""
    # Row lock: concurrent requests for one account run one after the other, so
    # the limits below hold and the account ends up with exactly one live link.
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

    raw = secrets.token_urlsafe(32)  # 256 bits from the OS CSPRNG
    expires_at = now + timedelta(minutes=settings.password_reset_token_minutes)
    # Unused older links stop working; used and expired ones stay (they count towards the hourly limit).
    await db.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == user_id, PasswordResetToken.consumed_at.is_(None), PasswordResetToken.expires_at > now)
        .values(expires_at=now)
    )
    db.add(PasswordResetToken(
        user_id=user_id, token_hash=hash_token(raw), created_at=now, expires_at=expires_at, requested_ip=ip_address,
    ))
    await db.commit()
    logger.info("password_reset_requested", extra={"outcome": "link_created", "user_id": str(user_id)})
    rendered = email_templates.password_reset(reset_link(raw), settings.password_reset_token_minutes)
    return PendingEmail(
        email_service.Email(to=address, subject=rendered.subject, text=rendered.text, html=rendered.html),
        expires_at=expires_at,
    )


async def send(pending: PendingEmail) -> None:
    """Send a reset email (after the response). Failures are logged by class only, never with the link."""
    if pending.expires_at is not None and clock.utcnow() >= pending.expires_at:
        logger.warning("password_reset_email_skipped_expired")
        return
    delivery = await email_service.send(pending.email)
    if delivery not in (email_service.Delivery.sent, email_service.Delivery.outbox):
        logger.warning("password_reset_email_not_sent", extra={"delivery": delivery.value})


async def _state_of(db: AsyncSession, token_hash: str) -> TokenState:
    row = await db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash))
    if row is None:
        return TokenState.invalid
    if row.consumed_at is not None:
        return TokenState.used
    return TokenState.expired


async def check(db: AsyncSession, raw_token: str) -> None:
    """Raise unless the link can still be used (lets the page explain before a password is typed)."""
    token_hash = hash_token(raw_token)
    row = await db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash))
    if row is None or row.consumed_at is not None or row.expires_at <= clock.utcnow():
        raise _refused(await _state_of(db, token_hash))
    user = await db.get(User, row.user_id)
    if user is None or not user.is_active:
        raise _refused(TokenState.invalid)


async def reset_password(db: AsyncSession, raw_token: str, new_password: str, *, ip_address: str | None) -> None:
    """Set a new password from an emailed link. Ends every session; nobody is signed in. Commits."""
    token_hash = hash_token(raw_token)
    now = clock.utcnow()
    # Atomic: of two submissions of one link, exactly one gets a row back.
    user_id: uuid.UUID | None = await db.scalar(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.token_hash == token_hash,
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
        await db.rollback()  # the link stays unused; it cannot help an inactive account anyway
        raise _refused(TokenState.invalid)

    user.password_hash = hash_password(new_password)
    user.password_changed_at = now
    await db.execute(
        delete(PasswordResetToken).where(
            PasswordResetToken.user_id == user.id, PasswordResetToken.consumed_at.is_(None)
        )
    )
    await auth_service.revoke_all_sessions(db, user.id)
    audit_service.record(
        db, AuditAction.user_password_reset, actor_id=user.id, target_type="user", target_id=user.id,
        ip_address=ip_address, details={"verified_with": "email_link"},
    )
    await db.commit()
    logger.info("password_reset_completed", extra={"user_id": str(user.id)})
