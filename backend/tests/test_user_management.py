"""Admin > Users (D88): listing with search, filters, sorting and paging;
bulk activation; what a user row may and may not contain."""

import os
from datetime import date, datetime, timedelta, timezone

import pytest

from app.core.permissions import RoleCode
from app.models import Patient, User
from app.services import rbac_service
from tests.conftest import login

USERS = "/api/v1/users/"


@pytest.fixture
async def admin(make_user, client):
    user = await make_user(RoleCode.admin)
    return user, await login(client, user.email)


@pytest.fixture
def tag():
    return f"zz{os.urandom(3).hex()}"


async def listed(client, headers, **params):
    response = await client.get(USERS, params=params, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def names(page):
    return [u["name"] for u in page["items"]]


async def test_rows_carry_profile_phone_and_never_secrets(client, db_session, admin, make_user, tag):
    patient_user = await make_user(RoleCode.patient, name=f"{tag} Pat")
    db_session.add(Patient(user_id=patient_user.id, first_name="Pat", last_name="X", date_of_birth=date(1990, 1, 1), phone="+92 300 5550101"))
    await db_session.commit()
    page = await listed(client, admin[1], q=tag)
    row = page["items"][0]
    assert row["phone"] == "+92 300 5550101"
    assert row["patient_id"] is not None and row["doctor_id"] is None
    assert row["photo_url"] is None
    text = str(page).lower()
    for secret in ("password", "hash", "token"):
        assert secret not in text


async def test_search_matches_name_email_and_phone_case_insensitively(client, db_session, admin, make_user, tag):
    await make_user(RoleCode.receptionist, name=f"{tag} Alpha")
    await make_user(RoleCode.receptionist, name="Someone", email=f"{tag}-beta@example.com")
    phoned = await make_user(RoleCode.patient, name="Gamma Person")
    db_session.add(Patient(user_id=phoned.id, first_name="G", last_name="P", date_of_birth=date(1990, 1, 1), phone=f"0300-{tag}"))
    await db_session.commit()
    assert sorted(names(await listed(client, admin[1], q=tag.upper()))) == ["Gamma Person", "Someone", f"{tag} Alpha"]


async def test_role_filter_counts_multi_role_users_under_each_role(client, db_session, admin, make_user, tag):
    both = await make_user(RoleCode.patient, name=f"{tag} Both")
    await rbac_service.grant_roles(db_session, both.id, [RoleCode.receptionist])
    await db_session.commit()
    await make_user(RoleCode.patient, name=f"{tag} Patient")
    await make_user(RoleCode.doctor, name=f"{tag} Doctor")
    assert names(await listed(client, admin[1], q=tag, role="patient")) == [f"{tag} Both", f"{tag} Patient"]
    receptionists = await listed(client, admin[1], q=tag, role="receptionist")
    assert names(receptionists) == [f"{tag} Both"]
    assert receptionists["items"][0]["roles"] == ["patient", "receptionist"]  # no role dropped


async def test_status_and_joined_date_filters_combine(client, db_session, admin, make_user, tag):
    old = await make_user(RoleCode.patient, name=f"{tag} Old")
    await make_user(RoleCode.patient, name=f"{tag} New")
    await make_user(RoleCode.patient, name=f"{tag} Off", is_active=False)
    stored = await db_session.get(User, old.id)
    stored.created_at = datetime(2026, 1, 10, 12, tzinfo=timezone.utc)
    await db_session.commit()

    assert names(await listed(client, admin[1], q=tag, is_active="false")) == [f"{tag} Off"]
    january = await listed(client, admin[1], q=tag, joined_from="2026-01-01", joined_to="2026-01-31")
    assert names(january) == [f"{tag} Old"]
    today = (datetime.now(timezone.utc) + timedelta(hours=5)).date().isoformat()  # clinic is Asia/Karachi in tests
    recent = await listed(client, admin[1], q=tag, joined_from=today, is_active="true")
    assert names(recent) == [f"{tag} New"]
    bad = await client.get(USERS, params={"joined_from": "2026-02-01", "joined_to": "2026-01-01"}, headers=admin[1])
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "INVALID_DATE_RANGE"


async def test_sorting_is_server_side_and_stable(client, db_session, admin, make_user, tag):
    a = await make_user(RoleCode.patient, name=f"{tag} a", email=f"{tag}-c@example.com")
    b = await make_user(RoleCode.doctor, name=f"{tag} B", email=f"{tag}-a@example.com", is_active=False)
    c = await make_user(RoleCode.receptionist, name=f"{tag} c", email=f"{tag}-b@example.com")
    for user, day in ((a, 3), (b, 1), (c, 2)):
        stored = await db_session.get(User, user.id)
        stored.created_at = datetime(2026, 1, day, tzinfo=timezone.utc)
    await db_session.commit()

    async def order(sort):
        return names(await listed(client, admin[1], q=tag, sort=sort))

    assert await order("name") == [f"{tag} a", f"{tag} B", f"{tag} c"]  # case-insensitive
    assert await order("-name") == [f"{tag} c", f"{tag} B", f"{tag} a"]
    assert await order("email") == [f"{tag} B", f"{tag} c", f"{tag} a"]
    assert await order("role") == [f"{tag} B", f"{tag} c", f"{tag} a"]  # doctor, receptionist, patient
    assert await order("-role") == [f"{tag} a", f"{tag} c", f"{tag} B"]
    assert await order("status") == [f"{tag} a", f"{tag} c", f"{tag} B"]  # active first
    assert await order("-created_at") == [f"{tag} a", f"{tag} c", f"{tag} B"]
    assert (await client.get(USERS, params={"sort": "password"}, headers=admin[1])).status_code == 422


async def test_pagination_reports_real_totals_without_overlap(client, admin, make_user, tag):
    for i in range(12):
        await make_user(RoleCode.patient, name=f"{tag} {i:02d}")
    first = await listed(client, admin[1], q=tag, page_size=10, page=1)
    second = await listed(client, admin[1], q=tag, page_size=10, page=2)
    assert first["total"] == 12 and first["total_pages"] == 2
    assert len(first["items"]) == 10 and len(second["items"]) == 2
    assert not set(names(first)) & set(names(second))


async def test_bulk_status_applies_every_rule_per_user(client, admin, make_role, make_user):
    me, headers = admin
    ok_user = await make_user(RoleCode.patient)
    other_admin = await make_user(RoleCode.admin)
    results = await client.post(
        f"{USERS}bulk-status", json={"user_ids": [str(ok_user.id), str(me.id), str(other_admin.id), str(ok_user.id)], "is_active": False},
        headers=headers,
    )
    assert results.status_code == 200, results.text
    by_id = {r["user_id"]: r for r in results.json()}
    assert len(results.json()) == 3  # duplicates once
    assert by_id[str(ok_user.id)]["ok"] is True
    assert by_id[str(me.id)]["code"] == "SELF_DEACTIVATION"
    assert by_id[str(other_admin.id)]["ok"] is True  # `me` is still an active admin

    # The deactivated user's session ends at once.
    assert (await client.post("/api/v1/auth/login", json={"email": ok_user.email, "password": "Str0ng-test-password"})).status_code == 403


async def test_bulk_status_never_removes_the_last_administrator(client, make_role, make_user):
    await make_role("user_manager", ["user:read", "user:deactivate"])
    manager = await make_user("user_manager")
    admins = [await make_user(RoleCode.admin) for _ in range(2)]
    headers = await login(client, manager.email)
    results = (await client.post(
        f"{USERS}bulk-status", json={"user_ids": [str(a.id) for a in admins], "is_active": False}, headers=headers
    )).json()
    assert [r["ok"] for r in results] == [True, False]
    assert results[1]["code"] == "LAST_ADMIN"


async def test_edit_accepts_only_name_and_email(client, admin, make_user):
    user = await make_user(RoleCode.patient)
    response = await client.patch(f"{USERS}{user.id}", json={"name": "Renamed", "roles": ["admin"]}, headers=admin[1])
    assert response.status_code == 422
    response = await client.patch(f"{USERS}{user.id}", json={"is_active": False}, headers=admin[1])
    assert response.status_code == 422
    assert (await client.patch(f"{USERS}{user.id}", json={"name": "Renamed"}, headers=admin[1])).json()["name"] == "Renamed"


@pytest.mark.parametrize("role", [RoleCode.patient, RoleCode.doctor, RoleCode.receptionist])
async def test_user_management_is_closed_to_other_roles(client, auth_headers, role):
    headers = await auth_headers(role)
    assert (await client.get(USERS, headers=headers)).status_code == 403
    assert (await client.post(f"{USERS}bulk-status", json={"user_ids": [str(os.urandom(16).hex()[:8])], "is_active": False}, headers=headers)).status_code in (403, 422)
