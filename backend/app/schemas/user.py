import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import LoginEmail


class UserResponse(BaseModel):
    id: uuid.UUID
    name: str
    email: EmailStr
    is_active: bool
    roles: list[str]
    created_at: datetime


class MeResponse(UserResponse):
    permissions: list[str]
    doctor_id: uuid.UUID | None = None
    patient_id: uuid.UUID | None = None


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
    name: str | None = Field(default=None, min_length=1, max_length=100)
    email: LoginEmail | None = None


class RolesUpdate(BaseModel):
    roles: list[str] = Field(min_length=1)


class RoleResponse(BaseModel):
    code: str
    name: str
    description: str | None
    permissions: list[str]
