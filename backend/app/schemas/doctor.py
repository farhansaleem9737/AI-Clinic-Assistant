import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class DoctorCreate(BaseModel):
    user_id: uuid.UUID
    department_id: uuid.UUID
    specialization: str
    bio: str | None = None
    years_of_experience: int = Field(default=0, ge=0)
    consultation_fee: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)


class DoctorUpdate(BaseModel):
    department_id: uuid.UUID | None = None
    specialization: str | None = None
    bio: str | None = None
    years_of_experience: int | None = Field(default=None, ge=0)
    consultation_fee: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)


class DoctorResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    # Sourced from the related User row, not stored on the Doctor table.
    name: str
    department_id: uuid.UUID
    specialization: str
    bio: str | None = None
    years_of_experience: int
    consultation_fee: Decimal | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
