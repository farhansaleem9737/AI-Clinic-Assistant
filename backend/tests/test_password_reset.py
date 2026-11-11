"""Forgot password by emailed 6-digit code (D126, D127).

No real email: the development backend writes each message to a temporary
folder, which the tests read as the user's inbox. Only test accounts are used.
"""

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
from app.core.security import hash_token, verify_password
from app.models.admin import AuditLog
from app.models.password_reset import PasswordResetToken
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.services import email_service, password_reset_service
from tests.conftest import TEST_PASSWORD, TEST_PASSWORD_HASH
from tests.test_auth import Session

FORGOT = "/api/v1/auth/forgot-password"
VERIFY = "/api/v1/auth/verify-reset-otp"
RESET = "/api/v1/auth/reset-password"
LOGIN = "/api/v1/auth/login"
NEW_PASSWORD = "A-brand-new passphrase 42"
GENERIC = "If an account exists for this email, you'll receive a 6-digit code shortly."


def emails(outbox):
    """The development outbox's messages, oldest first, decoded."""
    if not outbox.exists():
        return []
    parsed = [BytesParser(policy=policy.default).parsebytes(p.read_bytes()) for p in sorted(outbox.glob("*.eml"))]
    return [(m["To"], str(m["Subject"]), m.get_body(("plain",)).get_content(), m.get_body(("html",)).get_content()) for m in parsed]


def code_in(text: str) -> str:
    return re.search(r"^\s+(\d{6})\s*$", text, re.M).group(1)


async def request_code(client, outbox, email: str) -> str:
    response = await client.post(FORGOT, json={"email": email})
    assert response.status_code == 200, response.text
    return code_in(emails(outbox)[-1][2])


async def verify(client, email: str, code: str):
    return await client.post(VERIFY, json={"email": email, "code": code})


async def grant_for(client, outbox, email: str) -> str:
    response = await verify(client, email, await request_code(client, outbox, email))
    assert response.status_code == 200, response.text
    return response.json()["reset_token"]


def wrong(code: str) -> str:
    return f"{(int(code) + 1) % 1_000_000:06d}"


async def test_request_emails_a_code_and_stores_only_its_hmac(client, db_session, make_user, isolated_side_channels):
    user = await make_user(RoleCode.patient)
    response = await client.post(FORGOT, json={"email": user.email.upper()})  # normalized like sign-in
    assert response.json() == {"message": GENERIC}

    [(to, subject, text, html)] = emails(isolated_side_channels)
    assert to == user.email and subject == "Your password reset code — Clinic AI Assistant"
    assert "We received a request to reset your password." in text and "This code expires in 10 minutes." in text
    assert "If you did not request this, you can ignore this email." in text
    code = code_in(text)
    assert code in html and "reset-password#" not in text + html and "token" not in text.lower()  # a code, no link

    [row] = (await db_session.scalars(select(PasswordResetToken).where(PasswordResetToken.user_id == user.id))).all()
    assert row.code_hash and code not in row.code_hash and row.token_hash is None
    assert row.attempts == 0 and row.verified_at is None and row.consumed_at is None
    assert timedelta(minutes=9) < row.expires_at - row.created_at <= timedelta(minutes=10)


@pytest.mark.parametrize("case", ["unknown", "inactive"])
async def test_no_account_gets_the_same_answers_and_no_email(client, make_user, isolated_side_channels, case):
    email = "nobody-here@example.com" if case == "unknown" else (await make_user(RoleCode.patient, is_active=False)).email
    response = await client.post(FORGOT, json={"email": email})
    assert response.status_code == 200 and response.json() == {"message": GENERIC}
    assert "set-cookie" not in response.headers
    assert emails(isolated_side_channels) == []
    refused = await verify(client, email, "123456")
    assert refused.status_code == 400 and refused.json()["error"]["code"] == "RESET_CODE_INVALID"


