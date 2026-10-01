from datetime import datetime, timedelta

import pytest

from app.core.permissions import RoleCode
from app.models.doctor import Doctor
from app.models.patient import Patient
from app.models.user import User
from tests.conftest import login

SUMMARY = "/api/v1/dashboard/summary"
APPOINTMENTS = "/api/v1/appointments/"


def iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


@pytest.fixture
async def scene(client, clinic):
    """Alice: two appointments with Dr A (one later cancelled) and one with
    Dr B. Bob: one with Dr A. All on day +3."""
    headers = {
        "alice": await clinic.headers_for(clinic.patient_a.user_id),
        "bob": await clinic.headers_for(clinic.patient_b.user_id),
        "dr_a": await clinic.headers_for(clinic.doctor_a.user_id),
        "dr_b": await clinic.headers_for(clinic.doctor_b.user_id),
        "reception": await clinic.headers_for(clinic.receptionist.id),
        "admin": await clinic.headers_for(clinic.admin.id),
    }

    async def book(who, doctor, hhmm):
        response = await client.post(
            APPOINTMENTS, json={"doctor_id": str(doctor.id), "starts_at": iso(clinic.slot(3, hhmm))}, headers=headers[who]
        )
        assert response.status_code == 201, response.text
        return response.json()["id"]

    a1 = await book("alice", clinic.doctor_a, "09:00")
    a2 = await book("alice", clinic.doctor_a, "10:00")
    await book("alice", clinic.doctor_b, "11:00")
    await book("bob", clinic.doctor_a, "12:00")
    cancelled = await client.post(
        f"{APPOINTMENTS}{a2}/status", json={"status": "cancelled", "cancellation_reason": "patient_request"},
        headers=headers["alice"],
    )
    assert cancelled.status_code == 200
    return headers, a1


