"""Self-registration needs a code emailed to the address first; doctors and
receptionists must be adults."""

from datetime import date

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.permissions import RoleCode
from app.models.user import User
from app.services import email_verification_service

REGISTER = "/api/v1/auth/register"
SEND_CODE = "/api/v1/auth/register/verification-code"


@pytest.fixture(autouse=True)
def verification_on(monkeypatch):
    monkeypatch.setattr(settings, "email_verification_required", True)
    monkeypatch.setattr(email_verification_service.secrets, "randbelow", lambda _: 123456)


def patient(email: str, **extra) -> dict:
    return {"first_name": "Pat", "last_name": "Example", "date_of_birth": "1990-05-17", "email": email, "password": "pw-123456", **extra}


async def test_a_patient_registers_with_the_emailed_code(client, isolated_side_channels):
    assert (await client.post(SEND_CODE, json={"email": "Otp@Example.com"})).status_code == 204
    [sent] = list(isolated_side_channels.iterdir())
    assert "123456" in sent.read_text(encoding="utf-8")

    missing = await client.post(REGISTER, json=patient("otp@example.com"))
    assert missing.json()["error"]["code"] == "VERIFICATION_REQUIRED"
    wrong = await client.post(REGISTER, json=patient("otp@example.com", verification_code="000000"))
    assert wrong.json()["error"]["code"] == "INVALID_VERIFICATION_CODE"

    ok = await client.post(REGISTER, json=patient("otp@example.com", verification_code="123456", sex_at_birth="female"))
    assert ok.status_code == 201
    # Single use.
    again = await client.post(REGISTER, json=patient("otp2@example.com", verification_code="123456"))
    assert again.json()["error"]["code"] == "INVALID_VERIFICATION_CODE"


async def test_codes_stop_working_after_too_many_wrong_guesses(client):
    await client.post(SEND_CODE, json={"email": "guess@example.com"})
    for _ in range(settings.email_verification_max_attempts):
        await client.post(REGISTER, json=patient("guess@example.com", verification_code="999999"))
    locked = await client.post(REGISTER, json=patient("guess@example.com", verification_code="123456"))
    assert locked.json()["error"]["code"] == "INVALID_VERIFICATION_CODE"


async def test_no_code_for_a_taken_email_and_no_instant_resend(client, make_user):
    existing = await make_user(RoleCode.patient)
    assert (await client.post(SEND_CODE, json={"email": existing.email})).json()["error"]["code"] == "EMAIL_TAKEN"
    assert (await client.post(SEND_CODE, json={"email": "new@example.com"})).status_code == 204
    resent = await client.post(SEND_CODE, json={"email": "new@example.com"})
    assert resent.status_code == 429 and resent.json()["error"]["code"] == "CODE_RECENTLY_SENT"


async def test_doctors_must_be_adults_and_their_details_are_kept(client, db_session):
    await client.post(SEND_CODE, json={"email": "young.doc@example.com"})
    body = {"account_type": "doctor", "name": "Young Doc", "email": "young.doc@example.com", "password": "pw-123456", "gender": "male"}
    minor = date.today().replace(year=date.today().year - 17).isoformat()
    too_young = await client.post(REGISTER, json={**body, "date_of_birth": minor, "verification_code": "123456"})
    assert too_young.status_code == 422
    ok = await client.post(REGISTER, json={**body, "date_of_birth": "1980-01-31", "verification_code": "123456"})
    assert ok.status_code == 201
    user = await db_session.scalar(select(User).where(User.email == "young.doc@example.com"))
    assert (user.date_of_birth, user.gender) == (date(1980, 1, 31), "male")


async def test_receptionists_created_by_an_admin_must_be_adults(client, auth_headers):
    headers = await auth_headers(RoleCode.admin)
    body = {"name": "Rita Reception", "email": "rita@example.com", "password": "pw-12345678", "roles": ["receptionist"]}
    assert (await client.post("/api/v1/users/", json=body, headers=headers)).status_code == 422
    minor = {**body, "date_of_birth": date.today().replace(year=date.today().year - 16).isoformat()}
    assert (await client.post("/api/v1/users/", json=minor, headers=headers)).status_code == 422
    ok = await client.post("/api/v1/users/", json={**body, "date_of_birth": "1995-06-01", "gender": "female"}, headers=headers)
    assert ok.status_code == 201
