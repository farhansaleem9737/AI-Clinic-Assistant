import uuid
from datetime import date

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import require_any_permission, require_permission
from app.api.deps.pagination import page_params
from app.core.permissions import Perm, Principal
from app.db.session import get_db
from app.models.appointment import AppointmentStatus
from app.schemas.appointment import (
    AppointmentCreate,
    AppointmentDoctor,
    AppointmentRead,
    AppointmentStaffRead,
    AppointmentUpdate,
    Reschedule,
    StatusChange,
    StatusHistoryRead,
)
from app.schemas.common import Page
from app.schemas.patient import PatientSummary
from app.services import appointment_service
from app.services.appointment_service import AppointmentFilters, AppointmentView
from app.services.pagination import PageParams

router = APIRouter(prefix="/appointments", tags=["appointments"])

READ = (Perm.appointment_read_own, Perm.appointment_read_assigned, Perm.appointment_read_any)
# Doctors and staff see internal notes; patients do not.
STAFF_VIEW = (Perm.appointment_read_any, Perm.appointment_read_assigned)


def to_response(view: AppointmentView, principal: Principal) -> AppointmentRead:
    a = view.appointment
    base = dict(
        id=a.id,
        status=a.status,
        starts_at=a.starts_at,
        ends_at=a.ends_at,
        timezone=view.timezone,
        reason=a.reason,
        doctor=AppointmentDoctor(
            id=a.doctor_id,
            name=view.doctor_name,
            title=view.doctor_title,
            room_number=view.doctor_room,
            specialization=view.specialization,
            department_id=view.department_id,
            department_name=view.department_name,
        ),
        patient=PatientSummary(id=a.patient_id, mrn=view.patient_mrn, name=view.patient_name, date_of_birth=view.patient_dob),
        cancellation_reason=a.cancellation_reason,
        cancellation_note=a.cancellation_note,
        cancelled_at=a.cancelled_at,
        rescheduled_from_id=a.rescheduled_from_id,
        rescheduled_to_id=view.rescheduled_to_id,
        allowed_transitions=view.allowed_transitions,
        can_reschedule=view.can_reschedule,
        created_at=a.created_at,
        updated_at=a.updated_at,
    )
    if principal.has_any(*STAFF_VIEW):
        return AppointmentStaffRead(**base, staff_notes=a.staff_notes, booked_by_user_id=a.booked_by_user_id)
    return AppointmentRead(**base)


ResponseModel = AppointmentStaffRead | AppointmentRead


@router.get("/", response_model=Page[AppointmentStaffRead] | Page[AppointmentRead])
async def list_appointments(
    patient_id: uuid.UUID | None = None,
    doctor_id: uuid.UUID | None = None,
    department_id: uuid.UUID | None = None,
    status_: list[AppointmentStatus] | None = Query(None, alias="status"),
    date_from: date | None = Query(None, description="Clinic-local calendar date"),
    date_to: date | None = Query(None, description="Clinic-local calendar date, inclusive"),
    upcoming: bool = Query(False, description="Only open appointments that have not ended yet"),
    newest_first: bool = False,
    params: PageParams = Depends(page_params),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_any_permission(*READ)),
):
    filters = AppointmentFilters(
        patient_id=patient_id,
        doctor_id=doctor_id,
        department_id=department_id,
        statuses=tuple(status_ or ()),
        date_from=date_from,
        date_to=date_to,
        upcoming=upcoming,
        newest_first=newest_first,
    )
    views, total = await appointment_service.list_appointments(db, principal, params, filters)
    return Page(
        items=[to_response(v, principal) for v in views], total=total, page=params.page, page_size=params.page_size
    )


@router.post("/", response_model=ResponseModel, status_code=status.HTTP_201_CREATED)
async def book_appointment(
    body: AppointmentCreate,
    response: Response,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key", max_length=100),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_any_permission(Perm.appointment_create, Perm.appointment_create_own)),
):
    view, replayed = await appointment_service.book(db, principal, body, idempotency_key)
    if replayed:
        response.status_code = status.HTTP_200_OK
        response.headers["Idempotent-Replayed"] = "true"
    return to_response(view, principal)


@router.get("/{appointment_id}", response_model=ResponseModel)
async def get_appointment(
    appointment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_any_permission(*READ)),
):
    return to_response(await appointment_service.get_view(db, principal, appointment_id), principal)


@router.patch("/{appointment_id}", response_model=AppointmentStaffRead)
async def update_appointment(
    appointment_id: uuid.UUID,
    body: AppointmentUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.appointment_manage)),
):
    return to_response(await appointment_service.update(db, principal, appointment_id, body), principal)


@router.post("/{appointment_id}/status", response_model=ResponseModel)
async def change_status(
    appointment_id: uuid.UUID,
    body: StatusChange,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_any_permission(*READ)),
):
    # Which transitions this caller may make on this appointment is decided by
    # the state machine in the service, not here.
    return to_response(await appointment_service.change_status(db, principal, appointment_id, body), principal)


@router.post("/{appointment_id}/reschedule", response_model=ResponseModel, status_code=status.HTTP_201_CREATED)
async def reschedule_appointment(
    appointment_id: uuid.UUID,
    body: Reschedule,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_any_permission(Perm.appointment_manage, Perm.appointment_reschedule_own)),
):
    return to_response(await appointment_service.reschedule(db, principal, appointment_id, body), principal)


@router.get("/{appointment_id}/history", response_model=list[StatusHistoryRead])
async def appointment_history(
    appointment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_any_permission(*READ)),
):
    rows = await appointment_service.history(db, principal, appointment_id)
    return [
        StatusHistoryRead(
            from_status=r.from_status,
            to_status=r.to_status,
            changed_by_user_id=r.changed_by_user_id,
            reason=r.reason,
            changed_at=r.changed_at,
        )
        for r in rows
    ]
