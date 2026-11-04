"""Notification email: SMTP transport, the outbox, workflows and privacy (D109).

No real email is sent: the SMTP server is a fake in this process, and the
default test backend writes files to a temporary folder.
"""

import logging
import smtplib
import ssl
from datetime import datetime, timedelta
from email import message_from_bytes
from email.policy import default as default_policy

import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy import select

from app.core.config import EmailBackend, Environment, Settings, settings
from app.models.email import EmailOutbox
from app.services import email_outbox_service, email_service, email_templates, reminder_service

DB = "postgresql+asyncpg://u:p@h/db"
PASSWORD = "smtp-pass-DO-NOT-LOG"


def iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


class FakeSMTP:
    """Stands in for smtplib.SMTP / SMTP_SSL; records what the client did."""

    instances: list["FakeSMTP"] = []
    failure: Exception | None = None

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port, self.timeout, self.context = host, port, timeout, context
        self.tls = None
        self.logged_in = None
        self.sent = []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context):
        self.tls = context

    def login(self, user, password):
        if isinstance(FakeSMTP.failure, smtplib.SMTPAuthenticationError):
            raise FakeSMTP.failure
        self.logged_in = (user, password)

    def send_message(self, message):
        if FakeSMTP.failure is not None:
            raise FakeSMTP.failure
        self.sent.append(message)
        return {}


@pytest.fixture
def smtp(monkeypatch):
    FakeSMTP.instances, FakeSMTP.failure = [], None
    monkeypatch.setattr(email_service.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(email_service.smtplib, "SMTP_SSL", FakeSMTP)
    for name, value in {
        "email_backend": EmailBackend.smtp, "smtp_host": "smtp.example.com", "smtp_port": 587, "smtp_starttls": True,
        "smtp_ssl": False, "smtp_username": "apikey", "smtp_password": SecretStr(PASSWORD), "smtp_timeout_seconds": 7,
        "email_from": "Clinic AI Assistant <no-reply@clinic.example>",
    }.items():
        monkeypatch.setattr(settings, name, value)
    return FakeSMTP


EMAIL = email_service.Email(to="alice@example.com", subject="Hi", text="Plain", html="<p>Rich</p>")


# ---- configuration -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides, error",
    [
        ({"smtp_starttls": False, "smtp_ssl": False}, "without TLS is refused"),
        ({"smtp_ssl": True, "smtp_starttls": True}, "Choose one"),
        ({"smtp_port": 465, "smtp_starttls": True}, "Port 465 uses implicit TLS"),
        ({"smtp_username": "apikey"}, "go together"),
        ({"email_from": "not an address"}, "EMAIL_FROM"),
        ({"email_backend": "smtp", "smtp_host": None}, "needs SMTP_HOST"),
    ],
)
def test_unsafe_or_incomplete_smtp_settings_are_refused(overrides, error):
    values = {"database_url": DB, "smtp_host": "smtp.example.com", **overrides}
    with pytest.raises(ValidationError, match=error):
        Settings(**values)


def test_plaintext_only_to_a_local_test_server_and_only_when_asked():
    Settings(database_url=DB, smtp_host="localhost", smtp_port=1025, smtp_starttls=False, smtp_allow_plaintext_localhost=True)
    with pytest.raises(ValidationError):
        Settings(database_url=DB, smtp_host="mail.example.com", smtp_starttls=False, smtp_allow_plaintext_localhost=True)


def test_missing_smtp_settings_mean_no_email_outside_development(monkeypatch):
    monkeypatch.setattr(settings, "email_backend", None)
    monkeypatch.setattr(settings, "environment", Environment.production)
    monkeypatch.setattr(settings, "smtp_host", None)
    assert settings.effective_email_backend is EmailBackend.none


# ---- the SMTP transport --------------------------------------------------------------------


async def test_starttls_with_verified_certificates_then_login_then_send(smtp):
    assert await email_service.deliver(EMAIL) is email_service.Delivery.sent
    [server] = smtp.instances
    assert (server.host, server.port, server.timeout) == ("smtp.example.com", 587, 7)
    assert server.tls.verify_mode is ssl.CERT_REQUIRED and server.tls.check_hostname
    assert server.tls.minimum_version >= ssl.TLSVersion.TLSv1_2
    assert server.logged_in == ("apikey", PASSWORD)
    [message] = server.sent
    parsed = message_from_bytes(bytes(message), policy=default_policy)
    assert parsed.get_body(("plain",)).get_content().strip() == "Plain"
    assert parsed.get_body(("html",)).get_content().strip() == "<p>Rich</p>"
    assert parsed["Message-ID"] and parsed["From"] == "Clinic AI Assistant <no-reply@clinic.example>"


