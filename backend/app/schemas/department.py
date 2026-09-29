import uuid
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _check_timezone(value: str | None) -> str | None:
    if value is None:
        return value
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"Unknown IANA timezone: {value}") from exc
    return value


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    # Defaults to the clinic timezone when omitted.
    timezone: str | None = Field(default=None, max_length=64)

    _tz = field_validator("timezone")(_check_timezone)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name must not be blank")
        return value


class DepartmentUpdate(DepartmentCreate):
    name: str | None = Field(default=None, min_length=1, max_length=100)


class DepartmentPublic(BaseModel):
    """What anyone may see: no status, no internal timestamps."""

    id: uuid.UUID
    name: str
    description: str | None = None

    model_config = ConfigDict(from_attributes=True)


class DepartmentResponse(DepartmentPublic):
    timezone: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
