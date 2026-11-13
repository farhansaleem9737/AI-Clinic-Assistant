"""Doctor's receptionists (D131).

* /doctors/me/...: a doctor manages only their own receptionists and
  invitations (the doctor comes from the session, never from the URL).
* /receptionist-invitations/...: accepting an invitation (public, rate limited;
  the token travels in the body, never in a URL).
* /receptionists/me/doctors: the doctors a receptionist works for. To act for
  one of them, the client sends X-Acting-Doctor-Id on ordinary appointment and
  patient requests; the backend checks the assignment on every request.
"""

import uuid

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import get_current_principal, require_permission
from app.core.config import settings
from app.core.permissions import Perm, Principal
from app.core.rate_limit import rate_limit
from app.db.session import get_db
from app.models.doctor_receptionist import AssignmentStatus, ReceptionistInvitation
from app.schemas.receptionist import (
    AcceptNewReceptionistAccount,
    AcceptWithExistingAccount,
    AssignedDoctorRead,
    AssignmentPermissionsUpdate,
    AssignmentRead,
    AssignmentStatusUpdate,
    InvitationToken,
    ReceptionistInvitationCreate,
    ReceptionistInvitationPreviewRead,
    ReceptionistInvitationRead,
)
from app.services import receptionist_service
from app.services.receptionist_service import AssignmentView

doctor_router = APIRouter(prefix="/doctors/me", tags=["receptionists"])
public_router = APIRouter(prefix="/receptionist-invitations", tags=["receptionists"])
router = APIRouter(prefix="/receptionists", tags=["receptionists"])

_doctor = Depends(require_permission(Perm.receptionist_manage_own))
_limited = Depends(rate_limit("receptionist_invitation", lambda: settings.invite_attempts_per_minute))


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _assignment(view: AssignmentView) -> AssignmentRead:
    a = view.assignment
    return AssignmentRead(
        id=a.id, receptionist_user_id=a.receptionist_user_id, name=view.name, email=view.email,
        account_active=view.account_active, status=a.status, permissions=list(a.permissions),
        created_at=a.created_at, updated_at=a.updated_at,
    )


def _invitation(i: ReceptionistInvitation) -> ReceptionistInvitationRead:
    return ReceptionistInvitationRead(
        id=i.id, email=i.email, name=i.name, permissions=list(i.permissions),
        status=receptionist_service.invitation_status(i), created_at=i.created_at, expires_at=i.expires_at,
        revoked_at=i.revoked_at, delivery_status=i.delivery_status,
    )


# ---- doctor side -------------------------------------------------------------------------


@doctor_router.post(
    "/receptionist-invitations", response_model=ReceptionistInvitationRead, status_code=status.HTTP_201_CREATED
)
async def invite_receptionist(
    body: ReceptionistInvitationCreate, request: Request, principal: Principal = _doctor, db: AsyncSession = Depends(get_db)
):
    """Email a one-time link (valid RECEPTIONIST_INVITE_EXPIRE_HOURS). A new
    invitation to the same address replaces an open one."""
    invitation = await receptionist_service.invite(
        db, principal, email=body.email, name=body.name, permissions=body.permissions, ip=_ip(request)
    )
    return _invitation(invitation)


@doctor_router.get("/receptionist-invitations", response_model=list[ReceptionistInvitationRead])
async def list_invitations(principal: Principal = _doctor, db: AsyncSession = Depends(get_db)):
    return [_invitation(i) for i in await receptionist_service.list_invitations(db, principal)]


@doctor_router.delete("/receptionist-invitations/{invitation_id}", response_model=ReceptionistInvitationRead)
async def revoke_invitation(
    invitation_id: uuid.UUID, request: Request, principal: Principal = _doctor, db: AsyncSession = Depends(get_db)
):
    return _invitation(await receptionist_service.revoke_invitation(db, principal, invitation_id, ip=_ip(request)))


