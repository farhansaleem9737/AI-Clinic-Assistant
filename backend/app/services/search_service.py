"""Header search (D86, D119): what each caller may look up, decided here from
their permissions, never from the request.

| Category     | Needs                                                  |
|--------------|--------------------------------------------------------|
| doctors      | any signed-in user (the public directory)              |
| departments  | any signed-in user (active departments only)           |
| patients     | patient:read_any, or patient:read_assigned (own only)  |
| users        | user:read                                              |
| appointments | appointment:read_any + user:read (clinic oversight)    |

So a patient finds doctors and departments; a receptionist adds patients; a
doctor adds *their* patients (people with an appointment with them); an
administrator adds users and appointments. Their own appointments stay on
My Appointments: the header search is not a second way into them.

Each section goes through the same service and visibility rule as its own list
page, is capped, and carries only labels (names, MRN, dates, status): no
contact details, nothing clinical. The search text is never logged.
"""

from enum import StrEnum

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Perm, Principal
from app.models.department import Department

SEARCH_LIMIT = 5


class Category(StrEnum):
    patients = "patients"
    doctors = "doctors"
    departments = "departments"
    appointments = "appointments"
    users = "users"


def categories(principal: Principal) -> list[Category]:
    """The caller's categories, in the order the results are shown."""
    allowed = []
    if principal.has_any(Perm.patient_read_any, Perm.patient_read_assigned):
        allowed.append(Category.patients)
    allowed += [Category.doctors, Category.departments]
    if principal.has(Perm.appointment_read_any) and principal.has(Perm.user_read):
        allowed.append(Category.appointments)
    if principal.has(Perm.user_read):
        allowed.append(Category.users)
    return allowed


async def departments(db: AsyncSession, term: str, limit: int = SEARCH_LIMIT) -> list[Department]:
    """Active departments whose name or description contains the term (bound
    parameters; LIKE wildcards in the term are matched literally)."""
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    query = (
        select(Department)
        .where(
            Department.is_active.is_(True),
            or_(Department.name.ilike(pattern, escape="\\"), Department.description.ilike(pattern, escape="\\")),
        )
        # Name matches first, then alphabetical.
        .order_by(Department.name.ilike(pattern, escape="\\").desc(), Department.name, Department.id)
        .limit(limit)
    )
    return list((await db.scalars(query)).all())
