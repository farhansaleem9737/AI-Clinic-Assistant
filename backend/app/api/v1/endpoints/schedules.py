import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query, status
from pydantic import AwareDatetime
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import require_any_permission, require_permission
from app.core import clock
from app.core.permissions import Perm, Principal
from app.db.session import get_db
from app.schemas.schedule import (
    AvailabilityRead,
    ScheduleExceptionCreate,
    ScheduleExceptionRead,
    ScheduleTemplateCreate,
    ScheduleTemplateRead,
    ScheduleTemplateUpdate,
    SlotRead,
)
from app.services import availability_service, schedule_service
from app.services.appointment_service import booking_lead

router = APIRouter(tags=["schedules"])

MANAGE = (Perm.schedule_manage_own, Perm.schedule_manage_any)


@router.get("/doctors/{doctor_id}/availability", response_model=AvailabilityRead)
async def doctor_availability(
    doctor_id: uuid.UUID,
    date_from: date = Query(description="Local calendar date in the doctor's department timezone"),
    date_to: date = Query(description="Inclusive; at most 31 days after date_from"),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.availability_read)),
):
    bookable, slots = await availability_service.available_slots(
        db, doctor_id, date_from, date_to, now=clock.utcnow(), min_lead=booking_lead(principal)
    )
    return AvailabilityRead(
        doctor_id=doctor_id,
        timezone=bookable.timezone.key,
        slots=[SlotRead(starts_at=s.starts_at, ends_at=s.ends_at) for s in slots],
    )


# ---- weekly templates -------------------------------------------------------------


@router.get("/schedules", response_model=list[ScheduleTemplateRead])
async def list_templates(
    doctor_id: uuid.UUID,
    include_inactive: bool = False,
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_permission(Perm.schedule_read)),
):
    return await schedule_service.list_templates(db, doctor_id, include_inactive=include_inactive)


@router.post("/schedules", response_model=ScheduleTemplateRead, status_code=status.HTTP_201_CREATED)
async def create_template(
    body: ScheduleTemplateCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_any_permission(*MANAGE)),
):
    return await schedule_service.create_template(db, principal, body)


@router.patch("/schedules/{template_id}", response_model=ScheduleTemplateRead)
async def update_template(
    template_id: uuid.UUID,
    body: ScheduleTemplateUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_any_permission(*MANAGE)),
):
    return await schedule_service.update_template(db, principal, template_id, body)


@router.post("/schedules/{template_id}/deactivate", response_model=ScheduleTemplateRead)
async def deactivate_template(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_any_permission(*MANAGE)),
):
    return await schedule_service.deactivate_template(db, principal, template_id)


# ---- one-off exceptions -------------------------------------------------------------


@router.get("/schedule-exceptions", response_model=list[ScheduleExceptionRead])
async def list_exceptions(
    doctor_id: uuid.UUID,
    start: AwareDatetime | None = None,
    end: AwareDatetime | None = None,
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_permission(Perm.schedule_read)),
):
    return await schedule_service.list_exceptions(db, doctor_id, start=start, end=end)


@router.post("/schedule-exceptions", response_model=ScheduleExceptionRead, status_code=status.HTTP_201_CREATED)
async def create_exception(
    body: ScheduleExceptionCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_any_permission(*MANAGE)),
):
    return await schedule_service.create_exception(db, principal, body)


@router.delete("/schedule-exceptions/{exception_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_exception(
    exception_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_any_permission(*MANAGE)),
):
    await schedule_service.delete_exception(db, principal, exception_id)
