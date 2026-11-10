"""Continue with Google (D123). Google is never contacted: the code exchange is
replaced, and ID tokens are signed with a local RSA key whose public half stands
in for Google's certificates, so the real verification code runs.
"""

import time
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from google.auth import crypt, jwt as google_jwt
from pydantic import SecretStr, ValidationError
from sqlalchemy import select

from app.core import clock
from app.core.config import Settings, settings
from app.core.permissions import RoleCode
from app.models.doctor_application import DoctorApplication
from app.models.oauth import OAuthIdentity
from app.models.user import User
from app.services import google_oidc, rbac_service
from app.services.google_oidc import GoogleIdentity, GoogleSignInError
from tests.conftest import TEST_PASSWORD
from tests.test_auth import Session, cookies_from

API = "/api/v1/auth"
CLIENT_ID = "test-client.apps.googleusercontent.com"


@pytest.fixture
def google(monkeypatch):
    """Google switched on, with a scripted identity per authorization code."""
    monkeypatch.setattr(settings, "google_oauth_enabled", True)
    monkeypatch.setattr(settings, "google_oauth_client_id", CLIENT_ID)
    monkeypatch.setattr(settings, "google_oauth_client_secret", SecretStr("test-secret"))
    people: dict[str, GoogleIdentity] = {}
    seen = {}

    async def exchange(code, verifier):
        if code not in people:
            raise GoogleSignInError("rejected", code="GOOGLE_CODE_REJECTED")
        seen["verifier"] = verifier
        return code

    async def verify(token, *, nonce):
        seen["nonce"] = nonce
        return people[token]

    monkeypatch.setattr(google_oidc, "exchange_code", exchange)
    monkeypatch.setattr(google_oidc, "verify_id_token", verify)

    def person(code, sub, email, given="Gina", family="Google"):
        people[code] = GoogleIdentity(subject=sub, email=email, given_name=given, family_name=family, name=f"{given} {family}")

    person.seen = seen
    return person


async def start(client, intent="login", remember=False):
    response = await client.get(f"{API}/google/start", params={"intent": intent, "remember": remember})
    assert response.status_code == 303, response.text
    url = urlparse(response.headers["location"])
    query = parse_qs(url.query)
    binder = cookies_from(response)["g_oauth"]
    assert binder["httponly"] and binder["samesite"].lower() == "lax" and binder["path"] == "/api/v1/auth/google"
    return query, binder.value


async def callback(client, state, binder, code=None, error=None):
    params = {"state": state, **({"code": code} if code else {}), **({"error": error} if error else {})}
    client.cookies.clear()
    response = await client.get(f"{API}/google/callback", params=params, headers={"Cookie": f"g_oauth={binder}"} if binder else {})
    assert response.status_code == 303
    return response, response.headers["location"].removeprefix(settings.frontend_base_url)


# ---- the authorization request ------------------------------------------------------------


async def test_start_sends_the_browser_to_google_with_state_pkce_and_nonce(client, google):
    query, binder = await start(client)
    assert query["client_id"] == [CLIENT_ID] and query["response_type"] == ["code"]
    assert query["redirect_uri"] == [settings.google_redirect_uri]
    assert query["redirect_uri"][0].endswith("/api/v1/auth/google/callback")
    assert query["scope"] == ["openid email profile"]  # identity only, no offline access
    assert query["code_challenge_method"] == ["S256"] and len(query["code_challenge"][0]) == 43
    assert len(query["state"][0]) >= 32 and len(query["nonce"][0]) >= 32 and binder
    assert "access_type" not in query


async def test_google_is_off_until_configured(client):
    assert (await client.get(f"{API}/providers")).json() == {"google": False}
    response = await client.get(f"{API}/google/start")
    assert response.status_code == 303 and response.headers["location"].endswith("/login?google=unavailable")
    with pytest.raises(ValidationError, match="GOOGLE_OAUTH_CLIENT_ID"):
        Settings(google_oauth_enabled=True, google_oauth_client_id=None, google_oauth_client_secret=None)


# ---- a new person: registration ---------------------------------------------------------------


