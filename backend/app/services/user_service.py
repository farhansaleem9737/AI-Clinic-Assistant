"""Admin user management: staff accounts, activation, role grants."""

import logging
import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from datetime import date, datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from sqlalchemy import case, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BusinessRuleError, ConflictError, DomainError, NotFoundError, PermissionDeniedError
from app.core.permissions import Perm, Principal, RoleCode
from app.models.doctor import Doctor
from app.models.patient import Patient
from app.models.rbac import Permission, Role, RolePermission, UserRole
from app.models.stored_file import StoredFile
from app.models.user import User
from app.services import admin_service, auth_service, rbac_service
from app.services.audit_service import AuditAction, record
from app.services.pagination import PageParams, paginate

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UserWithRoles:
    user: User
    roles: list[str]
    # From the linked doctor or patient profile; users themselves have no phone or photo.
    phone: str | None = None
    photo_key: str | None = None
    doctor_id: uuid.UUID | None = None
    patient_id: uuid.UUID | None = None


class UserSort(StrEnum):
    name = "name"
    name_desc = "-name"
    email = "email"
    email_desc = "-email"
    role = "role"
    role_desc = "-role"
    status = "status"
    status_desc = "-status"
    joined = "created_at"
    joined_desc = "-created_at"


# Role sort (D88): a user sorts by their most privileged role, in this order;
# users without a role come last. Ties fall back to name, then id.
ROLE_RANK = {RoleCode.admin: 0, RoleCode.doctor: 1, RoleCode.receptionist: 2, RoleCode.patient: 3, RoleCode.doctor_applicant: 4}
_UNRANKED = 5
_NO_ROLE = 9


@dataclass(frozen=True)
class RoleWithPermissions:
    role: Role
    permissions: list[str]


async def _roles_by_user(db: AsyncSession, user_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, list[str]]:
    rows = await db.execute(
        select(UserRole.user_id, Role.code)
        .join(Role, Role.id == UserRole.role_id)
        .where(UserRole.user_id.in_(list(user_ids)))
        .order_by(Role.code)
    )
    grouped: dict[uuid.UUID, list[str]] = defaultdict(list)
    for user_id, code in rows:
        grouped[user_id].append(code)
    return grouped


async def _profiles_by_user(db: AsyncSession, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict]:
    """Phone, photo and profile id from the doctor or patient profile (doctor wins if both)."""
    found: dict[uuid.UUID, dict] = {}
    for model, key in ((Patient, "patient_id"), (Doctor, "doctor_id")):
        rows = await db.execute(
            select(model.user_id, model.id, model.phone, StoredFile.object_key)
            .outerjoin(StoredFile, StoredFile.id == model.photo_file_id)
            .where(model.user_id.in_(user_ids))
        )
        for user_id, profile_id, phone, photo_key in rows:
            entry = found.setdefault(user_id, {})
            entry[key] = profile_id
            if phone:
                entry["phone"] = phone
            if photo_key:
                entry["photo_key"] = photo_key
    return found


async def _with_roles(db: AsyncSession, users: Sequence[User]) -> list[UserWithRoles]:
    ids = [u.id for u in users]
    roles = await _roles_by_user(db, ids)
    profiles = await _profiles_by_user(db, ids)
    return [UserWithRoles(u, roles.get(u.id, []), **profiles.get(u.id, {})) for u in users]


async def _get(db: AsyncSession, user_id: uuid.UUID) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise NotFoundError("User not found")
    return user


def _refuse_admin_grant(codes: Iterable[str]) -> None:
    # The admin role is granted only by the bootstrap command or an accepted
    # invitation (D87), never as a field in an account form.
    if RoleCode.admin in set(codes):
        raise BusinessRuleError(
            "Administrators are added by invitation: Users > Invite Administrator",
            code="ADMIN_REQUIRES_INVITATION",
        )


def _role_rank():
    """Each user's most privileged role as a number (see ROLE_RANK)."""
    rank = case(
        *((Role.code == code.value, value) for code, value in ROLE_RANK.items()), else_=_UNRANKED
    )
    return (
        select(func.min(rank))
        .select_from(UserRole)
        .join(Role, Role.id == UserRole.role_id)
        .where(UserRole.user_id == User.id)
        .correlate(User)
        .scalar_subquery()
    )


