"""The receptionist's Patients page (D80): search, status, doctor and
registration-date filters, sorting and paging, and who may do what."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import update

from app.core.permissions import RoleCode
from app.models.patient import Patient

BASE = "/api/v1/patients/"


def iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


@pytest.fixture
async def scene(client, clinic):
    """Alice has two appointments with Dr Alpha, Bob one with Dr Beta, the
    walk-in none."""
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    bob = await clinic.headers_for(clinic.patient_b.user_id)
    for headers, doctor, days, hhmm in (
        (alice, clinic.doctor_a, 2, "10:00"),
        (alice, clinic.doctor_a, 3, "11:00"),
        (bob, clinic.doctor_b, 2, "12:00"),
    ):
        response = await client.post(
            "/api/v1/appointments/", json={"doctor_id": str(doctor.id), "starts_at": iso(clinic.slot(days, hhmm))}, headers=headers
        )
        assert response.status_code == 201, response.text
    return {"reception": await clinic.headers_for(clinic.receptionist.id), "alice": alice}


async def ids(client, headers, **params):
    response = await client.get(BASE, params={"page_size": 100, **params}, headers=headers)
    assert response.status_code == 200, response.text
    return [p["id"] for p in response.json()["items"]]


async def test_doctor_filter_means_an_appointment_relationship_without_duplicates(client, clinic, scene):
    reception = scene["reception"]
    response = await client.get(BASE, params={"doctor_id": str(clinic.doctor_a.id)}, headers=reception)
    body = response.json()
    assert [p["id"] for p in body["items"]] == [str(clinic.patient_a.id)]  # two appointments, one row
    assert body["total"] == 1
    assert await ids(client, reception, doctor_id=str(clinic.doctor_b.id)) == [str(clinic.patient_b.id)]


async def test_filters_combine(client, clinic, scene):
    reception = scene["reception"]
    assert await ids(client, reception, doctor_id=str(clinic.doctor_a.id), is_active="false") == []
    assert await ids(client, reception, doctor_id=str(clinic.doctor_a.id), q="Alice") == [str(clinic.patient_a.id)]
    assert await ids(client, reception, doctor_id=str(clinic.doctor_a.id), q="Bob") == []


async def test_search_by_phone_email_and_mrn(client, make_patient, auth_headers):
    reception = await auth_headers(RoleCode.receptionist)
    target = await make_patient(first_name="Zara", phone="+92 300 1234567", email="Zara.Q@Example.com")
    assert await ids(client, reception, q="300 1234") == [str(target.id)]
    assert await ids(client, reception, q="zara.q@example") == [str(target.id)]
    mrn = (await client.get(f"{BASE}{target.id}", headers=reception)).json()["mrn"]
    assert await ids(client, reception, q=mrn.lower()) == [str(target.id)]


async def test_status_filter(client, make_patient, auth_headers):
    reception = await auth_headers(RoleCode.receptionist)
    inactive = await make_patient(first_name="Gone", is_active=False)
    found = await ids(client, reception, is_active="false")
    assert str(inactive.id) in found
    assert str(inactive.id) not in await ids(client, reception, is_active="true")


async def test_registration_date_range_is_inclusive(client, db_session, make_patient, auth_headers):
    reception = await auth_headers(RoleCode.receptionist)
    old = await make_patient(first_name="Early")
    new = await make_patient(first_name="Recent")
    ten_days_ago = datetime.now(timezone.utc) - timedelta(days=10)
    await db_session.execute(update(Patient).where(Patient.id == old.id).values(created_at=ten_days_ago))
    await db_session.commit()

    # Dates are the clinic's calendar (the tests run it in Asia/Karachi).
    day = ten_days_ago.astimezone(ZoneInfo("Asia/Karachi")).date()
    on_that_day = await ids(client, reception, registered_from=day.isoformat(), registered_to=day.isoformat())
    assert str(old.id) in on_that_day and str(new.id) not in on_that_day
    later = await ids(client, reception, registered_from=(day + timedelta(days=2)).isoformat())
    assert str(new.id) in later and str(old.id) not in later

    bad = await client.get(BASE, params={"registered_from": "2026-05-02", "registered_to": "2026-05-01"}, headers=reception)
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "INVALID_RANGE"


async def test_sorting_and_paging_are_stable(client, make_patient, auth_headers):
    reception = await auth_headers(RoleCode.receptionist)
    for i in range(5):
        await make_patient(first_name=f"Pager{i}", last_name="Same")
    pages = []
    for page in (1, 2, 3):
        body = (
            await client.get(BASE, params={"q": "Pager", "page_size": 2, "page": page, "sort": "registered_newest"}, headers=reception)
        ).json()
        assert body["total"] == 5 and body["total_pages"] == 3
        pages += [p["id"] for p in body["items"]]
    assert len(pages) == len(set(pages)) == 5  # nothing repeated or skipped


async def test_a_doctor_filter_cannot_widen_a_doctors_view(client, clinic, scene):
    """Dr Beta asking for Dr Alpha's patients sees none: the doctor filter
    only narrows what the caller may already see."""
    dr_b = await clinic.headers_for(clinic.doctor_b.user_id)
    assert await ids(client, dr_b, doctor_id=str(clinic.doctor_a.id)) == []
    assert await ids(client, dr_b) == [str(clinic.patient_b.id)]


async def test_patients_cannot_list_patients(client, scene):
    assert (await client.get(BASE, headers=scene["alice"])).status_code == 403


async def test_reception_registers_without_a_login_and_cannot_change_status(client, clinic, scene, auth_headers):
    reception = scene["reception"]
    created = await client.post(
        BASE, json={"first_name": "New", "last_name": "Walkin", "date_of_birth": "1980-01-01"}, headers=reception
    )
    assert created.status_code == 201
    body = created.json()
    assert body["has_account"] is False and body["is_active"] is True and body["mrn"].startswith("MRN")
    # Activation is an administrator's permission (patient:deactivate).
    assert (await client.post(f"{BASE}{body['id']}/deactivate", headers=reception)).status_code == 403
    admin = await auth_headers(RoleCode.admin)
    assert (await client.post(f"{BASE}{body['id']}/deactivate", headers=admin)).status_code == 200


async def test_reception_books_for_the_chosen_patient(client, clinic, scene):
    response = await client.post(
        "/api/v1/appointments/",
        json={
            "doctor_id": str(clinic.doctor_a.id),
            "patient_id": str(clinic.walk_in.id),
            "starts_at": iso(clinic.slot(4, "10:00")),
        },
        headers=scene["reception"],
    )
    assert response.status_code == 201, response.text
    assert response.json()["patient"]["id"] == str(clinic.walk_in.id)
    assert str(clinic.walk_in.id) in await ids(client, scene["reception"], doctor_id=str(clinic.doctor_a.id))
