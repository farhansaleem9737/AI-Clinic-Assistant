from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime


class DoctorCreate(BaseModel):
    user_id: int
    department_id: int
    specialization: str
    bio: str | None = None
    years_of_experience: int = Field(default=0, ge=0)
    consultation_fee: float | None = Field(default=None, ge=0)


class DoctorUpdate(BaseModel):
    department_id: int | None = None
    specialization: str | None = None
    bio: str | None = None
    years_of_experience: int | None = Field(default=None, ge=0)
    consultation_fee: float | None = Field(default=None, ge=0)


class DoctorResponse(BaseModel):
    id: int
    user_id: int
    # Sourced from the related User row, not stored on the Doctor table.
    name: str
    department_id: int
    specialization: str
    bio: str | None = None
    years_of_experience: int
    consultation_fee: float | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
