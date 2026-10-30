"""AI usage records and limits (D100).

Every message that reaches the provider is recorded (tokens, model, tool
calls; never content) and counted against configurable limits: per user per
minute and per clinic day, and for the whole server. 0 disables a limit.
The per-user check holds a transaction-scoped advisory lock (namespace 5)
for the rest of the request, so one user's parallel requests cannot both
slip under the limit. The server-wide limits count finished requests, so
requests still in flight at the same moment can exceed them by a few.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.config import settings
from app.core.exceptions import RateLimitedError
from app.core.permissions import Principal
from app.models.ai import AiUsage

logger = logging.getLogger(__name__)

_USER_LOCK = 5


@dataclass(frozen=True)
class UsageSummary:
    requests_today: int
    daily_limit: int
    remaining_today: int | None
    per_minute_limit: int
    input_tokens_today: int
    output_tokens_today: int
    resets_at: datetime


def _day_start(now: datetime) -> datetime:
    tz = ZoneInfo(settings.clinic_timezone)
    return datetime.combine(now.astimezone(tz).date(), time.min, tzinfo=tz)


async def _count(db: AsyncSession, since: datetime, user_id=None) -> int:
    query = select(func.count()).select_from(AiUsage).where(AiUsage.created_at >= since)
    if user_id is not None:
        query = query.where(AiUsage.user_id == user_id)
    return await db.scalar(query) or 0


async def check_limits(db: AsyncSession, principal: Principal) -> None:
    """Raise RateLimitedError (429) when this request would go over a limit."""
    await db.execute(text("SELECT pg_advisory_xact_lock(:ns, hashtext(:key))"), {"ns": _USER_LOCK, "key": str(principal.user_id)})
    now = clock.utcnow()
    minute_ago = now - timedelta(minutes=1)
    day_start = _day_start(now)
    checks = (
        (settings.ai_rate_limit_per_minute, minute_ago, principal.user_id, "AI_USER_RATE_LIMITED",
         "You're sending messages quickly. Please wait a minute and try again."),
        (settings.ai_daily_request_limit, day_start, principal.user_id, "AI_USER_DAILY_LIMIT",
         "You've reached today's limit for assistant messages. It resets tomorrow."),
        (settings.ai_global_rate_limit_per_minute, minute_ago, None, "AI_SERVER_BUSY",
         "The assistant is busy right now. Please try again in a minute."),
        (settings.ai_global_daily_request_limit, day_start, None, "AI_SERVER_DAILY_LIMIT",
         "The assistant has reached its usage limit for today. Please try again tomorrow."),
    )
    for limit, since, user_id, code, message in checks:
        if limit and await _count(db, since, user_id) >= limit:
            logger.info("ai_limit_reached", extra={"code": code, "user_id": str(principal.user_id)})
            raise RateLimitedError(message, code=code)


def record(
    db: AsyncSession,
    user_id,
    *,
    status: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    model_requests: int = 0,
    tool_calls: int = 0,
    error_code: str | None = None,
) -> AiUsage:
    """Add (not commit) one usage row; the caller's transaction commits it.
    Takes the user id, not the Principal: it is also called after a rollback,
    when the Principal's user row is expired."""
    row = AiUsage(
        user_id=user_id,
        provider=settings.ai_provider.value,
        model=(settings.ai_model_name or "")[:100],
        status=status,
        error_code=error_code,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model_requests=model_requests,
        tool_calls=tool_calls,
    )
    db.add(row)
    if settings.ai_log_token_usage:
        logger.info(
            "ai_usage",
            extra={
                "user_id": str(user_id), "model": row.model, "status": status, "input_tokens": input_tokens,
                "output_tokens": output_tokens, "model_requests": model_requests, "tool_calls": tool_calls,
            },
        )
    return row


async def summary(db: AsyncSession, principal: Principal) -> UsageSummary:
    now = clock.utcnow()
    day_start = _day_start(now)
    count, tokens_in, tokens_out = (
        await db.execute(
            select(func.count(), func.coalesce(func.sum(AiUsage.input_tokens), 0), func.coalesce(func.sum(AiUsage.output_tokens), 0))
            .where(AiUsage.user_id == principal.user_id, AiUsage.created_at >= day_start)
        )
    ).one()
    limit = settings.ai_daily_request_limit
    return UsageSummary(
        requests_today=count,
        daily_limit=limit,
        remaining_today=max(0, limit - count) if limit else None,
        per_minute_limit=settings.ai_rate_limit_per_minute,
        input_tokens_today=int(tokens_in),
        output_tokens_today=int(tokens_out),
        resets_at=day_start + timedelta(days=1),
    )