async def test_a_new_google_user_registers_as_a_patient_without_a_password(client, google, db_session):
    google("code-new", "sub-new", "new.patient@example.com", "Nadia", "Noor")
    query, binder = await start(client, intent="register", remember=True)
    response, path = await callback(client, query["state"][0], binder, code="code-new")
    assert path == "/register/google"
    assert google.seen["nonce"] == query["nonce"][0]  # this sign-in's own nonce
    ticket = cookies_from(response)["g_signup"].value
    cookie = {"Cookie": f"g_signup={ticket}"}

    prefill = (await client.get(f"{API}/google/signup", headers=cookie)).json()
    assert prefill == {"email": "new.patient@example.com", "given_name": "Nadia", "family_name": "Noor"}

    body = {"account_type": "patient", "first_name": "Nadia", "last_name": "Noor", "date_of_birth": "1990-05-01", "sex_at_birth": "female"}
    assert (await client.post(f"{API}/google/signup", json={**body, "password": "x" * 10}, headers=cookie)).status_code == 422
    assert (await client.post(f"{API}/google/signup", json={**body, "account_type": "admin"}, headers=cookie)).status_code == 422
    created = await client.post(f"{API}/google/signup", json=body, headers=cookie)
    assert created.status_code == 201, created.text
    session = Session(created)  # the normal Strict refresh cookie + CSRF cookie
    assert cookies_from(created)["refresh_token"]["samesite"].lower() == "strict"

    me = (await client.get(f"{API}/me", headers={"Authorization": f"Bearer {created.json()['access_token']}"})).json()
    assert me["email"] == "new.patient@example.com" and me["roles"] == ["patient"] and me["patient_id"]
    user = await db_session.scalar(select(User).where(User.email == "new.patient@example.com"))
    assert user.password_hash is None  # no placeholder password
    assert (await db_session.scalar(select(OAuthIdentity).where(OAuthIdentity.user_id == user.id))).subject == "sub-new"

    # The ticket is used up; the session works like any other (rotation, logout).
    assert (await client.post(f"{API}/google/signup", json=body, headers=cookie)).status_code == 400
    client.cookies.clear()
    rotated = await client.post(f"{API}/refresh", headers=session.headers())
    assert rotated.status_code == 200
    session.update(rotated)
    assert (await client.post(f"{API}/logout", headers=session.headers())).status_code == 204
    # A Google-only account cannot be signed into with any password.
    assert (await client.post(f"{API}/login", json={"email": user.email, "password": "anything-at-all"})).status_code == 401


async def test_a_doctor_applicant_still_waits_for_review(client, google, db_session, make_department):
    department = await make_department()
    google("code-doc", "sub-doc", "dr.new@example.com", "Dina", "Doc")
    query, binder = await start(client, intent="register")
    response, _ = await callback(client, query["state"][0], binder, code="code-doc")
    cookie = {"Cookie": f"g_signup={cookies_from(response)['g_signup'].value}"}
    created = await client.post(
        f"{API}/google/signup",
        json={"account_type": "doctor", "name": "Dina Doc", "date_of_birth": "1980-01-01", "gender": "female",
              "department_id": str(department.id), "specialization": "Dermatologist"},
        headers=cookie,
    )
    assert created.status_code == 201, created.text
    user = await db_session.scalar(select(User).where(User.email == "dr.new@example.com"))
    assert await rbac_service.role_codes_for(db_session, user.id) == {"doctor_applicant"}  # not a doctor yet
    application = await db_session.scalar(select(DoctorApplication).where(DoctorApplication.user_id == user.id))
    assert application.status.value == "pending_review"


# ---- an existing account -----------------------------------------------------------------------


async def test_a_linked_user_signs_in_and_keeps_their_roles(client, google, make_user, db_session):
    user = await make_user(RoleCode.receptionist)
    db_session.add(OAuthIdentity(user_id=user.id, provider="google", subject="sub-staff", email=user.email))
    await db_session.commit()
    google("code-staff", "sub-staff", user.email)
    query, binder = await start(client)
    response, path = await callback(client, query["state"][0], binder, code="code-staff")
    assert path == "/auth/google/complete"
    handoff = cookies_from(response)["g_handoff"]
    assert handoff["httponly"] and int(handoff["max-age"]) <= 120
    assert "access_token" not in response.headers["location"] and "refresh" not in response.headers["location"]

    done = await client.post(f"{API}/google/complete", headers={"Cookie": f"g_handoff={handoff.value}"})
    assert done.status_code == 200, done.text
    Session(done)
    me = (await client.get(f"{API}/me", headers={"Authorization": f"Bearer {done.json()['access_token']}"})).json()
    assert me["id"] == str(user.id) and me["roles"] == ["receptionist"]  # unchanged: never elevated
    again = await client.post(f"{API}/google/complete", headers={"Cookie": f"g_handoff={handoff.value}"})
    assert again.status_code == 400  # single use


