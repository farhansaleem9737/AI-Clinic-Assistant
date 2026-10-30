import uuid

import pytest

from app.core.permissions import RoleCode
from tests.conftest import login, login_as

BASE = "/api/v1/patients/"
WALK_IN = {"first_name": "Walk", "last_name": "In", "date_of_birth": "1985-02-03", "phone": "555-0142"}


@pytest.fixture
async def reception(auth_headers):
    return await auth_headers(RoleCode.receptionist)


# ---- registration by staff ---------------------------------------------------


async def test_receptionist_registers_walk_in_without_login(client, reception):
    response = await client.post(BASE, json=WALK_IN, headers=reception)
    assert response.status_code == 201
    body = response.json()
    assert body["mrn"].startswith("MRN") and len(body["mrn"]) == 11
    assert body["user_id"] is None and body["has_account"] is False
    assert body["registered_by_user_id"] is not None


async def test_mrns_are_unique(client, reception):
    first = await client.post(BASE, json=WALK_IN, headers=reception)
    second = await client.post(BASE, json=WALK_IN, headers=reception)
    assert first.json()["mrn"] != second.json()["mrn"]


@pytest.mark.parametrize("role", [RoleCode.patient, RoleCode.doctor])
async def test_patients_and_doctors_cannot_register_patients(client, auth_headers, role):
    assert (await client.post(BASE, json=WALK_IN, headers=await auth_headers(role))).status_code == 403


async def test_invalid_patient_data_is_422(client, reception):
    future = {**WALK_IN, "date_of_birth": "2999-01-01"}
    assert (await client.post(BASE, json=future, headers=reception)).status_code == 422
    missing = {"first_name": "A"}
    assert (await client.post(BASE, json=missing, headers=reception)).status_code == 422


# ---- ownership isolation -------------------------------------------------------


async def test_patient_a_cannot_see_patient_b(client, db_session, make_patient):
    patient_a = await make_patient(with_account=True)
    patient_b = await make_patient(with_account=True)
    headers_a = await login_as(client, db_session, patient_a.user_id)

    assert (await client.get(f"{BASE}{patient_a.id}", headers=headers_a)).status_code == 200
    # Same response as for an id that does not exist: existence is not disclosed.
    assert (await client.get(f"{BASE}{patient_b.id}", headers=headers_a)).status_code == 404
    assert (await client.get(f"{BASE}{uuid.uuid4()}", headers=headers_a)).status_code == 404
    # Nor can they list, edit, or re-link anyone.
    assert (await client.get(BASE, headers=headers_a)).status_code == 403
    assert (await client.patch(f"{BASE}{patient_b.id}", json={"phone": "x"}, headers=headers_a)).status_code == 403


async def test_patient_view_omits_staff_fields(client, db_session, make_patient):
    patient = await make_patient(with_account=True)
    headers = await login_as(client, db_session, patient.user_id)
    body = (await client.get(f"{BASE}{patient.id}", headers=headers)).json()
    assert "registered_by_user_id" not in body and "is_active" not in body


async def test_doctor_without_appointments_sees_no_patients(client, db_session, make_doctor, make_patient):
    doctor = await make_doctor()
    patient = await make_patient()
    headers = await login_as(client, db_session, doctor.user_id)
    assert (await client.get(f"{BASE}{patient.id}", headers=headers)).status_code == 404
    assert (await client.get(BASE, headers=headers)).json()["total"] == 0


async def test_unauthenticated_is_401(client, make_patient):
    patient = await make_patient()
    assert (await client.get(f"{BASE}{patient.id}")).status_code == 401
    assert (await client.get(f"{BASE}me")).status_code == 401


# ---- own profile ---------------------------------------------------------------


