"""Role and permission vocabulary, plus the authenticated principal.

Permissions are a closed, developer-owned set: every value here is seeded into
the ``permissions`` table by a migration, and code checks them by these names.
Roles are data (admin-composable); ``RoleCode`` only names the built-in ones
that the code itself needs to refer to (e.g. "self-registration grants patient").
"""

import uuid
from dataclasses import dataclass
from enum import StrEnum

from app.models.user import User


class RoleCode(StrEnum):
    patient = "patient"
    doctor = "doctor"
    receptionist = "receptionist"
    admin = "admin"


class Perm(StrEnum):
    # Users & roles
    user_read = "user:read"
    user_create = "user:create"
    user_update = "user:update"
    user_deactivate = "user:deactivate"
    user_assign_role = "user:assign_role"
    role_read = "role:read"

    # Departments
    department_manage = "department:manage"

    # Doctors
    doctor_read = "doctor:read"
    doctor_create = "doctor:create"
    doctor_update = "doctor:update"
    doctor_deactivate = "doctor:deactivate"
    doctor_update_own = "doctor:update_own"


@dataclass(frozen=True)
class Principal:
    """Who is calling, and what they may do. Passed into services."""

    user: User
    roles: frozenset[str]
    permissions: frozenset[str]
    doctor_id: uuid.UUID | None = None

    @property
    def user_id(self) -> uuid.UUID:
        return self.user.id

    def has(self, *perms: Perm) -> bool:
        return all(p in self.permissions for p in perms)

    def has_any(self, *perms: Perm) -> bool:
        return any(p in self.permissions for p in perms)