async def summary(client, headers) -> dict:
    response = await client.get(SUMMARY, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


# ---- access -------------------------------------------------------------------------


async def test_anonymous_is_401(client):
    assert (await client.get(SUMMARY)).status_code == 401


async def test_deactivated_user_is_401(client, db_session, make_user):
    user = await make_user(RoleCode.patient)
    headers = await login(client, user.email)
    (await db_session.get(User, user.id)).is_active = False
    await db_session.commit()
    assert (await client.get(SUMMARY, headers=headers)).status_code == 401


async def test_user_without_permissions_gets_only_the_account_section(client, make_user):
    user = await make_user(role=None)
    body = await summary(client, await login(client, user.email))
    assert body["account"] == {"is_active": True, "roles": []}
    assert body["patient"] is None and body["doctor"] is None
    assert body["front_desk"] is None and body["overview"] is None


# ---- patient ---------------------------------------------------------------------------


async def test_patient_counts_cover_only_their_own_appointments(client, scene):
    headers, _ = scene
    alice = await summary(client, headers["alice"])
    assert alice["patient"] == {
        "has_profile": True,
        "profile_active": True,
        "upcoming_appointments": 2,  # the cancelled one is not upcoming
        "total_appointments": 3,
        "my_doctors": 2,
    }
    bob = await summary(client, headers["bob"])
    assert bob["patient"]["total_appointments"] == 1
    assert bob["patient"]["my_doctors"] == 1


async def test_patient_gets_no_staff_sections(client, scene):
    headers, _ = scene
    body = await summary(client, headers["alice"])
    assert body["doctor"] is None and body["front_desk"] is None and body["overview"] is None


async def test_my_doctors_ignores_doctors_seen_only_in_cancelled_appointments(client, clinic, scene):
    headers, _ = scene
    listed = await client.get(APPOINTMENTS, params={"doctor_id": str(clinic.doctor_b.id)}, headers=headers["alice"])
    only_with_b = listed.json()["items"][0]["id"]
    await client.post(
        f"{APPOINTMENTS}{only_with_b}/status", json={"status": "cancelled", "cancellation_reason": "patient_request"},
        headers=headers["alice"],
    )
    assert (await summary(client, headers["alice"]))["patient"]["my_doctors"] == 1


async def test_patient_login_without_profile(client, make_user):
    user = await make_user(RoleCode.patient)
    body = await summary(client, await login(client, user.email))
    assert body["patient"] == {
        "has_profile": False, "profile_active": False, "upcoming_appointments": 0, "total_appointments": 0, "my_doctors": 0,
    }


async def test_deactivated_patient_record_is_reported(client, db_session, clinic):
    headers = await clinic.headers_for(clinic.patient_a.user_id)
    (await db_session.get(Patient, clinic.patient_a.id)).is_active = False
    await db_session.commit()
    body = await summary(client, headers)
    assert body["account"]["is_active"] is True
    assert body["patient"]["profile_active"] is False


async def test_finished_appointments_are_not_upcoming(client, clinic, scene, freeze_clock):
    headers, _ = scene
    freeze_clock(clinic.slot(3, "09:45"))  # 09:00-09:30 is over; 11:00 still ahead
    assert (await summary(client, headers["alice"]))["patient"]["upcoming_appointments"] == 1


async def test_upcoming_list_matches_the_upcoming_count(client, clinic, scene, freeze_clock):
    """The dashboard lists exactly the appointments its "upcoming" card counts."""
    headers, _ = scene
    for now in (clinic.slot(0, "08:00"), clinic.slot(3, "09:45")):
        freeze_clock(now)
        count = (await summary(client, headers["alice"]))["patient"]["upcoming_appointments"]
        listed = await client.get(APPOINTMENTS, params={"scope": "upcoming", "page_size": 50}, headers=headers["alice"])
        items = listed.json()["items"]
        assert listed.json()["total"] == count == len(items)
        assert [i["starts_at"] for i in items] == sorted(i["starts_at"] for i in items)  # soonest first
        assert all(i["status"] not in {"cancelled", "completed", "no_show"} for i in items)
        assert all(i["patient"]["id"] == str(clinic.patient_a.id) for i in items)  # only Alice's own


async def test_patient_cannot_list_another_patients_appointments(client, clinic, scene):
    headers, _ = scene
    response = await client.get(
        APPOINTMENTS, params={"patient_id": str(clinic.patient_b.id), "scope": "upcoming"}, headers=headers["alice"]
    )
    assert response.status_code == 200
    assert response.json()["items"] == []


# ---- doctor ----------------------------------------------------------------------------


async def test_doctor_sees_only_their_own_workload(client, clinic, scene, freeze_clock):
    headers, a1 = scene
    freeze_clock(clinic.slot(3, "08:40"))
    await client.post(f"{APPOINTMENTS}{a1}/status", json={"status": "checked_in"}, headers=headers["reception"])

    dr_a = (await summary(client, headers["dr_a"]))["doctor"]
    assert dr_a["has_profile"] is True
    assert dr_a["today"]["date"] == (clinic.today + timedelta(days=3)).isoformat()
    assert dr_a["today"]["timezone"] == "Asia/Karachi"
    assert dr_a["today"]["total"] == 3  # incl. the cancelled one
    assert dr_a["today"]["checked_in"] == 1
    assert dr_a["today"]["awaiting_check_in"] == 1
    assert dr_a["today"]["cancelled"] == 1
    assert dr_a["upcoming_appointments"] == 2
    assert dr_a["my_patients"] == 2

    dr_b = (await summary(client, headers["dr_b"]))["doctor"]
    assert dr_b["today"]["total"] == 1 and dr_b["my_patients"] == 1


async def test_doctor_today_is_empty_on_other_days(client, scene):
    headers, _ = scene
    today = (await summary(client, headers["dr_a"]))["doctor"]["today"]
    assert today["total"] == 0  # the appointments are three days away


async def test_doctor_gets_no_clinic_wide_sections(client, scene):
    headers, _ = scene
    body = await summary(client, headers["dr_a"])
    assert body["patient"] is None and body["front_desk"] is None and body["overview"] is None


async def test_doctor_login_without_profile(client, auth_headers):
    body = await summary(client, await auth_headers(RoleCode.doctor))
    assert body["doctor"] == {"has_profile": False, "today": None, "upcoming_appointments": 0, "my_patients": 0}


# ---- receptionist and admin --------------------------------------------------------------


async def test_receptionist_sees_clinic_workload_but_not_user_totals(client, clinic, scene, freeze_clock):
    headers, _ = scene
    freeze_clock(clinic.slot(3, "08:00"))
    body = await summary(client, headers["reception"])
    assert body["front_desk"]["today"]["total"] == 4
    assert body["front_desk"]["today"]["awaiting_check_in"] == 3
    assert body["front_desk"]["today"]["cancelled"] == 1
    assert body["front_desk"]["upcoming_appointments"] == 3
    assert body["patient"] is None and body["doctor"] is None

    overview = body["overview"]
    assert overview["patients_total"] >= 3 and overview["doctors_active"] >= 2
    assert overview["appointments_total"] == 4
    # No user:read, no department:manage.
    assert overview["users_total"] is None and overview["users_active"] is None
    assert overview["departments_active"] is None


async def test_admin_overview_counts_are_correct(client, db_session, clinic, scene):
    headers, _ = scene
    before = (await summary(client, headers["admin"]))["overview"]
    assert before["users_total"] == before["users_active"]
    assert before["appointments_total"] == 4 and before["departments_active"] >= 1

    (await db_session.get(User, clinic.receptionist.id)).is_active = False
    (await db_session.get(Doctor, clinic.doctor_b.id)).is_active = False
    (await db_session.get(Patient, clinic.walk_in.id)).is_active = False
    await db_session.commit()

    after = (await summary(client, headers["admin"]))["overview"]
    assert after["users_total"] == before["users_total"]
    assert after["users_active"] == before["users_active"] - 1
    assert after["doctors_active"] == before["doctors_active"] - 1
    assert after["patients_total"] == before["patients_total"]
    assert after["patients_active"] == before["patients_active"] - 1


async def test_sections_follow_permissions_not_role_names(client, make_role, make_user, scene):
    """A custom role with only appointment:read_any gets the front-desk
    section and the appointment total, and nothing else."""
    await make_role("scheduler", ["appointment:read_any"])
    user = await make_user("scheduler")
    body = await summary(client, await login(client, user.email))
    assert body["front_desk"] is not None
    assert body["overview"] == {
        "users_total": None, "users_active": None, "doctors_active": None, "departments_active": None,
        "patients_total": None, "patients_active": None, "appointments_total": 4,
    }


# ---- appointment location ------------------------------------------------------------------


async def test_room_number_is_shown_only_on_authorised_appointments(client, db_session, clinic, scene):
    headers, a1 = scene
    (await db_session.get(Doctor, clinic.doctor_a.id)).room_number = "B-12"
    (await db_session.get(Doctor, clinic.doctor_a.id)).phone = "555-0100"
    await db_session.commit()

    # The patient, the doctor and reception see where the appointment is.
    for who in ("alice", "dr_a", "reception"):
        body = (await client.get(f"{APPOINTMENTS}{a1}", headers=headers[who])).json()
        assert body["doctor"]["room_number"] == "B-12"
    own = (await client.get(f"{APPOINTMENTS}{a1}", headers=headers["alice"])).text
    assert "555-0100" not in own  # no other staff-only doctor field comes with it

    # Another patient cannot reach the appointment at all …
    assert (await client.get(f"{APPOINTMENTS}{a1}", headers=headers["bob"])).status_code == 404
    # … and the public directory still does not publish the room.
    public = await client.get(f"/api/v1/public/doctors/{clinic.doctor_a.id}")
    assert "room_number" not in public.json() and "B-12" not in public.text
