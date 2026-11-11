"""Continue with Google (D123): who a Google identity is in this clinic.

Google proves an identity; this application decides what it may do. Google's
tokens are used once, to verify the identity, and never stored or used as our
own credentials: a successful sign-in ends in ``auth_service.start_session``,
the same session, refresh-cookie, CSRF and role rules as a password sign-in.

Identity resolution, in order:

1. Google ``sub`` already linked → that user (if active). Roles are untouched.
2. Not linked, but an account exists with the same email (D128) → never an
   automatic link (an email match proves nothing about who controls our
   account). A short ``link`` step, bound to that user and this Google ``sub``,
   asks the owner to prove control of the account: its password, or a code
   emailed to it (patients and applicants only; staff and admins need the
   password). Then Google is linked and the normal session starts. Linking from
   Account settings after a normal sign-in still works too.
3. Neither → a registration ticket: the person completes the normal patient or
   doctor-applicant form (no password, no email code: Google verified the
   address). Doctor applicants still wait for review; staff and admin roles are
   never available here.

The browser carries three short-lived HttpOnly cookies (path /api/v1/auth/google):
``g_oauth`` binds Google's callback to the browser that started it; ``g_handoff``
lets the app page finish the session (so the Strict session cookies are set on a
same-site request and no token is ever put in a URL); ``g_signup`` holds the
registration ticket; ``g_link`` the linking step. The database keeps only hashes; every step is single-use.
"""

import hashlib
import hmac
import logging
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.config import settings
from app.core.exceptions import (
    BusinessRuleError,
    EmailUnavailableError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitedError,
)
from app.core.permissions import Principal, RoleCode
from app.core.security import hash_token, verify_password
from app.models.oauth import GOOGLE, OAuthFlow, OAuthIdentity
from app.models.user import User
from app.services import (
    audit_service,
    auth_service,
    doctor_application_service,
    email_service,
    email_templates,
    patient_service,
    rbac_service,
)
from app.services.audit_service import AuditAction
from app.services.google_oidc import GoogleIdentity, GoogleSignInError

logger = logging.getLogger(__name__)

BINDER_COOKIE = "g_oauth"
HANDOFF_COOKIE = "g_handoff"
SIGNUP_COOKIE = "g_signup"
LINK_COOKIE = "g_link"
HANDOFF_SECONDS = 120
# Linking at sign-in (D128).
LINK_MINUTES = 15
LINK_MAX_ATTEMPTS = 5
LINK_CODE_MINUTES = 10
LINK_RESEND_SECONDS = 60
# Accounts whose link needs the password: an emailed code proves only the mailbox,
# which is too little for anyone who can see other people's records.
PASSWORD_ONLY_ROLES = frozenset({RoleCode.admin, RoleCode.doctor, RoleCode.receptionist})


def _oidc():
    # Imported at call time so tests can replace the network functions.
    from app.services import google_oidc

    return google_oidc


@dataclass
class Outcome:
    """Where the browser goes after Google's callback, and the cookie to set."""

    path: str
    cookie: tuple[str, str, int] | None = None
    clear: list[str] = field(default_factory=lambda: [BINDER_COOKIE])


def ensure_enabled() -> None:
    if not settings.google_oauth_enabled:
        raise NotFoundError("Google sign-in is not available", code="GOOGLE_SIGN_IN_DISABLED")


def _error_path(purpose: str, reason: str) -> str:
    base = {"link": "/account", "register": "/register"}.get(purpose, "/login")
    return f"{base}?google={reason}"


# Short reasons the frontend turns into messages (never the internal detail).
_REASONS = {
    "GOOGLE_STATE_INVALID": "expired",
    "GOOGLE_UNAVAILABLE": "unavailable",
    "GOOGLE_EMAIL_UNVERIFIED": "unverified",
    "GOOGLE_IDENTITY_IN_USE": "in_use",
    "GOOGLE_ALREADY_LINKED": "already_linked",
    "ACCOUNT_INACTIVE": "inactive",
}


def reason_for(code: str) -> str:
    return _REASONS.get(code, "failed")


# ---- single-use steps ------------------------------------------------------------------


async def _new_step(db: AsyncSession, **values) -> None:
    db.add(OAuthFlow(provider=GOOGLE, **values))
    await db.flush()


