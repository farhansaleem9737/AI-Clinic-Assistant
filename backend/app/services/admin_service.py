"""Administrators: the first-administrator bootstrap, invitations and the
admin role's lifecycle (D87).

The admin role is granted in exactly two ways:

* ``bootstrap_first_admin``: a command-line action on a database that has
  never had an administrator. It only ever creates a new account.
* an invitation: created by an administrator, accepted by whoever controls
  the invited email (a new account), or by that account's owner signed in
  and re-entering their password (an existing account).

Every change to the set of administrators takes the same advisory lock, so
"is this the last active administrator?" and "is there an administrator
yet?" are answered without races.
"""

import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.config import settings
from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError, PermissionDeniedError
from app.core.permissions import Perm, Principal, RoleCode
from app.core.security import hash_password, hash_token, verify_password
from app.models.admin import AdminInvitation
from app.models.rbac import Role, UserRole
from app.models.user import User
from app.services import auth_service, email_service, rbac_service
from app.services.audit_service import AuditAction, record

logger = logging.getLogger(__name__)

# pg_advisory_xact_lock namespaces 1 and 2 belong to bookings.
_ADMIN_SET_LOCK = 3
_INVITED_EMAIL_LOCK = 4


async def lock_admin_set(db: AsyncSession) -> None:
    """Serialize every change to who is an administrator (transaction-scoped)."""
    await db.execute(text("SELECT pg_advisory_xact_lock(:ns, 0)"), {"ns": _ADMIN_SET_LOCK})


def _admin_user_ids():
    return select(UserRole.user_id).join(Role, Role.id == UserRole.role_id).where(Role.code == RoleCode.admin)


async def admin_exists(db: AsyncSession) -> bool:
    """Whether any account, active or not, has ever been left holding the admin role."""
    return await db.scalar(select(func.count()).select_from(_admin_user_ids().subquery())) > 0


async def active_admins_other_than(db: AsyncSession, user_id: uuid.UUID) -> int:
    return await db.scalar(
        select(func.count(User.id)).where(User.id.in_(_admin_user_ids()), User.is_active.is_(True), User.id != user_id)
    )


def _require_password(principal: Principal, password: str) -> None:
    """Recent re-authentication for sensitive changes: the caller re-enters
    their password even though they hold a valid session."""
    if not verify_password(password, principal.user.password_hash):
        raise PermissionDeniedError("Your password is incorrect", code="REAUTHENTICATION_FAILED")


# ---- first administrator ---------------------------------------------------------------


async def bootstrap_first_admin(db: AsyncSession, *, name: str, email: str, password: str) -> User:
    """Create the first administrator: a new account, on a database with no
    administrator. Refuses everything else; it never promotes an existing account."""
    await lock_admin_set(db)
    if await admin_exists(db):
        raise ConflictError(
            "An administrator already exists. Invite further administrators from Admin > Users.",
            code="ADMIN_EXISTS",
        )
    if await db.scalar(select(User.id).where(User.email == email)) is not None:
        raise ConflictError(
            "That email already belongs to an account. The first administrator must be a new account.",
            code="EMAIL_TAKEN",
        )
    user = await auth_service.create_user(db, name=name, email=email, password=password)
    await rbac_service.grant_roles(db, user.id, [RoleCode.admin])
    record(db, AuditAction.admin_bootstrapped, actor_id=None, target_type="user", target_id=user.id,
           details={"email": email, "via": "cli"})
    await db.commit()
    logger.info("admin_bootstrapped", extra={"user_id": str(user.id)})
    return user


async def reset_admin_password(db: AsyncSession, *, email: str, password: str) -> User:
    """Command-line recovery for an administrator who cannot sign in. Only
    administrator accounts; every session of the account ends; audited."""
    user = await db.scalar(select(User).where(User.email == email).with_for_update())
    if user is None or not await rbac_service.user_has_role(db, user.id, RoleCode.admin):
        raise NotFoundError("No administrator account has that email", code="ADMIN_NOT_FOUND")
    user.password_hash = hash_password(password)
    await auth_service.revoke_all_sessions(db, user.id)
    record(db, AuditAction.admin_password_reset, actor_id=None, target_type="user", target_id=user.id,
           details={"via": "cli"})
    await db.commit()
    logger.info("admin_password_reset", extra={"user_id": str(user.id)})
    return user


# ---- invitations -----------------------------------------------------------------------


