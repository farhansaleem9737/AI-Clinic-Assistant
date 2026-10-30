"""In-app notifications (D86).

Created by real events, in the same transaction as the event (``notify``
adds rows and never commits), so a notification exists exactly when its
event does. Read through the caller's own user id only: someone else's
notification is "not found".
"""

import logging
import uuid
from collections.abc import Iterable
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.exceptions import NotFoundError
from app.core.permissions import Perm, Principal
from app.models.notification import Notification
from app.models.rbac import Permission, RolePermission, UserRole
from app.models.user import User

logger = logging.getLogger(__name__)

MAX_LIST = 50


def notify(db: AsyncSession, user_ids: Iterable[uuid.UUID], *, type: str, title: str, message: str, link: str | None = None) -> None:
    """Queue a notification for each user (deduplicated). Does not commit."""
    for user_id in dict.fromkeys(u for u in user_ids if u is not None):
        db.add(Notification(user_id=user_id, type=type, title=title, message=message, link=link))


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


def when(instant: datetime, tz: ZoneInfo) -> str:
    """"Fri 23 Apr 2027, 10:00" in the clinic's timezone."""
    return instant.astimezone(tz).strftime("%a %d %b %Y, %H:%M")


async def list_mine(db: AsyncSession, principal: Principal, limit: int = 20) -> list[Notification]:
    query = (
        select(Notification)
        .where(Notification.user_id == principal.user_id)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(min(limit, MAX_LIST))
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
