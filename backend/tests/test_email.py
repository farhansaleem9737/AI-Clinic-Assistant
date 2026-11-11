"""Notification email: SMTP transport, the outbox, workflows and privacy (D109).

No real email is sent: the SMTP server is a fake in this process, and the
default test backend writes files to a temporary folder.
"""

import logging
import smtplib
import socket
import uuid
import ssl
from datetime import datetime, timedelta
from email import message_from_bytes
from email.policy import default as default_policy

import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy import select

from app.core.config import EmailBackend, Environment, Settings, settings
from app.models.email import EmailOutbox
from app.models.user import User
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

    def noop(self):
        self.nooped = True

    def close(self):
        pass

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
        ({"smtp_username": "apikey", "smtp_password": None}, "go together"),  # explicit: a local .env may set one
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
    monkeypatch.setattr(settings, "brevo_api_key", None)  # a local .env may set one
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
        (socket.gaierror(11001, "getaddrinfo failed"), "gaierror 11001", False),  # DNS: which network error it was
        (ConnectionRefusedError(10061, "refused"), "ConnectionRefusedError 10061", False),
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
    assert out.subject == "Your appointment is booked — Clinic AI Assistant"
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


async def quiet_doctor(client, clinic):
    """Doctor A gets no email: the run tests below count the patient's only."""
    headers = await clinic.headers_for(clinic.doctor_a.user_id)
    response = await client.put("/api/v1/notifications/preferences", json={"emails": False}, headers=headers)
    assert response.status_code == 200, response.text


async def outbox(db, user_id=None):
    query = select(EmailOutbox).order_by(EmailOutbox.created_at)
    if user_id is not None:
        query = query.where(EmailOutbox.user_id == user_id)
    return list((await db.scalars(query)).all())


async def test_booking_cancelling_and_rescheduling_email_the_patient_and_the_doctor(client, clinic, db_session):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    first = await book(client, clinic, alice, days=2, reason="Chest pain, private")
    second = await book(client, clinic, alice, days=3)
    await client.post(f"/api/v1/appointments/{first['id']}/status", json={"status": "cancelled", "cancellation_reason": "patient_request"}, headers=alice)
    moved = await client.post(f"/api/v1/appointments/{second['id']}/reschedule", json={"starts_at": iso(clinic.slot(4, "11:00"))}, headers=alice)
    assert moved.status_code == 201
    mine = await outbox(db_session, clinic.patient_a.user_id)
    assert [m.kind for m in mine] == ["appointment_booked", "appointment_booked", "appointment_cancelled", "appointment_rescheduled"]
    doctors = await outbox(db_session, clinic.doctor_a.user_id)
    assert [m.kind for m in doctors] == [
        "doctor_appointment_booked", "doctor_appointment_booked", "doctor_appointment_cancelled", "doctor_appointment_rescheduled",
    ]
    for m in mine + doctors:
        assert "Chest pain" not in m.text_body + m.html_body  # never the reason for the visit
    for m in doctors:
        assert "Alice" not in m.text_body + m.html_body  # nor the patient's name
    rescheduled = mine[-1]
    assert "rescheduled" in rescheduled.text_body and "11:00 (Asia/Karachi)" in rescheduled.text_body
    assert f"{settings.frontend_base_url}/appointments/{moved.json()['id']}" in rescheduled.text_body
    # The first booking was cancelled before its receipt went out: that receipt is withdrawn, the cancellation stays.
    receipt = next(m for m in mine if m.dedupe_key == f"appointment_booked:{first['id']}")
    assert receipt.status == "expired" and receipt.text_body == ""
    assert next(m for m in mine if m.kind == "appointment_cancelled").status == "pending"


