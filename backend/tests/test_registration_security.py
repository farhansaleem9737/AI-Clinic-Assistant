from sqlalchemy import select

from app.models.user import User
from app.services import rbac_service

REGISTER = "/api/v1/auth/register"


def payload(email: str, **extra) -> dict:
    return {
        "first_name": "Pat",
        "last_name": "Example",
        "date_of_birth": "1990-05-17",
        "email": email,
        "password": "pw-123456",
        **extra,
    }


async def test_register_creates_patient(client):
    response = await client.post(REGISTER, json=payload("pat@example.com"))
    assert response.status_code == 201
    body = response.json()
    assert body["roles"] == ["patient"]
    assert "password" not in body and "password_hash" not in body


async def test_register_ignores_requested_admin_role(client, db_session):
    response = await client.post(
        REGISTER,
        json=payload("mallory@example.com", role="admin"),
    )
    assert response.status_code == 201
    assert response.json()["roles"] == ["patient"]

    stored = await db_session.scalar(select(User).where(User.email == "mallory@example.com"))
    assert await rbac_service.role_codes_for(db_session, stored.id) == {"patient"}


async def test_register_cannot_choose_any_staff_role(client):
    for i, role in enumerate(["doctor", "receptionist", "admin"]):
        response = await client.post(
            REGISTER, json=payload(f"x{i}@example.com", role=role)
        )
        assert response.status_code == 201
        assert response.json()["roles"] == ["patient"]


async def test_register_duplicate_email_is_409(client, make_user):
    user = await make_user()
    response = await client.post(REGISTER, json=payload(user.email))
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EMAIL_TAKEN"


async def test_registration_creates_login_and_patient_profile_together(client):
    response = await client.post(REGISTER, json=payload("newpat@example.com", phone="555-0101"))
    assert response.status_code == 201
    login = await client.post("/api/v1/auth/login", json={"email": "newpat@example.com", "password": "pw-123456"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    me = await client.get("/api/v1/patients/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["first_name"] == "Pat" and me.json()["mrn"].startswith("MRN")


async def test_registration_rejects_future_date_of_birth(client):
    response = await client.post(REGISTER, json=payload("future@example.com", date_of_birth="2999-01-01"))
    assert response.status_code == 422
