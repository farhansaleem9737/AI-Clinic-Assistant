from app.models.user import UserRole

DEPTS = "/api/v1/departments/"
DOCS = "/api/v1/doctors/"


async def test_department_create_requires_auth(client):
    response = await client.post(DEPTS, json={"name": "Cardiology"})
    assert response.status_code == 401


async def test_department_create_forbidden_for_non_admin(client, auth_headers):
    for role in (UserRole.patient, UserRole.doctor, UserRole.receptionist):
        response = await client.post(DEPTS, json={"name": "Cardiology"}, headers=await auth_headers(role))
        assert response.status_code == 403


async def test_admin_creates_department_and_duplicate_is_409(client, auth_headers):
    admin = await auth_headers(UserRole.admin)
    created = await client.post(DEPTS, json={"name": "Cardiology"}, headers=admin)
    assert created.status_code == 201

    duplicate = await client.post(DEPTS, json={"name": "Cardiology"}, headers=admin)
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "DEPARTMENT_EXISTS"

    fetched = await client.get(f"{DEPTS}{created.json()['id']}")
    assert fetched.status_code == 200


async def test_missing_department_is_404(client):
    response = await client.get(f"{DEPTS}999999")
    assert response.status_code == 404


async def _department(client, admin) -> int:
    response = await client.post(DEPTS, json={"name": "Neurology"}, headers=admin)
    return response.json()["id"]


async def test_doctor_lifecycle(client, auth_headers, make_user):
    admin = await auth_headers(UserRole.admin)
    dept_id = await _department(client, admin)
    doctor_user = await make_user(UserRole.doctor)

    payload = {"user_id": doctor_user.id, "department_id": dept_id, "specialization": "Neurologist"}
    created = await client.post(DOCS, json=payload, headers=admin)
    assert created.status_code == 201
    doctor = created.json()
    assert doctor["name"] == doctor_user.name

    duplicate = await client.post(DOCS, json=payload, headers=admin)
    assert duplicate.status_code == 409

    listed = await client.get(DOCS)
    assert any(d["id"] == doctor["id"] for d in listed.json())

    updated = await client.put(f"{DOCS}{doctor['id']}", json={"years_of_experience": 5}, headers=admin)
    assert updated.status_code == 200
    assert updated.json()["years_of_experience"] == 5

    deleted = await client.delete(f"{DOCS}{doctor['id']}", headers=admin)
    assert deleted.status_code == 204
    assert (await client.get(f"{DOCS}{doctor['id']}")).status_code == 404


async def test_doctor_profile_requires_doctor_role(client, auth_headers, make_user):
    admin = await auth_headers(UserRole.admin)
    dept_id = await _department(client, admin)
    patient = await make_user(UserRole.patient)

    response = await client.post(
        DOCS, json={"user_id": patient.id, "department_id": dept_id, "specialization": "X"}, headers=admin
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "USER_NOT_DOCTOR"


async def test_doctor_update_to_missing_department_is_404(client, auth_headers, make_user):
    admin = await auth_headers(UserRole.admin)
    dept_id = await _department(client, admin)
    doctor_user = await make_user(UserRole.doctor)
    created = await client.post(
        DOCS, json={"user_id": doctor_user.id, "department_id": dept_id, "specialization": "X"}, headers=admin
    )

    response = await client.put(f"{DOCS}{created.json()['id']}", json={"department_id": 999999}, headers=admin)
    assert response.status_code == 404


async def test_doctor_writes_forbidden_for_non_admin(client, auth_headers):
    patient = await auth_headers(UserRole.patient)
    payload = {"user_id": 1, "department_id": 1, "specialization": "X"}
    assert (await client.post(DOCS, json=payload, headers=patient)).status_code == 403
    assert (await client.delete(f"{DOCS}1", headers=patient)).status_code == 403
