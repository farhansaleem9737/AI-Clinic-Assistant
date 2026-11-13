import dataclasses
import uuid

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthenticationError, PermissionDeniedError
from app.core.permissions import DELEGATED_PERMS, Perm, Principal
from app.core.security import decode_access_token
from app.db.session import get_db
from app.services import rbac_service

# HTTPBearer (not OAuth2PasswordBearer): /auth/login takes a JSON body, so the
# OAuth2 password-form flow would make Swagger's Authorize button fail.
# auto_error=False turns a missing header into our 401 instead of a bare 403.
bearer_scheme = HTTPBearer(auto_error=False)


# A doctor_receptionist names the doctor they are working for on each request (D131).
ACTING_DOCTOR_HEADER = "X-Acting-Doctor-Id"


async def get_current_principal(
    request: Request,
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

    principal = await rbac_service.load_principal_by_id(db, user_id)
    # A deactivated account loses access immediately, not when its token expires.
    if principal is None or not principal.user.is_active:
        raise invalid
    # So does a token issued before the password was last reset or changed (D126).
    # `iat` has whole seconds, so compare in whole seconds: a token issued in the
    # same second as the change (the changing browser's own new one) still works.
    changed = principal.user.password_changed_at
    if changed is not None and int(claims.get("iat", 0)) < int(changed.timestamp()):
        raise invalid
    acting_for = request.headers.get(ACTING_DOCTOR_HEADER)
    if acting_for:
        principal = await _with_delegation(db, principal, acting_for)
    return principal


async def _with_delegation(db: AsyncSession, principal: Principal, acting_for: str) -> Principal:
    """The caller's rights for this request while working for one doctor (D131):
    their role's own permissions plus what that doctor's ACTIVE assignment lends,
    read from the database now (never from the token or the client). One answer
    for "no such doctor", "not assigned", "suspended" and "revoked"."""
    from app.services import receptionist_service

    try:
        doctor_id = uuid.UUID(acting_for)
    except ValueError:
        doctor_id = None
    delegation = (
        await receptionist_service.active_delegation(db, principal, doctor_id) if doctor_id is not None else None
    )
    if delegation is None:
        raise PermissionDeniedError("You are not working for this doctor", code="NOT_ASSIGNED_TO_DOCTOR")
    lent = {perm for p in delegation.permissions for perm in DELEGATED_PERMS[p]}
    return dataclasses.replace(principal, permissions=principal.permissions | lent, delegation=delegation)


def require_permission(*perms: Perm):
    """Layer 1 of authorization: may this *kind* of caller do this *kind* of
    thing? Whether they may touch a particular row is the service's decision."""

    async def checker(principal: Principal = Depends(get_current_principal)) -> Principal:
        if not principal.has(*perms):
            raise PermissionDeniedError("You do not have permission to perform this action")
        return principal

    return checker


def require_any_permission(*perms: Perm):
    """Like require_permission, but one of the listed permissions suffices.
    Used where different roles reach the same endpoint with different scopes
    (e.g. a patient reading their own record vs. reception reading any)."""

    async def checker(principal: Principal = Depends(get_current_principal)) -> Principal:
        if not principal.has_any(*perms):
            raise PermissionDeniedError("You do not have permission to perform this action")
        return principal

    return checker
