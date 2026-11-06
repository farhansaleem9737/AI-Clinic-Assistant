"""Allergies, diagnoses and medications (D112)."""

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, BeforeValidator, Field, model_validator


def _blank_is_none(value: object) -> object:
    if isinstance(value, str):
        value = " ".join(value.split())
        return value or None
    return value


def _trimmed(value: object) -> object:
    return (value.strip() or None) if isinstance(value, str) else value


def _required(value: str | None) -> str:
    if not value:
        raise ValueError("This field is required")
    return value


# One line of text: whitespace collapsed; blank means "not given".
def Text(max_length: int):  # noqa: N802 (a type alias factory)
    return Annotated[Annotated[str, Field(max_length=max_length)] | None, BeforeValidator(_blank_is_none)]


def RequiredText(max_length: int):  # noqa: N802
    return Annotated[str, BeforeValidator(_blank_is_none), AfterValidator(_required), Field(max_length=max_length)]


Source = Literal["patient", "clinician"]


# ---- written (create and edit take the whole entry) -------------------------------------


class AllergyWrite(BaseModel):
    substance: RequiredText(120)
    reaction: Text(200) = None
    severity: Literal["mild", "moderate", "severe", "unknown"] = "unknown"


class DiagnosisWrite(BaseModel):
    condition: RequiredText(200)
    status: Literal["active", "resolved"] = "active"
    diagnosed_on: date | None = None
    # Several lines allowed: only the ends are trimmed.
    notes: Annotated[Annotated[str, Field(max_length=1000)] | None, BeforeValidator(_trimmed)] = None


class MedicationWrite(BaseModel):
    name: RequiredText(200)
    dosage: Text(100) = None
    frequency: Text(100) = None
    instructions: Text(500) = None
    start_date: date | None = None
    end_date: date | None = None
    status: Literal["active", "stopped"] = "active"

    @model_validator(mode="after")
    def dates_in_order(self) -> "MedicationWrite":
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("The end date cannot be before the start date")
        return self


# ---- read ---------------------------------------------------------------------------------


class EntryMeta(BaseModel):
    id: uuid.UUID
    # Who recorded it: the patient themselves, or a clinician (their name).
    source: Source
    recorded_by: str | None
    recorded_by_me: bool
    # Whether the caller may edit or remove this entry.
    can_edit: bool
    created_at: datetime
    updated_at: datetime


class AllergyRead(EntryMeta):
    substance: str
    reaction: str | None
    severity: str


class DiagnosisRead(EntryMeta):
    condition: str
    status: str
    diagnosed_on: date | None
    notes: str | None


class MedicationRead(EntryMeta):
    name: str
    dosage: str | None
    frequency: str | None
    instructions: str | None
    start_date: date | None
    end_date: date | None
    status: str


class HealthRecords(BaseModel):
    """A patient's current entries, and what the caller may add."""

    allergies: list[AllergyRead]
    diagnoses: list[DiagnosisRead]
    medications: list[MedicationRead]
    can_add_allergies: bool
    can_add_diagnoses: bool
    can_add_medications: bool
