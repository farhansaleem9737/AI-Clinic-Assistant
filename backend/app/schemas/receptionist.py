"""Doctor's receptionists (D131): requests and responses."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.permissions import AssignmentPermission
from app.schemas.admin import Name, Token, _Strict
from app.schemas.common import LoginEmail

# Unknown names fail validation here; the service normalizes what remains.
Permissions = list[AssignmentPermission]


class ReceptionistInvitationCreate(_Strict):
    email: LoginEmail
    name: Name | None = None
    permissions: Permissions = Field(default_factory=list, max_length=len(AssignmentPermission))


class ReceptionistInvitationRead(BaseModel):
    id: uuid.UUID
    email: str
    name: str | None
    permissions: list[str]
    status: Literal["pending", "accepted", "revoked", "expired"]
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    # What the email provider said: sent, outbox (development), failed, not_configured.
    delivery_status: str | None


class AssignmentRead(BaseModel):
    """One of this doctor's receptionists, as this doctor has set them up."""

    id: uuid.UUID
    receptionist_user_id: uuid.UUID
    name: str
    email: str
    account_active: bool
    status: Literal["active", "suspended", "revoked"]
    permissions: list[str]
    created_at: datetime
    updated_at: datetime


class AssignmentPermissionsUpdate(_Strict):
    permissions: Permissions = Field(max_length=len(AssignmentPermission))


class AssignmentStatusUpdate(_Strict):
    # Removing is DELETE: it cannot be undone by setting a status.
    status: Literal["active", "suspended"]


class AssignedDoctorRead(BaseModel):
    """A doctor this receptionist works for, and what that doctor allows."""

    assignment_id: uuid.UUID
    doctor_id: uuid.UUID
    name: str
    title: str | None
    specialization: str
    department: str
    status: Literal["active", "suspended"]
    permissions: list[str]


class ReceptionistInvitationPreviewRead(BaseModel):
    email: str
    name: str | None
    doctor_name: str
    status: Literal["pending", "accepted", "revoked", "expired"]
    expires_at: datetime
    account_exists: bool
    permissions: list[str]


class AcceptNewReceptionistAccount(_Strict):
    token: Token
    name: Name | None = None
    password: str = Field(min_length=8, max_length=128)


class AcceptWithExistingAccount(_Strict):
    token: Token
    current_password: str = Field(min_length=1, max_length=128)


class InvitationToken(_Strict):
    token: Token