async def test_the_booking_email_has_the_real_details_and_status(client, clinic, db_session):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    appt = await book(client, clinic, alice, days=2, hhmm="14:30")
    [mail] = await outbox(db_session, clinic.patient_a.user_id)
    assert mail.to_address == (await db_session.get(User, clinic.patient_a.user_id)).email  # their registered address
    doctor = await db_session.get(User, clinic.doctor_a.user_id)
    local = clinic.slot(2, "14:30").astimezone(clinic.tz)
    label = email_templates.status_label(appt["status"])
    for body in (mail.text_body, mail.html_body):
        assert doctor.name in body and local.strftime("%A %d %B %Y") in body and "14:30 (Asia/Karachi)" in body
        assert label in body and clinic.department.name in body
    if appt["status"] != "confirmed":
        assert "confirmed" not in mail.subject.lower()  # never claims more than the database says
    assert f"Status: {label}" in mail.text_body
    assert f'href="{settings.frontend_base_url}/appointments/{appt["id"]}"' in mail.html_body
    assert "token" not in mail.html_body.lower()  # the link carries no credentials


async def test_a_doctor_is_not_emailed_about_their_own_change(client, clinic, db_session):
    from app.models.appointment import Appointment

    alice = await clinic.headers_for(clinic.patient_a.user_id)
    appt = await book(client, clinic, alice)
    row = await db_session.get(Appointment, uuid.UUID(appt["id"]))
    await email_outbox_service.appointment_email(db_session, row, "appointment_cancelled", actor=clinic.doctor_a.user_id)
    await db_session.commit()
    kinds = [m.kind for m in await outbox(db_session, clinic.doctor_a.user_id)]
    assert kinds == ["doctor_appointment_booked"]


async def test_cancelling_withdraws_unsent_reminders(client, clinic, db_session):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    appt = await book(client, clinic, alice, days=2)
    starts = datetime.fromisoformat(appt["starts_at"].replace("Z", "+00:00"))
    await reminder_service.run(db_session, now=starts - timedelta(hours=23))
    await client.post(f"/api/v1/appointments/{appt['id']}/status", json={"status": "cancelled", "cancellation_reason": "patient_request"}, headers=alice)
    by_kind = {m.kind: m.status for m in await outbox(db_session, clinic.patient_a.user_id)}
    assert by_kind == {"appointment_booked": "expired", "appointment_reminder": "expired", "appointment_cancelled": "pending"}


async def test_the_clinic_confirming_emails_the_patient(client, clinic, db_session):
    await quiet_doctor(client, clinic)
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
    patients = {clinic.patient_a.user_id, clinic.patient_b.user_id}
    assert [m for m in await outbox(db_session) if m.user_id in patients] == []


async def test_reminder_emails_for_each_reminder_once(client, clinic, db_session):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    appt = await book(client, clinic, alice, days=2)
    starts = datetime.fromisoformat(appt["starts_at"].replace("Z", "+00:00"))
    await reminder_service.run(db_session, now=starts - timedelta(hours=23))
    await reminder_service.run(db_session, now=starts - timedelta(hours=22))  # repeated run
    await reminder_service.run(db_session, now=starts - timedelta(minutes=50))  # the 1-hour one
    await reminder_service.run(db_session, now=starts - timedelta(minutes=40))  # repeated run
    reminders = [m for m in await outbox(db_session) if m.kind == "appointment_reminder"]
    assert len(reminders) == 2 and all(m.subject.startswith("Reminder: your appointment on") for m in reminders)
    assert all(m.expires_at == starts for m in reminders)


async def test_reminder_emails_only_for_the_configured_offsets(client, clinic, db_session, monkeypatch):
    monkeypatch.setattr(settings, "email_reminder_offsets_minutes", [1440])
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    appt = await book(client, clinic, alice, days=2)
    starts = datetime.fromisoformat(appt["starts_at"].replace("Z", "+00:00"))
    await reminder_service.run(db_session, now=starts - timedelta(hours=23))
    await reminder_service.run(db_session, now=starts - timedelta(minutes=50))  # the 1-hour one: in-app only
    reminders = [m for m in await outbox(db_session) if m.kind == "appointment_reminder"]
    assert len(reminders) == 1


async def test_nothing_is_queued_when_email_is_switched_off(client, clinic, db_session, monkeypatch):
    monkeypatch.setattr(settings, "email_backend", EmailBackend.none)
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    await book(client, clinic, alice)
    assert await outbox(db_session) == []
    assert email_outbox_service.OutboxResult() == await email_outbox_service.run(db_session)


