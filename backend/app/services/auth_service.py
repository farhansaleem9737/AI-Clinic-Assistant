"""Registration, login, refresh-token rotation and logout.

Refresh tokens form *families*: login starts one, each refresh revokes the
presented token and issues its successor in the same family. If a token that
was already rotated is presented again, someone kept a copy, so the entire
family is revoked (architecture §4, D7).
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.config import settings
from app.core.exceptions import AuthenticationError, ConflictError, PermissionDeniedError
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.services import rbac_service

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClientInfo:
    user_agent: str | None = None
    ip_address: str | None = None


@dataclass(frozen=True)
class SessionTokens:
    access_token: str
    # None when no new refresh token was issued (see the reuse grace period).
    refresh_token: str | None
    # Whether the session cookie should outlive the browser ("Remember me").
    persistent: bool = False


async def create_user(db: AsyncSession, *, name: str, email: str, password: str) -> User:
    """Create a login identity. Does not commit or grant roles."""
    if await db.scalar(select(User.id).where(User.email == email)) is not None:
        raise ConflictError("Email already registered", code="EMAIL_TAKEN")
    user = User(name=name, email=email, password_hash=hash_password(password))
    db.add(user)
    await db.flush()
    return user


async def _issue_refresh_token(
    db: AsyncSession, user_id: uuid.UUID, family_id: uuid.UUID, client: ClientInfo, *, persistent: bool
) -> tuple[RefreshToken, str]:
    raw = generate_refresh_token()
    lifetime = (
        timedelta(days=settings.refresh_token_expire_days)
        if persistent
        else timedelta(hours=settings.session_token_expire_hours)
    )
    token = RefreshToken(
        user_id=user_id,
        family_id=family_id,
        token_hash=hash_token(raw),
        persistent=persistent,
        expires_at=clock.utcnow() + lifetime,
        user_agent=(client.user_agent or "")[:255] or None,
        ip_address=client.ip_address,
    )
    db.add(token)
    await db.flush()
    return token, raw


async def _access_token_for(db: AsyncSession, user: User) -> str:
    return create_access_token(user.id, await rbac_service.role_codes_for(db, user.id))


async def login(
    db: AsyncSession, email: str, password: str, client: ClientInfo, *, remember_me: bool = False
) -> SessionTokens:
    user = await db.scalar(select(User).where(User.email == email))

    # Same error, and (via the dummy hash) the same timing, for an unknown
    # email and a wrong password: the hash check always runs.
    password_ok = verify_password(password, user.password_hash if user else None)
    if user is None or not password_ok:
        logger.info("login_failed")
        raise AuthenticationError("Incorrect email or password", code="INVALID_CREDENTIALS")

    if not user.is_active:
        logger.info("login_rejected_inactive", extra={"user_id": str(user.id)})
        raise PermissionDeniedError("Account is inactive", code="ACCOUNT_INACTIVE")

    _, raw = await _issue_refresh_token(db, user.id, uuid.uuid7(), client, persistent=remember_me)
    access = await _access_token_for(db, user)
    await db.commit()
    logger.info("login_succeeded", extra={"user_id": str(user.id)})
    return SessionTokens(access_token=access, refresh_token=raw, persistent=remember_me)


async def _revoke_family(db: AsyncSession, family_id: uuid.UUID) -> None:
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=clock.utcnow())
    )


async def refresh(db: AsyncSession, raw_token: str, client: ClientInfo) -> SessionTokens:
    invalid = AuthenticationError("Invalid refresh token", code="INVALID_REFRESH_TOKEN")
    now = clock.utcnow()

    # Row lock: two concurrent refreshes of one token are serialized, so the
    # second sees the first one's rotation instead of racing it.
    stored = await db.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw_token)).with_for_update()
    )
    if stored is None:
        raise invalid

    if stored.revoked_at is not None:
        rotated = stored.replaced_by_id is not None
        if rotated and now - stored.revoked_at <= timedelta(seconds=settings.refresh_reuse_grace_seconds):
            # Benign race (e.g. two tabs refreshing at once): the browser
            # already holds the successor cookie, so hand out an access token
            # and leave the cookie alone.
            user = await db.get(User, stored.user_id)
            if user is None or not user.is_active:
                raise invalid
            return SessionTokens(access_token=await _access_token_for(db, user), refresh_token=None)
        if rotated:
            await _revoke_family(db, stored.family_id)
            await db.commit()
            logger.warning(
                "refresh_token_reuse_detected",
                extra={"user_id": str(stored.user_id), "family_id": str(stored.family_id)},
            )
        raise invalid

    if stored.expires_at <= now:
        raise AuthenticationError("Refresh token expired", code="REFRESH_TOKEN_EXPIRED")

    user = await db.get(User, stored.user_id)
    if user is None or not user.is_active:
        await _revoke_family(db, stored.family_id)
        await db.commit()
        raise invalid

    successor, raw = await _issue_refresh_token(db, user.id, stored.family_id, client, persistent=stored.persistent)
    stored.revoked_at = now
    stored.replaced_by_id = successor.id
    access = await _access_token_for(db, user)
    await db.commit()
    return SessionTokens(access_token=access, refresh_token=raw, persistent=stored.persistent)


async def logout(db: AsyncSession, raw_token: str | None) -> None:
    if not raw_token:
        return
    stored = await db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw_token)))
    if stored is not None:
        await _revoke_family(db, stored.family_id)
        await db.commit()
        logger.info("logout", extra={"user_id": str(stored.user_id)})


async def revoke_all_sessions(db: AsyncSession, user_id: uuid.UUID) -> None:
    """End every session of a user (deactivation, password reset). Does not commit."""
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=clock.utcnow())
    )
