"""Endpoints for the platform, not for users (D108).

POST /internal/reminders/run is called by Cloud Scheduler every few minutes:
it creates due reminders, then sends what is waiting in the email outbox.
The Cloud Run service itself stays public (the frontend calls it), so this
endpoint checks its caller:

- in production, a Google-signed OIDC ID token (Authorization: Bearer) whose
  audience is REMINDERS_OIDC_AUDIENCE and whose e-mail is the scheduler's
  service account, REMINDERS_INVOKER_EMAIL;
- otherwise (development, another scheduler), the shared secret
  REMINDERS_CRON_SECRET in the X-Reminders-Secret header.

With neither configured the endpoint does not exist (404). A run is
idempotent: repeating, retrying or overlapping it creates nothing twice.
"""

import hmac
import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.exceptions import AuthenticationError, NotFoundError
from app.db.session import get_db
from app.schemas.follow_up import ReminderRunRead
from app.services import email_outbox_service, reminder_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal", tags=["internal"], include_in_schema=False)


def _verify_google_token(token: str) -> dict:
    # Imported here: only the reminder run needs it, and it fetches Google's
    # public keys over the network (blocking, so it runs in a thread).
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    return id_token.verify_oauth2_token(token, google_requests.Request(), audience=settings.reminders_oidc_audience)


async def require_scheduler(request: Request) -> None:
    secret = settings.reminders_cron_secret
    oidc = settings.reminders_oidc_audience and settings.reminders_invoker_email
    if not secret and not oidc:
        raise NotFoundError("Not found")
    sent = request.headers.get("X-Reminders-Secret")
    if secret and sent and hmac.compare_digest(sent.encode(), secret.get_secret_value().encode()):
        return
    auth = request.headers.get("Authorization", "")
    if oidc and auth.startswith("Bearer "):
        try:
            claims = await run_in_threadpool(_verify_google_token, auth.removeprefix("Bearer ").strip())
        except Exception:  # invalid, expired, wrong audience, or keys unreachable
            claims = None
        if claims and claims.get("email_verified") and claims.get("email") == settings.reminders_invoker_email:
            return
    logger.warning("reminder_run_refused")
    raise AuthenticationError("Not allowed to run reminders")


@router.post("/reminders/run", response_model=ReminderRunRead, dependencies=[Depends(require_scheduler)])
async def run_reminders(db: AsyncSession = Depends(get_db)):
    """The reminders, then the email outbox (D109): one scheduled job does both."""
    reminders = await reminder_service.run(db)
    emails = await email_outbox_service.run(db)
    return ReminderRunRead(**vars(reminders), **{f"emails_{k}": v for k, v in vars(emails).items()})
