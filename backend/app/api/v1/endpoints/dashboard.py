from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import get_current_principal, require_permission
from app.core.permissions import Perm, Principal
from app.db.session import get_db
from app.schemas.dashboard import AdminDashboard, DashboardSummary
from app.services import dashboard_service

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummary)
async def dashboard_summary(
    db: AsyncSession = Depends(get_db),
    # Any signed-in, active user. What they receive is decided per section by
    # their permissions, in the service.
    principal: Principal = Depends(get_current_principal),
):
    return await dashboard_service.get_summary(db, principal)


@router.get("/admin", response_model=AdminDashboard)
async def admin_dashboard(
    day: date | None = Query(None, description="As-of date in the clinic's timezone; default today"),
    db: AsyncSession = Depends(get_db),
    # Clinic-wide totals and the newest accounts: administrators only.
    _: Principal = Depends(require_permission(Perm.user_read, Perm.appointment_read_any, Perm.patient_read_any)),
):
    return await dashboard_service.admin_dashboard(db, day)