async def _consume(db: AsyncSession, kind: str, raw: str | None, *, binder: str | None = None) -> OAuthFlow:
    """Atomically mark a live step used and return it; otherwise GOOGLE_STATE_INVALID
    (unknown, expired, already used, or another browser's). Another browser's
    attempt leaves the step untouched, so it cannot burn the real user's sign-in."""
    invalid = GoogleSignInError("This Google sign-in has expired. Please try again.", code="GOOGLE_STATE_INVALID")
    if not raw:
        raise invalid
    now = clock.utcnow()
    conditions = [
        OAuthFlow.token_hash == hash_token(raw),
        OAuthFlow.kind == kind,
        OAuthFlow.consumed_at.is_(None),
        OAuthFlow.expires_at > now,
    ]
    if binder is not None or kind == "authorize":
        # Google's answer must reach the browser that started (login CSRF).
        conditions.append(OAuthFlow.binder_hash == hash_token(binder or ""))
    row = await db.scalar(
        update(OAuthFlow)
        .where(*conditions)
        .values(consumed_at=now)
        .returning(OAuthFlow)
        .execution_options(synchronize_session=False)
    )
    if row is None:
        raise invalid
    return row


async def _purge(db: AsyncSession) -> None:
    await db.execute(delete(OAuthFlow).where(OAuthFlow.expires_at < clock.utcnow() - timedelta(days=1)))


# ---- 1. start ----------------------------------------------------------------------------


async def begin(
    db: AsyncSession, *, purpose: str, remember_me: bool = False, user_id: uuid.UUID | None = None,
    login_hint: str | None = None,
) -> tuple[str, str]:
    """(Google authorization URL, binder cookie value) for a new sign-in."""
    ensure_enabled()
    oidc = _oidc()
    state, binder, nonce = oidc.random_token(), oidc.random_token(), oidc.random_token()
    verifier, challenge = oidc.pkce_pair()
    await _purge(db)
    await _new_step(
        db, kind="authorize", purpose=purpose, token_hash=hash_token(state), binder_hash=hash_token(binder),
        code_verifier=verifier, nonce=nonce, user_id=user_id, remember_me=remember_me,
        expires_at=clock.utcnow() + timedelta(minutes=settings.google_oauth_flow_minutes),
    )
    await db.commit()
    return oidc.authorize_url(state=state, nonce=nonce, code_challenge=challenge, login_hint=login_hint), binder


# ---- 2. Google's callback ------------------------------------------------------------------


async def callback(
    db: AsyncSession, *, state: str | None, code: str | None, error: str | None, binder: str | None
) -> Outcome:
    """Validate Google's answer and decide the next step. Never raises: every
    failure is a redirect with a short reason, and nothing is half-done."""
    purpose = "login"
    try:
        flow = await _consume(db, "authorize", state, binder=binder)
        purpose = flow.purpose
        await db.commit()  # used up before anything else happens: no replay
        if error:
            return Outcome(_error_path(purpose, "cancelled" if error == "access_denied" else "failed"))
        if not code:
            raise GoogleSignInError("Google returned no code", code="GOOGLE_CODE_REJECTED")
        oidc = _oidc()
        identity = await oidc.verify_id_token(await oidc.exchange_code(code, flow.code_verifier), nonce=flow.nonce)
        if purpose == "link":
            await _link(db, flow.user_id, identity)
            return Outcome("/account?google=linked")
        return await _sign_in_or_register(db, flow, identity)
    except (GoogleSignInError, PermissionDeniedError, NotFoundError) as exc:
        await db.rollback()
        logger.info("google_sign_in_failed", extra={"code": exc.code, "purpose": purpose})
        return Outcome(_error_path(purpose, reason_for(exc.code)))


