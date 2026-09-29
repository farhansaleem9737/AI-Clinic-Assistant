import uuid

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthenticationError, PermissionDeniedError
from app.core.permissions import Perm, Principal
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.user import User
from app.services import rbac_service

# HTTPBearer (not OAuth2PasswordBearer): /auth/login takes a JSON body, so the
# OAuth2 password-form flow would make Swagger's Authorize button fail.
# auto_error=False turns a missing header into our 401 instead of a bare 403.
bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> Principal:
    invalid = AuthenticationError("Could not validate credentials")
    if credentials is None:
        raise invalid

    try:
        claims = decode_access_token(credentials.credentials)
        user_id = uuid.UUID(claims["sub"])
    except (JWTError, KeyError, TypeError, ValueError):
        raise invalid

    user = await db.get(User, user_id)
    # A deactivated account loses access immediately, not when its token expires.
    if user is None or not user.is_active:
        raise invalid

    return await rbac_service.load_principal(db, user)


def require_permission(*perms: Perm):
    """Layer 1 of authorization: may this *kind* of caller do this *kind* of
    thing? Whether they may touch a particular row is the service's decision."""

    async def checker(principal: Principal = Depends(get_current_principal)) -> Principal:
        if not principal.has(*perms):
            raise PermissionDeniedError("You do not have permission to perform this action")
        return principal

    return checker
