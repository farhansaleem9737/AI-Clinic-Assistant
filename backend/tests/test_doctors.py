import uuid
from decimal import Decimal

import pytest

from app.core.permissions import RoleCode
from tests.conftest import login

PUBLIC = "/api/v1/public/doctors/"
STAFF = "/api/v1/doctors/"


@pytest.fixture
async def admin(auth_headers):
    return await auth_headers(RoleCode.admin)


# ---- creation ---------------------------------------------------------------


async def test_admin_creates_doctor_with_new_account(client, admin, make_department):
    department = await make_department()
    body = {
        "account": {"name": "Dr New", "email": "drnew@example.com", "password": "pw-12345678"},
        "department_id": str(department.id),
        "title": "Dr.",
        "specialization": "Cardiologist",
        "license_number": "PMC-12345",
        "consultation_fee": "150.00",
        "phone": "+92 300 0000000",
        "room_number": "B-12",
    }
    response = await client.post(STAFF, json=body, headers=admin)
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["name"] == "Dr New"
    assert created["consultation_fee"] == "150.00"  # Decimal as a string, never a float
    assert created["department_name"] == department.name

    doctor_headers = await login(client, "drnew@example.com", "pw-12345678")
    me = await client.get(f"{STAFF}me", headers=doctor_headers)
    assert me.status_code == 200 and me.json()["id"] == created["id"]


