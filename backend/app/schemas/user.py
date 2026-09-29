import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class UserCreate(BaseModel):
    """Self-registration body.

    There is deliberately no ``role`` field: a client choosing its own role
    let anyone register as admin. Any ``role`` sent is ignored and the account
    is always created as a patient; staff accounts are created by an admin.
    """

    name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


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


class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(max_length=128)


class AccessTokenResponse(BaseModel):
    """The refresh token never appears in a body: it travels only in an
    HttpOnly cookie that JavaScript cannot read."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int
