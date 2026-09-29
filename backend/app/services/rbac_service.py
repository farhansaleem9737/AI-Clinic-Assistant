import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.permissions import Principal, RoleCode
from app.models.doctor import Doctor
from app.models.rbac import Permission, Role, RolePermission, UserRole
from app.models.user import User


async def role_codes_for(db: AsyncSession, user_id: uuid.UUID) -> set[str]:
    result = await db.scalars(
        select(Role.code).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user_id)
    )
    return set(result.all())


async def load_principal(db: AsyncSession, user: User) -> Principal:
    """Resolve roles and permissions from the database: a role change or
    deactivation takes effect on the very next request."""
    rows = await db.execute(
        select(Role.code, Permission.code)
        .select_from(UserRole)
        .join(Role, Role.id == UserRole.role_id)
        .outerjoin(RolePermission, RolePermission.role_id == Role.id)
        .outerjoin(Permission, Permission.id == RolePermission.permission_id)
        .where(UserRole.user_id == user.id)
    )
    roles: set[str] = set()
    permissions: set[str] = set()
    for role_code, permission_code in rows:
        roles.add(role_code)
        if permission_code is not None:
            permissions.add(permission_code)

    doctor_id = await db.scalar(select(Doctor.id).where(Doctor.user_id == user.id))
    return Principal(user=user, roles=frozenset(roles), permissions=frozenset(permissions), doctor_id=doctor_id)


async def user_has_role(db: AsyncSession, user_id: uuid.UUID, role: RoleCode) -> bool:
    return role.value in await role_codes_for(db, user_id)


async def get_roles_by_code(db: AsyncSession, codes: Iterable[str]) -> list[Role]:
    codes = set(codes)
    roles = list((await db.scalars(select(Role).where(Role.code.in_(codes)))).all())
    missing = codes - {r.code for r in roles}
    if missing:
        raise NotFoundError("Unknown role", code="UNKNOWN_ROLE", details={"roles": sorted(missing)})
    return roles


async def grant_roles(
    db: AsyncSession, user_id: uuid.UUID, codes: Iterable[str], granted_by: uuid.UUID | None = None
) -> None:
    """Add roles to a user (idempotent). Does not commit."""
    held = await role_codes_for(db, user_id)
    for role in await get_roles_by_code(db, codes):
        if role.code not in held:
            db.add(UserRole(user_id=user_id, role_id=role.id, granted_by_user_id=granted_by))