async def _sign_in_or_register(db: AsyncSession, flow: OAuthFlow, identity: GoogleIdentity) -> Outcome:
    linked = await db.scalar(
        select(OAuthIdentity).where(OAuthIdentity.provider == GOOGLE, OAuthIdentity.subject == identity.subject)
    )
    if linked is not None:
        user = await db.get(User, linked.user_id)
        if user is None or not user.is_active:
            raise PermissionDeniedError("Account is inactive", code="ACCOUNT_INACTIVE")
        linked.email, linked.last_login_at = identity.email, clock.utcnow()
        handoff = _oidc().random_token()
        await _new_step(
            db, kind="handoff", purpose=flow.purpose, token_hash=hash_token(handoff), binder_hash=hash_token(handoff),
            user_id=user.id, remember_me=flow.remember_me,
            expires_at=clock.utcnow() + timedelta(seconds=HANDOFF_SECONDS),
        )
        await db.commit()
        return Outcome("/auth/google/complete", cookie=(HANDOFF_COOKIE, handoff, HANDOFF_SECONDS))

    existing = await db.scalar(select(User).where(User.email == identity.email.strip().lower()))
    if existing is not None:
        # Same address, but this Google account was never linked to that login (D128):
        # the owner must prove control of the account before anything is linked.
        if not existing.is_active:
            raise PermissionDeniedError("Account is inactive", code="ACCOUNT_INACTIVE")
        other = await db.scalar(
            select(OAuthIdentity.id).where(OAuthIdentity.user_id == existing.id, OAuthIdentity.provider == GOOGLE)
        )
        if other is not None:  # a different Google account is already this login's
            raise GoogleSignInError("Another Google account is already linked.", code="GOOGLE_ALREADY_LINKED")
        ticket = _oidc().random_token()
        await _new_step(
            db, kind="link", purpose=flow.purpose, token_hash=hash_token(ticket), binder_hash=hash_token(ticket),
            user_id=existing.id, remember_me=flow.remember_me, subject=identity.subject, email=identity.email,
            expires_at=clock.utcnow() + timedelta(minutes=LINK_MINUTES),
        )
        await db.commit()
        logger.info("google_link_offered", extra={"user_id": str(existing.id)})
        return Outcome("/login/link-google", cookie=(LINK_COOKIE, ticket, LINK_MINUTES * 60))

    ticket = _oidc().random_token()
    await _new_step(
        db, kind="signup", purpose=flow.purpose, token_hash=hash_token(ticket), binder_hash=hash_token(ticket),
        remember_me=flow.remember_me, subject=identity.subject, email=identity.email,
        given_name=(identity.given_name or "")[:100] or None, family_name=(identity.family_name or "")[:100] or None,
        expires_at=clock.utcnow() + timedelta(minutes=settings.google_oauth_signup_minutes),
    )
    await db.commit()
    return Outcome("/register/google", cookie=(SIGNUP_COOKIE, ticket, settings.google_oauth_signup_minutes * 60))


# ---- 3a. a known user: the app page finishes the session --------------------------------------


async def complete(db: AsyncSession, raw: str | None, client: auth_service.ClientInfo) -> auth_service.SessionTokens:
    ensure_enabled()
    flow = await _consume(db, "handoff", raw)
    user = await db.get(User, flow.user_id)
    tokens = await auth_service.start_session(db, user, client, remember_me=flow.remember_me)
    logger.info("login_succeeded", extra={"user_id": str(user.id), "method": "google"})
    return tokens


# ---- 3b. a new person: the registration form -------------------------------------------------


async def signup_ticket(db: AsyncSession, raw: str | None) -> OAuthFlow:
    """The live registration ticket (not used up), for prefilling the form."""
    ensure_enabled()
    flow = (
        await db.scalar(
            select(OAuthFlow).where(
                OAuthFlow.token_hash == hash_token(raw), OAuthFlow.kind == "signup",
                OAuthFlow.consumed_at.is_(None), OAuthFlow.expires_at > clock.utcnow(),
            )
        )
        if raw else None
    )
    if flow is None:
        raise GoogleSignInError("This Google sign-up has expired. Please start again.", code="GOOGLE_STATE_INVALID")
    return flow


async def signup(db: AsyncSession, raw: str | None, data, client: auth_service.ClientInfo) -> auth_service.SessionTokens:
    """Create the account the person asked for (patient, or doctor applicant
    awaiting review) with the Google identity linked and no password, through
    the same services as the normal registration, then sign them in."""
    ensure_enabled()
    flow = await _consume(db, "signup", raw)  # rolled back with everything else if the form is refused
    link = auth_service.OAuthLink(provider=GOOGLE, subject=flow.subject, email=flow.email)
    registration = data.model_copy(update={"email": flow.email, "password": None})
    try:
        if registration.account_type == "doctor":
            user = await doctor_application_service.register(db, registration, oauth=link)
        else:
            user = await patient_service.register_self(db, registration, oauth=link)
    except IntegrityError as exc:  # the same Google account registering twice at once
        await db.rollback()
        raise GoogleSignInError("This Google account is already registered.", code="GOOGLE_IDENTITY_IN_USE") from exc
    audit_service.record(
        db, AuditAction.user_google_registered, actor_id=user.id, target_type="user", target_id=user.id,
        ip_address=client.ip_address, details={"account_type": registration.account_type},
    )
    return await auth_service.start_session(db, user, client, remember_me=flow.remember_me)


