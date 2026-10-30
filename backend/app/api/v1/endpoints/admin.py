"""Administrator management (D87): invitations, accepting them, and removing
the admin role. Granting the admin role has no endpoint of its own: only an
accepted invitation (or the command-line bootstrap) grants it."""

import uuid

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import get_current_principal, require_permission
from app.core.config import settings
from app.core.permissions import Perm, Principal
from app.core.rate_limit import rate_limit
from app.db.session import get_db
from app.schemas.admin import (
    AcceptExistingAccount,
    AcceptNewAccount,
    InvitationCreate,
    InvitationPreviewRead,
    InvitationRead,
    Reauthentication,
    TokenBody,
)
from app.schemas.user import UserResponse
from app.services import admin_service, rbac_service
from app.services.admin_service import InvitationView

router = APIRouter(prefix="/admin", tags=["admin"])
# Reached from the emailed link, before the invitee has an account. The token
# travels in the body, never in a URL.
public_router = APIRouter(prefix="/auth/admin-invitations", tags=["auth"])

_limited = Depends(rate_limit("admin_invitation", lambda: settings.invite_attempts_per_minute))


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _read(view: InvitationView) -> InvitationRead:
    i = view.invitation
    return InvitationRead(
        id=i.id,
        email=i.email,
        name=i.name,
        role=i.role_code,
        status=view.status,
        invited_by_name=view.invited_by_name,
        created_at=i.created_at,
        expires_at=i.expires_at,
        accepted_at=i.accepted_at,
        revoked_at=i.revoked_at,
        delivery_status=i.delivery_status,
        last_sent_at=i.last_sent_at,
    )


@router.get("/invitations", response_model=list[InvitationRead])
async def list_invitations(
    include_closed: bool = Query(False, description="Also accepted and revoked invitations"),
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_permission(Perm.admin_invitation_manage)),
):
    return [_read(v) for v in await admin_service.list_invitations(db, include_closed=include_closed)]


@router.post("/invitations", response_model=InvitationRead, status_code=status.HTTP_201_CREATED)
async def create_invitation(
    body: InvitationCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.admin_invitation_manage)),
):
    """Records the invitation, then emails the link. `delivery_status` says
    what the email provider answered; the link itself is never returned."""
    view = await admin_service.create_invitation(
        db, principal, email=body.email, name=body.name, current_password=body.current_password, ip=_ip(request)
    )
    return _read(view)


@router.post("/invitations/{invitation_id}/resend", response_model=InvitationRead)
async def resend_invitation(
    invitation_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.admin_invitation_manage)),
):
    return _read(await admin_service.resend_invitation(db, principal, invitation_id, ip=_ip(request)))


@router.post("/invitations/{invitation_id}/revoke", response_model=InvitationRead)
async def revoke_invitation(
    invitation_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.admin_invitation_manage)),
):
    return _read(await admin_service.revoke_invitation(db, principal, invitation_id, ip=_ip(request)))


@router.post("/administrators/{user_id}/revoke-role", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_admin_role(
    user_id: uuid.UUID,
    body: Reauthentication,
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.user_assign_role)),
):
    await admin_service.revoke_admin_role(
        db, principal, user_id, current_password=body.current_password, ip=_ip(request)
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _user_response(db: AsyncSession, user) -> UserResponse:
    return UserResponse(
        id=user.id,
        name=user.name,
        email=user.email,
        is_active=user.is_active,
        roles=sorted(await rbac_service.role_codes_for(db, user.id)),
        created_at=user.created_at,
    )


@public_router.post("/preview", response_model=InvitationPreviewRead, dependencies=[_limited])
async def preview_invitation(body: TokenBody, db: AsyncSession = Depends(get_db)):
    p = await admin_service.preview(db, body.token)
    return InvitationPreviewRead(
        email=p.email, name=p.name, status=p.status, expires_at=p.expires_at, account_exists=p.account_exists
    )


@public_router.post(
    "/accept", response_model=UserResponse, status_code=status.HTTP_201_CREATED, dependencies=[_limited]
)
async def accept_with_new_account(body: AcceptNewAccount, request: Request, db: AsyncSession = Depends(get_db)):
    """Creates the invited account as an administrator. No session is issued:
    the new administrator signs in through the normal login."""
    user = await admin_service.accept_with_new_account(
        db, body.token, name=body.name, password=body.password, ip=_ip(request)
    )
    return await _user_response(db, user)


@public_router.post("/accept-existing", response_model=UserResponse, dependencies=[_limited])
async def accept_with_existing_account(
    body: AcceptExistingAccount,
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    user = await admin_service.accept_with_existing_account(
        db, body.token, principal, current_password=body.current_password, ip=_ip(request)
    )
    return await _user_response(db, user)
