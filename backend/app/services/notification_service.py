"""In-app notifications (D86, D108).

Created by real events, in the same transaction as the event (``notify``
adds rows and never commits), so a notification exists exactly when its
event does. Scheduled ones (reminders) are inserted by the reminder run with
a ``dedupe_key``, at most once per user. Read through the caller's own user
id only: someone else's notification is "not found".
"""

import logging
import re
import uuid
from collections.abc import Iterable
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.exceptions import NotFoundError
from app.core.permissions import Perm, Principal
from app.models.notification import Notification, NotificationPreference
from app.models.rbac import Permission, Role, RolePermission, UserRole
from app.models.user import User

logger = logging.getLogger(__name__)

MAX_LIST = 50

# Optional categories a user may switch off (NotificationPreference columns).
# Types not listed are essential: a doctor's new booking, an application to review.
CATEGORY_BY_TYPE = {
    "appointment_confirmed": "appointment_updates",
    "appointment_rescheduled": "appointment_updates",
    "appointment_cancelled": "appointment_updates",
    "appointment_booked_for_you": "appointment_updates",
    "patient_checked_in": "appointment_updates",
    "appointment_reminder": "reminders",
    "follow_up_due": "follow_ups",
}
CATEGORIES = ("appointment_updates", "reminders", "follow_ups")
# Preference switches: the categories, and whether the enabled ones also come by email (D109).
SWITCHES = (*CATEGORIES, "emails")

_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
# Where a notification may lead: pages of this app only (the database also
# refuses anything that is not an internal path).
_LINKS = re.compile(
    rf"^/(dashboard|appointments|appointments/{_UUID}|appointments/book(\?doctor={_UUID})?|schedule"
    r"|doctor/profile|doctor/application|profile|admin/doctors|admin/users)$"
)


def safe_link(link: str | None) -> str | None:
    if link is None or _LINKS.match(link):
        return link
    logger.warning("notification_link_dropped", extra={"link": link[:80]})
    return None


def notify(db: AsyncSession, user_ids: Iterable[uuid.UUID], *, type: str, title: str, message: str, link: str | None = None) -> None:
    """Queue a notification for each user (deduplicated). Does not commit."""
    link = safe_link(link)
    for user_id in dict.fromkeys(u for u in user_ids if u is not None):
        db.add(Notification(user_id=user_id, type=type, title=title, message=message, link=link))


async def opted_in(db: AsyncSession, user_ids: Iterable[uuid.UUID], type: str) -> list[uuid.UUID]:
    """The users among `user_ids` who receive `type` (all of them for essential types)."""
    users = list(dict.fromkeys(u for u in user_ids if u is not None))
    category = CATEGORY_BY_TYPE.get(type)
    if category is None or not users:
        return users
    off = set(
        await db.scalars(
            select(NotificationPreference.user_id).where(
                NotificationPreference.user_id.in_(users), getattr(NotificationPreference, category).is_(False)
            )
        )
    )
    return [u for u in users if u not in off]


async def notify_optional(
    db: AsyncSession, user_ids: Iterable[uuid.UUID], *, type: str, title: str, message: str, link: str | None = None
) -> None:
    """Like ``notify``, skipping users who switched this type's category off."""
    notify(db, await opted_in(db, user_ids, type), type=type, title=title, message=message, link=link)


async def notify_once(
    db: AsyncSession, user_id: uuid.UUID, *, dedupe_key: str, type: str, title: str, message: str, link: str | None = None
) -> bool:
    """Insert a scheduled notification unless this user already has `dedupe_key`
    (a repeated or concurrent run). Returns whether it was created. Does not commit."""
    created = await db.scalar(
        insert(Notification)
        .values(
            id=uuid.uuid7(), user_id=user_id, type=type, title=title, message=message, link=safe_link(link),
            dedupe_key=dedupe_key, created_at=clock.utcnow(),
        )
        .on_conflict_do_nothing(index_elements=["user_id", "dedupe_key"])
        .returning(Notification.id)
    )
    return created is not None


async def holders_of(db: AsyncSession, permission: Perm) -> list[uuid.UUID]:
    """Active users whose roles grant `permission`."""
    rows = await db.scalars(
        select(User.id)
        .distinct()
        .join(UserRole, UserRole.user_id == User.id)
        .join(RolePermission, RolePermission.role_id == UserRole.role_id)
        .join(Permission, Permission.id == RolePermission.permission_id)
        .where(Permission.code == permission.value, User.is_active.is_(True))
    )
    return list(rows.all())


async def with_role(db: AsyncSession, role: str) -> list[uuid.UUID]:
    """Active users who have `role` (e.g. the front desk)."""
    rows = await db.scalars(
        select(User.id)
        .distinct()
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(Role.code == role, User.is_active.is_(True))
    )
    return list(rows.all())


def when(instant: datetime, tz: ZoneInfo) -> str:
    """"Fri 23 Apr 2027, 10:00" in the clinic's timezone."""
    return instant.astimezone(tz).strftime("%a %d %b %Y, %H:%M")


async def list_mine(db: AsyncSession, principal: Principal, limit: int = 20, offset: int = 0) -> list[Notification]:
    query = (
        select(Notification)
        .where(Notification.user_id == principal.user_id)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .offset(offset)
        .limit(min(limit, MAX_LIST + 1))  # +1: the caller checks for a next page
    )
    return list((await db.scalars(query)).all())


async def unread_count(db: AsyncSession, principal: Principal) -> int:
    return await db.scalar(
        select(func.count()).select_from(Notification).where(
            Notification.user_id == principal.user_id, Notification.read_at.is_(None)
        )
    )


async def mark_read(db: AsyncSession, principal: Principal, notification_id: uuid.UUID) -> Notification:
    notification = await db.scalar(
        select(Notification).where(Notification.id == notification_id, Notification.user_id == principal.user_id)
    )
    if notification is None:
        raise NotFoundError("Notification not found")
    if notification.read_at is None:
        notification.read_at = clock.utcnow()
        await db.commit()
        await db.refresh(notification)
    return notification


async def mark_all_read(db: AsyncSession, principal: Principal) -> int:
    result = await db.execute(
        update(Notification)
        .where(Notification.user_id == principal.user_id, Notification.read_at.is_(None))
        .values(read_at=clock.utcnow())
    )
    await db.commit()
    return result.rowcount or 0


# ---- preferences (D108): the caller's own ---------------------------------------------


async def get_preferences(db: AsyncSession, principal: Principal) -> dict[str, bool]:
    row = await db.get(NotificationPreference, principal.user_id)
    return {c: (getattr(row, c) if row is not None else True) for c in SWITCHES}


async def update_preferences(db: AsyncSession, principal: Principal, changes: dict[str, bool]) -> dict[str, bool]:
    row = await db.get(NotificationPreference, principal.user_id)
    if row is None:
        row = NotificationPreference(user_id=principal.user_id)
        db.add(row)
    for category, value in changes.items():
        if category in SWITCHES:
            setattr(row, category, value)
    await db.commit()
    return await get_preferences(db, principal)