class InvitationStatus(StrEnum):
    pending = "pending"
    accepted = "accepted"
    revoked = "revoked"
    expired = "expired"


def status_of(invitation: AdminInvitation, now: datetime | None = None) -> InvitationStatus:
    if invitation.accepted_at is not None:
        return InvitationStatus.accepted
    if invitation.revoked_at is not None:
        return InvitationStatus.revoked
    if invitation.expires_at <= (now or clock.utcnow()):
        return InvitationStatus.expired
    return InvitationStatus.pending


@dataclass(frozen=True)
class InvitationView:
    invitation: AdminInvitation
    status: InvitationStatus
    invited_by_name: str | None


@dataclass(frozen=True)
class InvitationPreview:
    email: str
    name: str | None
    status: InvitationStatus
    expires_at: datetime
    account_exists: bool


def _new_token() -> str:
    return secrets.token_urlsafe(32)


def invitation_link(raw_token: str) -> str:
    # In the fragment: browsers never send it to a server or in a Referer.
    return f"{settings.frontend_base_url}/accept-admin-invite#token={raw_token}"


def _invitation_email(invitation: AdminInvitation, raw_token: str, inviter_name: str) -> email_service.Email:
    hours = settings.admin_invite_expire_hours
    return email_service.Email(
        to=invitation.email,
        subject="You have been invited to administer Clinic AI Assistant",
        text=(
            f"Hello{' ' + invitation.name if invitation.name else ''},\n\n"
            f"{inviter_name} has invited you to become an administrator of Clinic AI Assistant.\n\n"
            f"Accept the invitation here (the link works once and expires in {hours} hours):\n"
            f"{invitation_link(raw_token)}\n\n"
            "If you were not expecting this, ignore this email.\n"
        ),
    )


async def _deliver(db: AsyncSession, invitation: AdminInvitation, raw_token: str, inviter_name: str) -> None:
    delivery = await email_service.send(_invitation_email(invitation, raw_token, inviter_name))
    invitation.delivery_status = delivery
    invitation.last_sent_at = clock.utcnow() if delivery in (email_service.Delivery.sent, email_service.Delivery.outbox) else invitation.last_sent_at
    await db.commit()


async def _views(db: AsyncSession, invitations: list[AdminInvitation]) -> list[InvitationView]:
    inviter_ids = {i.invited_by_user_id for i in invitations if i.invited_by_user_id}
    names = dict((await db.execute(select(User.id, User.name).where(User.id.in_(inviter_ids)))).all()) if inviter_ids else {}
    now = clock.utcnow()
    return [InvitationView(i, status_of(i, now), names.get(i.invited_by_user_id)) for i in invitations]


async def list_invitations(db: AsyncSession, *, include_closed: bool = False) -> list[InvitationView]:
    query = select(AdminInvitation).order_by(AdminInvitation.created_at.desc(), AdminInvitation.id.desc())
    if not include_closed:
        query = query.where(AdminInvitation.accepted_at.is_(None), AdminInvitation.revoked_at.is_(None))
    return await _views(db, list((await db.scalars(query.limit(200))).all()))


async def create_invitation(
    db: AsyncSession, principal: Principal, *, email: str, name: str | None, current_password: str, ip: str | None = None
) -> InvitationView:
    _require_password(principal, current_password)
    # Two administrators inviting the same address at once: one wins.
    await db.execute(text("SELECT pg_advisory_xact_lock(:ns, hashtext(:email))"), {"ns": _INVITED_EMAIL_LOCK, "email": email})

    existing_user = await db.scalar(select(User.id).where(User.email == email))
    if existing_user is not None and await rbac_service.user_has_role(db, existing_user, RoleCode.admin):
        raise ConflictError("That account is already an administrator", code="ALREADY_ADMIN")
    now = clock.utcnow()
    open_invites = (
        await db.scalars(
            select(AdminInvitation).where(
                AdminInvitation.email == email,
                AdminInvitation.accepted_at.is_(None),
                AdminInvitation.revoked_at.is_(None),
                AdminInvitation.expires_at > now,
            )
        )
    ).all()
    if open_invites:
        raise ConflictError(
            "There is already a pending invitation for this email. Resend or revoke it instead.",
            code="INVITATION_PENDING",
        )

    raw = _new_token()
    invitation = AdminInvitation(
        email=email,
        name=name,
        token_hash=hash_token(raw),
        role_code=RoleCode.admin,
        invited_by_user_id=principal.user_id,
        created_at=now,
        expires_at=now + timedelta(hours=settings.admin_invite_expire_hours),
    )
    db.add(invitation)
    await db.flush()
    record(db, AuditAction.admin_invited, actor_id=principal.user_id, target_type="admin_invitation",
           target_id=invitation.id, ip_address=ip,
           details={"email": email, "existing_account": existing_user is not None, "expires_at": invitation.expires_at.isoformat()})
    await db.commit()
    logger.info("admin_invitation_created", extra={"invitation_id": str(invitation.id), "by": str(principal.user_id)})
    # Sent after the commit: a recorded invitation whose email failed can be
    # resent; an email for an invitation that was rolled back could not be.
    await _deliver(db, invitation, raw, principal.user.name)
    return (await _views(db, [invitation]))[0]