# ---- Account › Connected accounts ------------------------------------------------------------


async def _reauthenticate(db: AsyncSession, user: User, raw_refresh: str | None, current_password: str | None) -> None:
    """Linking or unlinking a sign-in method needs a recent sign-in, or the password."""
    if current_password is not None:
        if not verify_password(current_password, user.password_hash):
            raise BusinessRuleError("The current password is incorrect.", code="INCORRECT_PASSWORD")
        return
    if await auth_service.password_change_needs_current(db, user.id, raw_refresh):
        raise PermissionDeniedError(
            "For your security, enter your password (or sign in again) to change sign-in methods.",
            code="REAUTHENTICATION_REQUIRED",
        )


async def status(db: AsyncSession, principal: Principal) -> dict:
    identity = await db.scalar(
        select(OAuthIdentity).where(OAuthIdentity.user_id == principal.user_id, OAuthIdentity.provider == GOOGLE)
    )
    return {
        "enabled": settings.google_oauth_enabled,
        "linked": identity is not None,
        "email": identity.email if identity else None,
        "has_password": principal.user.password_hash is not None,
    }


async def begin_link(
    db: AsyncSession, principal: Principal, raw_refresh: str | None, current_password: str | None
) -> tuple[str, str]:
    ensure_enabled()
    await _reauthenticate(db, principal.user, raw_refresh, current_password)
    return await begin(db, purpose="link", user_id=principal.user_id, login_hint=principal.user.email)


async def _link(db: AsyncSession, user_id: uuid.UUID, identity: GoogleIdentity) -> None:
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise PermissionDeniedError("Account is inactive", code="ACCOUNT_INACTIVE")
    owner = await db.scalar(
        select(OAuthIdentity).where(OAuthIdentity.provider == GOOGLE, OAuthIdentity.subject == identity.subject)
    )
    if owner is not None and owner.user_id != user_id:
        raise GoogleSignInError("This Google account is linked to another account.", code="GOOGLE_IDENTITY_IN_USE")
    mine = await db.scalar(
        select(OAuthIdentity).where(OAuthIdentity.user_id == user_id, OAuthIdentity.provider == GOOGLE)
    )
    if mine is not None and mine.subject != identity.subject:
        raise GoogleSignInError("Another Google account is already linked.", code="GOOGLE_ALREADY_LINKED")
    if mine is None:
        db.add(OAuthIdentity(user_id=user_id, provider=GOOGLE, subject=identity.subject, email=identity.email))
    else:
        mine.email = identity.email
    audit_service.record(
        db, AuditAction.user_google_linked, actor_id=user_id, target_type="user", target_id=user_id, details={},
    )
    try:
        await db.commit()
    except IntegrityError as exc:  # linked elsewhere at the same moment
        await db.rollback()
        raise GoogleSignInError("This Google account is linked to another account.", code="GOOGLE_IDENTITY_IN_USE") from exc
    logger.info("google_linked", extra={"user_id": str(user_id)})


async def unlink(
    db: AsyncSession, principal: Principal, raw_refresh: str | None, current_password: str | None, ip: str | None
) -> None:
    await _reauthenticate(db, principal.user, raw_refresh, current_password)
    identity = await db.scalar(
        select(OAuthIdentity).where(OAuthIdentity.user_id == principal.user_id, OAuthIdentity.provider == GOOGLE)
    )
    if identity is None:
        raise NotFoundError("No Google account is linked", code="GOOGLE_NOT_LINKED")
    if principal.user.password_hash is None:
        raise BusinessRuleError(
            "Google is your only way to sign in. Set a password first, then unlink Google.",
            code="LAST_SIGN_IN_METHOD",
        )
    await db.delete(identity)
    audit_service.record(
        db, AuditAction.user_google_unlinked, actor_id=principal.user_id, target_type="user",
        target_id=principal.user_id, ip_address=ip, details={},
    )
    await db.commit()
    logger.info("google_unlinked", extra={"user_id": str(principal.user_id)})


