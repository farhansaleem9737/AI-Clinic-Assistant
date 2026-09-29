from pydantic import BaseModel, ConfigDict
from datetime import datetime


class DepartmentCreate(BaseModel):
    name: str
    description: str | None = None


class DepartmentResponse(BaseModel):
    id: int
    name: str
    description: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
