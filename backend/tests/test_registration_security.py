from sqlalchemy import select

from app.models.user import User, UserRole

REGISTER = "/api/v1/auth/register"


async def test_register_creates_patient(client):
    response = await client.post(REGISTER, json={"name": "Pat", "email": "pat@example.com", "password": "pw-123456"})
    assert response.status_code == 201
    body = response.json()
    assert body["role"] == "patient"
    assert "password" not in body and "password_hash" not in body


async def test_register_ignores_requested_admin_role(client, db_session):
    response = await client.post(
        REGISTER,
        json={"name": "Mallory", "email": "mallory@example.com", "password": "pw-123456", "role": "admin"},
    )
    assert response.status_code == 201
    assert response.json()["role"] == "patient"

    stored = await db_session.scalar(select(User).where(User.email == "mallory@example.com"))
    assert stored.role == UserRole.patient


async def test_register_cannot_choose_any_staff_role(client):
    for i, role in enumerate(["doctor", "receptionist", "admin"]):
        response = await client.post(
            REGISTER, json={"name": "X", "email": f"x{i}@example.com", "password": "pw-123456", "role": role}
        )
        assert response.status_code == 201
        assert response.json()["role"] == "patient"


async def test_register_duplicate_email_is_409(client, make_user):
    user = await make_user()
    response = await client.post(REGISTER, json={"name": "Dup", "email": user.email, "password": "pw-123456"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EMAIL_TAKEN"
