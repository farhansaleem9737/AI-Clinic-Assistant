import uuid

import pytest

from app.core.permissions import RoleCode
from tests.conftest import TEST_PASSWORD, login

USERS = "/api/v1/users/"


@pytest.fixture
async def admin(auth_headers):
    return await auth_headers(RoleCode.admin)


async def test_anonymous_is_401(client):
    assert (await client.get(USERS)).status_code == 401


@pytest.mark.parametrize("role", [RoleCode.patient, RoleCode.doctor, RoleCode.receptionist])
async def test_non_admin_roles_are_403(client, auth_headers, role):
    headers = await auth_headers(role)
    assert (await client.get(USERS, headers=headers)).status_code == 403
    body = {"name": "X", "email": "x@example.com", "password": "pw-12345678", "roles": ["admin"]}
    assert (await client.post(USERS, json=body, headers=headers)).status_code == 403


async def test_admin_creates_staff_account_that_can_log_in(client, admin):
    body = {"name": "Rita Reception", "email": "rita@example.com", "password": "pw-12345678", "roles": ["receptionist"]}
    created = await client.post(USERS, json=body, headers=admin)
    assert created.status_code == 201
    assert created.json()["roles"] == ["receptionist"]

    me = await client.get("/api/v1/auth/me", headers=await login(client, "rita@example.com", "pw-12345678"))
    assert me.json()["roles"] == ["receptionist"]


async def test_create_with_unknown_role_is_rejected_and_nothing_is_saved(client, admin):
    body = {"name": "X", "email": "ghost@example.com", "password": "pw-12345678", "roles": ["wizard"]}
    response = await client.post(USERS, json=body, headers=admin)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "UNKNOWN_ROLE"

    listed = await client.get(USERS, params={"q": "ghost"}, headers=admin)
    assert listed.json()["total"] == 0


async def test_create_duplicate_email_is_409(client, admin, make_user):
    existing = await make_user()
    body = {"name": "X", "email": existing.email, "password": "pw-12345678", "roles": ["patient"]}
    assert (await client.post(USERS, json=body, headers=admin)).status_code == 409


async def test_user_create_without_assign_role_permission_cannot_grant_roles(client, make_role, make_user):
    await make_role("user_clerk", ["user:create", "user:read"])
    clerk = await make_user("user_clerk")
    headers = await login(client, clerk.email)
    body = {"name": "X", "email": "escalate@example.com", "password": "pw-12345678", "roles": ["admin"]}
    assert (await client.post(USERS, json=body, headers=headers)).status_code == 403


async def test_list_search_filter_and_paginate_in_sql(client, admin, make_user):
    for i in range(5):
        await make_user(RoleCode.doctor, email=f"searchdoc{i}@example.com", name=f"Searchable Doc {i}")
    await make_user(RoleCode.patient, email="searchpat@example.com", name="Searchable Patient")

    page1 = await client.get(USERS, params={"q": "searchable", "page_size": 2}, headers=admin)
    assert page1.status_code == 200
    assert page1.json()["total"] == 6
    assert len(page1.json()["items"]) == 2

    page3 = await client.get(USERS, params={"q": "searchable", "page_size": 2, "page": 3}, headers=admin)
    assert len(page3.json()["items"]) == 2
    assert {u["id"] for u in page1.json()["items"]}.isdisjoint({u["id"] for u in page3.json()["items"]})

    doctors = await client.get(USERS, params={"q": "searchable", "role": "doctor"}, headers=admin)
    assert doctors.json()["total"] == 5


async def test_page_size_is_capped(client, admin):
    assert (await client.get(USERS, params={"page_size": 1000}, headers=admin)).status_code == 422


async def test_deactivation_ends_sessions_and_blocks_login(client, admin, make_user):
    target = await make_user(RoleCode.receptionist)
    # Read before any failing request: a rollback expires loaded objects.
    target_id, target_email = target.id, target.email
    login_response = await client.post("/api/v1/auth/login", json={"email": target_email, "password": TEST_PASSWORD})
    target_headers = {"Authorization": f"Bearer {login_response.json()['access_token']}"}

    response = await client.post(f"{USERS}{target_id}/deactivate", headers=admin)
    assert response.status_code == 200 and response.json()["is_active"] is False

    assert (await client.get("/api/v1/auth/me", headers=target_headers)).status_code == 401
    relog = await client.post("/api/v1/auth/login", json={"email": target_email, "password": TEST_PASSWORD})
    assert relog.status_code == 403

    reactivated = await client.post(f"{USERS}{target_id}/activate", headers=admin)
    assert reactivated.json()["is_active"] is True


async def test_admin_cannot_deactivate_or_demote_self(client, make_user):
    me = await make_user(RoleCode.admin)
    me_id = me.id
    await make_user(RoleCode.admin)  # another admin exists, so only the self-rule applies
    headers = await login(client, me.email)

    response = await client.post(f"{USERS}{me_id}/deactivate", headers=headers)
    assert response.json()["error"]["code"] == "SELF_DEACTIVATION"

    response = await client.put(f"{USERS}{me_id}/roles", json={"roles": ["doctor"]}, headers=headers)
    assert response.json()["error"]["code"] == "SELF_DEMOTION"


async def test_last_active_admin_cannot_be_removed(client, make_role, make_user):
    await make_role("user_manager", ["user:read", "user:deactivate", "user:assign_role"])
    manager = await make_user("user_manager")
    only_admin_id = (await make_user(RoleCode.admin)).id
    headers = await login(client, manager.email)

    response = await client.post(f"{USERS}{only_admin_id}/deactivate", headers=headers)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "LAST_ADMIN"

    response = await client.put(f"{USERS}{only_admin_id}/roles", json={"roles": ["doctor"]}, headers=headers)
    assert response.json()["error"]["code"] == "LAST_ADMIN"


async def test_set_roles_replaces_the_role_set(client, admin, make_user):
    user = await make_user(RoleCode.patient)
    response = await client.put(f"{USERS}{user.id}/roles", json={"roles": ["doctor", "receptionist"]}, headers=admin)
    assert response.status_code == 200
    assert response.json()["roles"] == ["doctor", "receptionist"]

    me = await client.get("/api/v1/auth/me", headers=await login(client, user.email))
    assert "doctor:update_own" in me.json()["permissions"]


async def test_update_user_and_unknown_user(client, admin, make_user):
    user = await make_user()
    response = await client.patch(f"{USERS}{user.id}", json={"name": "Renamed"}, headers=admin)
    assert response.json()["name"] == "Renamed"
    assert (await client.get(f"{USERS}{uuid.uuid4()}", headers=admin)).status_code == 404


async def test_roles_endpoint_lists_roles_with_permissions(client, admin):
    response = await client.get("/api/v1/roles/", headers=admin)
    assert response.status_code == 200
    roles = {r["code"]: r for r in response.json()}
    assert {"patient", "doctor", "receptionist", "admin"} <= set(roles)
    assert "user:create" in roles["admin"]["permissions"]