async def _locked(db: AsyncSession, invitation_id: uuid.UUID) -> AdminInvitation:
    invitation = await db.scalar(select(AdminInvitation).where(AdminInvitation.id == invitation_id).with_for_update())
    if invitation is None:
        raise NotFoundError("Invitation not found")
    return invitation


async def resend_invitation(
    db: AsyncSession, principal: Principal, invitation_id: uuid.UUID, ip: str | None = None
) -> InvitationView:
    """A fresh link and a fresh lifetime. The old link stops working: only
    the hash of the newest token is kept."""
    invitation = await _locked(db, invitation_id)
    if status_of(invitation) in (InvitationStatus.accepted, InvitationStatus.revoked):
        raise ConflictError("This invitation is closed", code="INVITATION_CLOSED")
    raw = _new_token()
    now = clock.utcnow()
    invitation.token_hash = hash_token(raw)
    invitation.expires_at = now + timedelta(hours=settings.admin_invite_expire_hours)
    record(db, AuditAction.admin_invitation_resent, actor_id=principal.user_id, target_type="admin_invitation",
           target_id=invitation.id, ip_address=ip, details={"email": invitation.email})
    await db.commit()
    await _deliver(db, invitation, raw, principal.user.name)
    return (await _views(db, [invitation]))[0]


async def revoke_invitation(
    db: AsyncSession, principal: Principal, invitation_id: uuid.UUID, ip: str | None = None
) -> InvitationView:
    invitation = await _locked(db, invitation_id)
    if status_of(invitation) in (InvitationStatus.accepted, InvitationStatus.revoked):
        raise ConflictError("This invitation is closed", code="INVITATION_CLOSED")
    invitation.revoked_at = clock.utcnow()
    invitation.revoked_by_user_id = principal.user_id
    record(db, AuditAction.admin_invitation_revoked, actor_id=principal.user_id, target_type="admin_invitation",
           target_id=invitation.id, ip_address=ip, details={"email": invitation.email})
    await db.commit()
    logger.info("admin_invitation_revoked", extra={"invitation_id": str(invitation.id), "by": str(principal.user_id)})
    return (await _views(db, [invitation]))[0]


_INVALID = "This invitation link is not valid"


async def _by_token(db: AsyncSession, raw_token: str, *, lock: bool) -> AdminInvitation:
    query = select(AdminInvitation).where(AdminInvitation.token_hash == hash_token(raw_token))
    invitation = await db.scalar(query.with_for_update() if lock else query)
    if invitation is None:
        raise NotFoundError(_INVALID, code="INVITATION_INVALID")
    return invitation


async def preview(db: AsyncSession, raw_token: str) -> InvitationPreview:
    """What the invitation page shows. Only someone holding the token learns
    anything, and only about their own invitation."""
    invitation = await _by_token(db, raw_token, lock=False)
    exists = await db.scalar(select(User.id).where(User.email == invitation.email)) is not None
    return InvitationPreview(invitation.email, invitation.name, status_of(invitation), invitation.expires_at, exists)