async def test_an_email_match_is_never_linked_automatically(client, google, make_user, db_session):
    user = await make_user(RoleCode.patient, email="owner@example.com")
    google("code-hijack", "sub-unknown", "owner@example.com")
    query, binder = await start(client)
    _, path = await callback(client, query["state"][0], binder, code="code-hijack")
    assert path == "/login?google=link_required"
    assert await db_session.scalar(select(OAuthIdentity).where(OAuthIdentity.user_id == user.id)) is None


async def test_a_deactivated_account_cannot_sign_in_with_google(client, google, make_user, db_session):
    user = await make_user(RoleCode.patient, is_active=False)
    db_session.add(OAuthIdentity(user_id=user.id, provider="google", subject="sub-off", email=user.email))
    await db_session.commit()
    google("code-off", "sub-off", user.email)
    query, binder = await start(client)
    _, path = await callback(client, query["state"][0], binder, code="code-off")
    assert path == "/login?google=inactive"


# ---- the callback is single-use, bound to its browser and short-lived --------------------------------


async def test_state_must_be_known_unused_fresh_and_from_this_browser(client, google, monkeypatch):
    google("code-1", "sub-1", "one@example.com")
    _, path = await callback(client, "forged-state", "whatever", code="code-1")
    assert path == "/login?google=expired"

    query, binder = await start(client)
    _, path = await callback(client, query["state"][0], "another-browser", code="code-1")
    assert path == "/login?google=expired"  # login CSRF: another browser's answer is refused,
    _, path = await callback(client, query["state"][0], None, code="code-1")
    assert path == "/login?google=expired"  # as is one with no browser binding at all,
    _, path = await callback(client, query["state"][0], binder, code="code-1")
    assert path == "/register/google"  # without burning the real user's sign-in
    _, path = await callback(client, query["state"][0], binder, code="code-1")
    assert path == "/login?google=expired"  # which is then used up

    query, binder = await start(client)
    later = clock.utcnow() + timedelta(minutes=settings.google_oauth_flow_minutes + 1)
    monkeypatch.setattr(clock, "utcnow", lambda: later)
    _, path = await callback(client, query["state"][0], binder, code="code-1")
    assert path == "/login?google=expired"


async def test_cancelled_rejected_or_unverifiable_answers_sign_nobody_in(client, google, monkeypatch):
    query, binder = await start(client)
    _, path = await callback(client, query["state"][0], binder, error="access_denied")
    assert path == "/login?google=cancelled"

    query, binder = await start(client, intent="register")
    _, path = await callback(client, query["state"][0], binder, code="not-a-real-code")
    assert path == "/register?google=failed"

    async def bad_token(token, *, nonce):
        raise GoogleSignInError("invalid", code="GOOGLE_TOKEN_INVALID")

    google("code-x", "sub-x", "x@example.com")
    monkeypatch.setattr(google_oidc, "verify_id_token", bad_token)
    query, binder = await start(client)
    response, path = await callback(client, query["state"][0], binder, code="code-x")
    assert path == "/login?google=failed" and "g_handoff" not in cookies_from(response)


# ---- linking from Account settings ---------------------------------------------------------------


def _bearer_and_csrf(token):
    return {"Authorization": f"Bearer {token}", "Cookie": "csrf_token=t", settings.csrf_header_name: "t"}


async def test_linking_needs_the_password_or_a_fresh_sign_in_and_one_owner_per_google_account(client, google, make_user, db_session):
    user = await make_user(RoleCode.patient)
    other = await make_user(RoleCode.patient)
    db_session.add(OAuthIdentity(user_id=other.id, provider="google", subject="sub-taken", email=other.email))
    await db_session.commit()
    token = (await client.post(f"{API}/login", json={"email": user.email, "password": TEST_PASSWORD})).json()["access_token"]
    client.cookies.clear()
    headers = _bearer_and_csrf(token)

    assert (await client.post(f"{API}/google/link", json={"current_password": "wrong"}, headers=headers)).status_code == 400
    started = await client.post(f"{API}/google/link", json={"current_password": TEST_PASSWORD}, headers=headers)
    assert started.status_code == 200
    state = parse_qs(urlparse(started.json()["authorize_url"]).query)["state"][0]
    google("code-taken", "sub-taken", "someone@gmail.com")
    _, path = await callback(client, state, cookies_from(started)["g_oauth"].value, code="code-taken")
    assert path == "/account?google=in_use"

    started = await client.post(f"{API}/google/link", json={"current_password": TEST_PASSWORD}, headers=headers)
    state = parse_qs(urlparse(started.json()["authorize_url"]).query)["state"][0]
    google("code-mine", "sub-mine", "me.personal@gmail.com")
    _, path = await callback(client, state, cookies_from(started)["g_oauth"].value, code="code-mine")
    assert path == "/account?google=linked"
    status = (await client.get(f"{API}/google/identity", headers=headers)).json()
    assert status == {"enabled": True, "linked": True, "email": "me.personal@gmail.com", "has_password": True}

    # Unlinking is allowed: the password still signs in.
    assert (await client.post(f"{API}/google/unlink", json={"current_password": TEST_PASSWORD}, headers=headers)).status_code == 204
    assert (await client.get(f"{API}/google/identity", headers=headers)).json()["linked"] is False


