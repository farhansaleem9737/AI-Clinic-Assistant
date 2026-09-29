"""Admin user management: staff accounts, activation, role grants."""

import logging
import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError, PermissionDeniedError
from app.core.permissions import Perm, Principal, RoleCode
from app.models.rbac import Permission, Role, RolePermission, UserRole
from app.models.user import User
from app.services import auth_service, rbac_service
from app.services.pagination import PageParams, paginate

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UserWithRoles:
    user: User
    roles: list[str]


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


async def _with_roles(db: AsyncSession, users: Sequence[User]) -> list[UserWithRoles]:
    roles = await _roles_by_user(db, [u.id for u in users])
    return [UserWithRoles(u, roles.get(u.id, [])) for u in users]


async def _get(db: AsyncSession, user_id: uuid.UUID) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise NotFoundError("User not found")
    return user


async def _active_admins_other_than(db: AsyncSession, user_id: uuid.UUID) -> int:
    return await db.scalar(
        select(func.count(User.id))
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(Role.code == RoleCode.admin, User.is_active.is_(True), User.id != user_id)
    )


async def list_users(
    db: AsyncSession,
    params: PageParams,
    *,
    q: str | None = None,
    role: str | None = None,
    is_active: bool | None = None,
) -> tuple[list[UserWithRoles], int]:
    query = select(User).order_by(User.name, User.id)
    if q:
        pattern = f"%{q.strip()}%"
        query = query.where(or_(User.name.ilike(pattern), User.email.ilike(pattern)))
    if role:
        query = query.where(
            User.id.in_(select(UserRole.user_id).join(Role, Role.id == UserRole.role_id).where(Role.code == role))
        )
    if is_active is not None:
        query = query.where(User.is_active.is_(is_active))
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
    if not active:
        if user.id == principal.user_id:
            raise BusinessRuleError("You cannot deactivate your own account", code="SELF_DEACTIVATION")
        if RoleCode.admin in (await _roles_by_user(db, [user.id])).get(user.id, []):
            if await _active_admins_other_than(db, user.id) == 0:
                raise BusinessRuleError("Cannot deactivate the last active administrator", code="LAST_ADMIN")
        # Existing sessions end now, not when their tokens would have expired.
        await auth_service.revoke_all_sessions(db, user.id)
    user.is_active = active
    await db.commit()
    logger.info(
        "user_activated" if active else "user_deactivated",
        extra={"user_id": str(user.id), "by": str(principal.user_id)},
    )
    return await get_user(db, user.id)


async def set_roles(
    db: AsyncSession, principal: Principal, user_id: uuid.UUID, codes: list[str]
) -> UserWithRoles:
    user = await _get(db, user_id)
    wanted = set(codes)
    await rbac_service.get_roles_by_code(db, wanted)  # validates every code
    current = set((await _roles_by_user(db, [user.id])).get(user.id, []))

    if RoleCode.admin in current and RoleCode.admin not in wanted:
        if user.id == principal.user_id:
            raise BusinessRuleError("You cannot remove your own admin role", code="SELF_DEMOTION")
        if user.is_active and await _active_admins_other_than(db, user.id) == 0:
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
