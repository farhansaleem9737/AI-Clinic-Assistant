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
        json={"account_type": "doctor", "name": "Dr New Applicant", "email": "new.applicant@example.com", "password": "pw-123456", "date_of_birth": "1985-03-02", "gender": "female"},
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


async def test_patients_search_only_doctors_and_departments(client, clinic, make_department):
    await make_department("Cardiology")
    await make_department("Cardiac Archive", is_active=False)  # hidden: inactive
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    await book(client, clinic, alice)
    bob = await clinic.headers_for(clinic.patient_b.user_id)

    body = (await client.get(SEARCH, params={"q": "alpha"}, headers=bob)).json()
    assert body["categories"] == ["doctors", "departments"]
    assert [d["name"] for d in body["doctors"]] == ["Doctor Alpha"]
    # Not even their own appointments or profile: those have their own pages.
    assert body["patients"] is None and body["appointments"] is None and body["users"] is None

    cardio = (await client.get(SEARCH, params={"q": "cardi"}, headers=bob)).json()
    assert [d["name"] for d in cardio["departments"]] == ["Cardiology"]
    # Searching another patient's name finds nothing to open.
    alice_search = (await client.get(SEARCH, params={"q": "alice"}, headers=bob)).json()
    assert alice_search["patients"] is None and alice_search["appointments"] is None


async def test_reception_searches_patients_doctors_and_departments(client, clinic):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    await book(client, clinic, alice)
    reception = await clinic.headers_for(clinic.receptionist.id)
    body = (await client.get(SEARCH, params={"q": "alice"}, headers=reception)).json()
    assert body["categories"] == ["patients", "doctors", "departments"]
    assert [p["name"].split()[0] for p in body["patients"]] == ["Alice"]
    assert set(body["patients"][0]) == {"id", "name", "mrn"}  # no contact details
    assert body["appointments"] is None and body["users"] is None
    doctors = (await client.get(SEARCH, params={"q": "alpha"}, headers=reception)).json()["doctors"]
    assert [d["name"] for d in doctors] == ["Doctor Alpha"]


async def test_doctors_find_only_their_own_patients(client, clinic):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    await book(client, clinic, alice)  # Alice sees Doctor Alpha; Bob sees nobody
    dr_a = await clinic.headers_for(clinic.doctor_a.user_id)
    dr_b = await clinic.headers_for(clinic.doctor_b.user_id)

    mine = (await client.get(SEARCH, params={"q": "alice"}, headers=dr_a)).json()
    assert mine["categories"] == ["patients", "doctors", "departments"]
    assert [p["name"].split()[0] for p in mine["patients"]] == ["Alice"]
    assert mine["appointments"] is None and mine["users"] is None
    assert (await client.get(SEARCH, params={"q": "alice"}, headers=dr_b)).json()["patients"] == []
    assert (await client.get(SEARCH, params={"q": "bob"}, headers=dr_a)).json()["patients"] == []


async def test_admins_also_find_users_and_appointments_without_secrets(client, clinic):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    await book(client, clinic, alice)
    admin = await clinic.headers_for(clinic.admin.id)
    response = await client.get(SEARCH, params={"q": "receptionist"}, headers=admin)
    body = response.json()
    assert body["categories"] == ["patients", "doctors", "departments", "appointments", "users"]
    assert body["users"] and body["users"][0]["roles"] == ["receptionist"]
    assert "password" not in response.text
    found = (await client.get(SEARCH, params={"q": "alice"}, headers=admin)).json()
    assert len(found["appointments"]) == 1 and found["appointments"][0]["doctor_name"] == "Doctor Alpha"


async def test_wildcards_are_literal_and_short_queries_are_refused(client, clinic, auth_headers):
    bob = await clinic.headers_for(clinic.patient_b.user_id)
    assert (await client.get(SEARCH, params={"q": "%%"}, headers=bob)).json()["departments"] == []
    headers = await auth_headers(RoleCode.receptionist)
    assert (await client.get(SEARCH, params={"q": "a"}, headers=headers)).status_code == 422
    assert (await client.get(SEARCH, params={"q": " a "}, headers=headers)).status_code in (400, 422)
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
