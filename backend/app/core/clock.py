"""Single source of truth for "now" in this project.

Project datetime policy
-----------------------
Every persistent timestamp is a timezone-aware UTC datetime, stored in a
PostgreSQL ``TIMESTAMP WITH TIME ZONE`` column declared as
``DateTime(timezone=True)``.

Never use ``datetime.utcnow()``: it returns a *naive* datetime that only looks
like UTC, which is what allowed naive and aware values to mix in the first
place. It is also deprecated from Python 3.12 onward.
"""

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Current instant as a timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)
