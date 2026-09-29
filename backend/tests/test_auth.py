from datetime import timedelta
from http.cookies import SimpleCookie

import pytest
from jose import jwt
from sqlalchemy import select

from app.core import clock
from app.core.config import settings
from app.core.permissions import RoleCode
from app.core.security import create_access_token, hash_token
from app.models.refresh_token import RefreshToken
from tests.conftest import TEST_PASSWORD

LOGIN = "/api/v1/auth/login"
REFRESH = "/api/v1/auth/refresh"
LOGOUT = "/api/v1/auth/logout"
ME = "/api/v1/auth/me"


def cookies_from(response) -> dict[str, SimpleCookie]:
    """Parse every Set-Cookie header into {name: morsel}."""
    parsed = {}
    for header in response.headers.get_list("set-cookie"):
        jar = SimpleCookie()
        jar.load(header)
        for name, morsel in jar.items():
            parsed[name] = morsel
    return parsed


class Session:
    """The browser's view: the two cookies, sent explicitly so each test
    controls exactly which refresh token is presented."""

    def __init__(self, response):
        cookies = cookies_from(response)
        self.refresh = cookies[settings.refresh_cookie_name].value
        self.csrf = cookies[settings.csrf_cookie_name].value

    def headers(self, csrf: bool = True, refresh: str | None = None) -> dict[str, str]:
        headers = {"Cookie": f"{settings.refresh_cookie_name}={refresh or self.refresh}; {settings.csrf_cookie_name}={self.csrf}"}
        if csrf:
            headers[settings.csrf_header_name] = self.csrf
        return headers

    def update(self, response) -> None:
        cookies = cookies_from(response)
        if settings.refresh_cookie_name in cookies:
            self.refresh = cookies[settings.refresh_cookie_name].value
            self.csrf = cookies[settings.csrf_cookie_name].value


@pytest.fixture
def advance_clock(monkeypatch):
    def _advance(delta: timedelta) -> None:
        target = clock.utcnow() + delta
        monkeypatch.setattr(clock, "utcnow", lambda: target)

    return _advance


async def _login(client, make_user, **kwargs):
    user = await make_user(RoleCode.patient, **kwargs)
    response = await client.post(LOGIN, json={"email": user.email, "password": TEST_PASSWORD})
    assert response.status_code == 200, response.text
    return user, response


async def test_login_returns_access_token_and_sets_hardened_cookies(client, make_user):
    _, response = await _login(client, make_user)

    body = response.json()
    assert set(body) == {"access_token", "token_type", "expires_in"}
    assert "refresh" not in response.text

    cookies = cookies_from(response)
    refresh = cookies[settings.refresh_cookie_name]
    assert refresh["httponly"] is True
    assert refresh["samesite"].lower() == "strict"
    assert refresh["path"] == "/api/v1/auth"

    csrf = cookies[settings.csrf_cookie_name]
    assert not csrf["httponly"]
    assert csrf["path"] == "/"


async def test_only_the_hash_of_the_refresh_token_is_stored(client, make_user, db_session):
    user, response = await _login(client, make_user)
    raw = Session(response).refresh

    stored = (await db_session.scalars(select(RefreshToken).where(RefreshToken.user_id == user.id))).all()
    assert len(stored) == 1
    assert stored[0].token_hash == hash_token(raw)
    assert raw not in stored[0].token_hash


async def test_me_reports_roles_and_permissions(client, make_user):
    user = await make_user(RoleCode.admin)
    login = await client.post(LOGIN, json={"email": user.email, "password": TEST_PASSWORD})
    me = await client.get(ME, headers={"Authorization": f"Bearer {login.json()['access_token']}"})
    assert me.status_code == 200
    assert me.json()["roles"] == ["admin"]
    assert "user:create" in me.json()["permissions"]


async def test_refresh_requires_csrf_header(client, make_user):
    _, response = await _login(client, make_user)
    session = Session(response)

    response = await client.post(REFRESH, headers=session.headers(csrf=False))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_FAILED"


async def test_refresh_rejects_mismatched_csrf_header(client, make_user):
    _, response = await _login(client, make_user)
    session = Session(response)
    headers = session.headers()
    headers[settings.csrf_header_name] = "forged"

    response = await client.post(REFRESH, headers=headers)
    assert response.status_code == 403


async def test_refresh_without_session_is_401(client):
    response = await client.post(REFRESH)
    assert response.status_code == 401