async def test_the_only_sign_in_method_cannot_be_unlinked(client, google, db_session):
    google("code-solo", "sub-solo", "solo@example.com", "Sol", "Only")
    query, binder = await start(client, intent="register")
    response, _ = await callback(client, query["state"][0], binder, code="code-solo")
    created = await client.post(
        f"{API}/google/signup",
        json={"first_name": "Sol", "last_name": "Only", "date_of_birth": "1991-02-03"},
        headers={"Cookie": f"g_signup={cookies_from(response)['g_signup'].value}"},
    )
    session = Session(created)
    headers = {**session.headers(), "Authorization": f"Bearer {created.json()['access_token']}"}
    refused = await client.post(f"{API}/google/unlink", json={}, headers=headers)  # fresh sign-in: no password needed
    assert refused.status_code == 400 and refused.json()["error"]["code"] == "LAST_SIGN_IN_METHOD"


# ---- ID-token verification (the real code, a local key in place of Google's) ------------------------


@pytest.fixture
def signer(monkeypatch):
    monkeypatch.setattr(settings, "google_oauth_client_id", CLIENT_ID)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    certs = {"k1": public.decode()}
    fetches = []

    async def certificates(*, force=False):
        fetches.append(force)
        return certs

    monkeypatch.setattr(google_oidc, "certificates", certificates)

    def sign(kid="k1", **overrides):
        now = int(time.time())
        claims = {"iss": "https://accounts.google.com", "aud": CLIENT_ID, "sub": "1234567890", "email": "Pat@Example.com",
                  "email_verified": True, "nonce": "n-1", "iat": now, "exp": now + 600, **overrides}
        return google_jwt.encode(crypt.RSASigner.from_string(pem.decode(), key_id=kid), claims).decode()

    sign.certs, sign.fetches = certs, fetches
    return sign


async def test_a_valid_google_id_token_gives_the_identity(signer):
    identity = await google_oidc.verify_id_token(signer(), nonce="n-1")
    assert identity.subject == "1234567890" and identity.email == "pat@example.com"


@pytest.mark.parametrize(
    "overrides, nonce",
    [
        ({"aud": "someone-else.apps.googleusercontent.com"}, "n-1"),  # wrong audience
        ({"iss": "https://evil.example.com"}, "n-1"),  # wrong issuer
        ({"iat": int(time.time()) - 7200, "exp": int(time.time()) - 3600}, "n-1"),  # expired
        ({}, "another-sign-in"),  # nonce mismatch (replayed token)
        ({"email_verified": False}, "n-1"),  # unverified address
    ],
)
async def test_invalid_google_id_tokens_are_refused(signer, overrides, nonce):
    with pytest.raises(GoogleSignInError):
        await google_oidc.verify_id_token(signer(**overrides), nonce=nonce)


async def test_a_forged_signature_is_refused_and_rotated_keys_are_fetched_once(signer):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged_pem = other.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    now = int(time.time())
    forged = google_jwt.encode(
        crypt.RSASigner.from_string(forged_pem, key_id="k1"),
        {"iss": "accounts.google.com", "aud": CLIENT_ID, "sub": "1", "email": "a@b.c", "email_verified": True, "nonce": "n-1", "iat": now, "exp": now + 600},
    ).decode()
    with pytest.raises(GoogleSignInError):
        await google_oidc.verify_id_token(forged, nonce="n-1")

    # A token signed with a key not in the cache triggers exactly one refresh.
    token = signer(kid="k-new")
    with pytest.raises(GoogleSignInError):
        await google_oidc.verify_id_token(token, nonce="n-1")
    assert signer.fetches[-2:] == [False, True]
