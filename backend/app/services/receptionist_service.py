"""Receptionists who work for particular doctors (D131).

* A doctor invites someone by email with a set of permissions. The emailed
  link (only its SHA-256 is stored) creates the account, or is accepted by the
  signed-in owner of an existing receptionist account.
* Accepting creates or reactivates exactly one row per (doctor, receptionist),
  holding that doctor's permissions and status. Every doctor-side operation is
  scoped to the caller's own doctor id, so a doctor can neither see nor change
  another doctor's rows; an id from another doctor is "not found".
* ``active_delegation`` answers, on every request, whether this user may act
  for this doctor right now: role held, account active, assignment ACTIVE,
  doctor and doctor's account active. Suspending or removing takes effect on
  the receptionist's next request; tokens carry no doctor rights.

The clinic-wide ``receptionist`` role (front desk) is a different thing and is
not affected by anything here.
"""

import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.config import settings
from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError, PermissionDeniedError
from app.core.permissions import AssignmentPermission, Delegation, Principal, RoleCode, normalize_assignment_permissions
from app.core.security import hash_token, verify_password
from app.models.department import Department
from app.models.doctor import Doctor
from app.models.doctor_receptionist import AssignmentStatus, DoctorReceptionist, ReceptionistInvitation
from app.models.user import User
from app.services import audit_service, auth_service, email_service, rbac_service
from app.services.audit_service import AuditAction

logger = logging.getLogger(__name__)

# An existing account may accept only if it holds no roles other than these:
# a doctor cannot turn a patient's, a doctor's or an administrator's login into
# their receptionist. Such a person needs a separate account (or an admin).
_ELIGIBLE_ROLES = {RoleCode.doctor_receptionist.value, RoleCode.receptionist.value}


class InvitationStatus(StrEnum):
    pending = "pending"
    accepted = "accepted"
    revoked = "revoked"
    expired = "expired"


def invitation_status(invitation: ReceptionistInvitation, now: datetime | None = None) -> InvitationStatus:
    if invitation.accepted_at is not None:
        return InvitationStatus.accepted
    if invitation.revoked_at is not None:
        return InvitationStatus.revoked
    if invitation.expires_at <= (now or clock.utcnow()):
        return InvitationStatus.expired
    return InvitationStatus.pending


def _permissions(values) -> list[str]:
    try:
        return sorted(p.value for p in normalize_assignment_permissions(values))
    except ValueError:
        raise BusinessRuleError("Unknown permission", code="UNKNOWN_PERMISSION") from None


# ---- the per-request check ---------------------------------------------------------------


async def active_delegation(db: AsyncSession, principal: Principal, doctor_id: uuid.UUID) -> Delegation | None:
    if RoleCode.doctor_receptionist.value not in principal.roles or not principal.user.is_active:
        return None
    doctor_user = User.__table__.alias("doctor_user")
    row = (
        await db.execute(
            select(DoctorReceptionist.id, DoctorReceptionist.permissions)
            .join(Doctor, Doctor.id == DoctorReceptionist.doctor_id)
            .join(doctor_user, doctor_user.c.id == Doctor.user_id)
            .where(
                DoctorReceptionist.doctor_id == doctor_id,
                DoctorReceptionist.receptionist_user_id == principal.user_id,
                DoctorReceptionist.status == AssignmentStatus.active,
                Doctor.is_active.is_(True),
                doctor_user.c.is_active.is_(True),
            )
        )
    ).one_or_none()
    if row is None:
        return None
    # Re-validated on read: a value no longer in the vocabulary grants nothing.
    perms = frozenset(p for p in (AssignmentPermission(v) for v in row.permissions if v in AssignmentPermission))
    return Delegation(doctor_id=doctor_id, assignment_id=row.id, permissions=normalize_assignment_permissions(perms))


# ---- views ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class AssignmentView:
    assignment: DoctorReceptionist
    name: str
    email: str
    account_active: bool


@dataclass(frozen=True)
class DoctorView:
    assignment: DoctorReceptionist
    doctor_name: str
    title: str | None
    specialization: str
    department: str


