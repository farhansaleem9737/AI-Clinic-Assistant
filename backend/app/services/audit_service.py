"""Audit trail for sensitive actions (D87).

``record`` adds a row in the caller's transaction and never commits, so the
audit entry exists exactly when the action it describes does.
"""

import uuid
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin import AuditLog

# Never recorded, whatever a caller passes in ``details``.
_SECRET_KEYS = {"password", "password_hash", "token", "token_hash", "access_token", "refresh_token"}


class AuditAction(StrEnum):
    admin_bootstrapped = "admin.bootstrapped"
    admin_password_reset = "admin.password_reset"
    admin_invited = "admin.invitation_created"
    admin_invitation_resent = "admin.invitation_resent"
    admin_invitation_revoked = "admin.invitation_revoked"
    admin_invitation_accepted = "admin.invitation_accepted"
    admin_role_granted = "admin.role_granted"
    admin_role_revoked = "admin.role_revoked"
    user_roles_changed = "user.roles_changed"
    user_deactivated = "user.deactivated"
    user_activated = "user.activated"
    patient_activated = "patient.activated"
    patient_deactivated = "patient.deactivated"
    patient_identity_changed = "patient.identity_changed"
    doctor_created = "doctor.created"
    doctor_activated = "doctor.activated"
    doctor_deactivated = "doctor.deactivated"
    doctor_department_changed = "doctor.department_changed"
    doctor_application_approved = "doctor_application.approved"
    doctor_application_rejected = "doctor_application.rejected"


def record(
    db: AsyncSession,
    action: AuditAction,
    *,
    actor_id: uuid.UUID | None,
    target_type: str,
    target_id: uuid.UUID | str | None,
    ip_address: str | None = None,
    details: dict | None = None,
) -> AuditLog:
    clean = {k: v for k, v in (details or {}).items() if k not in _SECRET_KEYS} or None
    entry = AuditLog(
        actor_user_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        ip_address=(ip_address or None) and ip_address[:45],
        details=clean,
    )
    db.add(entry)
    return entry


async def entries_for(db: AsyncSession, target_type: str, target_id: uuid.UUID | str) -> list[AuditLog]:
    return list(
        (
            await db.scalars(
                select(AuditLog)
                .where(AuditLog.target_type == target_type, AuditLog.target_id == str(target_id))
                .order_by(AuditLog.created_at, AuditLog.id)
            )
        ).all()
    )