async def test_refresh_rotates_the_token(client, make_user):
    _, response = await _login(client, make_user)
    session = Session(response)
    first = session.refresh

    response = await client.post(REFRESH, headers=session.headers())
    assert response.status_code == 200
    assert response.json()["access_token"]
    session.update(response)
    assert session.refresh != first

    # The successor keeps working.
    response = await client.post(REFRESH, headers=session.headers())
    assert response.status_code == 200


async def test_reusing_a_rotated_token_revokes_the_whole_family(client, make_user, advance_clock):
    _, response = await _login(client, make_user)
    session = Session(response)
    stolen = session.refresh

    session.update(await client.post(REFRESH, headers=session.headers()))
    advance_clock(timedelta(seconds=settings.refresh_reuse_grace_seconds + 1))

    replay = await client.post(REFRESH, headers=session.headers(refresh=stolen))
    assert replay.status_code == 401

    # The legitimate holder's current token is now dead too: forced re-login.
    legit = await client.post(REFRESH, headers=session.headers())
    assert legit.status_code == 401


async def test_concurrent_refresh_within_grace_is_not_treated_as_theft(client, make_user):
    _, response = await _login(client, make_user)
    session = Session(response)
    original = session.refresh

    first = await client.post(REFRESH, headers=session.headers())
    assert first.status_code == 200
    session.update(first)

    # Second tab presents the same (just-rotated) token a moment later.
    second = await client.post(REFRESH, headers=session.headers(refresh=original))
    assert second.status_code == 200
    assert settings.refresh_cookie_name not in cookies_from(second)

    # And the family is still alive.
    assert (await client.post(REFRESH, headers=session.headers())).status_code == 200


async def test_logout_revokes_the_session(client, make_user):
    _, response = await _login(client, make_user)
    session = Session(response)

    logout = await client.post(LOGOUT, headers=session.headers())
    assert logout.status_code == 204
    cleared = cookies_from(logout)[settings.refresh_cookie_name]
    assert cleared.value == ""

    assert (await client.post(REFRESH, headers=session.headers())).status_code == 401


async def test_expired_refresh_token_is_rejected(client, make_user, advance_clock):
    _, response = await _login(client, make_user)
    session = Session(response)

    advance_clock(timedelta(days=settings.refresh_token_expire_days, seconds=1))
    response = await client.post(REFRESH, headers=session.headers())
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "REFRESH_TOKEN_EXPIRED"


async def test_deactivated_user_cannot_refresh_or_use_access_token(client, make_user, db_session):
    user, response = await _login(client, make_user)
    session = Session(response)
    access = {"Authorization": f"Bearer {response.json()['access_token']}"}

    from app.models.user import User

    (await db_session.get(User, user.id)).is_active = False
    await db_session.flush()

    assert (await client.post(REFRESH, headers=session.headers())).status_code == 401
    assert (await client.get(ME, headers=access)).status_code == 401


async def test_wrong_password_is_401(client, make_user):
    user = await make_user()
    response = await client.post(LOGIN, json={"email": user.email, "password": "wrong"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


async def test_unknown_email_gives_same_error_as_wrong_password(client):
    response = await client.post(LOGIN, json={"email": "nobody@example.com", "password": "x"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


async def test_inactive_user_cannot_log_in(client, make_user):
    user = await make_user(is_active=False)
    response = await client.post(LOGIN, json={"email": user.email, "password": TEST_PASSWORD})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ACCOUNT_INACTIVE"


async def test_garbage_token_is_401(client):
    response = await client.get(ME, headers={"Authorization": "Bearer not-a-jwt"})
    assert response.status_code == 401


async def test_token_with_non_uuid_subject_is_401_not_500(client):
    token = jwt.encode({"sub": "abc", "type": "access"}, settings.secret_key, algorithm=settings.algorithm)
    response = await client.get(ME, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


async def test_token_of_wrong_type_is_rejected(client, make_user):
    user = await make_user()
    token = jwt.encode({"sub": str(user.id), "type": "refresh"}, settings.secret_key, algorithm=settings.algorithm)
    response = await client.get(ME, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


async def test_expired_access_token_is_rejected(client, make_user):
    user = await make_user()
    token = create_access_token(user.id, ["patient"])
    # jose checks exp against the real clock, so build an already-expired token.
    expired = jwt.encode(
        {"sub": str(user.id), "type": "access", "exp": clock.utcnow() - timedelta(days=1)},
        settings.secret_key,
        algorithm=settings.algorithm,
    )
    assert (await client.get(ME, headers={"Authorization": f"Bearer {token}"})).status_code == 200
    assert (await client.get(ME, headers={"Authorization": f"Bearer {expired}"})).status_code == 401
