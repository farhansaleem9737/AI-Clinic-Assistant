"""Continue with Google (D123): who a Google identity is in this clinic.

Google proves an identity; this application decides what it may do. Google's
tokens are used once, to verify the identity, and never stored or used as our
own credentials: a successful sign-in ends in ``auth_service.start_session``,
the same session, refresh-cookie, CSRF and role rules as a password sign-in.

Identity resolution, in order:

1. Google ``sub`` already linked → that user (if active). Roles are untouched.
2. Not linked, but an account exists with the same email → no automatic link
   (an email match proves nothing about who controls our account): the user is
   told to sign in the usual way and link Google from Account settings.
3. Neither → a registration ticket: the person completes the normal patient or
   doctor-applicant form (no password, no email code: Google verified the
   address). Doctor applicants still wait for review; staff and admin roles are
   never available here.

The browser carries three short-lived HttpOnly cookies (path /api/v1/auth/google):
``g_oauth`` binds Google's callback to the browser that started it; ``g_handoff``
lets the app page finish the session (so the Strict session cookies are set on a
same-site request and no token is ever put in a URL); ``g_signup`` holds the
registration ticket. The database keeps only hashes; every step is single-use.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.config import settings
from app.core.exceptions import BusinessRuleError, NotFoundError, PermissionDeniedError
from app.core.permissions import Principal
from app.core.security import hash_token, verify_password
from app.models.oauth import GOOGLE, OAuthFlow, OAuthIdentity
from app.models.user import User
from app.services import audit_service, auth_service, doctor_application_service, patient_service
from app.services.audit_service import AuditAction
from app.services.google_oidc import GoogleIdentity, GoogleSignInError

logger = logging.getLogger(__name__)

BINDER_COOKIE = "g_oauth"
HANDOFF_COOKIE = "g_handoff"
SIGNUP_COOKIE = "g_signup"
HANDOFF_SECONDS = 120


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

    if await db.scalar(select(User.id).where(User.email == identity.email)) is not None:
        # Same address, but this Google account was never linked to that login.
        # Linking needs the owner to sign in first (Account › Connected accounts).
        return Outcome(_error_path(flow.purpose, "link_required"))

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
