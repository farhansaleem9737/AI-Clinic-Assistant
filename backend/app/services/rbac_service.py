import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.permissions import Principal, RoleCode
from app.models.doctor import Doctor
from app.models.patient import Patient
from app.models.rbac import Permission, Role, RolePermission, UserRole
from app.models.user import User


async def role_codes_for(db: AsyncSession, user_id: uuid.UUID) -> set[str]:
    result = await db.scalars(
        select(Role.code).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user_id)
    )
    return set(result.all())


def _principal_query(user_filter):
    """User, roles, permissions and doctor/patient ids in ONE query: each
    database round trip costs ~120 ms against the hosted database, and this
    runs on every authenticated request."""
    doctor_id = select(Doctor.id).where(Doctor.user_id == User.id).scalar_subquery()
    patient_id = select(Patient.id).where(Patient.user_id == User.id).scalar_subquery()
    return (
        select(User, Role.code, Permission.code, doctor_id, patient_id)
        .outerjoin(UserRole, UserRole.user_id == User.id)
        .outerjoin(Role, Role.id == UserRole.role_id)
        .outerjoin(RolePermission, RolePermission.role_id == Role.id)
        .outerjoin(Permission, Permission.id == RolePermission.permission_id)
        .where(user_filter)
    )


def _principal(rows) -> Principal | None:
    user, doctor_id, patient_id = None, None, None
    roles: set[str] = set()
    permissions: set[str] = set()
    for row_user, role_code, permission_code, row_doctor_id, row_patient_id in rows:
        user, doctor_id, patient_id = row_user, row_doctor_id, row_patient_id
        if role_code is not None:
            roles.add(role_code)
        if permission_code is not None:
            permissions.add(permission_code)
    if user is None:
        return None
    return Principal(
        user=user,
        roles=frozenset(roles),
        permissions=frozenset(permissions),
        doctor_id=doctor_id,
        patient_id=patient_id,
    )


async def load_principal(db: AsyncSession, user: User) -> Principal:
    """Resolve roles and permissions from the database: a role change or
    deactivation takes effect on the very next request."""
    return _principal(await db.execute(_principal_query(User.id == user.id)))


async def load_principal_by_id(db: AsyncSession, user_id: uuid.UUID) -> Principal | None:
    """The signed-in caller, read fresh in a single query (None if no such user)."""
    return _principal(await db.execute(_principal_query(User.id == user_id)))


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
