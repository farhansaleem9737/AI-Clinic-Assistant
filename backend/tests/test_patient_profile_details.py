"""The patient's own personal and contact details (D111)."""

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.models.admin import AuditLog
from app.models.patient import Patient

ME = "/api/v1/patients/me"


async def test_new_details_are_saved_and_the_national_id_only_ever_returned_masked(client, clinic, db_session):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    before = (await client.get(ME, headers=alice)).json()
    assert before["blood_group"] is None and before["national_id_masked"] is None and before["mrn"].startswith("MRN")

    saved = await client.patch(
        ME, json={"blood_group": "O+", "marital_status": "single", "national_id": "3410112345671", "country": "pk"}, headers=alice
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["blood_group"] == "O+" and body["marital_status"] == "single" and body["country"] == "PK"
    assert body["national_id_masked"] == "•••••-•••••67-1"
    assert "3410112345671" not in saved.text and "34101-1234567-1" not in saved.text
    stored = await db_session.scalar(select(Patient.national_id).where(Patient.id == clinic.patient_a.id))
    assert stored == "34101-1234567-1"  # the standard CNIC form
    # Audited as changed, never with its value.
    audit = (await db_session.scalars(select(AuditLog).where(AuditLog.target_id == str(clinic.patient_a.id)))).all()
    assert audit and "national_id" in audit[-1].details["fields"]
    assert "34101" not in str(audit[-1].details)


@pytest.mark.parametrize(
    "country, value, status, saved",
    [
        ("PK", "34101-1234567", 400, None),  # too short for a CNIC
        ("PK", "34101-1234567-1", 200, "34101-1234567-1"),
        ("GB", "AB 12 34 56 C", 200, "AB 12 34 56 C"),  # another country's ID is kept exactly
        ("GB", "<script>", 400, None),
    ],
)
async def test_national_ids_are_checked_by_country(client, clinic, db_session, country, value, status, saved):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    response = await client.patch(ME, json={"country": country, "national_id": value}, headers=alice)
    assert response.status_code == status, response.text
    if saved:
        stored = await db_session.scalar(select(Patient.national_id).where(Patient.id == clinic.patient_a.id))
        assert stored == saved


async def test_address_parts_and_a_partial_update_leave_other_fields_alone(client, clinic):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    await client.patch(ME, json={"phone": "+92 3001234567", "address": "House 5, Johar Town"}, headers=alice)
    response = await client.patch(ME, json={"city": " Lahore ", "province": "Punjab", "country": "PK"}, headers=alice)
    body = response.json()
    assert (body["city"], body["province"], body["country"]) == ("Lahore", "Punjab", "PK")
    assert body["phone"] == "+92 3001234567" and body["address"] == "House 5, Johar Town"
    assert (await client.patch(ME, json={"country": "Pakistan"}, headers=alice)).status_code == 422
    assert (await client.patch(ME, json={"blood_group": "Z+"}, headers=alice)).status_code == 422
    assert (await client.patch(ME, json={"marital_status": "complicated"}, headers=alice)).status_code == 422
    future = (date.today() + timedelta(days=2)).isoformat()
    assert (await client.patch(ME, json={"date_of_birth": future}, headers=alice)).status_code == 422


async def test_protected_fields_cannot_be_changed_and_a_new_name_reaches_the_account(client, clinic):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    before = (await client.get(ME, headers=alice)).json()
    response = await client.patch(
        ME,
        json={"first_name": "Alicia", "mrn": "MRN99999999", "is_active": False, "user_id": None, "roles": ["admin"], "has_account": False},
        headers=alice,
    )
    assert response.status_code == 200, response.text
    after = response.json()
    assert after["mrn"] == before["mrn"] and after["has_account"] is True and after["first_name"] == "Alicia"
    me = (await client.get("/api/v1/auth/me", headers=alice)).json()
    assert me["name"].startswith("Alicia ") and me["roles"] == ["patient"] and me["is_active"] is True


async def test_only_the_patient_themselves_and_with_a_session(client, clinic):
    assert (await client.get(ME)).status_code == 401
    assert (await client.patch(ME, json={"city": "Lahore"})).status_code == 401
    reception = await clinic.headers_for(clinic.receptionist.id)
    response = await client.patch(ME, json={"city": "Lahore"}, headers=reception)
    assert response.status_code in (403, 404)