async def _open_for_acceptance(db: AsyncSession, raw_token: str) -> AdminInvitation:
    # Row lock: two acceptances of one link run one after the other, and the
    # second sees accepted_at already set.
    invitation = await _by_token(db, raw_token, lock=True)
    match status_of(invitation):
        case InvitationStatus.accepted:
            raise ConflictError("This invitation has already been used", code="INVITATION_USED")
        case InvitationStatus.revoked:
            raise ConflictError("This invitation was revoked", code="INVITATION_REVOKED")
        case InvitationStatus.expired:
            raise ConflictError("This invitation has expired", code="INVITATION_EXPIRED")
    # An invitation is only as good as its sender's authority right now.
    inviter = await db.get(User, invitation.invited_by_user_id) if invitation.invited_by_user_id else None
    if inviter is None or not inviter.is_active or not (await rbac_service.load_principal(db, inviter)).has(
        Perm.admin_invitation_manage
    ):
        raise ConflictError("This invitation was revoked", code="INVITATION_REVOKED")
    return invitation


async def _grant_from(db: AsyncSession, invitation: AdminInvitation, user: User, ip: str | None, *, new_account: bool) -> None:
    await lock_admin_set(db)
    await rbac_service.grant_roles(db, user.id, [RoleCode.admin], granted_by=invitation.invited_by_user_id)
    invitation.accepted_at = clock.utcnow()
    invitation.accepted_user_id = user.id
    record(db, AuditAction.admin_invitation_accepted, actor_id=user.id, target_type="admin_invitation",
           target_id=invitation.id, ip_address=ip, details={"email": invitation.email, "new_account": new_account})
    record(db, AuditAction.admin_role_granted, actor_id=invitation.invited_by_user_id, target_type="user",
           target_id=user.id, ip_address=ip, details={"via": "invitation", "invitation_id": str(invitation.id)})
    await db.commit()
    logger.info("admin_invitation_accepted", extra={"invitation_id": str(invitation.id), "user_id": str(user.id)})


async def accept_with_new_account(
    db: AsyncSession, raw_token: str, *, name: str | None, password: str, ip: str | None = None
) -> User:
    """Create the invited account and make it an administrator, atomically."""
    invitation = await _open_for_acceptance(db, raw_token)
    if await db.scalar(select(User.id).where(User.email == invitation.email)) is not None:
        # Never overwrite an existing password or adopt an existing account.
        raise ConflictError(
            "An account with this email already exists. Sign in to it to accept the invitation.",
            code="ACCOUNT_EXISTS",
        )
    full_name = name or invitation.name
    if not full_name:
        raise BusinessRuleError("Enter your name", code="NAME_REQUIRED")
    user = await auth_service.create_user(db, name=full_name, email=invitation.email, password=password)
    await _grant_from(db, invitation, user, ip, new_account=True)
    return user


async def accept_with_existing_account(
    db: AsyncSession, raw_token: str, principal: Principal, *, current_password: str, ip: str | None = None
) -> User:
    """The signed-in owner of the invited email accepts. Signed in proves the
    session; the password proves it is the owner at the keyboard now."""
    _require_password(principal, current_password)
    invitation = await _open_for_acceptance(db, raw_token)
    if principal.user.email != invitation.email:
        raise PermissionDeniedError(
            "This invitation is for a different email address than the one you are signed in with",
            code="INVITATION_EMAIL_MISMATCH",
        )
    if RoleCode.admin in principal.roles:
        raise ConflictError("You are already an administrator", code="ALREADY_ADMIN")
    await _grant_from(db, invitation, principal.user, ip, new_account=False)
    return principal.user


# ---- removing the admin role -----------------------------------------------------------


async def revoke_admin_role(
    db: AsyncSession, principal: Principal, user_id: uuid.UUID, *, current_password: str, ip: str | None = None
) -> None:
    _require_password(principal, current_password)
    await lock_admin_set(db)
    user = await db.get(User, user_id)
    if user is None or not await rbac_service.user_has_role(db, user.id, RoleCode.admin):
        raise NotFoundError("Administrator not found")
    if user.id == principal.user_id:
        raise BusinessRuleError("You cannot remove your own administrator role", code="SELF_DEMOTION")
    if await active_admins_other_than(db, user.id) == 0:
        raise BusinessRuleError("Cannot remove the last active administrator", code="LAST_ADMIN")
    await db.execute(
        delete(UserRole).where(
            UserRole.user_id == user.id, UserRole.role_id.in_(select(Role.id).where(Role.code == RoleCode.admin))
        )
    )
    record(db, AuditAction.admin_role_revoked, actor_id=principal.user_id, target_type="user", target_id=user.id,
           ip_address=ip)
    await db.commit()
    logger.info("admin_role_revoked", extra={"user_id": str(user.id), "by": str(principal.user_id)})
