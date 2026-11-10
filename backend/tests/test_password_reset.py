"""Forgot password by email (D126)."""

import asyncio
import logging
import os
import re
import uuid
from datetime import timedelta
from email import policy
from email.parser import BytesParser

import pytest
from jose import jwt
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core import clock
from app.core.config import EmailBackend, settings
from app.core.exceptions import BusinessRuleError
from app.core.permissions import RoleCode
from app.core.security import hash_token
from app.models.admin import AuditLog
from app.models.password_reset import PasswordResetToken
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.services import email_service, password_reset_service
from tests.conftest import TEST_PASSWORD, TEST_PASSWORD_HASH
from tests.test_auth import Session

FORGOT = "/api/v1/auth/forgot-password"
CHECK = "/api/v1/auth/reset-password/check"
RESET = "/api/v1/auth/reset-password"
LOGIN = "/api/v1/auth/login"
NEW_PASSWORD = "A-brand-new passphrase 42"
GENERIC = "If an account exists for this email, you'll receive a password reset link shortly."


def emails(outbox):
    """The development outbox's messages, oldest first, decoded."""
    if not outbox.exists():
        return []
    parsed = [BytesParser(policy=policy.default).parsebytes(p.read_bytes()) for p in sorted(outbox.glob("*.eml"))]
    return [(m["To"], str(m["Subject"]), m.get_body(("plain",)).get_content()) for m in parsed]


def token_in(text: str) -> str:
    return re.search(r"/reset-password#token=([A-Za-z0-9_-]+)", text).group(1)


async def request_link(client, outbox, email: str) -> str:
    response = await client.post(FORGOT, json={"email": email})
    assert response.status_code == 200, response.text
    return token_in(emails(outbox)[-1][2])


async def test_request_emails_a_single_use_link_and_stores_only_its_hash(client, db_session, make_user, isolated_side_channels):
    user = await make_user(RoleCode.patient)
    response = await client.post(FORGOT, json={"email": user.email.upper()})  # normalized like sign-in
    assert response.json() == {"message": GENERIC}

    [(to, subject, text)] = emails(isolated_side_channels)
    assert to == user.email and subject == "Reset your password — Clinic AI Assistant"
    assert "This link expires in 15 minutes" in text and "safely ignore this email" in text
    raw = token_in(text)
    assert len(raw) >= 43  # 256 bits, URL-safe
    assert text.count(f"{settings.frontend_base_url}/reset-password#token={raw}") == 1

    [row] = (await db_session.scalars(select(PasswordResetToken).where(PasswordResetToken.user_id == user.id))).all()
    assert row.token_hash == hash_token(raw) and raw not in row.token_hash
    assert timedelta(minutes=14) < row.expires_at - row.created_at <= timedelta(minutes=15)
    assert row.consumed_at is None


@pytest.mark.parametrize("case", ["unknown", "inactive"])
async def test_no_account_gets_the_same_answer_and_no_email(client, make_user, isolated_side_channels, case):
    email = "nobody-here@example.com" if case == "unknown" else (await make_user(RoleCode.patient, is_active=False)).email
    response = await client.post(FORGOT, json={"email": email})
    assert response.status_code == 200 and response.json() == {"message": GENERIC}
    assert "set-cookie" not in response.headers
    assert emails(isolated_side_channels) == []


