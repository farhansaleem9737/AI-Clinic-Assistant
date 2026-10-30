"""Import every model so Base.metadata is complete (Alembic autogenerate, tests)."""

from app.models.admin import AdminInvitation, AuditLog
from app.models.ai import AiConversation, AiDocument, AiMessage, AiUsage
from app.models.appointment import Appointment, AppointmentStatusHistory
from app.models.department import Department
from app.models.doctor import Doctor, DoctorEducation, DoctorExperience
from app.models.doctor_application import DoctorApplication, DoctorApplicationDocument
from app.models.notification import ClinicSettings, Notification
from app.models.patient import Patient
from app.models.rbac import Permission, Role, RolePermission, UserRole
from app.models.refresh_token import RefreshToken
from app.models.schedule import ScheduleException, ScheduleTemplate
from app.models.user import User
from app.models.patient_document import PatientDocument
from app.models.stored_file import StoredFile

__all__ = [
    "AiConversation",
    "AiDocument",
    "AiMessage",
    "AiUsage",
    "AdminInvitation",
    "AuditLog",
    "Appointment",
    "AppointmentStatusHistory",
    "Department",
    "Doctor",
    "DoctorApplication",
    "DoctorApplicationDocument",
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
