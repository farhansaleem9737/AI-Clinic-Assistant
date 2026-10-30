import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.common import LoginEmail


class UserResponse(BaseModel):
    id: uuid.UUID
    name: str
    email: EmailStr
    is_active: bool
    roles: list[str]
    created_at: datetime


class AdminUserRead(UserResponse):
    """A user as listed in Admin > Users. Phone and photo come from the
    linked doctor or patient profile, when there is one."""

    phone: str | None = None
    photo_url: str | None = None
    doctor_id: uuid.UUID | None = None
    patient_id: uuid.UUID | None = None


class BulkStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    is_active: bool


class BulkStatusResult(BaseModel):
    user_id: uuid.UUID
    ok: bool
    code: str | None = None
    message: str | None = None


class MeResponse(UserResponse):
    permissions: list[str]
    doctor_id: uuid.UUID | None = None
    patient_id: uuid.UUID | None = None
    # Short-lived link to the user's own profile photo (doctor or patient), if any.
    photo_url: str | None = None


class UserLogin(BaseModel):
    email: LoginEmail
    password: str = Field(max_length=128)
    # Keep the session after the browser closes. Off by default: a shared
    # clinic computer should not stay signed in.
    remember_me: bool = False


class AccessTokenResponse(BaseModel):
    """The refresh token never appears in a body: it travels only in an
    HttpOnly cookie that JavaScript cannot read."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int


class AccountCreate(BaseModel):
    """Admin-created account. Roles are granted in the same transaction."""

    name: str = Field(min_length=1, max_length=100)
    email: LoginEmail
    password: str = Field(min_length=8, max_length=128)
    roles: list[str] = Field(min_length=1)


class UserUpdate(BaseModel):
    # Only these fields; anything else ("roles", "is_active", ...) is a 422.
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=100)
    email: LoginEmail | None = None


class RolesUpdate(BaseModel):
    roles: list[str] = Field(min_length=1)


class RoleResponse(BaseModel):
    code: str
    name: str
    description: str | None
    permissions: list[str]
