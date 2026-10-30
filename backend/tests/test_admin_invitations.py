"""Administrator provisioning (D87): the first-administrator bootstrap,
invitations, accepting them, and the admin role's lifecycle."""

import asyncio
import email
import email.policy
import os
import re
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core import clock
from app.core.exceptions import ConflictError
from app.core.permissions import RoleCode
from app.core.security import hash_token
from app.models import AdminInvitation, AuditLog, User, UserRole
from app.services import admin_service, rbac_service
from tests.conftest import TEST_PASSWORD, TEST_PASSWORD_HASH, login

INVITES = "/api/v1/admin/invitations"
PUBLIC = "/api/v1/auth/admin-invitations"
NEW_PASSWORD = "N3w-admin-password"


def outbox_token(outbox) -> str:
    """The token from the newest development email: the only place it exists."""
    newest = sorted(outbox.glob("*.eml"))[-1]
    # Decoded as a mail client would (the body may be quoted-printable).
    body = email.message_from_bytes(newest.read_bytes(), policy=email.policy.default).get_content()
    return re.search(r"accept-admin-invite#token=([A-Za-z0-9_-]+)", body).group(1)


@pytest.fixture
async def admin(make_user, client):
    user = await make_user(RoleCode.admin, name="Ada Admin")
    return user, await login(client, user.email)


async def invite(client, headers, email="new.admin@example.com", **extra):
    body = {"email": email, "current_password": TEST_PASSWORD, **extra}
    return await client.post(INVITES, json=body, headers=headers)


async def audit_actions(db_session, target_id) -> list[str]:
    rows = await db_session.scalars(select(AuditLog.action).where(AuditLog.target_id == str(target_id)))
    return list(rows.all())


# ---- public registration ----------------------------------------------------------------


@pytest.mark.parametrize("account_type", ["patient", "doctor"])
async def test_public_registration_ignores_every_privilege_field(client, db_session, account_type):
    shape = (
        {"first_name": "Mal", "last_name": "Lory", "date_of_birth": "1990-05-17"}
        if account_type == "patient"
        else {"account_type": "doctor", "name": "Mallory"}
    )
    body = {
        **shape,
        "email": f"mallory-{account_type}@example.com",
        "password": "pw-12345678",
        "role": "admin",
        "role_id": str(uuid.uuid4()),
        "roles": ["admin"],
        "is_admin": True,
        "is_superuser": True,
        "permissions": ["user:assign_role", "admin_invitation:manage"],
    }
    response = await client.post("/api/v1/auth/register", json=body)
    assert response.status_code == 201, response.text
    user = await db_session.scalar(select(User).where(User.email == body["email"]))
    roles = await rbac_service.role_codes_for(db_session, user.id)
    assert roles == ({"patient"} if account_type == "patient" else {"doctor_applicant"})


async def test_public_registration_rejects_administrator_as_account_type(client):
    body = {"account_type": "admin", "name": "M", "email": "m@example.com", "password": "pw-12345678"}
    assert (await client.post("/api/v1/auth/register", json=body)).status_code == 422


# ---- first administrator ---------------------------------------------------------------


async def test_bootstrap_creates_a_new_administrator_and_audits_it(db_session):
    user = await admin_service.bootstrap_first_admin(
        db_session, name="First Admin", email="first@example.com", password="pw-12345678"
    )
    assert await rbac_service.role_codes_for(db_session, user.id) == {"admin"}
    entry = await db_session.scalar(select(AuditLog).where(AuditLog.target_id == str(user.id)))
    assert entry.action == "admin.bootstrapped" and entry.actor_user_id is None
    assert "password" not in str(entry.details)


async def test_bootstrap_refuses_once_an_administrator_exists(db_session, make_user):
    await make_user(RoleCode.admin)
    with pytest.raises(ConflictError) as err:
        await admin_service.bootstrap_first_admin(db_session, name="X", email="x@example.com", password="pw-12345678")
    assert err.value.code == "ADMIN_EXISTS"


async def test_bootstrap_never_promotes_an_existing_account(db_session, make_user):
    patient = await make_user(RoleCode.patient)
    with pytest.raises(ConflictError) as err:
        await admin_service.bootstrap_first_admin(db_session, name="X", email=patient.email, password="pw-12345678")
    assert err.value.code == "EMAIL_TAKEN"
    assert await rbac_service.role_codes_for(db_session, patient.id) == {"patient"}