@doctor_router.get("/receptionists", response_model=list[AssignmentRead])
async def list_receptionists(
    include_revoked: bool = False, principal: Principal = _doctor, db: AsyncSession = Depends(get_db)
):
    views = await receptionist_service.list_receptionists(db, principal, include_revoked=include_revoked)
    return [_assignment(v) for v in views]


@doctor_router.get("/receptionists/{assignment_id}", response_model=AssignmentRead)
async def get_receptionist(assignment_id: uuid.UUID, principal: Principal = _doctor, db: AsyncSession = Depends(get_db)):
    return _assignment(await receptionist_service.get_receptionist(db, principal, assignment_id))


@doctor_router.patch("/receptionists/{assignment_id}/permissions", response_model=AssignmentRead)
async def update_permissions(
    assignment_id: uuid.UUID, body: AssignmentPermissionsUpdate, request: Request,
    principal: Principal = _doctor, db: AsyncSession = Depends(get_db),
):
    view = await receptionist_service.update_permissions(db, principal, assignment_id, body.permissions, ip=_ip(request))
    return _assignment(view)


@doctor_router.patch("/receptionists/{assignment_id}/status", response_model=AssignmentRead)
async def set_status(
    assignment_id: uuid.UUID, body: AssignmentStatusUpdate, request: Request,
    principal: Principal = _doctor, db: AsyncSession = Depends(get_db),
):
    view = await receptionist_service.set_status(
        db, principal, assignment_id, AssignmentStatus(body.status), ip=_ip(request)
    )
    return _assignment(view)


@doctor_router.delete("/receptionists/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_receptionist(
    assignment_id: uuid.UUID, request: Request, principal: Principal = _doctor, db: AsyncSession = Depends(get_db)
):
    """Ends this doctor's assignment only. The account and other doctors' assignments stay."""
    await receptionist_service.remove(db, principal, assignment_id, ip=_ip(request))


# ---- accepting ---------------------------------------------------------------------------


@public_router.post("/preview", response_model=ReceptionistInvitationPreviewRead, dependencies=[_limited])
async def preview_invitation(body: InvitationToken, db: AsyncSession = Depends(get_db)):
    p = await receptionist_service.preview(db, body.token)
    return ReceptionistInvitationPreviewRead(
        email=p.email, name=p.name, doctor_name=p.doctor_name, status=p.status, expires_at=p.expires_at,
        account_exists=p.account_exists, permissions=p.permissions,
    )


@public_router.post("/accept", status_code=status.HTTP_201_CREATED, dependencies=[_limited])
async def accept_with_new_account(
    body: AcceptNewReceptionistAccount, request: Request, db: AsyncSession = Depends(get_db)
) -> dict[str, str]:
    """Creates the invited account and assigns it. No session is issued: the
    receptionist signs in through the normal login."""
    await receptionist_service.accept_with_new_account(
        db, body.token, name=body.name, password=body.password, ip=_ip(request)
    )
    return {"message": "Your account is ready. Sign in to start."}


@public_router.post("/accept-existing", dependencies=[_limited])
async def accept_with_existing_account(
    body: AcceptWithExistingAccount, request: Request,
    principal: Principal = Depends(get_current_principal), db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    await receptionist_service.accept_with_existing_account(
        db, body.token, principal, current_password=body.current_password, ip=_ip(request)
    )
    return {"message": "You now work for this doctor too."}


# ---- receptionist side -------------------------------------------------------------------


@router.get("/me/doctors", response_model=list[AssignedDoctorRead])
async def my_doctors(principal: Principal = Depends(get_current_principal), db: AsyncSession = Depends(get_db)):
    return [
        AssignedDoctorRead(
            assignment_id=v.assignment.id, doctor_id=v.assignment.doctor_id, name=v.doctor_name, title=v.title,
            specialization=v.specialization, department=v.department, status=v.assignment.status,
            permissions=list(v.assignment.permissions),
        )
        for v in await receptionist_service.my_doctors(db, principal)
    ]
