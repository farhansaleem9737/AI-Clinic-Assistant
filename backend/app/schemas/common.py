from typing import Annotated

from pydantic import AfterValidator, BaseModel, EmailStr, computed_field


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