def _own_doctor(principal: Principal) -> uuid.UUID:
    if principal.doctor_id is None:
        raise PermissionDeniedError("Only doctors manage their receptionists", code="DOCTOR_PROFILE_REQUIRED")
    return principal.doctor_id


async def _assignment_views(db: AsyncSession, where) -> list[AssignmentView]:
    rows = await db.execute(
        select(DoctorReceptionist, User.name, User.email, User.is_active)
        .join(User, User.id == DoctorReceptionist.receptionist_user_id)
        .where(*where)
        .order_by(User.name)
    )
    return [AssignmentView(a, name, email, active) for a, name, email, active in rows.all()]


async def list_receptionists(db: AsyncSession, principal: Principal, *, include_revoked: bool = False) -> list[AssignmentView]:
    where = [DoctorReceptionist.doctor_id == _own_doctor(principal)]
    if not include_revoked:
        where.append(DoctorReceptionist.status != AssignmentStatus.revoked)
    return await _assignment_views(db, where)


async def get_receptionist(db: AsyncSession, principal: Principal, assignment_id: uuid.UUID) -> AssignmentView:
    views = await _assignment_views(
        db, [DoctorReceptionist.id == assignment_id, DoctorReceptionist.doctor_id == _own_doctor(principal)]
    )
    if not views:
        raise NotFoundError("Receptionist not found")
    return views[0]


async def _locked_assignment(db: AsyncSession, principal: Principal, assignment_id: uuid.UUID) -> DoctorReceptionist:
    """The caller's own assignment row, locked: concurrent changes serialize."""
    assignment = await db.scalar(
        select(DoctorReceptionist)
        .where(DoctorReceptionist.id == assignment_id, DoctorReceptionist.doctor_id == _own_doctor(principal))
        .with_for_update()
    )
    if assignment is None:
        raise NotFoundError("Receptionist not found")
    return assignment


async def update_permissions(
    db: AsyncSession, principal: Principal, assignment_id: uuid.UUID, permissions: list[str], ip: str | None = None
) -> AssignmentView:
    assignment = await _locked_assignment(db, principal, assignment_id)
    if assignment.status == AssignmentStatus.revoked:
        raise ConflictError("This receptionist was removed. Invite them again instead.", code="ASSIGNMENT_REVOKED")
    before, assignment.permissions = list(assignment.permissions), _permissions(permissions)
    audit_service.record(
        db, AuditAction.receptionist_permissions_changed, actor_id=principal.user_id, target_type="doctor_receptionist",
        target_id=assignment.id, ip_address=ip, details={"from": before, "to": assignment.permissions},
    )
    await db.commit()
    return await get_receptionist(db, principal, assignment_id)


async def set_status(
    db: AsyncSession, principal: Principal, assignment_id: uuid.UUID, status: AssignmentStatus, ip: str | None = None
) -> AssignmentView:
    """Suspend or reactivate. Removal is `remove`: it cannot be undone here."""
    if status not in (AssignmentStatus.active, AssignmentStatus.suspended):
        raise BusinessRuleError("Status must be active or suspended", code="INVALID_STATUS")
    assignment = await _locked_assignment(db, principal, assignment_id)
    if assignment.status == AssignmentStatus.revoked:
        raise ConflictError("This receptionist was removed. Invite them again instead.", code="ASSIGNMENT_REVOKED")
    if assignment.status != status:
        audit_service.record(
            db, AuditAction.receptionist_status_changed, actor_id=principal.user_id, target_type="doctor_receptionist",
            target_id=assignment.id, ip_address=ip, details={"from": assignment.status, "to": status.value},
        )
        assignment.status = status
        await db.commit()
    return await get_receptionist(db, principal, assignment_id)


async def remove(db: AsyncSession, principal: Principal, assignment_id: uuid.UUID, ip: str | None = None) -> None:
    """End this doctor's assignment. The person's account, and their work for
    other doctors, are untouched; the row stays (status revoked) for the record."""
    assignment = await _locked_assignment(db, principal, assignment_id)
    if assignment.status == AssignmentStatus.revoked:
        return
    previous = assignment.status
    assignment.status = AssignmentStatus.revoked
    assignment.permissions = []
    audit_service.record(
        db, AuditAction.receptionist_removed, actor_id=principal.user_id, target_type="doctor_receptionist",
        target_id=assignment.id, ip_address=ip, details={"from": previous},
    )
    await db.commit()
    logger.info("receptionist_removed", extra={"assignment_id": str(assignment.id), "by": str(principal.user_id)})