# ---- linking at sign-in: prove you own the existing account (D128) -----------------------


@dataclass
class LinkResult:
    tokens: auth_service.SessionTokens
    notice: email_service.Email  # to send after the response


def _link_code_hash(flow_id: uuid.UUID, code: str) -> str:
    return hmac.new(settings.secret_key.encode(), f"google-link:{flow_id}:{code}".encode(), hashlib.sha256).hexdigest()


def _link_expired() -> GoogleSignInError:
    return GoogleSignInError(
        "This Google sign-in has expired. Please continue with Google again.", code="GOOGLE_STATE_INVALID"
    )


async def _link_step(db: AsyncSession, raw: str | None, *, lock: bool = False) -> OAuthFlow:
    """The live linking step of this browser (its cookie), optionally row-locked."""
    ensure_enabled()
    if not raw:
        raise _link_expired()
    query = select(OAuthFlow).where(
        OAuthFlow.token_hash == hash_token(raw), OAuthFlow.kind == "link", OAuthFlow.consumed_at.is_(None),
        OAuthFlow.expires_at > clock.utcnow(), OAuthFlow.attempts < LINK_MAX_ATTEMPTS,
    )
    flow = await db.scalar(query.with_for_update() if lock else query)
    if flow is None:
        raise _link_expired()
    return flow


async def _active_user(db: AsyncSession, user_id: uuid.UUID) -> User:
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise PermissionDeniedError("This account can't sign in. Please contact the clinic.", code="ACCOUNT_INACTIVE")
    return user


async def link_methods(db: AsyncSession, user: User) -> list[str]:
    """How the owner may prove control: their password, and (except staff and admins) an emailed code."""
    methods = ["password"] if user.password_hash else []
    principal = await rbac_service.load_principal_by_id(db, user.id)
    privileged = principal is None or bool(set(principal.roles) & PASSWORD_ONLY_ROLES)
    if not privileged:
        methods.append("email_code")
    return methods


async def link_ticket(db: AsyncSession, raw: str | None) -> dict:
    """What the linking page needs: the account's address and the ways to prove ownership."""
    flow = await _link_step(db, raw)
    user = await _active_user(db, flow.user_id)
    retry = 0
    if flow.code_sent_at is not None:
        retry = max(int((flow.code_sent_at + timedelta(seconds=LINK_RESEND_SECONDS) - clock.utcnow()).total_seconds()), 0)
    return {
        "email": user.email,
        "methods": await link_methods(db, user),
        "code_sent": flow.code_sent_at is not None,
        "resend_in": retry,
        "attempts_left": LINK_MAX_ATTEMPTS - flow.attempts,
    }


async def send_link_code(db: AsyncSession, raw: str | None) -> None:
    """Email a 6-digit code to the existing account's own address (not one Google gave)."""
    flow = await _link_step(db, raw, lock=True)
    user = await _active_user(db, flow.user_id)
    if "email_code" not in await link_methods(db, user):
        await db.rollback()
        raise BusinessRuleError("Confirm with your password to link Google to this account.", code="LINK_METHOD_UNAVAILABLE")
    now = clock.utcnow()
    if flow.code_sent_at is not None and now - flow.code_sent_at < timedelta(seconds=LINK_RESEND_SECONDS):
        wait = LINK_RESEND_SECONDS - int((now - flow.code_sent_at).total_seconds())
        await db.rollback()
        raise RateLimitedError(
            "A code was sent moments ago. Please wait before asking for another.",
            code="CODE_RECENTLY_SENT", details={"retry_after_seconds": wait},
        )
    code = f"{secrets.randbelow(1_000_000):06d}"
    flow.code_hash, flow.code_sent_at = _link_code_hash(flow.id, code), now
    address, user_id = user.email, user.id
    await db.commit()
    rendered = email_templates.google_link_code(code, LINK_CODE_MINUTES)
    delivery = await email_service.send(email_service.Email(to=address, subject=rendered.subject, text=rendered.text, html=rendered.html))
    if delivery not in (email_service.Delivery.sent, email_service.Delivery.outbox):
        raise EmailUnavailableError("The code could not be sent. Please try again later.")
    logger.info("google_link_code_sent", extra={"user_id": str(user_id)})