@pytest.mark.parametrize("role", [RoleCode.admin, RoleCode.doctor, RoleCode.receptionist, RoleCode.patient])
async def test_reset_sets_the_password_ends_every_session_and_signs_nobody_in(
    client, db_session, make_user, isolated_side_channels, role
):
    user = await make_user(role)
    signed_in = await client.post(LOGIN, json={"email": user.email, "password": TEST_PASSWORD})
    session = Session(signed_in)
    # An access token issued before the reset (a second earlier than "now", as in real use).
    now = clock.utcnow()
    old_access = jwt.encode(
        {"sub": str(user.id), "roles": [role.value], "type": "access", "jti": uuid.uuid4().hex,
         "iat": now - timedelta(seconds=5), "exp": now + timedelta(minutes=10)},
        settings.secret_key, algorithm=settings.algorithm,
    )
    assert (await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {old_access}"})).status_code == 200

    raw = await request_link(client, isolated_side_channels, user.email)
    assert (await client.post(CHECK, json={"token": raw})).status_code == 204
    response = await client.post(RESET, json={"token": raw, "new_password": NEW_PASSWORD})
    assert response.status_code == 200, response.text
    assert "set-cookie" not in response.headers and "access_token" not in response.json()

    assert (await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {old_access}"})).status_code == 401
    assert (await client.post("/api/v1/auth/refresh", headers=session.headers())).status_code == 401
    live = await db_session.scalar(
        select(RefreshToken.id).where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
    )
    assert live is None
    assert (await client.post(LOGIN, json={"email": user.email, "password": TEST_PASSWORD})).status_code == 401
    fresh = await client.post(LOGIN, json={"email": user.email, "password": NEW_PASSWORD})
    assert fresh.status_code == 200
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {fresh.json()['access_token']}"})
    assert me.status_code == 200

    again = await client.post(RESET, json={"token": raw, "new_password": "Another passphrase 43"})
    assert again.status_code == 400 and again.json()["error"]["code"] == "RESET_TOKEN_USED"
    audit = await db_session.scalar(select(AuditLog).where(AuditLog.target_id == str(user.id), AuditLog.action == "user.password_reset"))
    assert audit is not None and NEW_PASSWORD not in str(audit.details) and raw not in str(audit.details)


async def test_expired_invalid_and_replaced_links_are_refused(client, make_user, isolated_side_channels, freeze_clock, monkeypatch):
    user = await make_user(RoleCode.patient)
    first = await request_link(client, isolated_side_channels, user.email)
    monkeypatch.setattr(settings, "password_reset_resend_seconds", 0)
    second = await request_link(client, isolated_side_channels, user.email)
    assert first != second

    replaced = await client.post(CHECK, json={"token": first})
    assert replaced.status_code == 400 and replaced.json()["error"]["code"] == "RESET_TOKEN_EXPIRED"
    bogus = await client.post(RESET, json={"token": "x" * 43, "new_password": NEW_PASSWORD})
    assert bogus.json()["error"]["code"] == "RESET_TOKEN_INVALID"

    freeze_clock(clock.utcnow() + timedelta(minutes=16))
    late = await client.post(RESET, json={"token": second, "new_password": NEW_PASSWORD})
    assert late.status_code == 400 and late.json()["error"]["code"] == "RESET_TOKEN_EXPIRED"
    assert (await client.post(LOGIN, json={"email": user.email, "password": TEST_PASSWORD})).status_code == 200


async def test_password_rule_is_enforced_without_using_up_the_link(client, make_user, isolated_side_channels):
    user = await make_user(RoleCode.patient)
    raw = await request_link(client, isolated_side_channels, user.email)
    assert (await client.post(RESET, json={"token": raw, "new_password": "short"})).status_code == 422
    assert (await client.post(RESET, json={"token": raw, "new_password": "x" * 129})).status_code == 422
    assert (await client.post(CHECK, json={"token": raw})).status_code == 204


async def test_links_per_account_and_requests_per_ip_are_bounded(client, make_user, isolated_side_channels, monkeypatch):
    user = await make_user(RoleCode.patient)
    monkeypatch.setattr(settings, "password_reset_requests_per_minute", 100)
    await request_link(client, isolated_side_channels, user.email)
    # A second request at once: same answer, no second email.
    assert (await client.post(FORGOT, json={"email": user.email})).json() == {"message": GENERIC}
    assert len(emails(isolated_side_channels)) == 1

    # At most PASSWORD_RESET_MAX_PER_HOUR links an hour, whatever the spacing.
    monkeypatch.setattr(settings, "password_reset_resend_seconds", 0)
    for _ in range(settings.password_reset_max_per_hour + 2):
        assert (await client.post(FORGOT, json={"email": user.email})).json() == {"message": GENERIC}
    assert len(emails(isolated_side_channels)) == settings.password_reset_max_per_hour

    # And per client IP (whatever the address, so it reveals nothing about accounts).
    monkeypatch.setattr(settings, "password_reset_requests_per_minute", 10)  # 9 used so far
    assert (await client.post(FORGOT, json={"email": "someone-else@example.com"})).status_code == 200
    assert (await client.post(FORGOT, json={"email": "someone-else@example.com"})).status_code == 429


async def test_google_only_account_is_told_to_use_google_and_gets_no_link(client, db_session, make_user, isolated_side_channels):
    user = await make_user(RoleCode.patient)
    row = await db_session.get(User, user.id)
    row.password_hash = None
    await db_session.commit()
    assert (await client.post(FORGOT, json={"email": user.email})).json() == {"message": GENERIC}
    [(_, _, text)] = emails(isolated_side_channels)
    assert "Continue with Google" in text and "#token=" not in text
    assert await db_session.scalar(select(PasswordResetToken.id).where(PasswordResetToken.user_id == user.id)) is None


@pytest.mark.parametrize("backend", ["none", "failing"])
async def test_email_trouble_keeps_the_answer_generic_and_logs_no_secrets(
    client, make_user, monkeypatch, caplog, backend
):
    user = await make_user(RoleCode.patient)
    if backend == "none":
        monkeypatch.setattr(settings, "email_backend", EmailBackend.none)
    else:
        async def refuse(_email):
            raise email_service.DeliveryError("SMTPServerDisconnected", permanent=False)

        monkeypatch.setattr(email_service, "deliver", refuse)
    sent = []
    real_send = password_reset_service.send

    async def spy(pending):
        sent.append(pending)
        await real_send(pending)

    monkeypatch.setattr(password_reset_service, "send", spy)

    with caplog.at_level(logging.DEBUG):
        response = await client.post(FORGOT, json={"email": user.email})
    assert response.status_code == 200 and response.json() == {"message": GENERIC}
    [pending] = sent
    raw = token_in(pending.email.text)
    assert raw not in caplog.text and "#token=" not in caplog.text
    assert "password_reset_email_not_sent" in caplog.text

    with caplog.at_level(logging.DEBUG):
        await client.post(RESET, json={"token": raw, "new_password": NEW_PASSWORD})
    assert NEW_PASSWORD not in caplog.text and raw not in caplog.text


async def test_two_submissions_of_one_link_cannot_both_succeed():
    """Real concurrency needs committed rows and two connections (outside the per-test rollback)."""
    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    raw = "concurrent-" + uuid.uuid4().hex + uuid.uuid4().hex
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        user = User(name="Race Test", email=f"race-{uuid.uuid4().hex[:8]}@example.com", password_hash=TEST_PASSWORD_HASH)
        setup.add(user)
        await setup.flush()
        now = clock.utcnow()
        setup.add(PasswordResetToken(user_id=user.id, token_hash=hash_token(raw), created_at=now, expires_at=now + timedelta(minutes=15)))
        await setup.commit()
    try:
        async def attempt(password):
            async with AsyncSession(engine, expire_on_commit=False) as session:
                try:
                    await password_reset_service.reset_password(session, raw, password, ip_address=None)
                    return "ok"
                except BusinessRuleError as exc:
                    return exc.code

        results = await asyncio.gather(attempt("First passphrase 1"), attempt("Second passphrase 2"))
        assert sorted(results) == ["RESET_TOKEN_USED", "ok"]
    finally:
        async with AsyncSession(engine) as cleanup:
            await cleanup.execute(delete(AuditLog).where(AuditLog.target_id == str(user.id)))
            await cleanup.execute(delete(User).where(User.id == user.id))
            await cleanup.commit()
        await engine.dispose()
