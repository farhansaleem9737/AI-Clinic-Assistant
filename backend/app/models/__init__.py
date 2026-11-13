"""Import every model so Base.metadata is complete (Alembic autogenerate, tests)."""

from app.models.admin import AdminInvitation, AuditLog
from app.models.ai import AiConversation, AiDocument, AiMessage, AiUsage
from app.models.appointment import Appointment, AppointmentStatusHistory
from app.models.catalog import (
    DepartmentSpecialization,
    DoctorSpecialization,
    MedicalTopic,
    MedicalTopicSpecialization,
    Specialization,
)
from app.models.department import Department
from app.models.doctor import Doctor, DoctorEducation, DoctorExperience
from app.models.document_extraction import DocumentExtraction
from app.models.email import EmailOutbox
from app.models.email_verification import EmailVerificationCode
from app.models.health_record import PatientAllergy, PatientDiagnosis, PatientMedication
from app.models.doctor_application import DoctorApplication, DoctorApplicationDocument
from app.models.notification import ClinicSettings, FollowUp, Notification, NotificationPreference
from app.models.oauth import OAuthFlow, OAuthIdentity
from app.models.doctor_receptionist import DoctorReceptionist, ReceptionistInvitation
from app.models.password_reset import PasswordResetToken
from app.models.patient import Patient
from app.models.rbac import Permission, Role, RolePermission, UserRole
from app.models.refresh_token import RefreshToken
from app.models.schedule import ScheduleException, ScheduleTemplate
from app.models.scheduling import QueueEntry, SchedulingPolicy, TokenCounter
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
    "DepartmentSpecialization",
    "Doctor",
    "DoctorApplication",
    "DoctorApplicationDocument",
    "DoctorEducation",
    "DoctorExperience",
    "DoctorSpecialization",
    "DocumentExtraction",
    "MedicalTopic",
    "MedicalTopicSpecialization",
    "EmailOutbox",
    "EmailVerificationCode",
    "FollowUp",
    "NotificationPreference",
    "Patient",
    "PatientAllergy",
    "PatientDiagnosis",
    "PatientMedication",
    "Permission",
    "RefreshToken",
    "OAuthFlow",
    "OAuthIdentity",
    "PasswordResetToken",
    "DoctorReceptionist",
    "ReceptionistInvitation",
    "Role",
    "RolePermission",
    "ScheduleException",
    "ScheduleTemplate",
    "SchedulingPolicy",
    "Specialization",
    "QueueEntry",
    "TokenCounter",
    "User",
    "UserRole",
]
