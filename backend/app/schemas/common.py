from datetime import date, datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import AfterValidator, BaseModel, EmailStr, Field, computed_field

from app.core.config import settings

# The same values as a patient's sex at birth; "unknown" is "prefer not to say".
Gender = Literal["female", "male", "intersex", "unknown"]

MAX_AGE_YEARS = 120
ADULT_AGE_YEARS = 18

# The six digits emailed before an account is created (auth/register/verification-code).
VerificationCode = Annotated[str, Field(pattern=r"^\d{6}$")]


def _years_before(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year - years)
    except ValueError:  # 29 February in a non-leap year
        return day.replace(year=day.year - years, day=28)


def check_birth_date(value: date, *, min_age: int = 0) -> date:
    """Not in the future, not more than 120 years ago, and at least ``min_age`` years ago."""
    today = datetime.now(ZoneInfo(settings.clinic_timezone)).date()
    if value > today:
        raise ValueError("Date of birth cannot be in the future")
    if value < _years_before(today, MAX_AGE_YEARS):
        raise ValueError("Date of birth is not plausible")
    if value > _years_before(today, min_age):
        raise ValueError(f"Must be at least {min_age} years old")
    return value


def adult_birth_date(value: date) -> date:
    return check_birth_date(value, min_age=ADULT_AGE_YEARS)


def _lowercase(value: str) -> str:
    return value.strip().lower()


# An email that identifies a login. Stored and compared in lowercase, so
# "John@Example.com" and "john@example.com" are one account, not two.
LoginEmail = Annotated[EmailStr, AfterValidator(_lowercase)]


def clean_name(value: str) -> str:
    """Trim a personal name and reject one that is only whitespace. Any
    letters are accepted: names are not limited to ASCII."""
    value = " ".join(value.split())
    if not value:
        raise ValueError("Name must not be blank")
    return value


class Page[T](BaseModel):
    """One page of a collection. `total` counts every match, not just this page."""

    items: list[T]
    total: int
    page: int
    page_size: int

    @computed_field
    @property
    def total_pages(self) -> int:
        return -(-self.total // self.page_size)  # ceiling division
