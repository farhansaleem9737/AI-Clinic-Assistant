from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import get_current_principal
from app.core.permissions import Principal
from app.db.session import get_db
from app.schemas.dashboard import DashboardSummary
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
