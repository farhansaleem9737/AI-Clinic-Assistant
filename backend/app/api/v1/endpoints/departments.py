import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import require_permission
from app.core.permissions import Perm
from app.db.session import get_db
from app.schemas.department import DepartmentCreate, DepartmentResponse
from app.services import department_service

router = APIRouter(prefix="/departments", tags=["departments"])


@router.post("/", response_model=DepartmentResponse, status_code=status.HTTP_201_CREATED)
async def create_department(
    dept_in: DepartmentCreate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission(Perm.department_manage)),
):
    return await department_service.create_department(db, dept_in)


@router.get("/", response_model=list[DepartmentResponse])
async def list_departments(db: AsyncSession = Depends(get_db)):
    return await department_service.list_departments(db)


@router.get("/{department_id}", response_model=DepartmentResponse)
async def get_department(department_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    return await department_service.get_department(db, department_id)
