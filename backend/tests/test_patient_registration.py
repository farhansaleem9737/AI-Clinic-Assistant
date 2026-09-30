"""Public patient self-registration: what it creates, and what it refuses.

The role-escalation basics live in test_registration_security.py; this file
covers the full flow behind the Create account page.
"""

import pytest
from sqlalchemy import select

from app.core.security import verify_password
from app.models.doctor import Doctor
from app.models.patient import Patient
from app.models.user import User
from app.services import patient_service, rbac_service

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
PASSWORD = "pw-123456"


def payload(email: str, **extra) -> dict:
    return {
        "first_name": "Pat",
        "last_name": "Example",
        "date_of_birth": "1990-05-17",
        "email": email,
        "password": PASSWORD,
        **extra,
    }


async def registered(db_session, email):
    user = await db_session.scalar(select(User).where(User.email == email))
    patient = await db_session.scalar(select(Patient).where(Patient.user_id == user.id)) if user else None
    return user, patient


# ---- what gets created ---------------------------------------------------------------


async def test_creates_user_patient_role_and_generated_mrn(client, db_session):
    response = await client.post(REGISTER, json=payload("whole@example.com", phone="555-0101"))
    assert response.status_code == 201
    user, patient = await registered(db_session, "whole@example.com")

    assert user.name == "Pat Example" and user.is_active is True
    assert await rbac_service.role_codes_for(db_session, user.id) == {"patient"}
    assert patient.first_name == "Pat" and patient.last_name == "Example"
    assert patient.user_id == user.id and patient.email == "whole@example.com"
    assert patient.mrn.startswith("MRN") and len(patient.mrn) == 11
    assert patient.registered_by_user_id is None  # self-registered


async def test_each_registration_gets_its_own_mrn(client, db_session):
    await client.post(REGISTER, json=payload("mrn1@example.com"))
    await client.post(REGISTER, json=payload("mrn2@example.com"))
    _, first = await registered(db_session, "mrn1@example.com")
    _, second = await registered(db_session, "mrn2@example.com")
    assert first.mrn != second.mrn


async def test_password_is_stored_only_as_a_hash(client, db_session):
    response = await client.post(REGISTER, json=payload("hash@example.com"))
    user, _ = await registered(db_session, "hash@example.com")
    assert PASSWORD not in user.password_hash
    assert user.password_hash.startswith("$2") and verify_password(PASSWORD, user.password_hash)
    # Nothing about the password comes back.
    assert PASSWORD not in response.text and "password" not in response.text.lower() and "$2" not in response.text


async def test_registration_does_not_sign_the_user_in_by_itself(client):
    """Established lifecycle: register, then log in (the frontend does both).
    Registration alone issues no session cookie and no token."""
    response = await client.post(REGISTER, json=payload("nocookie@example.com"))
    assert response.status_code == 201
    assert "set-cookie" not in response.headers
    assert "access_token" not in response.json()

    login = await client.post(LOGIN, json={"email": "nocookie@example.com", "password": PASSWORD})
    assert login.status_code == 200
    profile = await client.get(
        "/api/v1/patients/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"}
    )
    assert profile.status_code == 200 and profile.json()["first_name"] == "Pat"


# ---- privilege escalation ------------------------------------------------------------


