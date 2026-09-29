"""Registration, login, token refresh and logout.

Stage 1 moves the existing behaviour out of the routes unchanged, except that
self-registration can no longer choose a role. Refresh-token hashing, rotation
and reuse detection arrive with the Stage 2 authentication hardening.
"""

import logging
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.core.config import settings
from app.core.exceptions import AuthenticationError, ConflictError, PermissionDeniedError
from app.core.security import create_access_token, generate_refresh_token, hash_password, verify_password
from app.models.refresh_token import RefreshToken
from app.models.user import User, UserRole
from app.schemas.user import UserCreate

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str


def _access_token_for(user: User) -> str:
    return create_access_token(data={"sub": str(user.id), "role": user.role.value})


async def register_patient(db: AsyncSession, data: UserCreate) -> User:
    """Self-registration. Always creates a patient; staff accounts are created by an admin."""
    existing = await db.scalar(select(User.id).where(User.email == data.email))
    if existing is not None:
        raise ConflictError("Email already registered", code="EMAIL_TAKEN")

    user = User(
        name=data.name,
        email=data.email,
        password_hash=hash_password(data.password),
        role=UserRole.patient,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    logger.info("user_registered", extra={"user_id": user.id})
    return user


async def login(db: AsyncSession, email: str, password: str) -> TokenPair:
    user = await db.scalar(select(User).where(User.email == email))

    if user is None or not verify_password(password, user.password_hash):
        logger.info("login_failed")
        raise AuthenticationError("Incorrect email or password", code="INVALID_CREDENTIALS")

    if not user.is_active:
        logger.info("login_rejected_inactive", extra={"user_id": user.id})
        raise PermissionDeniedError("Account is inactive", code="ACCOUNT_INACTIVE")

    refresh_token = generate_refresh_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            token=refresh_token,
            expires_at=utcnow() + timedelta(days=settings.refresh_token_expire_days),
        )
    )
    await db.commit()
    logger.info("login_succeeded", extra={"user_id": user.id})
    return TokenPair(access_token=_access_token_for(user), refresh_token=refresh_token)


async def refresh_access_token(db: AsyncSession, refresh_token: str) -> str:
    stored = await db.scalar(select(RefreshToken).where(RefreshToken.token == refresh_token))

    if stored is None or stored.revoked:
        raise AuthenticationError("Invalid refresh token", code="INVALID_REFRESH_TOKEN")

    if stored.expires_at < utcnow():
        raise AuthenticationError("Refresh token expired", code="REFRESH_TOKEN_EXPIRED")

    user = await db.get(User, stored.user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("User not found or inactive", code="INVALID_REFRESH_TOKEN")

    return _access_token_for(user)


async def logout(db: AsyncSession, refresh_token: str) -> None:
    stored = await db.scalar(select(RefreshToken).where(RefreshToken.token == refresh_token))
    if stored is not None and not stored.revoked:
        stored.revoked = True
        await db.commit()
        logger.info("logout", extra={"user_id": stored.user_id})