# ---- the outbox run ------------------------------------------------------------------------


async def test_the_run_sends_once_clears_bodies_and_never_takes_a_claimed_row_twice(client, clinic, db_session, smtp):
    await quiet_doctor(client, clinic)
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
    assert server.sent[0]["To"] == row.to_address and server.sent[0]["Subject"].startswith("Your appointment")
    assert (await email_outbox_service.run(db_session, now=later)).sent == 0  # never again


async def test_temporary_failures_back_off_then_give_up_and_permanent_ones_stop_at_once(client, clinic, db_session, smtp, monkeypatch, caplog):
    await quiet_doctor(client, clinic)
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
    await quiet_doctor(client, clinic)
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    appt = await book(client, clinic, alice)
    starts = datetime.fromisoformat(appt["starts_at"].replace("Z", "+00:00"))
    result = await email_outbox_service.run(db_session, now=starts + timedelta(minutes=1))
    assert result.expired == 1 and (await outbox(db_session))[0].status == "expired"


async def test_development_writes_files_and_never_reports_them_as_sent(client, clinic, db_session, isolated_side_channels):
    await quiet_doctor(client, clinic)
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    await book(client, clinic, alice)
    result = await email_outbox_service.run(db_session, now=datetime.now().astimezone())
    assert result.written == 1 and result.sent == 0
    [row] = await outbox(db_session)
    assert row.status == "written"
    [file] = isolated_side_channels.glob("*.eml")
    parsed = message_from_bytes(file.read_bytes(), policy=default_policy)
    assert parsed["Subject"].startswith("Your appointment") and parsed.get_body(("html",)) is not None


# ---- setup checks (D124) -------------------------------------------------------------------


async def test_the_connection_check_logs_in_and_sends_nothing(smtp):
    await email_service.check_connection()
    [server] = smtp.instances
    assert server.logged_in == ("apikey", PASSWORD) and server.nooped and server.sent == []


async def test_the_connection_check_reports_a_safe_reason(smtp):
    smtp.failure = smtplib.SMTPAuthenticationError(535, PASSWORD.encode())
    with pytest.raises(email_service.DeliveryError) as err:
        await email_service.check_connection()
    assert err.value.reason == "SMTPAuthenticationError 535" and PASSWORD not in str(err.value)


@pytest.mark.parametrize("url", ["http://clinic.example", "https://localhost:5173"])
def test_production_email_links_must_be_public_https(url):
    with pytest.raises(ValidationError, match="FRONTEND_BASE_URL"):
        Settings(database_url=DB, environment="production", frontend_base_url=url)


async def test_a_failed_send_sets_a_wake_up_for_its_retry(monkeypatch):
    fired = []
    monkeypatch.setattr(email_outbox_service, "_start_kick", lambda: fired.append(True))
    monkeypatch.setattr(email_outbox_service, "_retry_timer", None)
    email_outbox_service._retry_at(datetime.now().astimezone() + timedelta(hours=7))  # the scheduled run's job
    assert email_outbox_service._retry_timer is None
    email_outbox_service._retry_at(datetime.now().astimezone() + timedelta(minutes=5))
    timer = email_outbox_service._retry_timer
    assert timer is not None
    email_outbox_service._retry_at(datetime.now().astimezone() + timedelta(minutes=15))  # a later one: keeps the earlier
    assert email_outbox_service._retry_timer is timer
    timer.cancel()


