"""Google's side of "Continue with Google" (D123): the authorization URL, the code
exchange and ID-token verification. No database, no sessions: those live in
``google_auth_service``.

Verification uses ``google.auth.jwt.decode`` (signature, ``aud``, ``iat``/``exp``)
against Google's published certificates, cached for as long as Google's
Cache-Control allows and re-fetched once when a token names an unknown key
(rotation). ``iss``, ``nonce`` and ``email_verified`` are checked here.

Nothing secret is ever logged: not the code, the tokens or the client secret.
"""

import asyncio
import base64
import hashlib
import logging
import re
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
from google.auth import exceptions as google_exceptions
from google.auth import jwt as google_jwt

from app.core.config import settings
from app.core.exceptions import BusinessRuleError

logger = logging.getLogger(__name__)

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
CERTS_URL = "https://www.googleapis.com/oauth2/v1/certs"
ISSUERS = {"accounts.google.com", "https://accounts.google.com"}
SCOPES = "openid email profile"  # identity only: no Google API access, no refresh token
CLOCK_SKEW_SECONDS = 60


class GoogleSignInError(BusinessRuleError):
    """Google did not confirm an identity we can trust. ``code`` says why (for logs
    and the redirect); the user sees a plain message."""

    code = "GOOGLE_SIGN_IN_FAILED"


@dataclass(frozen=True)
class GoogleIdentity:
    subject: str
    email: str
    given_name: str | None
    family_name: str | None
    name: str | None


# ---- PKCE, state, nonce ------------------------------------------------------------


def random_token() -> str:
    return secrets.token_urlsafe(32)


def pkce_pair() -> tuple[str, str]:
    """(verifier, S256 challenge). The verifier is 86 URL-safe characters (43-128 allowed)."""
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    return verifier, challenge


def authorize_url(*, state: str, nonce: str, code_challenge: str, login_hint: str | None = None) -> str:
    params = {
        "client_id": settings.google_oauth_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    if login_hint:
        params["login_hint"] = login_hint
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


# ---- network ------------------------------------------------------------------------

_client: httpx.AsyncClient | None = None


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=settings.google_oauth_timeout_seconds)
    return _client


async def exchange_code(code: str, code_verifier: str) -> str:
    """The ID token for an authorization code (server to server, with the client secret)."""
    try:
        response = await _http().post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_oauth_client_id,
                "client_secret": settings.google_oauth_client_secret.get_secret_value(),
                "redirect_uri": settings.google_redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": code_verifier,
            },
            headers={"Accept": "application/json"},
        )
    except httpx.HTTPError as exc:
        logger.warning("google_token_exchange_unreachable", extra={"error": type(exc).__name__})
        raise GoogleSignInError("Google could not be reached", code="GOOGLE_UNAVAILABLE") from exc
    if response.status_code != 200:
        # Google's error code only ("invalid_grant": used, expired or forged code).
        error = (response.json().get("error") if response.headers.get("content-type", "").startswith("application/json") else None)
        logger.info("google_token_exchange_rejected", extra={"status": response.status_code, "google_error": error})
        raise GoogleSignInError("Google did not accept the sign-in", code="GOOGLE_CODE_REJECTED")
    id_token = response.json().get("id_token")
    if not id_token:
        raise GoogleSignInError("Google returned no identity", code="GOOGLE_CODE_REJECTED")
    return id_token


_certs: dict[str, str] = {}
_certs_expire_at = 0.0
_certs_lock = asyncio.Lock()


def _max_age(cache_control: str | None) -> int:
    match = re.search(r"max-age=(\d+)", cache_control or "")
    return int(match.group(1)) if match else 3600


async def certificates(*, force: bool = False) -> dict[str, str]:
    """Google's signing certificates by key id, cached per Cache-Control."""
    global _certs, _certs_expire_at
    if not force and _certs and time.monotonic() < _certs_expire_at:
        return _certs
    async with _certs_lock:
        if not force and _certs and time.monotonic() < _certs_expire_at:
            return _certs
        try:
            response = await _http().get(CERTS_URL)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            if _certs:  # keep using the last good keys rather than fail every sign-in
                logger.warning("google_certs_refresh_failed", extra={"error": type(exc).__name__})
                return _certs
            raise GoogleSignInError("Google could not be reached", code="GOOGLE_UNAVAILABLE") from exc
        _certs = response.json()
        _certs_expire_at = time.monotonic() + _max_age(response.headers.get("cache-control"))
        return _certs


def _decode(token: str, certs: dict[str, str]) -> dict:
    return google_jwt.decode(
        token, certs=certs, audience=settings.google_oauth_client_id, clock_skew_in_seconds=CLOCK_SKEW_SECONDS
    )


async def verify_id_token(token: str, *, nonce: str) -> GoogleIdentity:
    """The identity in a Google ID token, after checking everything that matters:
    signature (Google's key), audience (this client), issuer, expiry, the nonce of
    this sign-in, and that Google verified the email address."""
    certs = await certificates()
    try:
        try:
            claims = _decode(token, certs)
        except ValueError as exc:
            if "Certificate for key id" not in str(exc):
                raise
            claims = _decode(token, await certificates(force=True))  # Google rotated its keys
    except (ValueError, google_exceptions.GoogleAuthError) as exc:
        logger.info("google_id_token_invalid", extra={"reason": type(exc).__name__})
        raise GoogleSignInError("Google's answer could not be verified", code="GOOGLE_TOKEN_INVALID") from exc

    if claims.get("iss") not in ISSUERS:
        raise GoogleSignInError("Google's answer could not be verified", code="GOOGLE_TOKEN_INVALID")
    if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise GoogleSignInError("Google's answer could not be verified", code="GOOGLE_TOKEN_INVALID")
    if not claims.get("sub") or not claims.get("email"):
        raise GoogleSignInError("Google did not share an email address", code="GOOGLE_TOKEN_INVALID")
    if claims.get("email_verified") is not True:
        raise GoogleSignInError("This Google account's email address is not verified", code="GOOGLE_EMAIL_UNVERIFIED")
    return GoogleIdentity(
        subject=str(claims["sub"]),
        email=str(claims["email"]).strip().lower(),
        given_name=claims.get("given_name"),
        family_name=claims.get("family_name"),
        name=claims.get("name"),
    )
