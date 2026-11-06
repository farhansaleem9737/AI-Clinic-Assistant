"""Specializations in the medical catalog (D118)."""

import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SpecializationPublic(BaseModel):
    """A catalog specialization as the directory shows it."""

    id: uuid.UUID
    name: str
    slug: str
    department_ids: list[uuid.UUID]
    # Publicly listed doctors linked to it (within the department, when one was asked for).
    doctor_count: int


class SpecializationAdmin(SpecializationPublic):
    description: str | None = None
    aliases: list[str]
    is_active: bool


class _SpecializationFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str | None = Field(default=None, max_length=500)
    aliases: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("description")
    @classmethod
    def _blank_description(cls, value: str | None) -> str | None:
        return (value or "").strip() or None

    @field_validator("aliases")
    @classmethod
    def _alias_length(cls, values: list[str]) -> list[str]:
        if any(len(v.strip()) > 100 for v in values):
            raise ValueError("Each alias is at most 100 characters")
        return values


def _name(value: str | None) -> str | None:
    if value is None:
        return None
    value = " ".join(value.split())
    if not value:
        raise ValueError("Name must not be blank")
    return value


class SpecializationCreate(_SpecializationFields):
    name: str = Field(min_length=1, max_length=120)
    department_ids: list[uuid.UUID] = Field(min_length=1, max_length=10)
    is_active: bool = True

    _strip = field_validator("name")(_name)


class SpecializationUpdate(_SpecializationFields):
    """Omitted fields stay as they are; `department_ids` replaces the list."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    aliases: list[str] | None = Field(default=None, max_length=20)
    department_ids: list[uuid.UUID] | None = Field(default=None, min_length=1, max_length=10)
    is_active: bool | None = None

    _strip = field_validator("name")(_name)


class SpecializationRef(BaseModel):
    id: uuid.UUID
    name: str
    slug: str

    model_config = ConfigDict(from_attributes=True)


class DoctorSpecializationsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    specialization_ids: list[uuid.UUID] = Field(max_length=10)
