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
    # Self-registered as a doctor, credentials not yet verified. Holds no
    # clinical permission: only their own application (D77).
    doctor_applicant = "doctor_applicant"
    # Works for specific doctors only, invited by each of them (D131). Unlike the
    # clinic-wide `receptionist` (front desk), holds no patient or appointment
    # permission of its own: every such right comes from an active assignment
    # to the doctor named in the request (see Delegation).
    doctor_receptionist = "doctor_receptionist"


class Perm(StrEnum):
    # Users & roles
    user_read = "user:read"
    user_create = "user:create"
    user_update = "user:update"
    user_deactivate = "user:deactivate"
    user_assign_role = "user:assign_role"
    role_read = "role:read"
    # Invite administrators and manage pending invitations (D87). The only
    # way the admin role is granted after the first administrator.
    admin_invitation_manage = "admin_invitation:manage"

    # Departments
    department_manage = "department:manage"

    # The clinic's own details (name, contact), D86
    settings_manage = "settings:manage"

    # Doctors
    doctor_read = "doctor:read"
    doctor_create = "doctor:create"
    doctor_update = "doctor:update"
    doctor_deactivate = "doctor:deactivate"
    doctor_update_own = "doctor:update_own"
    # A doctor invites, scopes and removes their own receptionists (D131).
    receptionist_manage_own = "receptionist:manage_own"

    # Doctor applications: self-registration, then credential review
    doctor_application_manage_own = "doctor_application:manage_own"
    doctor_application_review = "doctor_application:review"

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
    # Book outside the normal rules (custom time or duration, authorized double
    # booking), always with a reason and an audit entry (D117). Staff only.
    appointment_override = "appointment:override"

    # Document
    document_read_own="document:read_own"
    document_upload_own="document:upload_own"
    document_retract_own="document:retract_own"
    document_read_assigned="document:read_assigned"
    document_upload_assigned="document:upload_assigned"
    document_retract_assigned="document:retract_assigned"

    # Allergies, diagnoses and medications (D112). Patients report their own
    # allergies and medicines; treating doctors record all three.
    health_record_read_own = "health_record:read_own"
    health_record_report_own = "health_record:report_own"
    health_record_read_assigned = "health_record:read_assigned"
    health_record_write_assigned = "health_record:write_assigned"


class AssignmentPermission(StrEnum):
    """What one doctor lets one of their receptionists do (D131). Stored on the
    assignment, so the same person can hold different rights per doctor.
    Nothing here reaches clinical content: documents, diagnoses, medications,
    allergies and consultations are never delegated."""

    appointments_view = "appointments_view"
    appointments_create = "appointments_create"
    appointments_update = "appointments_update"
    appointments_cancel = "appointments_cancel"
    patients_view = "patients_view"
    patients_create = "patients_create"
    patients_update = "patients_update"


def normalize_assignment_permissions(values) -> frozenset[AssignmentPermission]:
    """Unknown names raise ValueError. Acting on something implies seeing it:
    any appointment right adds appointments_view; any patient right, and
    booking (which needs a patient), add patients_view."""
    perms = {AssignmentPermission(v) for v in values}
    A = AssignmentPermission
    if perms & {A.appointments_create, A.appointments_update, A.appointments_cancel}:
        perms.add(A.appointments_view)
    if perms & {A.patients_create, A.patients_update, A.appointments_create}:
        perms.add(A.patients_view)
    return frozenset(perms)


# The existing permission each assignment right stands for while the receptionist
# acts for that doctor. These are safe to lend only because every use of them is
# row-scoped through services/access.py, which limits a delegated caller to the
# one doctor's appointments and patients (and services that take a doctor id
# from the request check it against the delegation).
DELEGATED_PERMS: dict[AssignmentPermission, tuple[str, ...]] = {
    AssignmentPermission.appointments_view: ("appointment:read_assigned",),
    AssignmentPermission.appointments_create: ("appointment:create",),
    AssignmentPermission.appointments_update: ("appointment:manage",),
    AssignmentPermission.appointments_cancel: ("appointment:cancel_any",),
    AssignmentPermission.patients_view: ("patient:read_assigned",),
    AssignmentPermission.patients_create: ("patient:create",),
    AssignmentPermission.patients_update: ("patient:update",),
}


@dataclass(frozen=True)
class Delegation:
    """This request acts for one doctor through an ACTIVE assignment, verified
    against the database on every request (D131)."""

    doctor_id: uuid.UUID
    assignment_id: uuid.UUID
    permissions: frozenset[AssignmentPermission]

    def allows(self, permission: AssignmentPermission) -> bool:
        return permission in self.permissions


@dataclass(frozen=True)
class Principal:
    """Who is calling, and what they may do. Passed into services."""

    user: User
    roles: frozenset[str]
    permissions: frozenset[str]
    doctor_id: uuid.UUID | None = None
    patient_id: uuid.UUID | None = None
    # Set only for a doctor_receptionist acting for an assigned doctor (D131).
    # Deliberately separate from doctor_id: a receptionist is never "the doctor".
    delegation: Delegation | None = None

    @property
    def user_id(self) -> uuid.UUID:
        return self.user.id

    def has(self, *perms: Perm) -> bool:
        return all(p in self.permissions for p in perms)

    def has_any(self, *perms: Perm) -> bool:
        return any(p in self.permissions for p in perms)
