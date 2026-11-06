"""Changing the signed-in user's password (D116): recent sign-in or the current
password, every other session ended, this browser kept signed in, audited."""

from datetime import timedelta

from sqlalchemy import select

from app.core.config import settings
from app.core.permissions import RoleCode
from app.models.admin import AuditLog
from tests.conftest import TEST_PASSWORD
from tests.test_auth import LOGIN, ME, REFRESH, Session, advance_clock  # noqa: F401  (advance_clock is a fixture)

PASSWORD = "/api/v1/auth/password"
NEW = "a long new passphrase 2026!"


async def sign_in(client, email, password=TEST_PASSWORD):
    response = await client.post(LOGIN, json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    client.cookies.clear()  # each request below sends exactly this session's cookies
    session = Session(response)
    session.bearer = {"Authorization": f"Bearer {response.json()['access_token']}"}
    return session


def as_(session, csrf=True):
    return {**session.headers(csrf=csrf), **session.bearer}


async def test_right_after_sign_in_no_current_password_is_needed(client, make_user, db_session):
    user = await make_user(RoleCode.patient)
    other_device = await sign_in(client, user.email)
    me = await sign_in(client, user.email)
    assert (await client.get(PASSWORD, headers=as_(me))).json()["current_password_required"] is False

    changed = await client.post(PASSWORD, json={"new_password": NEW}, headers=as_(me))
    assert changed.status_code == 200, changed.text
    assert set(changed.json()) == {"access_token", "token_type", "expires_in"}  # nothing about the password
    me.update(changed)
    me.bearer = {"Authorization": f"Bearer {changed.json()['access_token']}"}

    # This browser stays signed in with its new session; the other device is signed out.
    assert (await client.get(ME, headers=me.bearer)).status_code == 200
    assert (await client.post(REFRESH, headers=me.headers())).status_code == 200
    assert (await client.post(REFRESH, headers=other_device.headers())).status_code == 401
    # Old password no longer works; the new one does.
    assert (await client.post(LOGIN, json={"email": user.email, "password": TEST_PASSWORD})).status_code == 401
    assert (await client.post(LOGIN, json={"email": user.email, "password": NEW})).status_code == 200

    entry = await db_session.scalar(select(AuditLog).where(AuditLog.target_id == str(user.id), AuditLog.action == "user.password_changed"))
    assert entry is not None and entry.details == {"verified_with": "recent_sign_in"}


async def test_later_the_current_password_is_required_and_checked(client, make_user, advance_clock):
    user = await make_user(RoleCode.receptionist)
    me = await sign_in(client, user.email)
    advance_clock(timedelta(minutes=settings.password_change_recent_auth_minutes + 1))
    assert (await client.get(PASSWORD, headers=as_(me))).json()["current_password_required"] is True

    missing = await client.post(PASSWORD, json={"new_password": NEW}, headers=as_(me))
    assert missing.status_code == 403 and missing.json()["error"]["code"] == "REAUTHENTICATION_REQUIRED"
    wrong = await client.post(PASSWORD, json={"new_password": NEW, "current_password": "not-it-at-all"}, headers=as_(me))
    assert wrong.status_code == 400 and wrong.json()["error"]["code"] == "INCORRECT_PASSWORD"
    ok = await client.post(PASSWORD, json={"new_password": NEW, "current_password": TEST_PASSWORD}, headers=as_(me))
    assert ok.status_code == 200, ok.text


async def test_weak_or_unchanged_passwords_are_refused(client, make_user):
    user = await make_user(RoleCode.doctor)
    me = await sign_in(client, user.email)
    assert (await client.post(PASSWORD, json={"new_password": "short"}, headers=as_(me))).status_code == 422
    same = await client.post(PASSWORD, json={"new_password": TEST_PASSWORD}, headers=as_(me))
    assert same.json()["error"]["code"] == "PASSWORD_UNCHANGED"


async def test_needs_the_csrf_header_and_this_browsers_session(client, make_user):
    user = await make_user(RoleCode.admin)
    me = await sign_in(client, user.email)
    assert (await client.post(PASSWORD, json={"new_password": NEW}, headers=as_(me, csrf=False))).status_code == 403
    bearer_only = await client.post(PASSWORD, json={"new_password": NEW}, headers=me.bearer)
    assert bearer_only.status_code in (401, 403)
    assert (await client.post(PASSWORD, json={"new_password": NEW})).status_code == 401  # not signed in
    # Nothing changed: the original password still signs in.
    assert (await client.post(LOGIN, json={"email": user.email, "password": TEST_PASSWORD})).status_code == 200