async def link_and_sign_in(
    db: AsyncSession, raw: str | None, client: auth_service.ClientInfo, *, password: str | None = None, code: str | None = None
) -> LinkResult:
    """Check the proof, link the Google identity to the existing user and start the
    normal session, in one transaction. A wrong proof counts an attempt and changes nothing else."""
    flow = await _link_step(db, raw, lock=True)
    user = await _active_user(db, flow.user_id)
    methods = await link_methods(db, user)
    now = clock.utcnow()
    if password is not None:
        if "password" not in methods:
            await db.rollback()
            raise BusinessRuleError("This account has no password. Use the emailed code.", code="LINK_METHOD_UNAVAILABLE")
        proven, wrong = verify_password(password, user.password_hash), "The password is incorrect."
        method = "password"
    else:
        if "email_code" not in methods:
            await db.rollback()
            raise BusinessRuleError("Confirm with your password to link Google to this account.", code="LINK_METHOD_UNAVAILABLE")
        fresh = flow.code_sent_at is not None and now - flow.code_sent_at < timedelta(minutes=LINK_CODE_MINUTES)
        proven = bool(fresh and flow.code_hash and hmac.compare_digest(_link_code_hash(flow.id, code or ""), flow.code_hash))
        wrong = "That code is incorrect or has expired. Check the email, or send a new code."
        method = "email_code"
    if not proven:
        flow.attempts += 1
        left = LINK_MAX_ATTEMPTS - flow.attempts
        await db.commit()
        logger.info("google_link_proof_rejected", extra={"user_id": str(flow.user_id), "method": method})
        if left <= 0:
            raise _link_expired()
        raise BusinessRuleError(wrong, code="LINK_PROOF_INVALID", details={"attempts_left": left})

    flow.consumed_at = now  # single use, in the same transaction as the link
    owner = await db.scalar(
        select(OAuthIdentity).where(OAuthIdentity.provider == GOOGLE, OAuthIdentity.subject == flow.subject)
    )
    if owner is not None and owner.user_id != user.id:
        await db.rollback()
        raise GoogleSignInError("This Google account is linked to another account.", code="GOOGLE_IDENTITY_IN_USE")
    if owner is None:
        mine = await db.scalar(select(OAuthIdentity.id).where(OAuthIdentity.user_id == user.id, OAuthIdentity.provider == GOOGLE))
        if mine is not None:
            await db.rollback()
            raise GoogleSignInError("Another Google account is already linked.", code="GOOGLE_ALREADY_LINKED")
        db.add(OAuthIdentity(user_id=user.id, provider=GOOGLE, subject=flow.subject, email=flow.email, last_login_at=now))
    audit_service.record(
        db, AuditAction.user_google_linked, actor_id=user.id, target_type="user", target_id=user.id,
        ip_address=client.ip_address, details={"at_sign_in": True, "verified_with": method},
    )
    try:
        await db.flush()
    except IntegrityError as exc:  # the same Google account linked at the same moment elsewhere
        await db.rollback()
        raise GoogleSignInError("This Google account is linked to another account.", code="GOOGLE_IDENTITY_IN_USE") from exc
    address, user_id = user.email, user.id
    tokens = await auth_service.start_session(db, user, client, remember_me=flow.remember_me)  # commits
    logger.info("google_linked", extra={"user_id": str(user_id), "at_sign_in": True, "method": method})
    logger.info("login_succeeded", extra={"user_id": str(user_id), "method": "google"})
    rendered = email_templates.google_linked_notice()
    return LinkResult(tokens, email_service.Email(to=address, subject=rendered.subject, text=rendered.text, html=rendered.html))


async def cancel_link(db: AsyncSession, raw: str | None) -> None:
    """The person chose not to link: the step is used up; nothing else changes."""
    if raw:
        await db.execute(
            update(OAuthFlow)
            .where(OAuthFlow.token_hash == hash_token(raw), OAuthFlow.kind == "link", OAuthFlow.consumed_at.is_(None))
            .values(consumed_at=clock.utcnow())
        )
        await db.commit()


async def send_notice(email: email_service.Email) -> None:
    """Best effort, after the response: the link stands whether or not this arrives."""
    delivery = await email_service.send(email)
    if delivery not in (email_service.Delivery.sent, email_service.Delivery.outbox):
        logger.warning("google_linked_notice_not_sent", extra={"delivery": delivery.value})
