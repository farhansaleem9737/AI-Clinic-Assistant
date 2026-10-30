"""Outgoing email (D87). One small abstraction over the configured backend.

* smtp: the message is handed to SMTP_HOST. ``sent`` means the server
  accepted it for delivery; any refusal or network error is ``failed``.
* outbox (development only): the message is written to a file in
  EMAIL_OUTBOX_DIR. It is never logged and never returned by the API, so a
  link in it reaches only someone with access to the developer's disk.
* none: nothing is sent and the caller is told so.

The message body is never logged: invitation links in it are credentials.
"""

import asyncio
import logging
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from enum import StrEnum

from app.core import clock
from app.core.config import EmailBackend, settings

logger = logging.getLogger(__name__)


class Delivery(StrEnum):
    sent = "sent"
    outbox = "outbox"
    failed = "failed"
    not_configured = "not_configured"


@dataclass(frozen=True)
class Email:
    to: str
    subject: str
    text: str


def _message(email: Email) -> EmailMessage:
    message = EmailMessage()
    message["From"] = settings.email_from
    message["To"] = email.to
    message["Subject"] = email.subject
    message.set_content(email.text)
    return message


def _send_smtp(message: EmailMessage) -> None:
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_seconds) as smtp:
        if settings.smtp_starttls:
            smtp.starttls(context=ssl.create_default_context())
        if settings.smtp_username:
            password = settings.smtp_password.get_secret_value() if settings.smtp_password else ""
            smtp.login(settings.smtp_username, password)
        refused = smtp.send_message(message)
        if refused:
            raise smtplib.SMTPRecipientsRefused(refused)


def _write_outbox(message: EmailMessage) -> None:
    folder = settings.email_outbox_dir
    folder.mkdir(parents=True, exist_ok=True)
    stamp = clock.utcnow().strftime("%Y%m%dT%H%M%S%f")
    (folder / f"{stamp}.eml").write_bytes(bytes(message))


async def send(email: Email) -> Delivery:
    backend = settings.effective_email_backend
    if backend is EmailBackend.none:
        logger.warning("email_not_configured", extra={"subject": email.subject})
        return Delivery.not_configured
    message = _message(email)
    try:
        if backend is EmailBackend.outbox:
            await asyncio.to_thread(_write_outbox, message)
            logger.info("email_written_to_outbox", extra={"subject": email.subject})
            return Delivery.outbox
        await asyncio.to_thread(_send_smtp, message)
    except (OSError, smtplib.SMTPException) as exc:
        # The exception text may echo addresses but never the body.
        logger.warning("email_failed", extra={"subject": email.subject, "error": type(exc).__name__})
        return Delivery.failed
    logger.info("email_sent", extra={"subject": email.subject})
    return Delivery.sent