def test_every_email_kind_renders_html_and_text_without_unescaped_values():
    ctx = {"name": "<b>x</b>", "when": "Fri 23 Apr 2027, 10:00", "date": "Friday 23 April 2027", "time": "10:00 (Asia/Karachi)",
           "doctor": "Dr. <i>A</i>", "department": "Cardiology", "status": "requested", "link": "/appointments",
           "old_when": "Thu 22 Apr 2027, 09:00", "due_date": "Mon 03 May 2027"}
    for kind in email_outbox_service.CATEGORY:
        out = email_templates.render(kind, ctx)
        assert out.subject.endswith("— Clinic AI Assistant") and out.text.strip() and "<b>x</b>" not in out.html
        assert "<i>A</i>" not in out.html
    booked = email_templates.render("appointment_booked", ctx)
    assert "request was received" in booked.subject and "Requested, awaiting confirmation" in booked.text
    assert "confirmed" in email_templates.render("appointment_booked", {**ctx, "status": "confirmed"}).subject


# ---- Brevo over HTTPS (D125): for hosts that block SMTP ports -------------------------------

BREVO_KEY = "xkeysib-DO-NOT-LOG"


@pytest.fixture
def brevo(monkeypatch):
    import httpx

    calls, replies = [], []

    def handler(request):
        calls.append(request)
        status, body = replies.pop(0) if replies else (201, {"messageId": "<1@brevo>"})
        return httpx.Response(status, json=body)

    monkeypatch.setattr(settings, "email_backend", EmailBackend.brevo)
    monkeypatch.setattr(settings, "brevo_api_key", SecretStr(BREVO_KEY))
    monkeypatch.setattr(settings, "email_from", "Clinic AI Assistant <clinic@example.com>")
    real = email_service._brevo_client

    def client():
        c = real()
        c._transport = httpx.MockTransport(handler)
        return c

    monkeypatch.setattr(email_service, "_brevo_client", client)
    return calls, replies


async def test_brevo_posts_the_message_over_https_with_the_key_in_a_header(brevo):
    import json as _json

    calls, _ = brevo
    assert await email_service.deliver(EMAIL) is email_service.Delivery.sent
    [request] = calls
    assert str(request.url) == "https://api.brevo.com/v3/smtp/email" and request.headers["api-key"] == BREVO_KEY
    body = _json.loads(request.content)
    assert body == {
        "sender": {"email": "clinic@example.com", "name": "Clinic AI Assistant"}, "to": [{"email": "alice@example.com"}],
        "subject": "Hi", "textContent": "Plain", "htmlContent": "<p>Rich</p>",
    }


@pytest.mark.parametrize(
    "status, body, reason, permanent",
    [
        (401, {"code": "unauthorized", "message": "Key not found " + BREVO_KEY}, "Brevo 401 unauthorized", False),
        (400, {"code": "invalid_parameter", "message": "email is not valid"}, "Brevo 400 invalid_parameter", True),
        (429, {"code": "too_many_requests"}, "Brevo 429 too_many_requests", False),
        (502, {"code": "Some free text!"}, "Brevo 502", False),
    ],
)
async def test_brevo_errors_keep_status_and_code_only(brevo, status, body, reason, permanent, caplog):
    _, replies = brevo
    replies.append((status, body))
    with pytest.raises(email_service.DeliveryError) as err:
        await email_service.deliver(EMAIL)
    assert err.value.reason == reason and err.value.permanent is permanent
    replies.append((status, body))
    with caplog.at_level(logging.DEBUG):
        assert await email_service.send(EMAIL) is email_service.Delivery.failed
    assert BREVO_KEY not in caplog.text


async def test_brevo_check_reads_the_account_and_sends_nothing(brevo):
    calls, replies = brevo
    replies.append((200, {"email": "owner@example.com"}))
    await email_service.check_connection()
    [request] = calls
    assert request.method == "GET" and request.url.path == "/v3/account"


def test_a_brevo_key_alone_selects_brevo_outside_development(monkeypatch):
    monkeypatch.setattr(settings, "email_backend", None)
    monkeypatch.setattr(settings, "environment", Environment.production)
    monkeypatch.setattr(settings, "smtp_host", None)
    monkeypatch.setattr(settings, "brevo_api_key", SecretStr(BREVO_KEY))
    assert settings.effective_email_backend is EmailBackend.brevo
    with pytest.raises(ValidationError, match="needs BREVO_API_KEY"):
        Settings(database_url=DB, email_backend="brevo", brevo_api_key="")
