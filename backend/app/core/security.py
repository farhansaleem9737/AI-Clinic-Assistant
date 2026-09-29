import hashlib
import secrets
import uuid
from collections.abc import Iterable
from datetime import timedelta

from jose import jwt
from passlib.context import CryptContext

from app.core.clock import utcnow
from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Verified against when the email is unknown, so a failed login takes the same
# time whether or not the account exists (no user enumeration by timing).
_DUMMY_HASH = pwd_context.hash(secrets.token_urlsafe(16))


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str | None) -> bool:
    if hashed_password is None:
        pwd_context.verify(plain_password, _DUMMY_HASH)
        return False
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(user_id: uuid.UUID, roles: Iterable[str]) -> str:
    """Short-lived JWT. Carries role codes for the frontend's menus only; the
    backend resolves permissions from the database on every request."""
    now = utcnow()
    claims = {
        "sub": str(user_id),
        "roles": sorted(roles),
        "type": "access",
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(claims, settings.secret_key, algorithm=settings.algorithm)


def decode_access_token(token: str) -> dict:
    """Raises ``jose.JWTError`` if the token is invalid or expired."""
    claims = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    if claims.get("type") != "access":
        raise jwt.JWTError("Not an access token")
    return claims


def generate_refresh_token() -> str:
    # Opaque random string, not a JWT: it only means something to our database.
    return secrets.token_urlsafe(32)


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(raw: str) -> str:
    """SHA-256 is right here (not bcrypt): the input is 256 random bits, so
    there is nothing to brute-force, and lookups must be by exact hash."""
    return hashlib.sha256(raw.encode()).hexdigest()
