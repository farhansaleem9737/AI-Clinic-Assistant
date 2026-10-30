import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.schemas.common import LoginEmail, clean_name

Name = Annotated[str, Field(min_length=1, max_length=100), AfterValidator(clean_name)]
# Tokens are 43 URL-safe characters; anything far off is not worth a lookup.
Token = Annotated[str, Field(min_length=20, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]


class _Strict(BaseModel):
    # Unknown fields are an error, not silently dropped: a request that tries
    # to set "roles" or "is_admin" here fails loudly.
    model_config = ConfigDict(extra="forbid")


class InvitationCreate(_Strict):
    email: LoginEmail
    name: Name | None = None
    # The only role this workflow grants; anything else is a validation error.
    role: Literal["admin"] = "admin"
    # Re-entered by the inviting administrator.
    current_password: str = Field(min_length=1, max_length=128)


class InvitationRead(BaseModel):
    id: uuid.UUID
    email: str
    name: str | None
    role: str
    status: Literal["pending", "accepted", "revoked", "expired"]
    invited_by_name: str | None
    created_at: datetime
    expires_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None
    # sent | outbox | failed | not_configured | None (never attempted)
    delivery_status: str | None
    last_sent_at: datetime | None


class TokenBody(_Strict):
    token: Token


class InvitationPreviewRead(BaseModel):
    email: str
    name: str | None
    status: Literal["pending", "accepted", "revoked", "expired"]
    expires_at: datetime
    # Whether to ask the visitor to sign in (existing account) or to set a
    # password (new account).
    account_exists: bool


class AcceptNewAccount(_Strict):
    token: Token
    name: Name | None = None
    password: str = Field(min_length=8, max_length=128)


class AcceptExistingAccount(_Strict):
    token: Token
    current_password: str = Field(min_length=1, max_length=128)


class Reauthentication(_Strict):
    current_password: str = Field(min_length=1, max_length=128)
