"""Scheduling policies and the day's queue (D117). Every route checks the
caller's permissions in the service; the API never trusts the client's view."""

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import get_current_principal
from app.core.permissions import Principal
from app.db.session import get_db
from app.schemas.scheduling import (
    CallResult,
    DeferBody,
    MyQueueEntry,
    QueueActionBody,
    QueueBoard,
    QueueEntryRead,
    SchedulePreview,
    SchedulePreviewRequest,
    SchedulingPolicyRead,
    SchedulingPolicyUpdate,
    SessionSummary,
    WalkInCreate,
)
from app.services import queue_service, scheduling_service

router = APIRouter(tags=["scheduling"])


@router.get("/doctors/{doctor_id}/scheduling-policy", response_model=SchedulingPolicyRead)
async def get_scheduling_policy(
    doctor_id: uuid.UUID, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_current_principal)
):
    return await scheduling_service.get_policy(db, principal, doctor_id)


@router.put("/doctors/{doctor_id}/scheduling-policy", response_model=SchedulingPolicyRead)
async def update_scheduling_policy(
    doctor_id: uuid.UUID,
    body: SchedulingPolicyUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """The doctor's own policy (or an administrator's change). Existing appointments
    are never modified; a new length that does not fit upcoming bookings is
    refused (409 SCHEDULE_CONFLICTS, listing them) unless
    keep_existing_appointments is true (D120)."""
    ip = request.client.host if request.client else None
    return await scheduling_service.update_policy(db, principal, doctor_id, body, ip=ip)


@router.post("/doctors/{doctor_id}/scheduling-policy/preview", response_model=SchedulePreview)
async def preview_scheduling_policy(
    doctor_id: uuid.UUID,
    body: SchedulePreviewRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """The times a date would offer with a proposed length and buffer, its
    booked/free capacity, and the upcoming bookings that would not fit (D120).
    Saves nothing."""
    return await scheduling_service.preview(db, principal, doctor_id, body)


@router.get("/queue/sessions", response_model=list[SessionSummary])
async def queue_sessions(
    session_date: date | None = Query(default=None, alias="date"),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    return await queue_service.sessions(db, principal, session_date)


@router.get("/queue/doctors/{doctor_id}", response_model=QueueBoard)
async def queue_board(
    doctor_id: uuid.UUID,
    session_date: date | None = Query(default=None, alias="date"),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    return await queue_service.board(db, principal, doctor_id, session_date)


@router.post("/queue/doctors/{doctor_id}/call-next", response_model=CallResult)
async def call_next(doctor_id: uuid.UUID, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    return await queue_service.call_next(db, principal, doctor_id)


@router.get("/queue/me", response_model=list[MyQueueEntry])
async def my_queue(db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    return await queue_service.my_queue(db, principal)


@router.post("/queue/walk-ins", response_model=QueueEntryRead, status_code=201)
async def register_walk_in(body: WalkInCreate, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    return await queue_service.register_walk_in(db, principal, body)


@router.post("/queue/entries/{entry_id}/check-in", response_model=QueueEntryRead)
async def check_in(entry_id: uuid.UUID, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    return await queue_service.check_in(db, principal, entry_id)


@router.post("/queue/entries/{entry_id}/call", response_model=CallResult)
async def call_entry(entry_id: uuid.UUID, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    return await queue_service.call_entry(db, principal, entry_id)


@router.post("/queue/entries/{entry_id}/start", response_model=QueueEntryRead)
async def start(entry_id: uuid.UUID, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    return await queue_service.start(db, principal, entry_id)


@router.post("/queue/entries/{entry_id}/complete", response_model=QueueEntryRead)
async def complete(entry_id: uuid.UUID, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    return await queue_service.complete(db, principal, entry_id)


@router.post("/queue/entries/{entry_id}/defer", response_model=QueueEntryRead)
async def defer(
    entry_id: uuid.UUID, body: DeferBody, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_current_principal)
):
    return await queue_service.defer(db, principal, entry_id, body.minutes, body.note)


@router.post("/queue/entries/{entry_id}/prioritize", response_model=QueueEntryRead)
async def prioritize(
    entry_id: uuid.UUID,
    body: QueueActionBody | None = None,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    return await queue_service.prioritize(db, principal, entry_id, body.note if body else None)


@router.post("/queue/entries/{entry_id}/absent", response_model=QueueEntryRead)
async def mark_absent(entry_id: uuid.UUID, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    return await queue_service.mark_absent(db, principal, entry_id)


@router.post("/queue/entries/{entry_id}/no-show", response_model=QueueEntryRead)
async def mark_no_show(entry_id: uuid.UUID, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    return await queue_service.mark_no_show(db, principal, entry_id)


@router.post("/queue/entries/{entry_id}/cancel", response_model=QueueEntryRead)
async def cancel(entry_id: uuid.UUID, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    return await queue_service.cancel(db, principal, entry_id)
