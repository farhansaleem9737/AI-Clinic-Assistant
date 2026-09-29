from jose import jwt

from app.core.config import settings
from app.models.user import UserRole
from tests.conftest import TEST_PASSWORD


async def test_login_me_refresh_logout_cycle(client, make_user):
    user = await make_user(UserRole.patient)

    login = await client.post("/api/v1/auth/login", json={"email": user.email, "password": TEST_PASSWORD})
    assert login.status_code == 200
    tokens = login.json()

    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == user.email

    refreshed = await client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"]

    logout = await client.post("/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]})
    assert logout.status_code == 204

    after = await client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert after.status_code == 401


async def test_wrong_password_is_401(client, make_user):
    user = await make_user()
    response = await client.post("/api/v1/auth/login", json={"email": user.email, "password": "wrong"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


async def test_unknown_email_gives_same_error_as_wrong_password(client):
    response = await client.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": "x"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


async def test_inactive_user_cannot_log_in(client, make_user):
    user = await make_user(is_active=False)
    response = await client.post("/api/v1/auth/login", json={"email": user.email, "password": TEST_PASSWORD})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ACCOUNT_INACTIVE"


async def test_garbage_token_is_401(client):
    response = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert response.status_code == 401


async def test_token_with_non_numeric_subject_is_401_not_500(client):
    token = jwt.encode({"sub": "abc"}, settings.secret_key, algorithm=settings.algorithm)
    response = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


async def test_unknown_refresh_token_is_401(client):
    response = await client.post("/api/v1/auth/refresh", json={"refresh_token": "nope"})
    assert response.status_code == 401
