"""Domain exceptions.

Services raise these instead of ``HTTPException`` so the same business logic
can later be called from places that are not HTTP requests (background jobs,
AI tools). Translating an exception into a status code is the API layer's job:
see ``app/api/error_handlers.py``.
"""

from typing import Any


class DomainError(Exception):
    """Base class for every expected, client-facing application error."""

    code = "DOMAIN_ERROR"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        self.details = details or {}


class NotFoundError(DomainError):
    code = "NOT_FOUND"


class ConflictError(DomainError):
    """The request clashes with existing state (duplicate, already exists)."""

    code = "CONFLICT"


class BusinessRuleError(DomainError):
    """Well-formed request that breaks a business rule."""

    code = "BUSINESS_RULE_VIOLATION"


class AuthenticationError(DomainError):
    """Caller's identity could not be established."""

    code = "AUTHENTICATION_FAILED"


class PermissionDeniedError(DomainError):
    """Caller is known but not allowed to do this."""

    code = "PERMISSION_DENIED"
