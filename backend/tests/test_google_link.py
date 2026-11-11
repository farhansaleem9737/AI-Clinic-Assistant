"""Linking Google to an existing account at sign-in (D128).

Google is scripted (tests/test_google_auth.py `google` fixture): each authorization
code yields a chosen verified identity. Emails go to the development outbox in a
temporary folder. Only test accounts are used.
"""

import asyncio
import os
import re
import uuid
from datetime import timedelta
from email import policy
from email.parser import BytesParser

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core import clock
from app.core.config import settings
from app.core.exceptions import BusinessRuleError
from app.core.permissions import RoleCode
from app.core.security import hash_token
from app.models.admin import AuditLog
from app.models.notification import NotificationPreference
from app.models.oauth import OAuthFlow, OAuthIdentity
from app.models.user import User
from app.services import auth_service, google_auth_service
from tests.conftest import TEST_PASSWORD, TEST_PASSWORD_HASH
from tests.test_auth import cookies_from
from tests.test_google_auth import API, callback, google, start  # noqa: F401  (google is a fixture)

LINK = f"{API}/google/link-ticket"


def emails(outbox):
    if not outbox.exists():
        return []
    parsed = [BytesParser(policy=policy.default).parsebytes(p.read_bytes()) for p in sorted(outbox.glob("*.eml"))]
    return [(m["To"], str(m["Subject"]), m.get_body(("plain",)).get_content()) for m in parsed]


async def google_sign_in(client, google, code, sub, email):
    """Continue with Google → callback; returns (path, cookies set)."""
    google(code, sub, email)
    query, binder = await start(client)
    response, path = await callback(client, query["state"][0], binder, code=code)
    return path, cookies_from(response)


async def offered(client, google, user, sub="sub-new"):
    """Google matches `user`'s address: the link step's cookie header."""
    path, cookies = await google_sign_in(client, google, f"code-{uuid.uuid4().hex[:6]}", sub, user.email)
    assert path == "/login/link-google"
    ticket = cookies["g_link"]
    assert ticket["httponly"] and ticket["path"] == "/api/v1/auth/google" and int(ticket["max-age"]) <= 15 * 60
    return {"Cookie": f"g_link={ticket.value}"}


async def me(client, token):
    return (await client.get(f"{API}/me", headers={"Authorization": f"Bearer {token}"})).json()


async def google_login(client, google, sub, email):
    path, cookies = await google_sign_in(client, google, f"code-{uuid.uuid4().hex[:6]}", sub, email)
    assert path == "/auth/google/complete", path
    done = await client.post(f"{API}/google/complete", headers={"Cookie": f"g_handoff={cookies['g_handoff'].value}"})
    assert done.status_code == 200
    return done.json()["access_token"]


async def test_password_proof_links_google_to_the_same_user_and_both_ways_sign_in(
    client, google, make_patient, db_session, isolated_side_channels
):
    patient = await make_patient(with_account=True)
    user = await db_session.get(User, patient.user_id)
    prefs = await db_session.get(NotificationPreference, user.id)
    if prefs is None:
        db_session.add(NotificationPreference(user_id=user.id, reminders=False))
    else:
        prefs.reminders = False
    await db_session.commit()
    users_before = await db_session.scalar(select(func.count()).select_from(User))

    cookie = await offered(client, google, user, sub="sub-alice")
    ticket = (await client.get(LINK, headers=cookie)).json()
    assert ticket == {"email": user.email, "methods": ["password", "email_code"], "code_sent": False, "resend_in": 0, "attempts_left": 5}
    # Nothing is linked and nobody signed in before the proof.
    assert await db_session.scalar(select(OAuthIdentity).where(OAuthIdentity.user_id == user.id)) is None

    linked = await client.post(f"{LINK}/verify", json={"password": TEST_PASSWORD}, headers=cookie)
    assert linked.status_code == 200, linked.text
    assert "g_link" in linked.headers.get("set-cookie", "")  # cleared
    via_link = await me(client, linked.json()["access_token"])
    assert via_link["id"] == str(user.id) and via_link["roles"] == ["patient"] and via_link["patient_id"] == str(patient.id)

    identity = await db_session.scalar(select(OAuthIdentity).where(OAuthIdentity.user_id == user.id))
    assert identity.subject == "sub-alice" and identity.provider == "google"
    assert await db_session.scalar(select(func.count()).select_from(User)) == users_before  # no duplicate account
    audit = await db_session.scalar(select(AuditLog).where(AuditLog.target_id == str(user.id), AuditLog.action == "user.google_linked"))
    assert audit.details == {"at_sign_in": True, "verified_with": "password"}
    # The owner is told, whoever linked it.
    assert any(to == user.email and "Google sign-in was connected" in subject for to, subject, _ in emails(isolated_side_channels))

    # Both sign-in methods: the same user, roles, profile and preferences.
    client.cookies.clear()
    by_password = await client.post(f"{API}/login", json={"email": user.email, "password": TEST_PASSWORD})
    assert by_password.status_code == 200
    by_google = await google_login(client, google, "sub-alice", user.email)
    a, b = await me(client, by_password.json()["access_token"]), await me(client, by_google)
    assert a["id"] == b["id"] == str(user.id) and a["roles"] == b["roles"] and a["patient_id"] == b["patient_id"]
    await db_session.refresh(user)
    assert user.password_hash == TEST_PASSWORD_HASH  # the password stays
    prefs = await db_session.get(NotificationPreference, user.id)
    await db_session.refresh(prefs)
    assert prefs.reminders is False


