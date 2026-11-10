import secrets

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import get_current_principal
from app.api.error_handlers import error_response
from app.core.config import settings
from app.core.exceptions import AuthenticationError, PermissionDeniedError
from app.core.permissions import Principal
from app.core.rate_limit import rate_limit
from app.core.security import generate_csrf_token
from app.core.storage import Storage, get_optional_storage
from app.db.session import get_db
from app.schemas.patient import PatientRegistration
from app.schemas.registration import RegistrationRequest, VerificationCodeRequest
from app.schemas.user import (
    AccessTokenResponse,
    MeResponse,
    MessageResponse,
    PasswordChange,
    PasswordChangeStatus,
    PasswordReset,
    PasswordResetRequest,
    PasswordResetToken,
    UserLogin,
    UserResponse,
)
from app.models.doctor import Doctor
from app.models.patient import Patient
from app.services import (
    auth_service,
    doctor_application_service,
    email_verification_service,
    file_service,
    password_reset_service,
    patient_service,
    rbac_service,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_info(request: Request) -> auth_service.ClientInfo:
    return auth_service.ClientInfo(
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )


def _set_session_cookies(response: Response, refresh_token: str, *, persistent: bool) -> None:
    # "Remember me" off: no Max-Age, so the browser drops both cookies when it
    # closes. On: they last as long as the refresh token does.
    max_age = settings.refresh_token_expire_days * 24 * 3600 if persistent else None
    # HttpOnly: JavaScript (and therefore XSS) can never read it. Path-scoped:
    # the browser sends it only to /auth/*, not with every API call.
    response.set_cookie(
        settings.refresh_cookie_name,
        refresh_token,
        max_age=max_age,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="strict",
        path=settings.auth_cookie_path,
    )
    # Double-submit CSRF token: readable by our frontend, which echoes it in a
    # header. A cross-site page can make the browser send cookies but can
    # neither read this one nor set the header.
    response.set_cookie(
        settings.csrf_cookie_name,
        generate_csrf_token(),
        max_age=max_age,
        httponly=False,
        secure=settings.secure_cookies,
        samesite="strict",
        path="/",
    )


def _clear_session_cookies(response: Response) -> None:
    for name, path, httponly in (
        (settings.refresh_cookie_name, settings.auth_cookie_path, True),
        (settings.csrf_cookie_name, "/", False),
    ):
        response.delete_cookie(
            name, path=path, httponly=httponly, secure=settings.secure_cookies, samesite="strict"
        )


def verify_csrf(request: Request) -> None:
    """Required on every endpoint that authenticates with the refresh cookie."""
    cookie = request.cookies.get(settings.csrf_cookie_name)
    header = request.headers.get(settings.csrf_header_name)
    if not cookie or not header or not secrets.compare_digest(cookie, header):
        raise PermissionDeniedError("Missing or invalid CSRF token", code="CSRF_FAILED")


def _access_response(access_token: str) -> AccessTokenResponse:
    return AccessTokenResponse(access_token=access_token, expires_in=settings.access_token_expire_minutes * 60)


@router.post(
    "/register/verification-code",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(rate_limit("verification_code", lambda: settings.verification_code_requests_per_minute))],
)
async def send_verification_code(body: VerificationCodeRequest, db: AsyncSession = Depends(get_db)):
    """Email a six-digit code that /register needs, proving the address is the user's.
    409 EMAIL_TAKEN for an address with an account; 429 while a recent code is still fresh."""
    await email_verification_service.send_code(db, body.email)


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegistrationRequest, db: AsyncSession = Depends(get_db)):
    """Self-registration as a patient (login + patient profile) or as a
    doctor applicant (login + pending application, no clinical access until
    an administrator approves it, D77). `account_type` defaults to "patient";
    any other value is rejected. Any "role" in the body is ignored; staff
    accounts are created by an admin. No session is issued here. With
    EMAIL_VERIFICATION_REQUIRED, `verification_code` must be the code emailed
    by /register/verification-code; it is used up by the registration."""
    if settings.email_verification_required:
        await email_verification_service.consume(db, body.email, body.verification_code)
    if isinstance(body, PatientRegistration):
        user = await patient_service.register_self(db, body)
    else:
        user = await doctor_application_service.register(db, body)
    return UserResponse(
        id=user.id,
        name=user.name,
        email=user.email,
        is_active=user.is_active,
        roles=sorted(await rbac_service.role_codes_for(db, user.id)),
        created_at=user.created_at,
    )


