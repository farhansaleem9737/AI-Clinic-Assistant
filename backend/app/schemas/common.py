from pydantic import BaseModel


class Page[T](BaseModel):
    """One page of a collection. `total` counts every match, not just this page."""

    items: list[T]
    total: int
    page: int
    page_size: int