async def test_email_code_proof_with_resend_wait(client, google, make_user, db_session, isolated_side_channels):
    user = await make_user(RoleCode.patient)
    cookie = await offered(client, google, user)
    assert (await client.post(f"{LINK}/code", headers=cookie)).status_code == 204
    [(to, subject, text)] = [m for m in emails(isolated_side_channels) if "connect Google" in m[1]]
    assert to == user.email and subject == "Your code to connect Google sign-in — Clinic AI Assistant"
    code = re.search(r"^\s+(\d{6})\s*$", text, re.M).group(1)
    again = await client.post(f"{LINK}/code", headers=cookie)
    assert again.status_code == 429 and again.json()["error"]["code"] == "CODE_RECENTLY_SENT"

    wrong = await client.post(f"{LINK}/verify", json={"code": f"{(int(code) + 1) % 10**6:06d}"}, headers=cookie)
    assert wrong.status_code == 400 and wrong.json()["error"]["code"] == "LINK_PROOF_INVALID"
    assert wrong.json()["error"]["details"]["attempts_left"] == 4
    ok = await client.post(f"{LINK}/verify", json={"code": code}, headers=cookie)
    assert ok.status_code == 200, ok.text
    assert (await me(client, ok.json()["access_token"]))["id"] == str(user.id)
    # The code and the step are used up.
    assert (await client.post(f"{LINK}/verify", json={"code": code}, headers=cookie)).json()["error"]["code"] == "GOOGLE_STATE_INVALID"


@pytest.mark.parametrize("role", [RoleCode.admin, RoleCode.doctor, RoleCode.receptionist])
async def test_staff_and_admins_must_use_their_password_and_keep_their_roles(client, google, make_user, db_session, role):
    user = await make_user(role)
    cookie = await offered(client, google, user)
    assert (await client.get(LINK, headers=cookie)).json()["methods"] == ["password"]
    refused = await client.post(f"{LINK}/code", headers=cookie)
    assert refused.status_code == 400 and refused.json()["error"]["code"] == "LINK_METHOD_UNAVAILABLE"
    assert (await client.post(f"{LINK}/verify", json={"code": "123456"}, headers=cookie)).json()["error"]["code"] == "LINK_METHOD_UNAVAILABLE"
    ok = await client.post(f"{LINK}/verify", json={"password": TEST_PASSWORD}, headers=cookie)
    assert ok.status_code == 200
    assert (await me(client, ok.json()["access_token"]))["roles"] == [role.value]  # never more


async def test_a_doctor_applicant_stays_an_applicant(client, google, make_user):
    user = await make_user(RoleCode.doctor_applicant)
    cookie = await offered(client, google, user)
    ok = await client.post(f"{LINK}/verify", json={"password": TEST_PASSWORD}, headers=cookie)
    assert (await me(client, ok.json()["access_token"]))["roles"] == ["doctor_applicant"]  # review not bypassed


async def test_wrong_passwords_are_limited_and_link_nothing(client, google, make_user, db_session):
    user = await make_user(RoleCode.patient)
    cookie = await offered(client, google, user)
    for left in (4, 3, 2, 1):
        wrong = await client.post(f"{LINK}/verify", json={"password": "not it"}, headers=cookie)
        assert wrong.status_code == 400 and wrong.json()["error"]["details"]["attempts_left"] == left
    last = await client.post(f"{LINK}/verify", json={"password": "not it"}, headers=cookie)
    assert last.json()["error"]["code"] == "GOOGLE_STATE_INVALID"
    assert (await client.post(f"{LINK}/verify", json={"password": TEST_PASSWORD}, headers=cookie)).json()["error"]["code"] == "GOOGLE_STATE_INVALID"
    assert await db_session.scalar(select(OAuthIdentity).where(OAuthIdentity.user_id == user.id)) is None
    assert "set-cookie" not in last.headers or "refresh" not in last.headers["set-cookie"]


async def test_expired_cancelled_missing_or_malformed_steps_link_nothing(client, google, make_user, db_session, freeze_clock):
    user = await make_user(RoleCode.patient)
    cookie = await offered(client, google, user)
    assert (await client.post(f"{LINK}/verify", json={}, headers=cookie)).status_code == 422
    assert (await client.post(f"{LINK}/verify", json={"password": "x", "code": "123456"}, headers=cookie)).status_code == 422
    client.cookies.clear()  # no g_link cookie at all
    assert (await client.post(f"{LINK}/verify", json={"password": TEST_PASSWORD})).json()["error"]["code"] == "GOOGLE_STATE_INVALID"

    assert (await client.post(f"{LINK}/cancel", headers=cookie)).status_code == 204
    assert (await client.get(LINK, headers=cookie)).status_code == 400

    cookie = await offered(client, google, user)
    freeze_clock(clock.utcnow() + timedelta(minutes=16))
    late = await client.post(f"{LINK}/verify", json={"password": TEST_PASSWORD}, headers=cookie)
    assert late.status_code == 400 and late.json()["error"]["code"] == "GOOGLE_STATE_INVALID"
    assert await db_session.scalar(select(OAuthIdentity).where(OAuthIdentity.user_id == user.id)) is None


