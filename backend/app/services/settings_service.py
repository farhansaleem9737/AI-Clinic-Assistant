"""The clinic's details, edited by administrators (D86).

Only display data lives here. Operational rules — timezone, slot length,
booking notice and horizon — are server configuration, shown read-only:
changing them from the browser could move or strand existing appointments.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.config import settings
from app.core.permissions import Principal
from app.models.notification import ClinicSettings
from app.schemas.settings import ClinicSettingsRead, ClinicSettingsUpdate, OperationalSettings

logger = logging.getLogger(__name__)


def _operational() -> OperationalSettings:
    return OperationalSettings(
        timezone=settings.clinic_timezone,
        default_slot_minutes=settings.default_slot_minutes,
        booking_min_lead_minutes=settings.booking_min_lead_minutes,
        booking_max_advance_days=settings.booking_max_advance_days,
        patient_cancellation_cutoff_minutes=settings.patient_cancellation_cutoff_minutes,
    )


def _read(row: ClinicSettings | None) -> ClinicSettingsRead:
    return ClinicSettingsRead(
        clinic_name=row.clinic_name if row else None,
        contact_phone=row.contact_phone if row else None,
        contact_email=row.contact_email if row else None,
        address=row.address if row else None,
        updated_at=row.updated_at if row else None,
        operational=_operational(),
    )


async def get(db: AsyncSession) -> ClinicSettingsRead:
    return _read(await db.get(ClinicSettings, 1))


async def update(db: AsyncSession, principal: Principal, data: ClinicSettingsUpdate) -> ClinicSettingsRead:
    row = await db.get(ClinicSettings, 1)
    if row is None:
        row = ClinicSettings(id=1)
        db.add(row)
    changes = data.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(row, field, value)
    row.updated_at = clock.utcnow()
    row.updated_by_user_id = principal.user_id
    await db.commit()
    await db.refresh(row)
    logger.info("clinic_settings_updated", extra={"by": str(principal.user_id), "fields": sorted(changes)})
    return _read(row)
