import secrets

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import get_current_principal
from app.api.error_handlers import error_response
from app.core.config import settings
from app.core.exceptions import AuthenticationError, PermissionDeniedError
from app.core.permissions import Principal
from app.core.security import generate_csrf_token
from app.core.storage import Storage, get_optional_storage
from app.db.session import get_db
from app.schemas.patient import PatientRegistration
from app.schemas.user import AccessTokenResponse, MeResponse, UserLogin, UserResponse
from app.models.doctor import Doctor
from app.models.patient import Patient
from app.services import auth_service, file_service, patient_service, rbac_service

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


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(body: PatientRegistration, db: AsyncSession = Depends(get_db)):
    """Self-registration always creates a patient (login + patient profile).
    Any "role" in the body is ignored; staff accounts are created by an admin."""
    user = await patient_service.register_self(db, body)
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