async def my_doctors(db: AsyncSession, principal: Principal) -> list[DoctorView]:
    """The doctors this receptionist works for (active or suspended), with what each allows."""
    if RoleCode.doctor_receptionist.value not in principal.roles:
        return []
    doctor_user = User.__table__.alias("doctor_user")
    rows = await db.execute(
        select(DoctorReceptionist, doctor_user.c.name, Doctor.title, Doctor.specialization, Department.name)
        .join(Doctor, Doctor.id == DoctorReceptionist.doctor_id)
        .join(doctor_user, doctor_user.c.id == Doctor.user_id)
        .join(Department, Department.id == Doctor.department_id)
        .where(
            DoctorReceptionist.receptionist_user_id == principal.user_id,
            DoctorReceptionist.status != AssignmentStatus.revoked,
            Doctor.is_active.is_(True),
            doctor_user.c.is_active.is_(True),
        )
        .order_by(doctor_user.c.name)
    )
    return [DoctorView(a, name, title, spec, dept) for a, name, title, spec, dept in rows.all()]


# ---- invitations ---------------------------------------------------------------------------


def invitation_link(raw_token: str) -> str:
    # In the fragment: browsers never send it to a server or in a Referer header.
    return f"{settings.frontend_base_url}/accept-receptionist-invite#token={raw_token}"


async def _doctor_name(db: AsyncSession, doctor_id: uuid.UUID) -> str:
    row = (
        await db.execute(select(User.name, Doctor.title).join(Doctor, Doctor.user_id == User.id).where(Doctor.id == doctor_id))
    ).one()
    return " ".join(filter(None, [row.title, row.name]))


def _invitation_email(invitation: ReceptionistInvitation, raw_token: str, doctor_name: str) -> email_service.Email:
    hours = settings.receptionist_invite_expire_hours
    greeting = f"Hello {invitation.name}," if invitation.name else "Hello,"
    text = (
        f"{greeting}\n\n{doctor_name} has invited you to work as their receptionist in Clinic AI Assistant.\n\n"
        f"Accept the invitation here (the link works once and expires in {hours} hours):\n"
        f"{invitation_link(raw_token)}\n\n"
        "If you did not expect this invitation, you can ignore this email.\n"
    )
    return email_service.Email(to=invitation.email, subject=f"{doctor_name} invited you to Clinic AI Assistant", text=text)


