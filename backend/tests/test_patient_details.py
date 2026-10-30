"""The receptionist's patient detail page (D81): identity, contact and
emergency contact, editing limits, the appointment lists for one patient,
and the medical boundary."""

from datetime import datetime

import pytest

BASE = "/api/v1/patients/"
EMERGENCY = {
    "emergency_contact_name": "Sarah Doe",
    "emergency_contact_relationship": "Spouse",
    "emergency_contact_phone": "+1 555 987 6543",
    "preferred_contact_method": "phone",
}


def iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


@pytest.fixture
async def reception(clinic):
    return await clinic.headers_for(clinic.receptionist.id)


async def test_reception_reads_identity_and_contact_but_nothing_clinical(client, clinic, reception):
    response = await client.get(f"{BASE}{clinic.patient_a.id}", headers=reception)
    assert response.status_code == 200
    body = response.json()
    assert body["mrn"].startswith("MRN") and body["is_active"] is True and body["created_at"]
    for field in EMERGENCY:
        assert field in body and body[field] is None
    # No clinical data and no secrets in the record.
    for forbidden in ("blood_type", "clinical_notes", "diagnoses", "password_hash"):
        assert forbidden not in body


async def test_reception_edits_contact_and_emergency_details(client, clinic, reception):
    url = f"{BASE}{clinic.patient_a.id}"
    response = await client.patch(url, json={**EMERGENCY, "address": "123 Main St\nLahore"}, headers=reception)
    assert response.status_code == 200, response.text
    body = (await client.get(url, headers=reception)).json()
    assert {k: body[k] for k in EMERGENCY} == EMERGENCY
    assert body["address"] == "123 Main St\nLahore"

    cleared = await client.patch(url, json={"emergency_contact_phone": "  "}, headers=reception)
    assert cleared.json()["emergency_contact_phone"] is None


@pytest.mark.parametrize(
    "change",
    [
        {"preferred_contact_method": "pigeon"},
        {"emergency_contact_phone": "call my wife"},
        {"phone": "x" * 31},
        {"email": "not-an-email"},
        {"date_of_birth": "2999-01-01"},
        {"emergency_contact_name": "x" * 101},
    ],
)
async def test_invalid_edits_are_rejected(client, clinic, reception, change):
    response = await client.patch(f"{BASE}{clinic.patient_a.id}", json=change, headers=reception)
    assert response.status_code == 422


async def test_mrn_and_registration_date_cannot_be_changed(client, clinic, reception):
    url = f"{BASE}{clinic.patient_a.id}"
    before = (await client.get(url, headers=reception)).json()
    response = await client.patch(
        url, json={"mrn": "MRN99999999", "created_at": "2000-01-01T00:00:00Z", "first_name": "Alicia"}, headers=reception
    )
    assert response.status_code == 200
    after = response.json()
    assert after["mrn"] == before["mrn"] and after["created_at"] == before["created_at"]
    assert after["first_name"] == "Alicia"


async def test_patients_see_only_themselves_and_may_set_their_emergency_contact(client, clinic):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    assert (await client.get(f"{BASE}{clinic.patient_b.id}", headers=alice)).status_code == 404
    own = await client.patch(f"{BASE}me", json=EMERGENCY, headers=alice)
    assert own.status_code == 200 and own.json()["emergency_contact_name"] == "Sarah Doe"
    # A patient cannot use the staff edit.
    assert (await client.patch(f"{BASE}{clinic.patient_a.id}", json={"first_name": "X"}, headers=alice)).status_code == 403


async def test_doctors_see_only_patients_they_treat(client, clinic):
    dr_a = await clinic.headers_for(clinic.doctor_a.user_id)
    assert (await client.get(f"{BASE}{clinic.patient_a.id}", headers=dr_a)).status_code == 404
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    booked = await client.post(
        "/api/v1/appointments/", json={"doctor_id": str(clinic.doctor_a.id), "starts_at": iso(clinic.slot(2, "10:00"))}, headers=alice
    )
    assert booked.status_code == 201
    assert (await client.get(f"{BASE}{clinic.patient_a.id}", headers=dr_a)).status_code == 200


async def test_medical_documents_stay_closed_to_reception(client, clinic, reception):
    response = await client.get(f"{BASE}{clinic.patient_a.id}/documents/", headers=reception)
    assert response.status_code in (403, 404)


async def test_one_patients_upcoming_and_recent_appointments(client, clinic, reception, freeze_clock):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    ids = []
    for days, hhmm in ((1, "10:00"), (3, "11:00"), (4, "12:00")):
        response = await client.post(
            "/api/v1/appointments/", json={"doctor_id": str(clinic.doctor_a.id), "starts_at": iso(clinic.slot(days, hhmm))}, headers=alice
        )
        ids.append(response.json()["id"])
    # Bob's appointment must never show on Alice's page.
    bob = await clinic.headers_for(clinic.patient_b.user_id)
    await client.post(
        "/api/v1/appointments/", json={"doctor_id": str(clinic.doctor_b.id), "starts_at": iso(clinic.slot(3, "11:00"))}, headers=bob
    )
    cancelled = await client.post(
        f"/api/v1/appointments/{ids[2]}/status", json={"status": "cancelled", "cancellation_reason": "patient_request"}, headers=reception
    )
    assert cancelled.status_code == 200
    freeze_clock(clinic.slot(2, "08:00"))  # day+1 is over

    params = {"patient_id": str(clinic.patient_a.id)}
    counts = (await client.get("/api/v1/appointments/counts", params=params, headers=reception)).json()
    assert counts == {"upcoming": 1, "past": 2, "all": 3}
    upcoming = (await client.get("/api/v1/appointments/", params={**params, "scope": "upcoming"}, headers=reception)).json()
    assert [a["id"] for a in upcoming["items"]] == [ids[1]]
    recent = (
        await client.get("/api/v1/appointments/", params={**params, "scope": "past", "newest_first": "true"}, headers=reception)
    ).json()
    # Newest first; the cancelled one keeps its real status.
    assert [a["id"] for a in recent["items"]] == [ids[2], ids[0]]
    assert [a["status"] for a in recent["items"]] == ["cancelled", "scheduled"]
    assert recent["items"][0]["doctor"]["specialization"] == "General Medicine"
