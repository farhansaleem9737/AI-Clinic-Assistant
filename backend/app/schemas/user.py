from pydantic import BaseModel, ConfigDict, EmailStr
from datetime import datetime


class UserCreate(BaseModel):
    """Self-registration body.

    There is deliberately no ``role`` field: a client choosing its own role
    let anyone register as admin. Any ``role`` sent is ignored and the account
    is always created as a patient; staff accounts are created by an admin.
    """

    name: str
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: int
    name: str
    email: EmailStr
    role: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)  # lets Pydantic read from SQLAlchemy objects

class UserLogin(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"