async def invite(
    db: AsyncSession, principal: Principal, *, email: str, name: str | None, permissions: list[str], ip: str | None = None
) -> ReceptionistInvitation:
    doctor_id = _own_doctor(principal)
    perms = _permissions(permissions)
    if email == principal.user.email:
        raise BusinessRuleError("You cannot invite yourself", code="SELF_INVITATION")
    existing = await db.scalar(select(User).where(User.email == email))
    if existing is not None:
        roles = await rbac_service.role_codes_for(db, existing.id)
        if roles - _ELIGIBLE_ROLES:
            raise ConflictError(
                "This email belongs to an account that cannot be a receptionist (for example a patient or doctor account).",
                code="ACCOUNT_NOT_ELIGIBLE",
            )
        assigned = await db.scalar(
            select(DoctorReceptionist.status).where(
                DoctorReceptionist.doctor_id == doctor_id, DoctorReceptionist.receptionist_user_id == existing.id
            )
        )
        if assigned in (AssignmentStatus.active, AssignmentStatus.suspended):
            raise ConflictError("This person already works for you", code="ALREADY_ASSIGNED")

    now = clock.utcnow()
    # A new invitation replaces an open one to the same address (a resend).
    await db.execute(
        update(ReceptionistInvitation)
        .where(
            ReceptionistInvitation.doctor_id == doctor_id,
            ReceptionistInvitation.email == email,
            ReceptionistInvitation.accepted_at.is_(None),
            ReceptionistInvitation.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    raw = secrets.token_urlsafe(32)
    invitation = ReceptionistInvitation(
        doctor_id=doctor_id, email=email, name=name, token_hash=hash_token(raw), permissions=perms,
        invited_by_user_id=principal.user_id, created_at=now,
        expires_at=now + timedelta(hours=settings.receptionist_invite_expire_hours),
    )
    db.add(invitation)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise ConflictError("An invitation to this email was just sent. Try again.", code="INVITATION_PENDING") from None
    audit_service.record(
        db, AuditAction.receptionist_invited, actor_id=principal.user_id, target_type="receptionist_invitation",
        target_id=invitation.id, ip_address=ip,
        details={"email": email, "permissions": perms, "existing_account": existing is not None},
    )
    await db.commit()
    # Sent after the commit and at once, never queued: the outbox would hold the
    # raw token in plain text (as for admin invitations, D87).
    delivery = await email_service.send(_invitation_email(invitation, raw, await _doctor_name(db, doctor_id)))
    invitation.delivery_status = delivery.value
    await db.commit()
    logger.info("receptionist_invited", extra={"invitation_id": str(invitation.id), "by": str(principal.user_id)})
    return invitation


async def list_invitations(db: AsyncSession, principal: Principal) -> list[ReceptionistInvitation]:
    """This doctor's invitations that were not accepted, newest first (pending, expired, revoked)."""
    return list(
        (
            await db.scalars(
                select(ReceptionistInvitation)
                .where(ReceptionistInvitation.doctor_id == _own_doctor(principal), ReceptionistInvitation.accepted_at.is_(None))
                .order_by(ReceptionistInvitation.created_at.desc())
                .limit(100)
            )
        ).all()
    )


async def revoke_invitation(
    db: AsyncSession, principal: Principal, invitation_id: uuid.UUID, ip: str | None = None
) -> ReceptionistInvitation:
    invitation = await db.scalar(
        select(ReceptionistInvitation)
        .where(ReceptionistInvitation.id == invitation_id, ReceptionistInvitation.doctor_id == _own_doctor(principal))
        .with_for_update()
    )
    if invitation is None:
        raise NotFoundError("Invitation not found")
    if invitation_status(invitation) in (InvitationStatus.accepted, InvitationStatus.revoked):
        raise ConflictError("This invitation is closed", code="INVITATION_CLOSED")
    invitation.revoked_at = clock.utcnow()
    audit_service.record(
        db, AuditAction.receptionist_invitation_revoked, actor_id=principal.user_id, target_type="receptionist_invitation",
        target_id=invitation.id, ip_address=ip, details={"email": invitation.email},
    )
    await db.commit()
    return invitation


# ---- accepting -------------------------------------------------------------------------------


@dataclass(frozen=True)
class InvitationPreview:
    email: str
    name: str | None
    doctor_name: str
    status: InvitationStatus
    expires_at: datetime
    account_exists: bool
    permissions: list[str]


async def _by_token(db: AsyncSession, raw_token: str, *, lock: bool) -> ReceptionistInvitation:
    query = select(ReceptionistInvitation).where(ReceptionistInvitation.token_hash == hash_token(raw_token))
    invitation = await db.scalar(query.with_for_update() if lock else query)
    if invitation is None:
        raise NotFoundError("This invitation link is not valid", code="INVITATION_INVALID")
    return invitation


async def preview(db: AsyncSession, raw_token: str) -> InvitationPreview:
    """What the acceptance page shows; only the holder of the token learns it."""
    invitation = await _by_token(db, raw_token, lock=False)
    exists = await db.scalar(select(User.id).where(User.email == invitation.email)) is not None
    return InvitationPreview(
        invitation.email, invitation.name, await _doctor_name(db, invitation.doctor_id), invitation_status(invitation),
        invitation.expires_at, exists, list(invitation.permissions),
    )


async def _open_for_acceptance(db: AsyncSession, raw_token: str) -> ReceptionistInvitation:
    # Row lock: two acceptances of one link run one after the other; the second sees accepted_at.
    invitation = await _by_token(db, raw_token, lock=True)
    match invitation_status(invitation):
        case InvitationStatus.accepted:
            raise ConflictError("This invitation has already been used", code="INVITATION_USED")
        case InvitationStatus.revoked:
            raise ConflictError("This invitation was revoked", code="INVITATION_REVOKED")
        case InvitationStatus.expired:
            raise ConflictError("This invitation has expired", code="INVITATION_EXPIRED")
    # Only as good as the doctor behind it, right now.
    doctor_ok = await db.scalar(
        select(Doctor.id)
        .join(User, User.id == Doctor.user_id)
        .where(Doctor.id == invitation.doctor_id, Doctor.is_active.is_(True), User.is_active.is_(True))
    )
    if doctor_ok is None:
        raise ConflictError("This invitation was revoked", code="INVITATION_REVOKED")
    return invitation


async def _assign(db: AsyncSession, invitation: ReceptionistInvitation, user: User, ip: str | None, *, new_account: bool) -> None:
    """One row per (doctor, receptionist): created, or reactivated with the invited permissions."""
    await rbac_service.grant_roles(db, user.id, [RoleCode.doctor_receptionist], granted_by=invitation.invited_by_user_id)
    assignment = await db.scalar(
        select(DoctorReceptionist)
        .where(DoctorReceptionist.doctor_id == invitation.doctor_id, DoctorReceptionist.receptionist_user_id == user.id)
        .with_for_update()
    )
    if assignment is None:
        assignment = DoctorReceptionist(doctor_id=invitation.doctor_id, receptionist_user_id=user.id)
        db.add(assignment)
    elif assignment.status != AssignmentStatus.revoked:
        raise ConflictError("You already work for this doctor", code="ALREADY_ASSIGNED")
    assignment.status = AssignmentStatus.active
    assignment.permissions = _permissions(invitation.permissions)
    assignment.assigned_by_user_id = invitation.invited_by_user_id
    invitation.accepted_at = clock.utcnow()
    invitation.accepted_user_id = user.id
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise ConflictError("You already work for this doctor", code="ALREADY_ASSIGNED") from None
    audit_service.record(
        db, AuditAction.receptionist_invitation_accepted, actor_id=user.id, target_type="doctor_receptionist",
        target_id=assignment.id, ip_address=ip,
        details={"invitation_id": str(invitation.id), "doctor_id": str(invitation.doctor_id), "new_account": new_account},
    )
    await db.commit()
    logger.info("receptionist_invitation_accepted", extra={"invitation_id": str(invitation.id), "user_id": str(user.id)})


async def accept_with_new_account(
    db: AsyncSession, raw_token: str, *, name: str | None, password: str, ip: str | None = None
) -> User:
    """Create the invited account (email from the invitation, which the link proves) and assign it, atomically."""
    invitation = await _open_for_acceptance(db, raw_token)
    if await db.scalar(select(User.id).where(User.email == invitation.email)) is not None:
        raise ConflictError(
            "An account with this email already exists. Sign in to it to accept the invitation.", code="ACCOUNT_EXISTS"
        )
    full_name = name or invitation.name
    if not full_name:
        raise BusinessRuleError("Enter your name", code="NAME_REQUIRED")
    user = await auth_service.create_user(db, name=full_name, email=invitation.email, password=password)
    await _assign(db, invitation, user, ip, new_account=True)
    return user


async def accept_with_existing_account(
    db: AsyncSession, raw_token: str, principal: Principal, *, current_password: str, ip: str | None = None
) -> None:
    """The signed-in owner of the invited address accepts, re-entering their password."""
    if not verify_password(current_password, principal.user.password_hash):
        raise PermissionDeniedError("Your password is incorrect", code="REAUTHENTICATION_FAILED")
    invitation = await _open_for_acceptance(db, raw_token)
    if principal.user.email != invitation.email:
        raise PermissionDeniedError(
            "This invitation is for a different email address than the one you are signed in with",
            code="INVITATION_EMAIL_MISMATCH",
        )
    if set(principal.roles) - _ELIGIBLE_ROLES:
        raise ConflictError("This account cannot be a receptionist", code="ACCOUNT_NOT_ELIGIBLE")
    await _assign(db, invitation, principal.user, ip, new_account=False)
