"""Follow-up visits on an appointment (D108): read by anyone who sees the
appointment; recorded by its doctor or the clinic; dismissed by them or the patient."""

import uuid

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import get_current_principal
from app.core.permissions import Principal
from app.db.session import get_db
from app.models.notification import FollowUp
from app.schemas.follow_up import FollowUpRead, FollowUpState, FollowUpWrite
from app.services import follow_up_service

router = APIRouter(tags=["follow-ups"])


def _read(f: FollowUp) -> FollowUpRead:
    return FollowUpRead(id=f.id, due_date=f.due_date, doctor_id=f.doctor_id)


@router.get("/appointments/{appointment_id}/follow-up", response_model=FollowUpState)
async def get_follow_up(
    appointment_id: uuid.UUID, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_current_principal)
):
    follow_up, can_manage = await follow_up_service.get_for_appointment(db, principal, appointment_id)
    return FollowUpState(follow_up=_read(follow_up) if follow_up else None, can_manage=can_manage)


@router.put("/appointments/{appointment_id}/follow-up", response_model=FollowUpRead)
async def record_follow_up(
    appointment_id: uuid.UUID,
    data: FollowUpWrite,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    return _read(await follow_up_service.record(db, principal, appointment_id, data.due_date))


@router.post("/follow-ups/{follow_up_id}/dismiss", status_code=status.HTTP_204_NO_CONTENT)
async def dismiss_follow_up(
    follow_up_id: uuid.UUID, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_current_principal)
):
    await follow_up_service.dismiss(db, principal, follow_up_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
