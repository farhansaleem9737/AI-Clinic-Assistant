from fastapi import Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.user import User, UserRole
from app.core.config import settings
from app.core.exceptions import AuthenticationError, PermissionDeniedError

# /auth/login takes a JSON body ({email, password}), not an OAuth2 password-flow
# form ({username, password}), so declaring OAuth2PasswordBearer made Swagger's
# Authorize button post the wrong content type and fail with 422.
# HTTPBearer describes what this API actually accepts: a bearer token header.
# auto_error=False lets a missing header fall through to the 401 below instead of
# HTTPBearer's default 403.
oauth2_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    invalid = AuthenticationError("Could not validate credentials")

    if credentials is None:
        raise invalid

    try:
        payload = jwt.decode(credentials.credentials, settings.secret_key, algorithms=[settings.algorithm])
        user_id = int(payload["sub"])
    except (JWTError, KeyError, TypeError, ValueError):
        raise invalid

    user = await db.get(User, user_id)
    if user is None:
        raise invalid

    return user


def require_role(*allowed_roles: UserRole):
    async def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise PermissionDeniedError("You do not have permission to perform this action")
        return current_user
    return role_checker
