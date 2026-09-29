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

    # Patients
    patient_read_own = "patient:read_own"
    patient_update_own = "patient:update_own"
    patient_read_assigned = "patient:read_assigned"
    patient_read_any = "patient:read_any"
    patient_create = "patient:create"
    patient_update = "patient:update"
    patient_deactivate = "patient:deactivate"

    # Schedules
    availability_read = "availability:read"
    schedule_read = "schedule:read"
    schedule_manage_own = "schedule:manage_own"
    schedule_manage_any = "schedule:manage_any"

    # Appointments
    appointment_read_own = "appointment:read_own"
    appointment_read_assigned = "appointment:read_assigned"
    appointment_read_any = "appointment:read_any"
    appointment_create_own = "appointment:create_own"
    appointment_create = "appointment:create"
    appointment_confirm_own = "appointment:confirm_own"
    appointment_cancel_own = "appointment:cancel_own"
    appointment_reschedule_own = "appointment:reschedule_own"
    appointment_cancel_assigned = "appointment:cancel_assigned"
    appointment_cancel_any = "appointment:cancel_any"
    appointment_manage = "appointment:manage"
    appointment_check_in = "appointment:check_in"
    appointment_consult = "appointment:consult"


@dataclass(frozen=True)
class Principal:
    """Who is calling, and what they may do. Passed into services."""

    user: User
    roles: frozenset[str]
    permissions: frozenset[str]
    doctor_id: uuid.UUID | None = None
    patient_id: uuid.UUID | None = None

    @property
    def user_id(self) -> uuid.UUID:
        return self.user.id

    def has(self, *perms: Perm) -> bool:
        return all(p in self.permissions for p in perms)

    def has_any(self, *perms: Perm) -> bool:
        return any(p in self.permissions for p in perms)
