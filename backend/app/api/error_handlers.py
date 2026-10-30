"""Translate every error into one response shape.

    {"error": {"code": "...", "message": "...", "details": {...}, "request_id": "..."}}

Domain exceptions get their status code here, keeping services free of HTTP.
Unexpected errors are logged in full but reach the client only as a generic 500
with the request id, never as a SQL or driver message.
"""

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import (
    AuthenticationError,
    BusinessRuleError,
    ConflictError,
    DomainError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitedError,
    StorageUnavailableError,
    FileTooLargeError,
    UnsupportedFileError
)
from app.core.logging import request_id_var
from app.services.ai.provider import AiUnavailableError

logger = logging.getLogger(__name__)

_STATUS_BY_EXCEPTION: dict[type[DomainError], int] = {
    NotFoundError: status.HTTP_404_NOT_FOUND,
    ConflictError: status.HTTP_409_CONFLICT,
    BusinessRuleError: status.HTTP_400_BAD_REQUEST,
    AuthenticationError: status.HTTP_401_UNAUTHORIZED,
    PermissionDeniedError: status.HTTP_403_FORBIDDEN,
    RateLimitedError: status.HTTP_429_TOO_MANY_REQUESTS,
    AiUnavailableError: status.HTTP_503_SERVICE_UNAVAILABLE,
    StorageUnavailableError: status.HTTP_503_SERVICE_UNAVAILABLE,
    FileTooLargeError: status.HTTP_413_CONTENT_TOO_LARGE,
    UnsupportedFileError:status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
}

_CODE_BY_HTTP_STATUS = {
    400: "BAD_REQUEST",
    401: "AUTHENTICATION_FAILED",
    403: "PERMISSION_DENIED",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
}


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
                "request_id": request_id_var.get(),
            }
        },
        headers=headers,
    )


def _status_for(exc: DomainError) -> int:
    for exc_type in type(exc).__mro__:
        if exc_type in _STATUS_BY_EXCEPTION:
            return _STATUS_BY_EXCEPTION[exc_type]
    return status.HTTP_400_BAD_REQUEST


async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    headers = {"WWW-Authenticate": "Bearer"} if isinstance(exc, AuthenticationError) else None
    return error_response(_status_for(exc), exc.code, exc.message, exc.details, headers)


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Pydantic's error entries include the rejected "input" value, which for a
    # login or registration body would echo the password back. Keep only the
    # location, message and type.
    errors = [
        {"loc": list(err.get("loc", ())), "msg": err.get("msg"), "type": err.get("type")}
        for err in exc.errors()
    ]
    return error_response(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "VALIDATION_ERROR",
        "Request validation failed",
        {"errors": errors},
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    # Framework-raised errors: unknown route (404), wrong method (405), etc.
    code = _CODE_BY_HTTP_STATUS.get(exc.status_code, "HTTP_ERROR")
    message = exc.detail if isinstance(exc.detail, str) else "Request failed"
    return error_response(exc.status_code, code, message, headers=getattr(exc, "headers", None))


async def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
    # A unique/foreign-key violation that a service did not pre-check (usually
    # two concurrent requests). The constraint name is enough for debugging;
    # the driver message can contain row values, so it is not logged.
    constraint = getattr(getattr(exc.orig, "__cause__", None), "constraint_name", None)
    logger.warning("integrity_error", extra={"constraint": constraint, "path": request.url.path})
    return error_response(
        status.HTTP_409_CONFLICT,
        "CONFLICT",
        "The request conflicts with existing data",
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled_error", extra={"path": request.url.path})
    return error_response(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "INTERNAL_ERROR",
        "An unexpected error occurred",
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, domain_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(IntegrityError, integrity_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
