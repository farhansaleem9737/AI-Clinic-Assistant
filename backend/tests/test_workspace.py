"""Notifications, global search and clinic settings (D86)."""

from datetime import datetime

from app.core.permissions import RoleCode

NOTIFICATIONS = "/api/v1/notifications"
SEARCH = "/api/v1/search"
SETTINGS = "/api/v1/settings/clinic"


def iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


async def book(client, clinic, headers, patient=None, days=2, hhmm="10:00"):
    body = {"doctor_id": str(clinic.doctor_a.id), "starts_at": iso(clinic.slot(days, hhmm))}
    if patient is not None:
        body["patient_id"] = str(patient.id)
    response = await client.post("/api/v1/appointments/", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


# ---- notifications --------------------------------------------------------------------------


async def test_a_booking_notifies_the_doctor_without_patient_details(client, clinic):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    appointment_id = await book(client, clinic, alice)
    dr_a = await clinic.headers_for(clinic.doctor_a.user_id)
    body = (await client.get(NOTIFICATIONS, headers=dr_a)).json()
    assert body["unread"] == 1
    [note] = body["items"]
    assert note["type"] == "appointment_booked" and note["link"] == f"/appointments/{appointment_id}"
    assert "Alice" not in note["message"] and note["read_at"] is None
    # The patient who booked is not told about their own action.
    assert (await client.get(f"{NOTIFICATIONS}/unread-count", headers=alice)).json() == {"unread": 0}


async def test_a_cancellation_notifies_everyone_but_whoever_cancelled(client, clinic):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    appointment_id = await book(client, clinic, alice)
    reception = await clinic.headers_for(clinic.receptionist.id)
    cancelled = await client.post(
        f"/api/v1/appointments/{appointment_id}/status",
        json={"status": "cancelled", "cancellation_reason": "clinic_decision"},
        headers=reception,
    )
    assert cancelled.status_code == 200
    alice_notes = (await client.get(NOTIFICATIONS, headers=alice)).json()["items"]
    assert [n["type"] for n in alice_notes] == ["appointment_cancelled"]
    dr_a = await clinic.headers_for(clinic.doctor_a.user_id)
    assert {n["type"] for n in (await client.get(NOTIFICATIONS, headers=dr_a)).json()["items"]} == {
        "appointment_booked",
        "appointment_cancelled",
    }
    assert (await client.get(f"{NOTIFICATIONS}/unread-count", headers=reception)).json() == {"unread": 0}


async def test_doctor_applications_notify_the_reviewers(client, clinic):
    registered = await client.post(
        "/api/v1/auth/register",
        json={"account_type": "doctor", "name": "Dr New Applicant", "email": "new.applicant@example.com", "password": "pw-123456"},
    )
    assert registered.status_code == 201
    admin = await clinic.headers_for(clinic.admin.id)
    [note] = (await client.get(NOTIFICATIONS, headers=admin)).json()["items"]
    assert note["type"] == "doctor_application" and "Dr New Applicant" in note["message"]
    reception = await clinic.headers_for(clinic.receptionist.id)
    assert (await client.get(NOTIFICATIONS, headers=reception)).json()["items"] == []


async def test_reading_notifications_is_limited_to_the_owner(client, clinic):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    await book(client, clinic, alice)
    dr_a = await clinic.headers_for(clinic.doctor_a.user_id)
    [note] = (await client.get(NOTIFICATIONS, headers=dr_a)).json()["items"]
    # Someone else's notification does not exist for them.
    assert (await client.post(f"{NOTIFICATIONS}/{note['id']}/read", headers=alice)).status_code == 404
    read = await client.post(f"{NOTIFICATIONS}/{note['id']}/read", headers=dr_a)
    assert read.status_code == 200 and read.json()["read_at"] is not None
    assert (await client.get(f"{NOTIFICATIONS}/unread-count", headers=dr_a)).json() == {"unread": 0}


async def test_mark_all_read(client, clinic):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    await book(client, clinic, alice, days=2)
    await book(client, clinic, alice, days=3)
    dr_a = await clinic.headers_for(clinic.doctor_a.user_id)
    assert (await client.get(f"{NOTIFICATIONS}/unread-count", headers=dr_a)).json() == {"unread": 2}
    assert (await client.post(f"{NOTIFICATIONS}/read-all", headers=dr_a)).json() == {"unread": 0}
    assert (await client.get(NOTIFICATIONS, headers=dr_a)).json()["unread"] == 0


async def test_notifications_need_a_session(client):
    assert (await client.get(NOTIFICATIONS)).status_code == 401


# ---- global search ----------------------------------------------------------------------


async def test_reception_searches_patients_doctors_and_appointments_but_not_users(client, clinic):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    await book(client, clinic, alice)
    reception = await clinic.headers_for(clinic.receptionist.id)
    body = (await client.get(SEARCH, params={"q": "alice"}, headers=reception)).json()
    assert [p["name"].split()[0] for p in body["patients"]] == ["Alice"]
    assert body["patients"][0]["mrn"].startswith("MRN")
    assert len(body["appointments"]) == 1 and body["appointments"][0]["doctor_name"] == "Doctor Alpha"
    assert body["users"] is None  # needs user:read
    doctors = (await client.get(SEARCH, params={"q": "alpha"}, headers=reception)).json()["doctors"]
    assert [d["name"] for d in doctors] == ["Doctor Alpha"]


async def test_patients_only_find_their_own_records(client, clinic):
    bob = await clinic.headers_for(clinic.patient_b.user_id)
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    await book(client, clinic, alice)
    body = (await client.get(SEARCH, params={"q": "alpha"}, headers=bob)).json()
    assert body["patients"] is None and body["users"] is None
    assert body["appointments"] == []  # Alice's appointment with Dr Alpha is invisible to Bob
    assert [d["name"] for d in body["doctors"]] == ["Doctor Alpha"]


async def test_admins_also_find_users_without_secrets(client, clinic):
    admin = await clinic.headers_for(clinic.admin.id)
    response = await client.get(SEARCH, params={"q": "receptionist"}, headers=admin)
    users = response.json()["users"]
    assert users and users[0]["roles"] == ["receptionist"]
    assert "password" not in response.text


async def test_search_needs_two_characters(client, auth_headers):
    headers = await auth_headers(RoleCode.receptionist)
    assert (await client.get(SEARCH, params={"q": "a"}, headers=headers)).status_code == 422
    assert (await client.get(SEARCH, params={"q": "ab"})).status_code == 401


# ---- clinic settings -----------------------------------------------------------------------


async def test_admins_edit_the_clinic_details_and_everyone_reads_them(client, clinic):
    admin = await clinic.headers_for(clinic.admin.id)
    saved = await client.put(
        SETTINGS,
        json={"clinic_name": "  Riverside Clinic ", "contact_phone": "+92 42 111 222", "contact_email": "desk@riverside.example"},
        headers=admin,
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["clinic_name"] == "Riverside Clinic" and body["updated_at"]
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    read = (await client.get(SETTINGS, headers=alice)).json()
    assert read["contact_email"] == "desk@riverside.example"
    assert read["operational"]["timezone"] == "Asia/Karachi" and read["operational"]["default_slot_minutes"] == 30

    cleared = await client.put(SETTINGS, json={"contact_phone": ""}, headers=admin)
    assert cleared.json()["contact_phone"] is None and cleared.json()["clinic_name"] == "Riverside Clinic"


async def test_only_admins_may_change_settings(client, clinic):
    for user_id in (clinic.receptionist.id, clinic.doctor_a.user_id, clinic.patient_a.user_id):
        headers = await clinic.headers_for(user_id)
        assert (await client.put(SETTINGS, json={"clinic_name": "Mine"}, headers=headers)).status_code == 403


async def test_settings_are_validated_and_secrets_are_not_settable(client, clinic):
    admin = await clinic.headers_for(clinic.admin.id)
    assert (await client.put(SETTINGS, json={"contact_email": "nope"}, headers=admin)).status_code == 422
    assert (await client.put(SETTINGS, json={"contact_phone": "call us"}, headers=admin)).status_code == 422
    response = await client.put(SETTINGS, json={"secret_key": "x", "database_url": "y", "clinic_name": "Ok"}, headers=admin)
    assert response.status_code == 200
    assert "secret_key" not in response.text and "database_url" not in response.text