def _order(sort: UserSort) -> list:
    name = func.lower(User.name)
    keys = {
        UserSort.name: [name.asc()],
        UserSort.name_desc: [name.desc()],
        UserSort.email: [User.email.asc()],
        UserSort.email_desc: [User.email.desc()],
        UserSort.role: [func.coalesce(_role_rank(), _NO_ROLE).asc(), name.asc()],
        UserSort.role_desc: [func.coalesce(_role_rank(), _NO_ROLE).desc(), name.asc()],
        UserSort.status: [User.is_active.desc(), name.asc()],  # Active first
        UserSort.status_desc: [User.is_active.asc(), name.asc()],
        UserSort.joined: [User.created_at.asc()],
        UserSort.joined_desc: [User.created_at.desc()],
    }[sort]
    # Stable paging: equal keys never swap rows between pages.
    return [*keys, User.id.asc()]


async def list_users(
    db: AsyncSession,
    params: PageParams,
    *,
    q: str | None = None,
    role: str | None = None,
    is_active: bool | None = None,
    joined_from: date | None = None,
    joined_to: date | None = None,
    sort: UserSort = UserSort.name,
) -> tuple[list[UserWithRoles], int]:
    """`joined_from/_to` are inclusive clinic-local dates. `q` matches name,
    email or the phone on the user's doctor or patient profile."""
    if joined_from and joined_to and joined_from > joined_to:
        raise BusinessRuleError("The start date must not be after the end date", code="INVALID_DATE_RANGE")
    query = select(User).order_by(*_order(sort))
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        with_phone = (
            select(Patient.user_id).where(Patient.user_id.is_not(None), Patient.phone.ilike(pattern))
            .union(select(Doctor.user_id).where(Doctor.phone.ilike(pattern)))
        )
        query = query.where(or_(User.name.ilike(pattern), User.email.ilike(pattern), User.id.in_(with_phone)))
    if role:
        # Many-to-many: a user with several roles matches each of them, once.
        query = query.where(
            User.id.in_(select(UserRole.user_id).join(Role, Role.id == UserRole.role_id).where(Role.code == role))
        )
    if is_active is not None:
        query = query.where(User.is_active.is_(is_active))
    tz = ZoneInfo(settings.clinic_timezone)
    if joined_from is not None:
        query = query.where(User.created_at >= datetime.combine(joined_from, time.min, tzinfo=tz))
    if joined_to is not None:
        query = query.where(User.created_at < datetime.combine(joined_to + timedelta(days=1), time.min, tzinfo=tz))
    users, total = await paginate(db, query, params)
    return await _with_roles(db, users), total


async def get_user(db: AsyncSession, user_id: uuid.UUID) -> UserWithRoles:
    return (await _with_roles(db, [await _get(db, user_id)]))[0]


async def create_account(
    db: AsyncSession, principal: Principal, *, name: str, email: str, password: str, roles: list[str]
) -> UserWithRoles:
    """Admin-created account (staff, or a patient registered at the desk)."""
    if roles and not principal.has(Perm.user_assign_role):
        raise PermissionDeniedError("Assigning roles requires the user:assign_role permission")
    _refuse_admin_grant(roles)
    user = await auth_service.create_user(db, name=name, email=email, password=password)
    await rbac_service.grant_roles(db, user.id, roles, granted_by=principal.user_id)
    await db.commit()
    logger.info("user_created", extra={"user_id": str(user.id), "by": str(principal.user_id), "roles": roles})
    return await get_user(db, user.id)


async def update_user(
    db: AsyncSession, principal: Principal, user_id: uuid.UUID, changes: dict
) -> UserWithRoles:
    user = await _get(db, user_id)
    if "email" in changes and changes["email"] != user.email:
        if await db.scalar(select(User.id).where(User.email == changes["email"])) is not None:
            raise ConflictError("Email already registered", code="EMAIL_TAKEN")
    for field, value in changes.items():
        setattr(user, field, value)
    await db.commit()
    logger.info("user_updated", extra={"user_id": str(user.id), "by": str(principal.user_id), "fields": sorted(changes)})
    return await get_user(db, user.id)


