from sqlalchemy import select

from app.core.permissions import Perm, RoleCode
from app.models.rbac import Permission, Role


async def test_every_permission_in_code_is_seeded(db_session):
    seeded = set((await db_session.scalars(select(Permission.code))).all())
    missing = {p.value for p in Perm} - seeded
    assert missing == set(), f"Perm values without a seeding migration: {missing}"


async def test_every_built_in_role_is_seeded(db_session):
    seeded = set((await db_session.scalars(select(Role.code))).all())
    assert {r.value for r in RoleCode} <= seeded


async def test_admin_holds_every_non_relationship_permission(client, auth_headers):
    """Admins get every capability except those scoped to *one's own* records,
    to patients one treats, or to clinical work — those belong to patients and
    doctors. An administrator does not run consultations."""
    clinician_only = {Perm.appointment_consult.value}
    me = await client.get("/api/v1/auth/me", headers=await auth_headers(RoleCode.admin))
    expected = {
        p.value for p in Perm if not p.value.endswith(("_own", "_assigned")) and p.value not in clinician_only
    }
    assert expected <= set(me.json()["permissions"])


async def test_user_without_roles_has_no_permissions(client, make_user):
    from tests.conftest import login

    user = await make_user(role=None)
    me = await client.get("/api/v1/auth/me", headers=await login(client, user.email))
    assert me.json()["roles"] == [] and me.json()["permissions"] == []


async def test_permissions_are_read_per_request_not_from_the_token(client, make_user, db_session):
    """Revoking a role takes effect on the next request, even with an unexpired token."""
    from app.models.rbac import UserRole
    from tests.conftest import login

    user = await make_user(RoleCode.admin)
    headers = await login(client, user.email)
    assert (await client.post("/api/v1/departments/", json={"name": "Before"}, headers=headers)).status_code == 201

    link = await db_session.scalar(select(UserRole).where(UserRole.user_id == user.id))
    await db_session.delete(link)
    await db_session.flush()

    assert (await client.post("/api/v1/departments/", json={"name": "After"}, headers=headers)).status_code == 403