async def test_implicit_tls_on_port_465(smtp, monkeypatch):
    monkeypatch.setattr(settings, "smtp_ssl", True)
    monkeypatch.setattr(settings, "smtp_starttls", False)
    monkeypatch.setattr(settings, "smtp_port", 465)
    await email_service.deliver(EMAIL)
    [server] = smtp.instances
    assert server.port == 465 and server.context.verify_mode is ssl.CERT_REQUIRED and server.tls is None


@pytest.mark.parametrize(
    "failure, reason, permanent",
    [
        (smtplib.SMTPAuthenticationError(535, b"5.7.8 bad credentials for apikey"), "SMTPAuthenticationError 535", False),
        (TimeoutError("timed out"), "TimeoutError", False),
        (smtplib.SMTPDataError(451, b"try later"), "SMTPDataError 451", False),
        (smtplib.SMTPRecipientsRefused({"alice@example.com": (550, b"no such user")}), "SMTPRecipientsRefused 550", True),
        (smtplib.SMTPNotSupportedError("STARTTLS extension not supported"), "SMTPNotSupportedError", False),
    ],
)
async def test_failures_are_classified_without_server_text_or_secrets(smtp, failure, reason, permanent, caplog):
    smtp.failure = failure
    with pytest.raises(email_service.DeliveryError) as err:
        await email_service.deliver(EMAIL)
    assert err.value.reason == reason and err.value.permanent is permanent
    with caplog.at_level(logging.DEBUG):
        assert await email_service.send(EMAIL) is email_service.Delivery.failed
    assert PASSWORD not in caplog.text and "bad credentials" not in caplog.text and "Plain" not in caplog.text


# ---- templates -----------------------------------------------------------------------------


def test_templates_escape_values_and_come_with_plain_text():
    out = email_templates.render(
        "appointment_booked",
        {"name": "<script>x</script>", "when": "Fri 23 Apr 2027, 10:00", "doctor": "Dr. A & B", "department": "Cardiology", "link": "/appointments"},
    )
    assert out.subject == "Your appointment is booked"
    assert "<script>" not in out.html and "&lt;script&gt;" in out.html and "Dr. A &amp; B" in out.html
    assert "When: Fri 23 Apr 2027, 10:00" in out.text and "Doctor: Dr. A & B" in out.text
    assert f"{settings.frontend_base_url}/appointments" in out.text
    # Links only to pages of the app.
    assert email_templates.app_url("https://evil.example") is None


# ---- workflows → outbox --------------------------------------------------------------------


