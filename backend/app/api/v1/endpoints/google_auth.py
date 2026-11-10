"""Continue with Google (D123). Thin routes: the decisions are in
``services/google_auth_service.py``, Google's protocol in ``services/google_oidc.py``.

    GET  /auth/providers               which extra sign-in methods are on (public)
    GET  /auth/google/start            redirect to Google (login or registration)
    GET  /auth/google/callback         Google's redirect back (registered in Google Cloud)
    POST /auth/google/complete         the app page finishes a known user's session
    GET  /auth/google/signup           prefill for a new person's registration form
    POST /auth/google/signup           create the account and sign in
    GET  /auth/google/identity         the signed-in user's Google link
    POST /auth/google/link             start linking Google to the signed-in user
    POST /auth/google/unlink           remove the link (not the last sign-in method)

Every browser redirect goes to FRONTEND_BASE_URL + a fixed path chosen here: never
a URL from the request, so there is no open redirect.
"""

from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import get_current_principal
from app.api.v1.endpoints.auth import _access_response, _client_info, _set_session_cookies, verify_csrf
from app.core.config import settings
from app.core.permissions import Principal
from app.core.rate_limit import rate_limit
from app.db.session import get_db
from app.schemas.google_auth import (
    GoogleIdentityStatus,
    GoogleLinkStart,
    GooglePrefill,
    GoogleSignupRequest,
    Reauthentication,
    SignInProviders,
)
from app.schemas.user import AccessTokenResponse
from app.services import google_auth_service as service

router = APIRouter(prefix="/auth", tags=["auth", "google"])

_limited = Depends(rate_limit("google_sign_in", lambda: settings.google_oauth_attempts_per_minute))


def _set(response: Response, name: str, value: str, max_age: int) -> None:
    # HttpOnly and Lax: sent on Google's top-level redirect back and on our own
    # requests, never readable by scripts, only to /api/v1/auth/google.
    response.set_cookie(
        name, value, max_age=max_age, httponly=True, secure=settings.secure_cookies, samesite="lax",
        path=settings.google_cookie_path,
    )


def _clear(response: Response, *names: str) -> None:
    for name in names:
        response.delete_cookie(name, path=settings.google_cookie_path, httponly=True, secure=settings.secure_cookies, samesite="lax")


def _to_app(path: str) -> RedirectResponse:
    return RedirectResponse(f"{settings.frontend_base_url}{path}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/providers", response_model=SignInProviders)
async def providers():
    """Whether the login and registration pages should offer Google."""
    return SignInProviders(google=settings.google_oauth_enabled)


@router.get("/google/start", dependencies=[_limited])
async def start(
    intent: Literal["login", "register"] = "login",
    remember: bool = False,
    db: AsyncSession = Depends(get_db),
):
    if not settings.google_oauth_enabled:
        return _to_app(f"/{intent}?google=unavailable")
    url, binder = await service.begin(db, purpose=intent, remember_me=remember)
    response = RedirectResponse(url, status_code=status.HTTP_303_SEE_OTHER)
    _set(response, service.BINDER_COOKIE, binder, settings.google_oauth_flow_minutes * 60)
    return response


@router.get("/google/callback", include_in_schema=False)
async def callback(
    request: Request,
    state: str | None = Query(None, max_length=200),
    code: str | None = Query(None, max_length=2000),
    error: str | None = Query(None, max_length=100),
    db: AsyncSession = Depends(get_db),
):
    outcome = await service.callback(
        db, state=state, code=code, error=error, binder=request.cookies.get(service.BINDER_COOKIE)
    )
    response = _to_app(outcome.path)
    _clear(response, *outcome.clear)
    if outcome.cookie:
        _set(response, *outcome.cookie)
    return response


@router.post("/google/complete", response_model=AccessTokenResponse)
async def complete(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    """Exchange the short handoff cookie for the normal session (Strict refresh
    cookie + CSRF cookie + access token), on this same-site request."""
    tokens = await service.complete(db, request.cookies.get(service.HANDOFF_COOKIE), _client_info(request))
    _clear(response, service.HANDOFF_COOKIE)
    _set_session_cookies(response, tokens.refresh_token, persistent=tokens.persistent)
    return _access_response(tokens.access_token)


@router.get("/google/signup", response_model=GooglePrefill)
async def signup_prefill(request: Request, db: AsyncSession = Depends(get_db)):
    flow = await service.signup_ticket(db, request.cookies.get(service.SIGNUP_COOKIE))
    return GooglePrefill(email=flow.email, given_name=flow.given_name, family_name=flow.family_name)


@router.post("/google/signup", response_model=AccessTokenResponse, status_code=status.HTTP_201_CREATED)
async def signup(body: GoogleSignupRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    """A patient account, or a doctor application awaiting review, for the verified
    Google identity in the ticket cookie. Never staff or admin."""
    tokens = await service.signup(db, request.cookies.get(service.SIGNUP_COOKIE), body, _client_info(request))
    _clear(response, service.SIGNUP_COOKIE)
    _set_session_cookies(response, tokens.refresh_token, persistent=tokens.persistent)
    return _access_response(tokens.access_token)


@router.get("/google/identity", response_model=GoogleIdentityStatus)
async def identity(principal: Principal = Depends(get_current_principal), db: AsyncSession = Depends(get_db)):
    return GoogleIdentityStatus(**await service.status(db, principal))


@router.post("/google/link", response_model=GoogleLinkStart, dependencies=[_limited])
async def link(
    body: Reauthentication,
    request: Request,
    response: Response,
    principal: Principal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
):
    """Start linking: the page then sends the browser to `authorize_url`."""
    verify_csrf(request)
    url, binder = await service.begin_link(
        db, principal, request.cookies.get(settings.refresh_cookie_name), body.current_password
    )
    _set(response, service.BINDER_COOKIE, binder, settings.google_oauth_flow_minutes * 60)
    return GoogleLinkStart(authorize_url=url)


@router.post("/google/unlink", status_code=status.HTTP_204_NO_CONTENT)
async def unlink(
    body: Reauthentication,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
):
    verify_csrf(request)
    await service.unlink(
        db, principal, request.cookies.get(settings.refresh_cookie_name), body.current_password,
        request.client.host if request.client else None,
    )
