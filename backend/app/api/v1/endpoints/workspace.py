"""The signed-in workspace around every page (D86): notifications, global
search, and the clinic's settings."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import get_current_principal, require_permission
from app.core.permissions import Perm, Principal
from app.db.session import get_db
from app.models.notification import Notification
from app.schemas.settings import (
    ClinicSettingsRead,
    ClinicSettingsUpdate,
    NotificationList,
    NotificationRead,
    SearchAppointment,
    SearchDoctor,
    SearchPatient,
    SearchResults,
    SearchUser,
    UnreadCount,
)
from app.services import (
    appointment_service,
    doctor_service,
    notification_service,
    patient_service,
    settings_service,
    user_service,
)
from app.services.appointment_service import AppointmentFilters, AppointmentSort
from app.services.doctor_service import DoctorFilters
from app.services.pagination import PageParams

router = APIRouter(tags=["workspace"])

SEARCH_LIMIT = 5


def to_notification(n: Notification) -> NotificationRead:
    return NotificationRead(
        id=n.id, type=n.type, title=n.title, message=n.message, link=n.link, read_at=n.read_at, created_at=n.created_at
    )


# ---- notifications: always the caller's own -------------------------------------------


@router.get("/notifications", response_model=NotificationList)
async def list_notifications(
    limit: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    items = await notification_service.list_mine(db, principal, limit)
    return NotificationList(
        items=[to_notification(n) for n in items], unread=await notification_service.unread_count(db, principal)
    )


@router.get("/notifications/unread-count", response_model=UnreadCount)
async def unread_notifications(
    db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_current_principal)
):
    return UnreadCount(unread=await notification_service.unread_count(db, principal))


@router.post("/notifications/{notification_id}/read", response_model=NotificationRead)
async def read_notification(
    notification_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    return to_notification(await notification_service.mark_read(db, principal, notification_id))


@router.post("/notifications/read-all", response_model=UnreadCount)
async def read_all_notifications(
    db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_current_principal)
):
    await notification_service.mark_all_read(db, principal)
    return UnreadCount(unread=0)


# ---- global search ----------------------------------------------------------------------


@router.get("/search", response_model=SearchResults)
async def search(
    q: str = Query(min_length=2, max_length=100, description="At least two characters"),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Up to five of each kind the caller may see. Every section goes through
    the same service (and visibility rules) as its own list page; nothing
    clinical is returned — names, MRNs, dates and statuses only."""
    term = q.strip()
    page = PageParams(page=1, page_size=SEARCH_LIMIT)
    results = SearchResults(query=term)

    if principal.has_any(Perm.patient_read_any, Perm.patient_read_assigned):
        patients, _ = await patient_service.list_patients(db, principal, page, q=term)
        results.patients = [SearchPatient(id=p.id, name=f"{p.first_name} {p.last_name}", mrn=p.mrn) for p in patients]

    doctors, _ = await doctor_service.list_doctors(db, page, DoctorFilters(q=term), public=True)
    results.doctors = [
        SearchDoctor(
            id=row.doctor.id,
            name=f"{row.doctor.title} {row.name}" if row.doctor.title else row.name,
            specialization=row.doctor.specialization,
        )
        for row in doctors
    ]

    if principal.has_any(Perm.appointment_read_own, Perm.appointment_read_assigned, Perm.appointment_read_any):
        views, _ = await appointment_service.list_appointments(
            db, principal, page, AppointmentFilters(q=term, sort=AppointmentSort.time_desc)
        )
        results.appointments = [
            SearchAppointment(
                id=v.appointment.id,
                starts_at=v.appointment.starts_at,
                timezone=v.timezone,
                patient_name=v.patient_name,
                doctor_name=f"{v.doctor_title} {v.doctor_name}" if v.doctor_title else v.doctor_name,
                status=v.appointment.status.value,
            )
            for v in views
        ]

    if principal.has(Perm.user_read):
        users, _ = await user_service.list_users(db, page, q=term)
        results.users = [SearchUser(id=u.user.id, name=u.user.name, email=u.user.email, roles=u.roles) for u in users]
    return results


# ---- clinic settings ---------------------------------------------------------------------


@router.get("/settings/clinic", response_model=ClinicSettingsRead)
async def get_clinic_settings(db: AsyncSession = Depends(get_db), _: Principal = Depends(get_current_principal)):
    """The clinic's name and contact details (for any signed-in user, e.g.
    the help page) and the read-only operational configuration."""
    return await settings_service.get(db)


@router.put("/settings/clinic", response_model=ClinicSettingsRead)
async def update_clinic_settings(
    body: ClinicSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.settings_manage)),
):
    return await settings_service.update(db, principal, body)
