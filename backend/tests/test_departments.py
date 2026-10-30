import uuid

import pytest

from app.core.permissions import RoleCode

PUBLIC = "/api/v1/public/departments/"
ADMIN = "/api/v1/departments/"


@pytest.fixture
async def admin(auth_headers):
    return await auth_headers(RoleCode.admin)


async def test_public_list_shows_only_active_departments_without_internal_fields(client, make_department):
    active = await make_department("Cardiology Pub")
    await make_department("Retired Pub", is_active=False)

    response = await client.get(PUBLIC, params={"q": "pub"})
    assert response.status_code == 200
    body = response.json()
    assert [d["name"] for d in body["items"]] == ["Cardiology Pub"]
    # D94: card fields only; never status, timezone or timestamps.
    assert set(body["items"][0]) == {"id", "name", "description", "icon", "color", "doctor_count", "doctors_preview"}

    assert (await client.get(f"{PUBLIC}{active.id}")).status_code == 200


async def test_public_get_of_inactive_department_is_404(client, make_department):
    retired = await make_department(is_active=False)
    assert (await client.get(f"{PUBLIC}{retired.id}")).status_code == 404


async def test_management_endpoints_require_permission(client, auth_headers):
    assert (await client.get(ADMIN)).status_code == 401
    for role in (RoleCode.patient, RoleCode.doctor, RoleCode.receptionist):
        headers = await auth_headers(role)
        assert (await client.get(ADMIN, headers=headers)).status_code == 403
        assert (await client.post(ADMIN, json={"name": "X"}, headers=headers)).status_code == 403


async def test_create_defaults_to_clinic_timezone(client, admin):
    from app.core.config import settings

    response = await client.post(ADMIN, json={"name": "  Dermatology  "}, headers=admin)
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Dermatology"
    assert body["timezone"] == settings.clinic_timezone
    assert body["is_active"] is True


async def test_invalid_timezone_is_422(client, admin):
    response = await client.post(ADMIN, json={"name": "X", "timezone": "Mars/Olympus"}, headers=admin)
    assert response.status_code == 422


async def test_duplicate_name_is_409_case_insensitively(client, admin):
    assert (await client.post(ADMIN, json={"name": "Neurology"}, headers=admin)).status_code == 201
    duplicate = await client.post(ADMIN, json={"name": "neurology"}, headers=admin)
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "DEPARTMENT_EXISTS"


async def test_update(client, admin, make_department):
    department = await make_department("Paeds")
    other = await make_department("Ortho")

    response = await client.patch(
        f"{ADMIN}{department.id}", json={"name": "Pediatrics", "timezone": "Europe/London"}, headers=admin
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Pediatrics"
    assert response.json()["timezone"] == "Europe/London"

    clash = await client.patch(f"{ADMIN}{department.id}", json={"name": other.name}, headers=admin)
    assert clash.status_code == 409


async def test_deactivating_keeps_doctors_and_hides_the_department(client, admin, make_department, make_doctor):
    """D89: doctors stay assigned (no longer refused with DEPARTMENT_HAS_ACTIVE_DOCTORS)."""
    department = await make_department()
    doctor = await make_doctor(department=department)
    department_id, doctor_id = department.id, doctor.id

    done = await client.post(f"{ADMIN}{department_id}/deactivate", headers=admin)
    assert done.status_code == 200 and done.json()["is_active"] is False
    profile = await client.get(f"/api/v1/doctors/{doctor_id}", headers=admin)
    assert profile.json()["department_id"] == str(department_id)

    assert (await client.get(f"{PUBLIC}{department_id}")).status_code == 404
    listed = await client.get(ADMIN, params={"include_inactive": True}, headers=admin)
    assert any(d["id"] == str(department_id) for d in listed.json()["items"])


async def test_no_delete_endpoint(client, admin, make_department):
    department = await make_department()
    assert (await client.delete(f"{ADMIN}{department.id}", headers=admin)).status_code == 405


async def test_unknown_department_is_404(client, admin):
    assert (await client.get(f"{ADMIN}{uuid.uuid4()}", headers=admin)).status_code == 404