@pytest.mark.parametrize("role", [RoleCode.admin, RoleCode.doctor, RoleCode.receptionist, RoleCode.patient])
async def test_code_then_new_password_is_saved_ends_every_session_and_signs_nobody_in(
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

    code = await request_code(client, isolated_side_channels, user.email)
    verified = await verify(client, user.email, code)
    assert verified.status_code == 200, verified.text
    body = verified.json()
    grant = body["reset_token"]
    assert set(body) == {"reset_token", "expires_in"} and 0 < body["expires_in"] <= 600
    assert "set-cookie" not in verified.headers
    # The reset token is not a sign-in.
    assert (await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {grant}"})).status_code == 401
    # The code is used up by the verification.
    assert (await verify(client, user.email, code)).json()["error"]["code"] == "RESET_CODE_INVALID"

    response = await client.post(RESET, json={"token": grant, "new_password": NEW_PASSWORD})
    assert response.status_code == 200, response.text
    assert response.json() == {"message": "Your password has been changed successfully. You can now sign in using your new password."}
    assert "set-cookie" not in response.headers and "access_token" not in response.json()

    # Saved in PostgreSQL (read back on its own, not from the session's cache).
    db_session.expire_all()
    stored = await db_session.scalar(select(User.password_hash).where(User.id == user.id))
    assert stored != TEST_PASSWORD_HASH and verify_password(NEW_PASSWORD, stored)

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

    again = await client.post(RESET, json={"token": grant, "new_password": "Another passphrase 43"})
    assert again.status_code == 400 and again.json()["error"]["code"] == "RESET_TOKEN_USED"
    audit = await db_session.scalar(select(AuditLog).where(AuditLog.target_id == str(user.id), AuditLog.action == "user.password_reset"))
    assert audit is not None and audit.details == {"verified_with": "email_code"}


async def test_five_wrong_codes_use_the_code_up(client, db_session, make_user, isolated_side_channels, monkeypatch):
    monkeypatch.setattr(settings, "password_reset_attempts_per_minute", 100)
    user = await make_user(RoleCode.patient)
    code = await request_code(client, isolated_side_channels, user.email)
    for _ in range(settings.password_reset_code_max_attempts):
        refused = await verify(client, user.email, wrong(code))
        assert refused.status_code == 400 and refused.json()["error"]["code"] == "RESET_CODE_INVALID"
    # Even the right code no longer works: a new one is needed.
    assert (await verify(client, user.email, code)).json()["error"]["code"] == "RESET_CODE_INVALID"
    row = await db_session.scalar(select(PasswordResetToken).where(PasswordResetToken.user_id == user.id))
    await db_session.refresh(row)
    assert row.attempts == settings.password_reset_code_max_attempts and row.token_hash is None


async def test_expired_and_replaced_codes_and_tokens_are_refused(client, make_user, isolated_side_channels, freeze_clock, monkeypatch):
    user = await make_user(RoleCode.patient)
    first = await request_code(client, isolated_side_channels, user.email)
    monkeypatch.setattr(settings, "password_reset_resend_seconds", 0)
    second = await request_code(client, isolated_side_channels, user.email)
    if first != second:  # 1 in a million they match
        assert (await verify(client, user.email, first)).json()["error"]["code"] == "RESET_CODE_INVALID"

    freeze_clock(clock.utcnow() + timedelta(minutes=11))
    assert (await verify(client, user.email, second)).json()["error"]["code"] == "RESET_CODE_INVALID"

    freeze_clock(clock.utcnow() + timedelta(minutes=1))
    grant = await grant_for(client, isolated_side_channels, user.email)
    freeze_clock(clock.utcnow() + timedelta(minutes=11))
    late = await client.post(RESET, json={"token": grant, "new_password": NEW_PASSWORD})
    assert late.status_code == 400 and late.json()["error"]["code"] == "RESET_TOKEN_EXPIRED"
    bogus = await client.post(RESET, json={"token": "x" * 43, "new_password": NEW_PASSWORD})
    assert bogus.json()["error"]["code"] == "RESET_TOKEN_INVALID"
    assert (await client.post(LOGIN, json={"email": user.email, "password": TEST_PASSWORD})).status_code == 200


async def test_a_new_code_cancels_an_unused_reset_token(client, make_user, isolated_side_channels, monkeypatch):
    user = await make_user(RoleCode.patient)
    grant = await grant_for(client, isolated_side_channels, user.email)
    monkeypatch.setattr(settings, "password_reset_resend_seconds", 0)
    await request_code(client, isolated_side_channels, user.email)
    refused = await client.post(RESET, json={"token": grant, "new_password": NEW_PASSWORD})
    assert refused.status_code == 400 and refused.json()["error"]["code"] == "RESET_TOKEN_EXPIRED"


async def test_an_old_style_link_token_no_longer_resets(client, db_session, make_user):
    """Rows from emailed links (D126) have no verified code: their tokens are refused."""
    user = await make_user(RoleCode.patient)
    raw = "old-link-" + uuid.uuid4().hex + uuid.uuid4().hex
    now = clock.utcnow()
    db_session.add(PasswordResetToken(user_id=user.id, token_hash=hash_token(raw), created_at=now, expires_at=now + timedelta(minutes=15)))
    await db_session.commit()
    refused = await client.post(RESET, json={"token": raw, "new_password": NEW_PASSWORD})
    assert refused.status_code == 400 and refused.json()["error"]["code"] == "RESET_TOKEN_EXPIRED"


async def test_password_rule_and_code_format_are_enforced_without_using_anything_up(client, make_user, isolated_side_channels):
    user = await make_user(RoleCode.patient)
    code = await request_code(client, isolated_side_channels, user.email)
    for bad in ("12345", "1234567", "12a456", ""):
        assert (await verify(client, user.email, bad)).status_code == 422
    grant = (await verify(client, user.email, code)).json()["reset_token"]
    assert (await client.post(RESET, json={"token": grant, "new_password": "short"})).status_code == 422
    assert (await client.post(RESET, json={"token": grant, "new_password": "x" * 129})).status_code == 422
    assert (await client.post(RESET, json={"token": grant, "new_password": NEW_PASSWORD})).status_code == 200


async def test_codes_per_account_and_requests_per_ip_are_bounded(client, make_user, isolated_side_channels, monkeypatch):
    user = await make_user(RoleCode.patient)
    monkeypatch.setattr(settings, "password_reset_requests_per_minute", 100)
    await request_code(client, isolated_side_channels, user.email)
    # A second request at once (inside the 60-second resend wait): same answer, no second email.
    assert (await client.post(FORGOT, json={"email": user.email})).json() == {"message": GENERIC}
    assert len(emails(isolated_side_channels)) == 1

    # At most PASSWORD_RESET_MAX_PER_HOUR codes an hour, whatever the spacing.
    monkeypatch.setattr(settings, "password_reset_resend_seconds", 0)
    for _ in range(settings.password_reset_max_per_hour + 2):
        assert (await client.post(FORGOT, json={"email": user.email})).json() == {"message": GENERIC}
    assert len(emails(isolated_side_channels)) == settings.password_reset_max_per_hour

    # And per client IP (whatever the address, so it reveals nothing about accounts).
    monkeypatch.setattr(settings, "password_reset_requests_per_minute", 10)  # 9 used so far
    assert (await client.post(FORGOT, json={"email": "someone-else@example.com"})).status_code == 200
    assert (await client.post(FORGOT, json={"email": "someone-else@example.com"})).status_code == 429


async def test_google_only_account_is_told_to_use_google_and_gets_no_code(client, db_session, make_user, isolated_side_channels):
    user = await make_user(RoleCode.patient)
    row = await db_session.get(User, user.id)
    row.password_hash = None
    await db_session.commit()
    assert (await client.post(FORGOT, json={"email": user.email})).json() == {"message": GENERIC}
    [(_, _, text, _)] = emails(isolated_side_channels)
    assert "Continue with Google" in text and not re.search(r"^\s+\d{6}\s*$", text, re.M)
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
    code = code_in(pending.email.text)
    assert "password_reset_email_not_sent" in caplog.text

    with caplog.at_level(logging.DEBUG):
        verified = await verify(client, user.email, code)
        grant = verified.json()["reset_token"]
        await client.post(RESET, json={"token": grant, "new_password": NEW_PASSWORD})
    for secret in (code, grant, NEW_PASSWORD):
        assert secret not in caplog.text


async def test_two_submissions_of_one_reset_token_cannot_both_succeed():
    """Real concurrency needs committed rows and two connections (outside the per-test rollback)."""
    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    raw = "concurrent-" + uuid.uuid4().hex + uuid.uuid4().hex
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        user = User(name="Race Test", email=f"race-{uuid.uuid4().hex[:8]}@example.com", password_hash=TEST_PASSWORD_HASH)
        setup.add(user)
        await setup.flush()
        now = clock.utcnow()
        setup.add(PasswordResetToken(
            user_id=user.id, token_hash=hash_token(raw), code_hash="0" * 64, created_at=now, verified_at=now,
            expires_at=now + timedelta(minutes=10),
        ))
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


async def test_concurrent_wrong_guesses_are_all_counted():
    """Guesses are counted under a row lock: parallel requests cannot slip past the limit."""
    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        user = User(name="Guess Test", email=f"guess-{uuid.uuid4().hex[:8]}@example.com", password_hash=TEST_PASSWORD_HASH)
        setup.add(user)
        await setup.flush()
        now = clock.utcnow()
        row_id = uuid.uuid7()
        setup.add(PasswordResetToken(
            id=row_id, user_id=user.id, code_hash=password_reset_service._code_hash(row_id, "111111"), created_at=now,
            expires_at=now + timedelta(minutes=10),
        ))
        await setup.commit()
    try:
        async def guess(code):
            async with AsyncSession(engine, expire_on_commit=False) as session:
                try:
                    await password_reset_service.verify_code(session, user.email, code)
                    return "ok"
                except BusinessRuleError as exc:
                    return exc.code

        await asyncio.gather(*(guess(f"{n:06d}") for n in range(200000, 200008)))
        assert await guess("111111") == "RESET_CODE_INVALID"  # 8 wrong guesses > 5: the code is used up
        async with AsyncSession(engine) as check:
            attempts = await check.scalar(select(PasswordResetToken.attempts).where(PasswordResetToken.id == row_id))
        assert attempts == settings.password_reset_code_max_attempts
    finally:
        async with AsyncSession(engine) as cleanup:
            await cleanup.execute(delete(User).where(User.id == user.id))
            await cleanup.commit()
        await engine.dispose()