async def test_a_deactivated_account_is_not_offered_a_link(client, google, make_user, db_session):
    user = await make_user(RoleCode.patient, is_active=False)
    path, cookies = await google_sign_in(client, google, "code-off", "sub-off", user.email)
    assert path == "/login?google=inactive" and "g_link" not in cookies


async def test_deactivated_while_linking_cannot_finish(client, google, make_user, db_session):
    user = await make_user(RoleCode.patient)
    cookie = await offered(client, google, user)
    row = await db_session.get(User, user.id)
    row.is_active = False
    await db_session.commit()
    refused = await client.post(f"{LINK}/verify", json={"password": TEST_PASSWORD}, headers=cookie)
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "ACCOUNT_INACTIVE"


async def test_a_google_account_linked_elsewhere_meanwhile_is_refused(client, google, make_user, db_session):
    user = await make_user(RoleCode.patient)
    other = await make_user(RoleCode.patient)
    cookie = await offered(client, google, user, sub="sub-contested")
    db_session.add(OAuthIdentity(user_id=other.id, provider="google", subject="sub-contested", email=other.email))
    await db_session.commit()
    refused = await client.post(f"{LINK}/verify", json={"password": TEST_PASSWORD}, headers=cookie)
    assert refused.status_code == 400 and refused.json()["error"]["code"] == "GOOGLE_IDENTITY_IN_USE"
    assert await db_session.scalar(select(OAuthIdentity).where(OAuthIdentity.user_id == user.id)) is None


async def test_a_different_google_account_on_a_linked_login_is_refused(client, google, make_user, db_session):
    user = await make_user(RoleCode.patient)
    db_session.add(OAuthIdentity(user_id=user.id, provider="google", subject="sub-first", email=user.email))
    await db_session.commit()
    path, cookies = await google_sign_in(client, google, "code-second", "sub-second", user.email)
    assert path == "/login?google=already_linked" and "g_link" not in cookies


async def test_a_changed_google_email_still_finds_the_same_user(client, google, make_user, db_session):
    user = await make_user(RoleCode.patient)
    db_session.add(OAuthIdentity(user_id=user.id, provider="google", subject="sub-stable", email=user.email))
    await db_session.commit()
    token = await google_login(client, google, "sub-stable", "renamed.address@gmail.com")
    assert (await me(client, token))["id"] == str(user.id)
    assert await db_session.scalar(select(func.count()).select_from(OAuthIdentity).where(OAuthIdentity.subject == "sub-stable")) == 1


async def test_a_new_google_user_still_registers(client, google):
    path, cookies = await google_sign_in(client, google, "code-fresh", "sub-fresh", "brand.new@example.com")
    assert path == "/register/google" and "g_signup" in cookies


async def test_two_proofs_at_once_link_once():
    """Real concurrency needs committed rows and two connections (outside the per-test rollback)."""
    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    raw = "link-" + uuid.uuid4().hex
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        user = User(name="Link Race", email=f"link-race-{uuid.uuid4().hex[:8]}@example.com", password_hash=TEST_PASSWORD_HASH)
        setup.add(user)
        await setup.flush()
        setup.add(OAuthFlow(
            kind="link", purpose="login", provider="google", token_hash=hash_token(raw), binder_hash=hash_token(raw),
            user_id=user.id, subject=f"sub-race-{uuid.uuid4().hex}", email=user.email,
            expires_at=clock.utcnow() + timedelta(minutes=15),
        ))
        await setup.commit()
    client = auth_service.ClientInfo(user_agent="test", ip_address=None)
    try:
        settings_enabled = settings.google_oauth_enabled
        settings.google_oauth_enabled = True

        async def attempt():
            async with AsyncSession(engine, expire_on_commit=False) as session:
                try:
                    await google_auth_service.link_and_sign_in(session, raw, client, password=TEST_PASSWORD)
                    return "ok"
                except BusinessRuleError as exc:
                    return exc.code

        results = await asyncio.gather(attempt(), attempt())
        assert sorted(results) == ["GOOGLE_STATE_INVALID", "ok"]
        async with AsyncSession(engine) as check:
            count = await check.scalar(select(func.count()).select_from(OAuthIdentity).where(OAuthIdentity.user_id == user.id))
        assert count == 1
    finally:
        settings.google_oauth_enabled = settings_enabled
        async with AsyncSession(engine) as cleanup:
            await cleanup.execute(delete(AuditLog).where(AuditLog.target_id == str(user.id)))
            await cleanup.execute(delete(User).where(User.id == user.id))
            await cleanup.commit()
        await engine.dispose()
