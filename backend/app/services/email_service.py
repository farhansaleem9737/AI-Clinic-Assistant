"""Outgoing email (D87, D109). One small abstraction over the configured backend.

* smtp: the message is handed to SMTP_HOST over TLS: STARTTLS (587) or
  implicit TLS (SMTP_SSL, 465), certificates verified, with timeouts.
  ``sent`` means the server accepted it for delivery; any refusal or network
  error is ``failed``. Plaintext is refused by the settings (a local test
  server only, explicitly). A server that does not offer STARTTLS is an error,
  never a silent fallback.
* outbox (development only): the message is written to a file in
  EMAIL_OUTBOX_DIR. It is never logged and never returned by the API, so a
  link in it reaches only someone with access to the developer's disk.
* none: nothing is sent and the caller is told so.

Bodies are never logged (invitation links in them are credentials), nor are
passwords; failures are recorded as an error class and SMTP code only.
"""

import asyncio
import logging
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import make_msgid
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
    html: str | None = None  # an HTML alternative to the plain text


class DeliveryError(Exception):
    """A send that did not succeed. `permanent`: trying again cannot help
    (e.g. the address was refused); otherwise it may later. `reason` is safe to
    store and log: an error class and SMTP code, never server text or secrets."""

    def __init__(self, reason: str, *, permanent: bool):
        super().__init__(reason)
        self.reason = reason
        self.permanent = permanent


def _message(email: Email) -> EmailMessage:
    message = EmailMessage()
    message["From"] = settings.email_from
    message["To"] = email.to
    message["Subject"] = email.subject
    message["Message-ID"] = make_msgid(domain=settings.email_from.rsplit("@", 1)[-1].strip(">") or None)
    message.set_content(email.text)
    if email.html:
        message.add_alternative(email.html, subtype="html")
    return message


def _tls_context() -> ssl.SSLContext:
    # Certificate and host name verified; TLS 1.2 or newer.
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def _send_smtp(message: EmailMessage) -> None:
    timeout = settings.smtp_timeout_seconds
    if settings.smtp_ssl:
        smtp = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=timeout, context=_tls_context())
    else:
        smtp = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=timeout)
    with smtp:
        if settings.smtp_starttls and not settings.smtp_ssl:
            smtp.starttls(context=_tls_context())  # raises if the server does not offer it
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password.get_secret_value())
        refused = smtp.send_message(message)
        if refused:
            raise smtplib.SMTPRecipientsRefused(refused)


def _write_outbox(message: EmailMessage) -> None:
    folder = settings.email_outbox_dir
    folder.mkdir(parents=True, exist_ok=True)
    stamp = clock.utcnow().strftime("%Y%m%dT%H%M%S%f")
    (folder / f"{stamp}.eml").write_bytes(bytes(message))


def _classify(exc: Exception) -> DeliveryError:
    name = type(exc).__name__
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        codes = sorted({code for code, _ in exc.recipients.values()})
        return DeliveryError(f"{name} {codes[0] if codes else ''}".strip(), permanent=all(500 <= c < 600 for c in codes))
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        # Wrong credentials are the operator's to fix; the message waits for it.
        return DeliveryError(f"{name} {exc.smtp_code}", permanent=False)
    if isinstance(exc, (smtplib.SMTPSenderRefused, smtplib.SMTPDataError)):
        code = exc.smtp_code
        return DeliveryError(f"{name} {code}", permanent=500 <= code < 600)
    if isinstance(exc, smtplib.SMTPResponseException):
        return DeliveryError(f"{name} {exc.smtp_code}", permanent=False)
    # Timeouts, refused connections, TLS failures, a missing STARTTLS: try again later.
    return DeliveryError(name, permanent=False)


async def deliver(email: Email) -> Delivery:
    """Send through the configured backend, raising DeliveryError on failure (the outbox retries)."""
    backend = settings.effective_email_backend
    if backend is EmailBackend.none:
        return Delivery.not_configured
    message = _message(email)
    try:
        if backend is EmailBackend.outbox:
            await asyncio.to_thread(_write_outbox, message)
            return Delivery.outbox
        await asyncio.to_thread(_send_smtp, message)
    except (OSError, smtplib.SMTPException) as exc:
        raise _classify(exc) from None
    return Delivery.sent


async def send(email: Email) -> Delivery:
    """Send now and report the outcome (admin invitations, whose result the admin sees at once)."""
    try:
        delivery = await deliver(email)
    except DeliveryError as exc:
        logger.warning("email_failed", extra={"subject": email.subject, "error": exc.reason})
        return Delivery.failed
    if delivery is Delivery.not_configured:
        logger.warning("email_not_configured", extra={"subject": email.subject})
    elif delivery is Delivery.outbox:
        logger.info("email_written_to_outbox", extra={"subject": email.subject})
    else:
        logger.info("email_sent", extra={"subject": email.subject})
    return delivery
