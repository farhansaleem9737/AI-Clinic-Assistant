"""The administrator's dashboard (D85): cumulative clinic totals as of a
date, growth against the end of the previous month, the newest accounts,
and who may see any of it."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select, update

from app.core.permissions import RoleCode
from app.models.appointment import Appointment
from app.models.department import Department
from app.models.doctor import Doctor
from app.models.patient import Patient
from app.models.user import User
from app.services.dashboard_service import growth

URL = "/api/v1/dashboard/admin"
TZ = ZoneInfo("Asia/Karachi")


def kpis(body):
    return {k["key"]: k for k in body["kpis"]}


@pytest.mark.parametrize(
    "total, previous, expected",
    [(12, 10, (20.0, "up")), (8, 10, (-20.0, "down")), (10, 10, (0.0, "flat")), (5, 0, (None, "new")), (0, 0, (0.0, "flat"))],
)
def test_growth_rule(total, previous, expected):
    assert growth(total, previous) == expected


async def test_totals_match_the_tables(client, db_session, clinic):
    admin = await clinic.headers_for(clinic.admin.id)
    body = (await client.get(URL, headers=admin)).json()
    expected = {
        "users": User,
        "doctors": Doctor,
        "patients": Patient,
        "appointments": Appointment,
        "departments": Department,
    }
    got = kpis(body)
    assert list(got) == ["users", "doctors", "patients", "appointments", "departments"]
    for key, model in expected.items():
        assert got[key]["total"] == await db_session.scalar(select(func.count()).select_from(model)), key
    assert body["timezone"] == "Asia/Karachi"


async def test_users_with_several_roles_count_once(client, db_session, clinic, make_user):
    from app.services import rbac_service

    admin = await clinic.headers_for(clinic.admin.id)
    before = kpis((await client.get(URL, headers=admin)).json())["users"]["total"]
    user = await make_user(RoleCode.receptionist)
    await rbac_service.grant_roles(db_session, user.id, [RoleCode.patient])
    await db_session.commit()
    after = kpis((await client.get(URL, headers=admin)).json())["users"]["total"]
    assert after == before + 1


async def test_doctor_applicants_are_users_but_not_doctors(client, clinic):
    admin = await clinic.headers_for(clinic.admin.id)
    before = kpis((await client.get(URL, headers=admin)).json())
    registered = await client.post(
        "/api/v1/auth/register",
        json={"account_type": "doctor", "name": "Dr Pending", "email": "pending@example.com", "password": "pw-123456"},
    )
    assert registered.status_code == 201
    after = kpis((await client.get(URL, headers=admin)).json())
    assert after["users"]["total"] == before["users"]["total"] + 1
    assert after["doctors"]["total"] == before["doctors"]["total"]


async def test_growth_compares_with_the_end_of_last_month(client, db_session, clinic, make_department):
    admin = await clinic.headers_for(clinic.admin.id)
    today = datetime.now(TZ).date()
    last_month = datetime.combine(today.replace(day=1) - timedelta(days=3), datetime.min.time(), tzinfo=TZ)
    old = [await make_department(f"Old {i}") for i in range(2)]
    await db_session.execute(update(Department).where(Department.id.in_([d.id for d in old])).values(created_at=last_month))
    await db_session.commit()
    body = (await client.get(URL, headers=admin)).json()
    departments = kpis(body)["departments"]
    # The clinic fixture's department and nothing else is new this month.
    assert departments["previous"] == 2 and departments["total"] == 3
    assert departments["change_percent"] == 50.0 and departments["trend"] == "up"
    assert body["compared_to"] == (today.replace(day=1) - timedelta(days=1)).isoformat()


async def test_an_earlier_date_leaves_out_later_records(client, db_session, clinic, make_patient):
    admin = await clinic.headers_for(clinic.admin.id)
    today = datetime.now(TZ).date()
    yesterday = today - timedelta(days=1)
    now_total = kpis((await client.get(URL, headers=admin)).json())["patients"]["total"]
    earlier = (await client.get(URL, params={"day": yesterday.isoformat()}, headers=admin)).json()
    assert earlier["date"] == yesterday.isoformat()
    # Every patient in this test was created today.
    assert kpis(earlier)["patients"]["total"] == now_total - 3
    assert kpis(earlier)["patients"]["total"] == 0


async def test_recent_users_newest_first_without_secrets(client, db_session, clinic, make_user):
    admin = await clinic.headers_for(clinic.admin.id)
    newest = await make_user(RoleCode.receptionist, name="Newest Person")
    await db_session.execute(
        update(User).where(User.id == newest.id).values(created_at=datetime.now(timezone.utc) + timedelta(seconds=5))
    )
    await db_session.commit()
    response = await client.get(URL, headers=admin)
    users = response.json()["recent_users"]
    assert len(users) == 5
    assert users[0]["name"] == "Newest Person" and users[0]["roles"] == ["receptionist"] and users[0]["is_active"] is True
    stamps = [u["created_at"] for u in users]
    assert stamps == sorted(stamps, reverse=True)
    for secret in ("password_hash", "$2b$", "refresh"):
        assert secret not in response.text


@pytest.mark.parametrize("role", [RoleCode.receptionist, RoleCode.doctor, RoleCode.patient, RoleCode.doctor_applicant])
async def test_only_administrators(client, auth_headers, role):
    assert (await client.get(URL, headers=await auth_headers(role))).status_code == 403


async def test_requires_a_session(client):
    assert (await client.get(URL)).status_code == 401