@router.post("/login", response_model=AccessTokenResponse)
async def login(credentials: UserLogin, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    tokens = await auth_service.login(
        db, credentials.email, credentials.password, _client_info(request), remember_me=credentials.remember_me
    )
    _set_session_cookies(response, tokens.refresh_token, persistent=tokens.persistent)
    return _access_response(tokens.access_token)


@router.post(
    "/refresh",
    response_model=AccessTokenResponse,
    responses={401: {"description": "No valid session"}, 403: {"description": "CSRF check failed"}},
)
async def refresh(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    raw = request.cookies.get(settings.refresh_cookie_name)
    if not raw:
        # Checked before CSRF: a visitor with no session at all gets a plain 401.
        raise AuthenticationError("No session", code="INVALID_REFRESH_TOKEN")
    verify_csrf(request)
    try:
        tokens = await auth_service.refresh(db, raw, _client_info(request))
    except AuthenticationError as exc:
        # A dead session cookie is useless: tell the browser to drop it. Built
        # here because a raised exception discards cookies set on `response`.
        failed = error_response(status.HTTP_401_UNAUTHORIZED, exc.code, exc.message)
        _clear_session_cookies(failed)
        return failed
    if tokens.refresh_token is not None:
        _set_session_cookies(response, tokens.refresh_token, persistent=tokens.persistent)
    return _access_response(tokens.access_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    raw = request.cookies.get(settings.refresh_cookie_name)
    if raw:
        verify_csrf(request)
        await auth_service.logout(db, raw)
    _clear_session_cookies(response)


# The password of the signed-in user (D116). Both endpoints read this browser's own
# session from the refresh cookie (sent only to /auth/*), so they also need the CSRF header.
_password_attempts = Depends(rate_limit("password_change", lambda: settings.password_change_attempts_per_minute))


@router.get("/password", response_model=PasswordChangeStatus)
async def password_change_status(
    request: Request, principal: Principal = Depends(get_current_principal), db: AsyncSession = Depends(get_db)
):
    """Whether changing the password needs the current one (it does unless this
    session signed in within PASSWORD_CHANGE_RECENT_AUTH_MINUTES)."""
    raw = request.cookies.get(settings.refresh_cookie_name)
    return PasswordChangeStatus(
        current_password_required=await auth_service.password_change_needs_current(db, principal.user_id, raw)
    )


@router.post("/password", response_model=AccessTokenResponse, dependencies=[_password_attempts])
async def change_password(
    body: PasswordChange,
    request: Request,
    response: Response,
    principal: Principal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
):
    """Change the signed-in user's password. Every other session ends; this
    browser receives a new session (cookies and access token) and stays signed in."""
    verify_csrf(request)
    tokens = await auth_service.change_password(
        db, principal.user_id, request.cookies.get(settings.refresh_cookie_name),
        new_password=body.new_password, current_password=body.current_password, client=_client_info(request),
    )
    _set_session_cookies(response, tokens.refresh_token, persistent=tokens.persistent)
    return _access_response(tokens.access_token)


# Forgot password (D126). Public; no session, so no CSRF cookie to check.
RESET_REQUESTED = "If an account exists for this email, you'll receive a password reset link shortly."
PASSWORD_RESET_DONE = "Your password has been reset. Sign in with your new password."
_reset_requests = Depends(rate_limit("password_reset_request", lambda: settings.password_reset_requests_per_minute))
_reset_attempts = Depends(rate_limit("password_reset", lambda: settings.password_reset_attempts_per_minute))


@router.post("/forgot-password", response_model=MessageResponse, dependencies=[_reset_requests])
async def forgot_password(
    body: PasswordResetRequest, request: Request, background: BackgroundTasks, db: AsyncSession = Depends(get_db)
):
    """Email a one-time reset link (valid PASSWORD_RESET_TOKEN_MINUTES) to an active
    account. The answer, and its timing, are the same whether or not the address
    has an account: the email goes out after the response."""
    pending = await password_reset_service.request_reset(db, body.email, ip_address=_client_info(request).ip_address)
    if pending is not None:
        background.add_task(password_reset_service.send, pending)
    return MessageResponse(message=RESET_REQUESTED)


@router.post("/reset-password/check", status_code=status.HTTP_204_NO_CONTENT, dependencies=[_reset_attempts])
async def check_reset_link(body: PasswordResetToken, db: AsyncSession = Depends(get_db)):
    """204 if the link can still be used; otherwise 400 RESET_TOKEN_INVALID, _EXPIRED or _USED.
    POST so the token never appears in a URL."""
    await password_reset_service.check(db, body.token)


@router.post("/reset-password", response_model=MessageResponse, dependencies=[_reset_attempts])
async def reset_password(body: PasswordReset, request: Request, db: AsyncSession = Depends(get_db)):
    """Set a new password with an emailed link. The link is used up; every session
    of the account ends; nobody is signed in (the user signs in with the new password)."""
    await password_reset_service.reset_password(
        db, body.token, body.new_password, ip_address=_client_info(request).ip_address
    )
    return MessageResponse(message=PASSWORD_RESET_DONE)


@router.get("/me", response_model=MeResponse)
async def me(
    principal: Principal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
    storage: Storage | None = Depends(get_optional_storage),
):
    user = principal.user
    # The caller's own profile photo, for the header avatar.
    photo = None
    if principal.doctor_id is not None:
        photo = (await db.get(Doctor, principal.doctor_id)).photo
    elif principal.patient_id is not None:
        photo = (await db.get(Patient, principal.patient_id)).photo
    return MeResponse(
        id=user.id,
        name=user.name,
        email=user.email,
        is_active=user.is_active,
        roles=sorted(principal.roles),
        permissions=sorted(principal.permissions),
        created_at=user.created_at,
        doctor_id=principal.doctor_id,
        patient_id=principal.patient_id,
        photo_url=file_service.photo_url(storage, photo),
    )