async def test_create_from_existing_user_requires_doctor_role(client, admin, make_user, make_department):
    department = await make_department()
    patient = await make_user(RoleCode.patient)
    response = await client.post(
        STAFF,
        json={"user_id": str(patient.id), "department_id": str(department.id), "specialization": "X"},
        headers=admin,
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "USER_NOT_DOCTOR"


async def test_create_links_existing_doctor_user_once(client, admin, make_user, make_department):
    department = await make_department()
    doctor_user = await make_user(RoleCode.doctor)
    body = {"user_id": str(doctor_user.id), "department_id": str(department.id), "specialization": "GP"}
    assert (await client.post(STAFF, json=body, headers=admin)).status_code == 201
    again = await client.post(STAFF, json=body, headers=admin)
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "DOCTOR_PROFILE_EXISTS"


async def test_create_requires_exactly_one_identity(client, admin, make_department, make_user):
    department = await make_department()
    user = await make_user(RoleCode.doctor)
    neither = {"department_id": str(department.id), "specialization": "X"}
    both = {**neither, "user_id": str(user.id), "account": {"name": "A", "email": "a@example.com", "password": "pw-12345678"}}
    assert (await client.post(STAFF, json=neither, headers=admin)).status_code == 422
    assert (await client.post(STAFF, json=both, headers=admin)).status_code == 422


async def test_create_in_inactive_department_is_rejected(client, admin, make_department):
    department = await make_department(is_active=False)
    body = {
        "account": {"name": "A", "email": "inactive-dept@example.com", "password": "pw-12345678"},
        "department_id": str(department.id),
        "specialization": "X",
    }
    response = await client.post(STAFF, json=body, headers=admin)
    assert response.json()["error"]["code"] == "DEPARTMENT_INACTIVE"


async def test_duplicate_license_is_409(client, admin, make_doctor, make_department):
    await make_doctor(license_number="LIC-1")
    department = await make_department()
    body = {
        "account": {"name": "A", "email": "lic@example.com", "password": "pw-12345678"},
        "department_id": str(department.id),
        "specialization": "X",
        "license_number": "LIC-1",
    }
    response = await client.post(STAFF, json=body, headers=admin)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "LICENSE_TAKEN"


async def test_negative_fee_is_422(client, admin, make_department):
    department = await make_department()
    body = {
        "account": {"name": "A", "email": "fee@example.com", "password": "pw-12345678"},
        "department_id": str(department.id),
        "specialization": "X",
        "consultation_fee": "-1",
    }
    assert (await client.post(STAFF, json=body, headers=admin)).status_code == 422


# ---- public directory -------------------------------------------------------


async def test_public_directory_hides_private_fields(client, make_doctor):
    doctor = await make_doctor(license_number="SECRET-LIC", phone="555-0100", room_number="R1")
    response = await client.get(f"{PUBLIC}{doctor.id}")
    assert response.status_code == 200
    body = response.json()
    for private in ("license_number", "phone", "room_number", "email", "user_id", "is_active"):
        assert private not in body
    assert "SECRET-LIC" not in response.text and "555-0100" not in response.text


async def test_public_directory_filters_in_sql(client, make_doctor, make_department):
    cardio = await make_department("Filter Cardio")
    derm = await make_department("Filter Derm")
    await make_doctor(name="Filter Alpha", department=cardio, specialization="Cardiologist",
                      years_of_experience=12, consultation_fee=Decimal("200.00"))
    await make_doctor(name="Filter Beta", department=cardio, specialization="Cardiologist",
                      years_of_experience=3, consultation_fee=Decimal("80.00"))
    await make_doctor(name="Filter Gamma", department=derm, specialization="Dermatologist",
                      years_of_experience=8, consultation_fee=Decimal("120.00"))

    async def names(**params):
        response = await client.get(PUBLIC, params={"q": "Filter", **params})
        assert response.status_code == 200
        return [d["name"] for d in response.json()["items"]]

    assert await names() == ["Filter Alpha", "Filter Beta", "Filter Gamma"]
    assert await names(department_id=str(cardio.id)) == ["Filter Alpha", "Filter Beta"]
    assert await names(specialization="derma") == ["Filter Gamma"]
    assert await names(min_experience=8) == ["Filter Alpha", "Filter Gamma"]
    assert await names(fee_min="100", fee_max="150") == ["Filter Gamma"]

    page = await client.get(PUBLIC, params={"q": "Filter", "page_size": 2, "page": 2})
    assert page.json()["total"] == 3 and [d["name"] for d in page.json()["items"]] == ["Filter Gamma"]


async def test_public_directory_excludes_inactive_doctors_departments_and_accounts(
    client, db_session, make_doctor, make_department, make_user
):
    await make_doctor(name="Hidden Inactive Doctor", is_active=False)
    closed = await make_department(is_active=False)
    await make_doctor(name="Hidden Closed Department", department=closed)
    doctor = await make_doctor(name="Hidden Disabled Login")
    from app.models.user import User

    (await db_session.get(User, doctor.user_id)).is_active = False
    await db_session.commit()

    response = await client.get(PUBLIC, params={"q": "Hidden"})
    assert response.json()["total"] == 0
    assert (await client.get(f"{PUBLIC}{doctor.id}")).status_code == 404


# ---- staff access and self-service -------------------------------------------


async def test_receptionist_reads_full_profiles_but_cannot_manage(client, auth_headers, make_doctor):
    doctor = await make_doctor(phone="555-0199")
    reception = await auth_headers(RoleCode.receptionist)
    response = await client.get(f"{STAFF}{doctor.id}", headers=reception)
    assert response.status_code == 200 and response.json()["phone"] == "555-0199"
    assert (await client.post(f"{STAFF}{doctor.id}/deactivate", headers=reception)).status_code == 403
    assert (await client.patch(f"{STAFF}{doctor.id}", json={"bio": "x"}, headers=reception)).status_code == 403


async def test_patient_cannot_use_staff_or_doctor_endpoints(client, auth_headers, make_doctor):
    doctor = await make_doctor()
    patient = await auth_headers(RoleCode.patient)
    assert (await client.get(STAFF, headers=patient)).status_code == 403
    assert (await client.get(f"{STAFF}{doctor.id}", headers=patient)).status_code == 403
    assert (await client.get(f"{STAFF}me", headers=patient)).status_code == 403


async def test_doctor_updates_only_permitted_own_fields(client, db_session, make_doctor, make_user):
    doctor = await make_doctor(consultation_fee=Decimal("100.00"))
    from app.models.user import User

    email = (await db_session.get(User, doctor.user_id)).email
    headers = await login(client, email)

    response = await client.patch(
        f"{STAFF}me", json={"bio": "Updated bio", "phone": "555-0123", "consultation_fee": "1.00"}, headers=headers
    )
    assert response.status_code == 200
    assert response.json()["bio"] == "Updated bio"
    assert response.json()["consultation_fee"] == "100.00"  # not a self-editable field

    # Cannot edit another doctor through the admin endpoint.
    other = await make_doctor()
    assert (await client.patch(f"{STAFF}{other.id}", json={"bio": "x"}, headers=headers)).status_code == 403


async def test_doctor_edits_languages_experience_and_qualifications_but_not_admin_fields(
    client, db_session, make_doctor
):
    from tests.conftest import login_as

    doctor = await make_doctor(specialization="Cardiologist", license_number="LIC-1", years_of_experience=5)
    headers = await login_as(client, db_session, doctor.user_id)
    response = await client.patch(
        f"{STAFF}me",
        json={
            "languages": "  English, Urdu ",
            "years_of_experience": 11,
            "qualifications": "MBBS, FCPS",
            "bio": "   ",
            # Administration-managed: ignored.
            "specialization": "Surgeon",
            "license_number": "FAKE",
            "is_active": False,
            "is_verified": False,
            "department_id": "00000000-0000-0000-0000-000000000000",
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["languages"] == "English, Urdu"
    assert body["years_of_experience"] == 11 and body["qualifications"] == "MBBS, FCPS"
    assert body["bio"] is None  # blank clears
    assert body["specialization"] == "Cardiologist" and body["license_number"] == "LIC-1"
    assert body["is_active"] is True and body["is_verified"] is True

    public = (await client.get(f"/api/v1/public/doctors/{doctor.id}")).json()
    assert public["languages"] == "English, Urdu" and public["years_of_experience"] == 11

    # Required fields cannot be emptied, and values are range-checked.
    kept = await client.patch(f"{STAFF}me", json={"years_of_experience": None}, headers=headers)
    assert kept.json()["years_of_experience"] == 11
    for bad in ({"years_of_experience": -1}, {"years_of_experience": 81}, {"languages": "x" * 201}):
        assert (await client.patch(f"{STAFF}me", json=bad, headers=headers)).status_code == 422


async def test_me_and_appointments_carry_the_doctors_photo(client, storage, clinic, monkeypatch):
    from app.api.v1.endpoints import appointments as appointments_endpoints
    from tests.fakes import image_bytes

    # Appointment responses sign photos through the storage module directly.
    monkeypatch.setattr(appointments_endpoints, "get_optional_storage", lambda: storage)

    doctor_headers = await clinic.headers_for(clinic.doctor_a.user_id)
    upload = await client.put(
        f"{STAFF}me/photo", files={"file": ("me.png", image_bytes(), "image/png")}, headers=doctor_headers
    )
    assert upload.status_code == 200
    me = (await client.get("/api/v1/auth/me", headers=doctor_headers)).json()
    assert me["photo_url"].startswith("https://fake-r2.test/doctor-photos/")

    alice = await clinic.headers_for(clinic.patient_a.user_id)
    booked = await client.post(
        "/api/v1/appointments/",
        json={"doctor_id": str(clinic.doctor_a.id), "starts_at": clinic.slot().isoformat()},
        headers=alice,
    )
    assert booked.status_code == 201
    assert booked.json()["doctor"]["photo_url"].startswith("https://fake-r2.test/doctor-photos/")
    assert (await client.get("/api/v1/auth/me", headers=alice)).json()["photo_url"] is None  # no photo yet


async def test_doctor_without_profile_gets_404_on_me(client, auth_headers):
    headers = await auth_headers(RoleCode.doctor)
    response = await client.get(f"{STAFF}me", headers=headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NO_DOCTOR_PROFILE"


async def test_deactivate_hides_from_public_but_not_from_staff(client, admin, make_doctor):
    doctor = await make_doctor()
    response = await client.post(f"{STAFF}{doctor.id}/deactivate", headers=admin)
    assert response.json()["is_active"] is False
    assert (await client.get(f"{PUBLIC}{doctor.id}")).status_code == 404
    assert (await client.get(f"{STAFF}{doctor.id}", headers=admin)).status_code == 200
    inactive = await client.get(STAFF, params={"is_active": False}, headers=admin)
    assert any(d["id"] == str(doctor.id) for d in inactive.json()["items"])


async def test_admin_update_and_move_department(client, admin, make_doctor, make_department):
    doctor = await make_doctor()
    target = await make_department()
    closed = await make_department(is_active=False)

    moved = await client.patch(f"{STAFF}{doctor.id}", json={"department_id": str(target.id)}, headers=admin)
    assert moved.json()["department_id"] == str(target.id)
    blocked = await client.patch(f"{STAFF}{doctor.id}", json={"department_id": str(closed.id)}, headers=admin)
    assert blocked.json()["error"]["code"] == "DEPARTMENT_INACTIVE"
    assert (await client.patch(f"{STAFF}{uuid.uuid4()}", json={"bio": "x"}, headers=admin)).status_code == 404


async def test_doctors_are_never_hard_deleted(client, admin, make_doctor):
    doctor = await make_doctor()
    assert (await client.delete(f"{STAFF}{doctor.id}", headers=admin)).status_code == 405