async def test_privilege_injection_cannot_create_a_privileged_account(client, db_session):
    """A hand-crafted request stuffing in every privileged-looking field."""
    forged_id = "00000000-0000-0000-0000-000000000001"
    attack = payload(
        "attacker@example.com",
        role="admin",
        roles=["admin", "doctor", "receptionist"],
        permissions=["*", "user:create"],
        is_admin=True,
        is_staff=True,
        is_superuser=True,
        is_active=False,
        id=forged_id,
        user_id=forged_id,
        doctor_id=forged_id,
        mrn="MRN-FORGED",
        registered_by_user_id=forged_id,
    )
    response = await client.post(REGISTER, json=attack)
    assert response.status_code == 201
    assert response.json()["roles"] == ["patient"]

    user, patient = await registered(db_session, "attacker@example.com")
    assert str(user.id) != forged_id
    assert user.is_active is True
    assert await rbac_service.role_codes_for(db_session, user.id) == {"patient"}
    assert patient.mrn != "MRN-FORGED" and patient.registered_by_user_id is None
    assert await db_session.scalar(select(Doctor.id).where(Doctor.user_id == user.id)) is None

    # What the account can actually do is a patient's, nothing more.
    login = await client.post(LOGIN, json={"email": "attacker@example.com", "password": PASSWORD})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    me = (await client.get("/api/v1/auth/me", headers=headers)).json()
    assert me["roles"] == ["patient"] and me["doctor_id"] is None
    assert not any(p.startswith(("user:", "role:", "doctor:", "department:")) for p in me["permissions"])
    assert (await client.get("/api/v1/users/", headers=headers)).status_code == 403
    assert (await client.get("/api/v1/patients/", headers=headers)).status_code == 403


# ---- atomicity -----------------------------------------------------------------------


async def test_user_is_rolled_back_when_patient_creation_fails(client, db_session, monkeypatch):
    """No orphan login if the second half of registration fails."""

    def broken_patient(**kwargs):
        raise RuntimeError("patient insert failed")

    monkeypatch.setattr(patient_service, "Patient", broken_patient)
    with pytest.raises(RuntimeError):
        await client.post(REGISTER, json=payload("orphan@example.com"))
    monkeypatch.undo()

    assert await db_session.scalar(select(User).where(User.email == "orphan@example.com")) is None
    # The address is still free: the same person can register once the fault is fixed.
    assert (await client.post(REGISTER, json=payload("orphan@example.com"))).status_code == 201


# ---- email uniqueness ----------------------------------------------------------------


async def test_email_is_case_insensitive_for_registration_and_login(client, db_session):
    assert (await client.post(REGISTER, json=payload("Mixed.Case@Example.COM"))).status_code == 201
    user, _ = await registered(db_session, "mixed.case@example.com")
    assert user is not None

    duplicate = await client.post(REGISTER, json=payload("MIXED.CASE@example.com"))
    assert duplicate.status_code == 409 and duplicate.json()["error"]["code"] == "EMAIL_TAKEN"

    login = await client.post(LOGIN, json={"email": "MIXED.case@EXAMPLE.com", "password": PASSWORD})
    assert login.status_code == 200


async def test_duplicate_email_error_reveals_no_database_details(client, make_user):
    user = await make_user()
    response = await client.post(REGISTER, json=payload(user.email))
    assert response.status_code == 409
    text = response.text.lower()
    assert "constraint" not in text and "ix_users" not in text and "sql" not in text


# ---- validation ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "override",
    [
        {"password": "short"},
        {"password": "x" * 129},
        {"email": "not-an-email"},
        {"first_name": "   "},
        {"last_name": ""},
        {"date_of_birth": "2999-01-01"},
        {"date_of_birth": "not-a-date"},
        {"first_name": "A" * 60, "last_name": "B" * 60},
    ],
)
async def test_invalid_registration_is_422_and_creates_nothing(client, db_session, override):
    response = await client.post(REGISTER, json={**payload("invalid@example.com"), **override})
    assert response.status_code == 422
    assert await db_session.scalar(select(User).where(User.email == "invalid@example.com")) is None


async def test_missing_required_fields_are_422(client):
    assert (await client.post(REGISTER, json={"email": "only@example.com"})).status_code == 422


async def test_names_are_trimmed_and_international_names_accepted(client, db_session):
    response = await client.post(
        REGISTER, json=payload("intl@example.com", first_name="  José  María ", last_name="Nguyễn-O'Brien")
    )
    assert response.status_code == 201
    _, patient = await registered(db_session, "intl@example.com")
    assert patient.first_name == "José María" and patient.last_name == "Nguyễn-O'Brien"

    assert (await client.post(REGISTER, json=payload("cjk@example.com", first_name="秀英", last_name="李"))).status_code == 201