async def book(client, clinic, headers, days=2, hhmm="10:00", reason=None):
    body = {"doctor_id": str(clinic.doctor_a.id), "starts_at": iso(clinic.slot(days, hhmm))}
    if reason:
        body["reason"] = reason
    response = await client.post("/api/v1/appointments/", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def outbox(db, user_id=None):
    query = select(EmailOutbox).order_by(EmailOutbox.created_at)
    if user_id is not None:
        query = query.where(EmailOutbox.user_id == user_id)
    return list((await db.scalars(query)).all())


async def test_booking_cancelling_and_rescheduling_queue_the_patients_emails_only(client, clinic, db_session):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    first = await book(client, clinic, alice, days=2, reason="Chest pain, private")
    second = await book(client, clinic, alice, days=3)
    await client.post(f"/api/v1/appointments/{first['id']}/status", json={"status": "cancelled", "cancellation_reason": "patient_request"}, headers=alice)
    moved = await client.post(f"/api/v1/appointments/{second['id']}/reschedule", json={"starts_at": iso(clinic.slot(4, "11:00"))}, headers=alice)
    assert moved.status_code == 201
    mails = await outbox(db_session)
    assert [m.kind for m in mails] == ["appointment_booked", "appointment_booked", "appointment_cancelled", "appointment_rescheduled"]
    assert {m.user_id for m in mails} == {clinic.patient_a.user_id}  # doctors get in-app notifications only
    for m in mails:
        assert "Chest pain" not in m.text_body + m.html_body  # never the reason for the visit
    rescheduled = mails[-1]
    assert "was moved" in rescheduled.text_body and "11:00" in rescheduled.text_body
    assert f"/appointments/{moved.json()['id']}" in rescheduled.text_body


async def test_the_clinic_confirming_emails_the_patient(client, clinic, db_session):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    appt = await book(client, clinic, alice)
    reception = await clinic.headers_for(clinic.receptionist.id)
    await client.post(f"/api/v1/appointments/{appt['id']}/status", json={"status": "confirmed"}, headers=reception)
    assert [m.kind for m in await outbox(db_session)] == ["appointment_booked", "appointment_confirmed"]


async def test_preferences_and_inactive_accounts_are_respected(client, clinic, db_session):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    await client.put("/api/v1/notifications/preferences", json={"emails": False}, headers=alice)
    await book(client, clinic, alice)
    bob = await clinic.headers_for(clinic.patient_b.user_id)
    await client.put("/api/v1/notifications/preferences", json={"appointment_updates": False}, headers=bob)
    await book(client, clinic, bob, days=3)
    assert await outbox(db_session) == []


async def test_reminder_emails_for_the_24_hour_reminder_once(client, clinic, db_session):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    appt = await book(client, clinic, alice, days=2)
    starts = datetime.fromisoformat(appt["starts_at"].replace("Z", "+00:00"))
    await reminder_service.run(db_session, now=starts - timedelta(hours=23))
    await reminder_service.run(db_session, now=starts - timedelta(hours=22))  # repeated run
    await reminder_service.run(db_session, now=starts - timedelta(minutes=50))  # the 1-hour one: in-app only
    reminders = [m for m in await outbox(db_session) if m.kind == "appointment_reminder"]
    assert len(reminders) == 1 and reminders[0].subject.startswith("Reminder: your appointment on")
    assert reminders[0].expires_at == starts


async def test_nothing_is_queued_when_email_is_switched_off(client, clinic, db_session, monkeypatch):
    monkeypatch.setattr(settings, "email_backend", EmailBackend.none)
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    await book(client, clinic, alice)
    assert await outbox(db_session) == []
    assert email_outbox_service.OutboxResult() == await email_outbox_service.run(db_session)


# ---- the outbox run ------------------------------------------------------------------------


async def test_the_run_sends_once_clears_bodies_and_never_takes_a_claimed_row_twice(client, clinic, db_session, smtp):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    await book(client, clinic, alice)
    # A second run while the first holds its claim finds nothing to do.
    claimed = await email_outbox_service._claim(db_session, datetime.now().astimezone())
    assert len(claimed) == 1 and claimed[0].status == "sending"
    assert await email_outbox_service._claim(db_session, datetime.now().astimezone()) == []
    # After the lease runs out (the claiming instance died), it is taken over and sent.
    later = datetime.now().astimezone() + email_outbox_service.LEASE + timedelta(seconds=1)
    result = await email_outbox_service.run(db_session, now=later)
    assert result.sent == 1
    [row] = await outbox(db_session)
    assert row.status == "sent" and row.sent_at and row.text_body == "" and row.html_body == "" and row.attempts == 2
    [server] = [s for s in smtp.instances if s.sent]
    assert server.sent[0]["To"] == row.to_address and server.sent[0]["Subject"] == "Your appointment is booked"
    assert (await email_outbox_service.run(db_session, now=later)).sent == 0  # never again


async def test_temporary_failures_back_off_then_give_up_and_permanent_ones_stop_at_once(client, clinic, db_session, smtp, monkeypatch, caplog):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    await book(client, clinic, alice)
    monkeypatch.setattr(settings, "email_max_attempts", 3)
    smtp.failure = smtplib.SMTPAuthenticationError(535, PASSWORD.encode())
    now = datetime.now().astimezone()
    with caplog.at_level(logging.DEBUG):
        first = await email_outbox_service.run(db_session, now=now)
    [row] = await outbox(db_session)
    await db_session.refresh(row)
    assert first.retrying == 1 and row.status == "pending" and row.attempts == 1
    assert row.next_attempt_at == now + timedelta(minutes=1) and row.last_error == "SMTPAuthenticationError 535"
    assert PASSWORD not in caplog.text and PASSWORD not in (row.last_error or "")
    # Not due yet: nothing happens.
    assert (await email_outbox_service.run(db_session, now=now + timedelta(seconds=30))).retrying == 0
    await email_outbox_service.run(db_session, now=now + timedelta(minutes=2))
    final = await email_outbox_service.run(db_session, now=now + timedelta(minutes=30))
    await db_session.refresh(row)
    assert final.failed == 1 and row.status == "failed" and row.attempts == 3

    bob = await clinic.headers_for(clinic.patient_b.user_id)
    await book(client, clinic, bob, days=3)
    smtp.failure = smtplib.SMTPRecipientsRefused({"bob@example.com": (550, b"no such user")})
    assert (await email_outbox_service.run(db_session, now=now + timedelta(hours=1))).failed == 1


async def test_a_reminder_that_could_not_be_sent_in_time_expires(client, clinic, db_session):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    appt = await book(client, clinic, alice)
    starts = datetime.fromisoformat(appt["starts_at"].replace("Z", "+00:00"))
    result = await email_outbox_service.run(db_session, now=starts + timedelta(minutes=1))
    assert result.expired == 1 and (await outbox(db_session))[0].status == "expired"


async def test_development_writes_files_and_never_reports_them_as_sent(client, clinic, db_session, isolated_side_channels):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    await book(client, clinic, alice)
    result = await email_outbox_service.run(db_session, now=datetime.now().astimezone())
    assert result.written == 1 and result.sent == 0
    [row] = await outbox(db_session)
    assert row.status == "written"
    [file] = isolated_side_channels.glob("*.eml")
    parsed = message_from_bytes(file.read_bytes(), policy=default_policy)
    assert parsed["Subject"] == "Your appointment is booked" and parsed.get_body(("html",)) is not None
