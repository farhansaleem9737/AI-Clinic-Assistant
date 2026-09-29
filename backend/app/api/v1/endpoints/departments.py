import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import require_permission
from app.api.deps.pagination import page_params
from app.core.permissions import Perm, Principal
from app.db.session import get_db
from app.schemas.common import Page
from app.schemas.department import DepartmentCreate, DepartmentPublic, DepartmentResponse, DepartmentUpdate
from app.services import department_service
from app.services.pagination import PageParams

router = APIRouter(prefix="/departments", tags=["departments"])
public_router = APIRouter(prefix="/public/departments", tags=["public"])


@public_router.get("/", response_model=Page[DepartmentPublic])
async def public_list_departments(
    q: str | None = Query(None, max_length=100),
    params: PageParams = Depends(page_params),
    db: AsyncSession = Depends(get_db),
):
    items, total = await department_service.list_departments(db, params, active_only=True, q=q)
    return Page(items=items, total=total, page=params.page, page_size=params.page_size)


@public_router.get("/{department_id}", response_model=DepartmentPublic)
async def public_get_department(department_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    return await department_service.get_department(db, department_id, active_only=True)


@router.get("/", response_model=Page[DepartmentResponse])
async def list_departments(
    q: str | None = Query(None, max_length=100),
    include_inactive: bool = True,
    params: PageParams = Depends(page_params),
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_permission(Perm.department_manage)),
):
    items, total = await department_service.list_departments(db, params, active_only=not include_inactive, q=q)
    return Page(items=items, total=total, page=params.page, page_size=params.page_size)


@router.post("/", response_model=DepartmentResponse, status_code=status.HTTP_201_CREATED)
async def create_department(
    body: DepartmentCreate,
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_permission(Perm.department_manage)),
):
    return await department_service.create_department(db, body)


@router.get("/{department_id}", response_model=DepartmentResponse)
async def get_department(
    department_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_permission(Perm.department_manage)),
):
    return await department_service.get_department(db, department_id)


@router.patch("/{department_id}", response_model=DepartmentResponse)
async def update_department(
    department_id: uuid.UUID,
    body: DepartmentUpdate,
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_permission(Perm.department_manage)),
):
    return await department_service.update_department(db, department_id, body)


@router.post("/{department_id}/deactivate", response_model=DepartmentResponse)
async def deactivate_department(
    department_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_permission(Perm.department_manage)),
):
    return await department_service.set_active(db, department_id, active=False)


@router.post("/{department_id}/activate", response_model=DepartmentResponse)
async def activate_department(
    department_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_permission(Perm.department_manage)),
):
    return await department_service.set_active(db, department_id, active=True)