async def test_patient_edits_contact_and_personal_details_but_not_the_mrn(client, db_session, make_patient):
    patient = await make_patient(with_account=True, first_name="Original")
    headers = await login_as(client, db_session, patient.user_id)
    before = (await client.get(f"{BASE}me", headers=headers)).json()
    response = await client.patch(
        f"{BASE}me",
        json={"phone": "555-0199", "address": "1 Clinic Road", "first_name": " Corrected ", "mrn": "MRN99999999", "is_active": False},
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["phone"] == "555-0199" and body["first_name"] == "Corrected"
    assert body["mrn"] == before["mrn"]
    # The account stays active: patients cannot change their own status.
    assert (await client.get(f"{BASE}me", headers=headers)).status_code == 200


async def test_patient_identity_change_is_audited_with_the_previous_values(client, db_session, make_patient):
    from sqlalchemy import select

    from app.models.admin import AuditLog

    patient = await make_patient(with_account=True, first_name="Original")
    headers = await login_as(client, db_session, patient.user_id)
    before = (await client.get(f"{BASE}me", headers=headers)).json()
    response = await client.patch(
        f"{BASE}me", json={"first_name": "New", "date_of_birth": "1985-05-05", "phone": "555-0100"}, headers=headers
    )
    assert response.status_code == 200 and response.json()["date_of_birth"] == "1985-05-05"
    entries = (await db_session.scalars(select(AuditLog).where(AuditLog.target_id == str(patient.id)))).all()
    changed = [e for e in entries if e.action == "patient.identity_changed"]
    assert len(changed) == 1
    assert changed[0].actor_user_id == patient.user_id
    assert changed[0].details == {
        "fields": ["date_of_birth", "first_name"],
        "previous": {"date_of_birth": before["date_of_birth"], "first_name": "Original"},
    }

    # A contact-only edit (or resending the same name) is not an identity change.
    assert (await client.patch(f"{BASE}me", json={"phone": "555-0101", "first_name": "New"}, headers=headers)).status_code == 200
    entries = (await db_session.scalars(select(AuditLog).where(AuditLog.target_id == str(patient.id)))).all()
    assert len([e for e in entries if e.action == "patient.identity_changed"]) == 1


async def test_patient_personal_details_are_validated(client, db_session, make_patient):
    patient = await make_patient(with_account=True)
    headers = await login_as(client, db_session, patient.user_id)
    for bad in ({"first_name": ""}, {"first_name": "   "}, {"date_of_birth": "2999-01-01"}, {"sex_at_birth": "robot"}):
        assert (await client.patch(f"{BASE}me", json=bad, headers=headers)).status_code == 422, bad


async def test_patient_login_without_profile_can_complete_it_once(client, make_user):
    user = await make_user(RoleCode.patient)
    headers = await login(client, user.email)
    assert (await client.get(f"{BASE}me", headers=headers)).json()["error"]["code"] == "NO_PATIENT_PROFILE"

    created = await client.post(f"{BASE}me", json=WALK_IN, headers=headers)
    assert created.status_code == 201
    assert created.json()["email"] == user.email

    again = await client.post(f"{BASE}me", json=WALK_IN, headers=headers)
    assert again.json()["error"]["code"] == "PATIENT_PROFILE_EXISTS"


# ---- search and staff edits ------------------------------------------------------


async def test_search_by_name_mrn_phone_and_dob_in_sql(client, reception, make_patient):
    from datetime import date

    target = await make_patient(first_name="Zubair", last_name="Searchable", phone="555-7777", date_of_birth=date(1970, 1, 2))
    await make_patient(first_name="Other", last_name="Searchable")

    async def ids(**params):
        response = await client.get(BASE, params=params, headers=reception)
        assert response.status_code == 200
        return [p["id"] for p in response.json()["items"]]

    assert str(target.id) in await ids(q="zubair searchable")
    assert await ids(q=target.mrn) == [str(target.id)]
    assert await ids(q="555-7777") == [str(target.id)]
    assert await ids(q="Searchable", date_of_birth="1970-01-02") == [str(target.id)]
    page = await client.get(BASE, params={"q": "Searchable", "page_size": 1}, headers=reception)
    assert page.json()["total"] == 2 and len(page.json()["items"]) == 1


async def test_staff_updates_demographics(client, reception, make_patient):
    patient = await make_patient(last_name="Typo")
    response = await client.patch(f"{BASE}{patient.id}", json={"last_name": "Corrected"}, headers=reception)
    assert response.status_code == 200 and response.json()["last_name"] == "Corrected"


async def test_only_admin_deactivates(client, reception, auth_headers, make_patient):
    patient = await make_patient()
    assert (await client.post(f"{BASE}{patient.id}/deactivate", headers=reception)).status_code == 403
    admin = await auth_headers(RoleCode.admin)
    response = await client.post(f"{BASE}{patient.id}/deactivate", headers=admin)
    assert response.json()["is_active"] is False
    assert (await client.delete(f"{BASE}{patient.id}", headers=admin)).status_code == 405


# ---- accounts ---------------------------------------------------------------


async def test_create_portal_login_for_walk_in(client, reception, make_patient):
    patient = await make_patient(first_name="Walkin")
    response = await client.post(
        f"{BASE}{patient.id}/account", json={"email": "walkin@example.com", "password": "pw-12345678"}, headers=reception
    )
    assert response.status_code == 201 and response.json()["has_account"] is True

    headers = await login(client, "walkin@example.com", "pw-12345678")
    me = await client.get(f"{BASE}me", headers=headers)
    assert me.json()["id"] == str(patient.id)

    again = await client.post(
        f"{BASE}{patient.id}/account", json={"email": "walkin2@example.com", "password": "pw-12345678"}, headers=reception
    )
    assert again.json()["error"]["code"] == "PATIENT_ALREADY_LINKED"


async def test_link_existing_patient_login(client, reception, make_patient, make_user):
    patient = await make_patient()
    user = await make_user(RoleCode.patient)
    staff_user = await make_user(RoleCode.receptionist)

    wrong_role = await client.post(f"{BASE}{patient.id}/link-account", json={"user_id": str(staff_user.id)}, headers=reception)
    assert wrong_role.json()["error"]["code"] == "USER_NOT_PATIENT"

    linked = await client.post(f"{BASE}{patient.id}/link-account", json={"user_id": str(user.id)}, headers=reception)
    assert linked.status_code == 200 and linked.json()["user_id"] == str(user.id)

    other = await make_patient()
    reused = await client.post(f"{BASE}{other.id}/link-account", json={"user_id": str(user.id)}, headers=reception)
    assert reused.json()["error"]["code"] == "ACCOUNT_ALREADY_LINKED"
