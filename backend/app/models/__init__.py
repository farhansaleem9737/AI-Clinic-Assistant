"""Import every model so Base.metadata is complete (Alembic autogenerate, tests)."""

from app.models.appointment import Appointment, AppointmentStatusHistory
from app.models.department import Department
from app.models.doctor import Doctor, DoctorEducation, DoctorExperience
from app.models.patient import Patient
from app.models.rbac import Permission, Role, RolePermission, UserRole
from app.models.refresh_token import RefreshToken
from app.models.schedule import ScheduleException, ScheduleTemplate
from app.models.user import User
from app.models.patient_document import PatientDocument
from app.models.stored_file import StoredFile

__all__ = [
    "Appointment",
    "AppointmentStatusHistory",
    "Department",
    "Doctor",
    "DoctorEducation",
    "DoctorExperience",
    "Patient",
    "Permission",
    "RefreshToken",
    "Role",
    "RolePermission",
    "ScheduleException",
    "ScheduleTemplate",
    "User",
    "UserRole",
]