def test_bootstrap_command_reads_the_password_from_a_prompt_and_never_prints_it(monkeypatch, capsys):
    from app.cli import create_admin

    calls = []

    async def fake_create(name, email, password):
        calls.append((name, email, password))

    answers = iter(["CREATE"])
    monkeypatch.setattr(create_admin, "_create", fake_create)
    monkeypatch.setattr(create_admin.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(create_admin.getpass, "getpass", lambda prompt: "S3cret-pass-word")
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    create_admin.main(["--email", "Boss@Example.com", "--name", "  The   Boss "])
    assert calls == [("The Boss", "boss@example.com", "S3cret-pass-word")]
    out = capsys.readouterr()
    assert "S3cret" not in out.out + out.err
    assert "@" not in out.out.split("Database:")[1].split("\n")[0]  # no credentials in the URL shown


def test_bootstrap_command_stops_without_confirmation(monkeypatch):
    from app.cli import create_admin

    monkeypatch.setattr(create_admin, "_create", lambda *a: pytest.fail("must not run"))
    monkeypatch.setattr(create_admin.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(create_admin.getpass, "getpass", lambda prompt: "S3cret-pass-word")
    monkeypatch.setattr("builtins.input", lambda prompt: "no")
    with pytest.raises(SystemExit):
        create_admin.main(["--email", "boss@example.com", "--name", "Boss"])


async def test_concurrent_bootstraps_create_exactly_one_administrator():
    """Two operators run the command at the same moment on an empty database.
    Commits real rows, so it cleans up after itself."""
    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    tag = os.urandom(3).hex()
    emails = [f"boot-{tag}-{i}@example.com" for i in range(2)]

    async def attempt(email):
        async with AsyncSession(engine, expire_on_commit=False) as db:
            try:
                await admin_service.bootstrap_first_admin(db, name="Boot", email=email, password="pw-12345678")
                return "created"
            except ConflictError as exc:
                return exc.code

    try:
        async with AsyncSession(engine) as db:
            if await admin_service.admin_exists(db):
                pytest.skip("the test database already has a committed administrator")
        results = await asyncio.gather(*(attempt(e) for e in emails))
        assert sorted(results) == ["ADMIN_EXISTS", "created"]
    finally:
        async with AsyncSession(engine) as db:
            ids = list((await db.scalars(select(User.id).where(User.email.in_(emails)))).all())
            await db.execute(delete(AuditLog).where(AuditLog.target_id.in_([str(i) for i in ids])))
            await db.execute(delete(UserRole).where(UserRole.user_id.in_(ids)))
            await db.execute(delete(User).where(User.email.in_(emails)))
            await db.commit()
        await engine.dispose()


# ---- creating invitations --------------------------------------------------------------


async def test_admin_invites_and_the_link_goes_only_to_the_email(client, db_session, admin, isolated_side_channels):
    me, headers = admin
    response = await invite(client, headers, name="Grace Hopper")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "pending" and body["role"] == "admin"
    assert body["delivery_status"] == "outbox"
    assert body["invited_by_name"] == "Ada Admin"
    assert "token" not in str(body).lower()

    token = outbox_token(isolated_side_channels)
    stored = await db_session.get(AdminInvitation, uuid.UUID(body["id"]))
    assert stored.token_hash == hash_token(token) and token not in stored.token_hash
    assert stored.invited_by_user_id == me.id
    lifetime = stored.expires_at - stored.created_at
    assert timedelta(hours=23, minutes=59) < lifetime <= timedelta(hours=24)
    assert await audit_actions(db_session, body["id"]) == ["admin.invitation_created"]

    listed = await client.get(INVITES, headers=headers)
    assert [i["email"] for i in listed.json()] == ["new.admin@example.com"]


@pytest.mark.parametrize("role", [RoleCode.patient, RoleCode.doctor, RoleCode.receptionist, RoleCode.doctor_applicant])
async def test_other_roles_cannot_invite_or_list(client, auth_headers, role):
    headers = await auth_headers(role)
    assert (await invite(client, headers)).status_code == 403
    assert (await client.get(INVITES, headers=headers)).status_code == 403


async def test_guests_cannot_invite(client):
    assert (await client.post(INVITES, json={"email": "x@example.com", "current_password": "x"})).status_code == 401


async def test_inviting_needs_the_admins_password_and_only_grants_admin(client, admin):
    _, headers = admin
    wrong = await client.post(INVITES, json={"email": "x@example.com", "current_password": "nope"}, headers=headers)
    assert wrong.status_code == 403 and wrong.json()["error"]["code"] == "REAUTHENTICATION_FAILED"
    assert (await invite(client, headers, role="receptionist")).status_code == 422
    assert (await invite(client, headers, permissions=["user:read"])).status_code == 422  # unknown fields refused


async def test_no_duplicate_pending_invitation_and_no_inviting_an_admin(client, admin, make_user):
    _, headers = admin
    assert (await invite(client, headers)).status_code == 201
    again = await invite(client, headers, email="NEW.ADMIN@example.com")
    assert again.json()["error"]["code"] == "INVITATION_PENDING"
    other = await make_user(RoleCode.admin)
    assert (await invite(client, headers, email=other.email)).json()["error"]["code"] == "ALREADY_ADMIN"


async def test_failed_delivery_is_reported_as_not_sent(client, admin, monkeypatch):
    from app.core.config import EmailBackend, settings

    monkeypatch.setattr(settings, "email_backend", EmailBackend.none)
    response = await invite(client, admin[1])
    assert response.status_code == 201
    assert response.json()["delivery_status"] == "not_configured"
    assert response.json()["last_sent_at"] is None


# ---- accepting with a new account ------------------------------------------------------


async def test_accept_creates_an_administrator_who_can_sign_in_and_reach_admin(client, db_session, admin, isolated_side_channels):
    _, headers = admin
    created = (await invite(client, headers, name="Grace Hopper")).json()
    token = outbox_token(isolated_side_channels)

    preview = await client.post(f"{PUBLIC}/preview", json={"token": token})
    assert preview.json() == {
        "email": "new.admin@example.com",
        "name": "Grace Hopper",
        "status": "pending",
        "expires_at": preview.json()["expires_at"],
        "account_exists": False,
    }

    accepted = await client.post(f"{PUBLIC}/accept", json={"token": token, "password": NEW_PASSWORD})
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["roles"] == ["admin"] and accepted.json()["name"] == "Grace Hopper"

    new_headers = await login(client, "new.admin@example.com", NEW_PASSWORD)
    me = (await client.get("/api/v1/auth/me", headers=new_headers)).json()
    assert {"user:read", "patient:read_any", "appointment:read_any", "admin_invitation:manage"} <= set(me["permissions"])
    assert (await client.get("/api/v1/dashboard/admin", headers=new_headers)).status_code == 200

    assert await audit_actions(db_session, created["id"]) == ["admin.invitation_created", "admin.invitation_accepted"]
    assert await audit_actions(db_session, accepted.json()["id"]) == ["admin.role_granted"]
    listed = (await client.get(INVITES, params={"include_closed": True}, headers=headers)).json()
    assert listed[0]["status"] == "accepted"


async def test_a_used_link_cannot_be_used_again(client, admin, isolated_side_channels):
    await invite(client, admin[1])
    token = outbox_token(isolated_side_channels)
    assert (await client.post(f"{PUBLIC}/accept", json={"token": token, "password": NEW_PASSWORD, "name": "G"})).status_code == 201
    again = await client.post(f"{PUBLIC}/accept", json={"token": token, "password": "Other-pass-123", "name": "G"})
    assert again.status_code == 409 and again.json()["error"]["code"] == "INVITATION_USED"
    assert (await client.post(f"{PUBLIC}/preview", json={"token": token})).json()["status"] == "accepted"


async def test_an_expired_link_is_refused(client, db_session, admin, isolated_side_channels):
    created = (await invite(client, admin[1])).json()
    token = outbox_token(isolated_side_channels)
    stored = await db_session.get(AdminInvitation, uuid.UUID(created["id"]))
    stored.expires_at = clock.utcnow() - timedelta(minutes=1)
    await db_session.commit()
    assert (await client.post(f"{PUBLIC}/preview", json={"token": token})).json()["status"] == "expired"
    response = await client.post(f"{PUBLIC}/accept", json={"token": token, "password": NEW_PASSWORD, "name": "G"})
    assert response.json()["error"]["code"] == "INVITATION_EXPIRED"
    assert await db_session.scalar(select(User.id).where(User.email == "new.admin@example.com")) is None


async def test_a_revoked_link_is_refused(client, db_session, admin, isolated_side_channels):
    _, headers = admin
    created = (await invite(client, headers)).json()
    token = outbox_token(isolated_side_channels)
    revoked = await client.post(f"{INVITES}/{created['id']}/revoke", headers=headers)
    assert revoked.json()["status"] == "revoked"
    response = await client.post(f"{PUBLIC}/accept", json={"token": token, "password": NEW_PASSWORD, "name": "G"})
    assert response.json()["error"]["code"] == "INVITATION_REVOKED"
    assert (await client.post(f"{INVITES}/{created['id']}/revoke", headers=headers)).status_code == 409
    assert "admin.invitation_revoked" in await audit_actions(db_session, created["id"])


async def test_resending_replaces_the_link(client, admin, isolated_side_channels):
    _, headers = admin
    created = (await invite(client, headers)).json()
    old = outbox_token(isolated_side_channels)
    await asyncio.sleep(0.01)  # distinct outbox file names
    assert (await client.post(f"{INVITES}/{created['id']}/resend", headers=headers)).status_code == 200
    new = outbox_token(isolated_side_channels)
    assert new != old
    assert (await client.post(f"{PUBLIC}/preview", json={"token": old})).status_code == 404
    assert (await client.post(f"{PUBLIC}/preview", json={"token": new})).json()["status"] == "pending"


async def test_an_unknown_link_says_only_that_it_is_invalid(client):
    response = await client.post(f"{PUBLIC}/preview", json={"token": "x" * 43})
    assert response.status_code == 404 and response.json()["error"]["code"] == "INVITATION_INVALID"
    assert (await client.post(f"{PUBLIC}/preview", json={"token": "short"})).status_code == 422


async def test_invitation_dies_with_its_senders_authority(client, db_session, admin, make_user, isolated_side_channels):
    me, headers = admin
    await make_user(RoleCode.admin)  # so the sender may be deactivated
    await invite(client, headers)
    token = outbox_token(isolated_side_channels)
    sender = await db_session.get(User, me.id)
    sender.is_active = False
    await db_session.commit()
    response = await client.post(f"{PUBLIC}/accept", json={"token": token, "password": NEW_PASSWORD, "name": "G"})
    assert response.json()["error"]["code"] == "INVITATION_REVOKED"


async def test_public_invitation_endpoints_are_rate_limited(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "invite_attempts_per_minute", 3)
    codes = [(await client.post(f"{PUBLIC}/preview", json={"token": "y" * 43})).status_code for _ in range(4)]
    assert codes == [404, 404, 404, 429]


# ---- accepting with an existing account ------------------------------------------------


async def test_existing_account_must_sign_in_as_itself_to_accept(client, db_session, admin, make_user, isolated_side_channels):
    _, headers = admin
    patient = await make_user(RoleCode.patient)
    await invite(client, headers, email=patient.email)
    token = outbox_token(isolated_side_channels)
    assert (await client.post(f"{PUBLIC}/preview", json={"token": token})).json()["account_exists"] is True

    # Holding the link is not enough: no new password over an existing account.
    response = await client.post(f"{PUBLIC}/accept", json={"token": token, "password": NEW_PASSWORD, "name": "X"})
    assert response.json()["error"]["code"] == "ACCOUNT_EXISTS"
    assert (await client.post(f"{PUBLIC}/accept-existing", json={"token": token, "current_password": TEST_PASSWORD})).status_code == 401

    stranger = await make_user(RoleCode.patient)
    mismatch = await client.post(
        f"{PUBLIC}/accept-existing", json={"token": token, "current_password": TEST_PASSWORD}, headers=await login(client, stranger.email)
    )
    assert mismatch.json()["error"]["code"] == "INVITATION_EMAIL_MISMATCH"

    owner = await login(client, patient.email)
    wrong = await client.post(f"{PUBLIC}/accept-existing", json={"token": token, "current_password": "nope"}, headers=owner)
    assert wrong.json()["error"]["code"] == "REAUTHENTICATION_FAILED"

    ok = await client.post(f"{PUBLIC}/accept-existing", json={"token": token, "current_password": TEST_PASSWORD}, headers=owner)
    assert ok.status_code == 200, ok.text
    assert ok.json()["roles"] == ["admin", "patient"]
    stored = await db_session.scalar(select(User).where(User.id == patient.id))
    assert stored.password_hash == TEST_PASSWORD_HASH  # untouched


# ---- concurrency -----------------------------------------------------------------------


async def test_two_simultaneous_acceptances_of_one_link_create_one_account():
    """Commits real rows (the row lock is only visible across connections),
    so it creates its own data and deletes it afterwards."""
    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    tag = os.urandom(3).hex()
    inviter_email, invitee_email = f"inviter-{tag}@example.com", f"invitee-{tag}@example.com"
    raw = f"race-token-{tag}-{'z' * 24}"

    async with AsyncSession(engine, expire_on_commit=False) as setup:
        inviter = User(name="Inviter", email=inviter_email, password_hash=TEST_PASSWORD_HASH)
        setup.add(inviter)
        await setup.flush()
        await rbac_service.grant_roles(setup, inviter.id, [RoleCode.admin])
        invitation = AdminInvitation(
            email=invitee_email, token_hash=hash_token(raw), role_code="admin", invited_by_user_id=inviter.id,
            expires_at=clock.utcnow() + timedelta(hours=1),
        )
        setup.add(invitation)
        await setup.commit()

    async def attempt(i):
        async with AsyncSession(engine, expire_on_commit=False) as db:
            try:
                await admin_service.accept_with_new_account(db, raw, name=f"Racer {i}", password=NEW_PASSWORD)
                return "accepted"
            except ConflictError as exc:
                return exc.code

    try:
        results = await asyncio.gather(*(attempt(i) for i in range(2)))
        assert sorted(results) == ["INVITATION_USED", "accepted"]
        async with AsyncSession(engine) as check:
            assert len((await check.scalars(select(User).where(User.email == invitee_email))).all()) == 1
    finally:
        async with AsyncSession(engine) as db:
            users = select(User.id).where(User.email.in_([inviter_email, invitee_email]))
            await db.execute(delete(AuditLog).where(AuditLog.target_id == str(invitation.id)))
            await db.execute(delete(AuditLog).where(AuditLog.actor_user_id.in_(users)))
            await db.execute(delete(AdminInvitation).where(AdminInvitation.id == invitation.id))
            await db.execute(delete(UserRole).where(UserRole.user_id.in_(users)))
            await db.execute(delete(User).where(User.email.in_([inviter_email, invitee_email])))
            await db.commit()
        await engine.dispose()


# ---- granting and removing the admin role elsewhere ------------------------------------


async def test_admin_role_cannot_be_granted_through_user_management(client, admin, make_user):
    _, headers = admin
    body = {"name": "X", "email": "x@example.com", "password": "pw-12345678", "roles": ["admin"]}
    created = await client.post("/api/v1/users/", json=body, headers=headers)
    assert created.json()["error"]["code"] == "ADMIN_REQUIRES_INVITATION"
    patient = await make_user(RoleCode.patient)
    promoted = await client.put(f"/api/v1/users/{patient.id}/roles", json={"roles": ["patient", "admin"]}, headers=headers)
    assert promoted.json()["error"]["code"] == "ADMIN_REQUIRES_INVITATION"


async def test_users_cannot_change_their_own_roles(client, auth_headers, make_user):
    headers = await auth_headers(RoleCode.receptionist)
    me = (await client.get("/api/v1/auth/me", headers=headers)).json()
    assert (await client.put(f"/api/v1/users/{me['id']}/roles", json={"roles": ["admin"]}, headers=headers)).status_code == 403
    assert (await client.patch(f"/api/v1/users/{me['id']}", json={"roles": ["admin"]}, headers=headers)).status_code == 403


async def test_revoking_the_admin_role(client, db_session, admin, make_user):
    me, headers = admin
    other = await make_user(RoleCode.admin)
    body = {"current_password": TEST_PASSWORD}
    url = "/api/v1/admin/administrators/{}/revoke-role"

    assert (await client.post(url.format(me.id), json=body, headers=headers)).json()["error"]["code"] == "SELF_DEMOTION"
    wrong = await client.post(url.format(other.id), json={"current_password": "nope"}, headers=headers)
    assert wrong.json()["error"]["code"] == "REAUTHENTICATION_FAILED"
    assert (await client.post(url.format(other.id), json=body, headers=headers)).status_code == 204
    assert await rbac_service.role_codes_for(db_session, other.id) == set()
    assert await audit_actions(db_session, other.id) == ["admin.role_revoked"]


async def test_the_last_active_administrator_cannot_be_removed(client, make_role, make_user):
    await make_role("user_manager", ["user:read", "user:deactivate", "user:assign_role"])
    manager = await make_user("user_manager")
    only_admin = await make_user(RoleCode.admin)
    headers = await login(client, manager.email)
    response = await client.post(
        f"/api/v1/admin/administrators/{only_admin.id}/revoke-role", json={"current_password": TEST_PASSWORD}, headers=headers
    )
    assert response.json()["error"]["code"] == "LAST_ADMIN"
    assert (await client.post(f"/api/v1/users/{only_admin.id}/deactivate", headers=headers)).json()["error"]["code"] == "LAST_ADMIN"


async def test_disabling_and_enabling_an_administrator_is_audited(client, db_session, admin, make_user):
    _, headers = admin
    other = await make_user(RoleCode.admin)
    assert (await client.post(f"/api/v1/users/{other.id}/deactivate", headers=headers)).status_code == 200
    assert (await client.post(f"/api/v1/users/{other.id}/activate", headers=headers)).status_code == 200
    assert await audit_actions(db_session, other.id) == ["user.deactivated", "user.activated"]


@pytest.mark.parametrize("role", [RoleCode.patient, RoleCode.doctor, RoleCode.receptionist])
async def test_admin_api_is_closed_to_other_roles(client, auth_headers, role):
    headers = await auth_headers(role)
    assert (await client.get("/api/v1/dashboard/admin", headers=headers)).status_code == 403
    assert (await client.post(f"/api/v1/admin/administrators/{uuid.uuid4()}/revoke-role",
                              json={"current_password": TEST_PASSWORD}, headers=headers)).status_code == 403


# ---- administrator password recovery ---------------------------------------------------


async def test_reset_admin_password_sets_it_ends_sessions_and_audits(client, db_session, make_user):
    admin_user = await make_user(RoleCode.admin)
    await login(client, admin_user.email)  # an open session
    await admin_service.reset_admin_password(db_session, email=admin_user.email, password="Brand-new-pass-1")
    await login(client, admin_user.email, "Brand-new-pass-1")
    old = await client.post("/api/v1/auth/login", json={"email": admin_user.email, "password": TEST_PASSWORD})
    assert old.status_code == 401
    assert "admin.password_reset" in await audit_actions(db_session, admin_user.id)


async def test_reset_admin_password_refuses_non_administrators(db_session, make_user):
    from app.core.exceptions import NotFoundError

    patient = await make_user(RoleCode.patient)
    with pytest.raises(NotFoundError):
        await admin_service.reset_admin_password(db_session, email=patient.email, password="Brand-new-pass-1")
    with pytest.raises(NotFoundError):
        await admin_service.reset_admin_password(db_session, email="nobody@example.com", password="Brand-new-pass-1")


def test_reset_command_prompts_and_needs_confirmation(monkeypatch, capsys):
    from app.cli import create_admin, reset_admin_password

    calls = []

    async def fake_reset(email, password):
        calls.append((email, password))

    monkeypatch.setattr(reset_admin_password, "_reset", fake_reset)
    monkeypatch.setattr(create_admin.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(create_admin.getpass, "getpass", lambda prompt: "S3cret-pass-word")
    monkeypatch.setattr("builtins.input", lambda prompt: "RESET")
    reset_admin_password.main(["--email", "Admin@Example.com"])
    assert calls == [("admin@example.com", "S3cret-pass-word")]
    assert "S3cret" not in capsys.readouterr().out

    monkeypatch.setattr("builtins.input", lambda prompt: "no")
    with pytest.raises(SystemExit):
        reset_admin_password.main(["--email", "admin@example.com"])
    assert len(calls) == 1