async def set_active(db: AsyncSession, principal: Principal, user_id: uuid.UUID, active: bool) -> UserWithRoles:
    user = await _get(db, user_id)
    is_admin = RoleCode.admin in (await _roles_by_user(db, [user.id])).get(user.id, [])
    if not active:
        if user.id == principal.user_id:
            raise BusinessRuleError("You cannot deactivate your own account", code="SELF_DEACTIVATION")
        if is_admin:
            await admin_service.lock_admin_set(db)  # no two deactivations race past the check
            if await admin_service.active_admins_other_than(db, user.id) == 0:
                raise BusinessRuleError("Cannot deactivate the last active administrator", code="LAST_ADMIN")
        # Existing sessions end now, not when their tokens would have expired.
        await auth_service.revoke_all_sessions(db, user.id)
    user.is_active = active
    record(
        db,
        AuditAction.user_activated if active else AuditAction.user_deactivated,
        actor_id=principal.user_id,
        target_type="user",
        target_id=user.id,
        details={"administrator": is_admin},
    )
    await db.commit()
    logger.info(
        "user_activated" if active else "user_deactivated",
        extra={"user_id": str(user.id), "by": str(principal.user_id)},
    )
    return await get_user(db, user.id)


@dataclass(frozen=True)
class BulkOutcome:
    user_id: uuid.UUID
    ok: bool
    code: str | None = None
    message: str | None = None


async def set_active_bulk(
    db: AsyncSession, principal: Principal, user_ids: list[uuid.UUID], active: bool
) -> list[BulkOutcome]:
    """Each user in its own transaction through ``set_active``, so every rule
    (self, last administrator, session revocation, audit) applies to each one,
    and one refusal does not undo the others."""
    outcomes = []
    for user_id in dict.fromkeys(user_ids):  # de-duplicated, order kept
        try:
            await set_active(db, principal, user_id, active)
            outcomes.append(BulkOutcome(user_id, True))
        except DomainError as exc:
            await db.rollback()
            # The rollback expired every loaded row, the caller's own included.
            await db.refresh(principal.user)
            outcomes.append(BulkOutcome(user_id, False, exc.code, exc.message))
    return outcomes


async def set_roles(
    db: AsyncSession, principal: Principal, user_id: uuid.UUID, codes: list[str]
) -> UserWithRoles:
    user = await _get(db, user_id)
    wanted = set(codes)
    await rbac_service.get_roles_by_code(db, wanted)  # validates every code
    current = set((await _roles_by_user(db, [user.id])).get(user.id, []))
    _refuse_admin_grant(wanted - current)

    if RoleCode.admin in current and RoleCode.admin not in wanted:
        if user.id == principal.user_id:
            raise BusinessRuleError("You cannot remove your own admin role", code="SELF_DEMOTION")
        await admin_service.lock_admin_set(db)
        if user.is_active and await admin_service.active_admins_other_than(db, user.id) == 0:
            raise BusinessRuleError("Cannot remove the last active administrator", code="LAST_ADMIN")

    removed = current - wanted
    if removed:
        await db.execute(
            delete(UserRole).where(
                UserRole.user_id == user.id,
                UserRole.role_id.in_(select(Role.id).where(Role.code.in_(removed))),
            )
        )
    await rbac_service.grant_roles(db, user.id, wanted - current, granted_by=principal.user_id)
    if removed or wanted - current:
        record(
            db,
            AuditAction.admin_role_revoked if RoleCode.admin in removed else AuditAction.user_roles_changed,
            actor_id=principal.user_id,
            target_type="user",
            target_id=user.id,
            details={"added": sorted(wanted - current), "removed": sorted(removed)},
        )
    await db.commit()
    logger.info(
        "user_roles_changed",
        extra={
            "user_id": str(user.id),
            "by": str(principal.user_id),
            "added": sorted(wanted - current),
            "removed": sorted(removed),
        },
    )
    return await get_user(db, user.id)


async def list_roles(db: AsyncSession) -> list[RoleWithPermissions]:
    roles = (await db.scalars(select(Role).order_by(Role.code))).all()
    rows = await db.execute(
        select(RolePermission.role_id, Permission.code)
        .join(Permission, Permission.id == RolePermission.permission_id)
        .order_by(Permission.code)
    )
    grouped: dict[uuid.UUID, list[str]] = defaultdict(list)
    for role_id, code in rows:
        grouped[role_id].append(code)
    return [RoleWithPermissions(role, grouped.get(role.id, [])) for role in roles]
