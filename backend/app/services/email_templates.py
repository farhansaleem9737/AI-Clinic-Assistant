"""Notification email templates (D109, D124).

One shared layout: a white card on a light background with the app's navy
(#102A56) and blue (#1677FF), table-based with inline styles and bgcolor
attributes so Gmail and Outlook render it, readable on phones, no scripts,
web fonts or images, and a plain-text version of everything. Only what the
recipient needs: when, with whom, the appointment's status as stored, where
to look. Never a reason for the visit, notes, diagnoses, documents, AI output
or links to them. Every value is HTML-escaped; links are built from
FRONTEND_BASE_URL and a known app path only, and carry no tokens.
"""

from dataclasses import dataclass
from html import escape

from app.core.config import settings
from app.services.notification_service import safe_link

BRAND = "Clinic AI Assistant"
NAVY = "#102A56"
BLUE = "#1677FF"
BACKGROUND = "#F7F9FC"
TEXT = "#172B4D"
MUTED = "#667085"
BORDER = "#E4EAF2"

# Appointment status as stored → (label, text colour, badge background).
STATUS = {
    "requested": ("Requested, awaiting confirmation", "#B54708", "#FFFAEB"),
    "scheduled": ("Scheduled", BLUE, "#EAF2FF"),
    "confirmed": ("Confirmed", "#067647", "#ECFDF3"),
    "checked_in": ("Checked in", BLUE, "#EAF2FF"),
    "in_progress": ("In progress", BLUE, "#EAF2FF"),
    "completed": ("Completed", MUTED, "#F2F4F7"),
    "cancelled": ("Cancelled", "#B42318", "#FEF3F2"),
}


@dataclass(frozen=True)
class Rendered:
    subject: str
    text: str
    html: str


def app_url(path: str | None) -> str | None:
    path = safe_link(path)
    return f"{settings.frontend_base_url}{path}" if path else None


def status_label(status: str | None) -> str | None:
    return STATUS[status][0] if status in STATUS else None


def _badge(status: str) -> str:
    label, colour, background = STATUS[status]
    return (
        f'<span style="display:inline-block;padding:3px 10px;border-radius:999px;background:{background};'
        f'color:{colour};font-size:13px;font-weight:600">{escape(label)}</span>'
    )


_SIGN_IN_NOTE = "You will be asked to sign in first."


def _default_footer() -> tuple[str, str]:
    """(HTML, text): why the email came and where to change which ones come."""
    url = f"{settings.frontend_base_url}/dashboard"
    html = (
        f"You receive this because you have an account at {BRAND}. "
        f'Choose which emails you get under Notifications › Settings in the <a href="{escape(url, quote=True)}" style="color:{BLUE}">app</a>. '
        "Please do not reply to this email."
    )
    text = (
        f"You receive this because you have an account at {BRAND}.\n"
        f"Choose which emails you get under Notifications > Settings in the app: {url}"
    )
    return html, text


def _layout(*, heading: str, greeting: str, lines: list[str], facts: list[tuple[str, str]], status: str | None,
            action: tuple[str, str] | None, note: str | None = _SIGN_IN_NOTE, footer: str | None = None,
            code: str | None = None, after: list[str] | None = None) -> str:
    cell = f'padding:8px 0;font-size:14px;vertical-align:top;border-bottom:1px solid {BORDER}'
    rows = "".join(
        f'<tr><td style="{cell};color:{MUTED};width:110px">{escape(k)}</td>'
        f'<td style="{cell};color:{TEXT};font-weight:600">{escape(v)}</td></tr>'
        for k, v in facts
    )
    if status in STATUS:
        rows += f'<tr><td style="{cell};color:{MUTED};width:110px">Status</td><td style="{cell}">{_badge(status)}</td></tr>'
    facts_html = (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="{BACKGROUND}" '
        f'style="width:100%;margin:16px 0;background:{BACKGROUND};border-radius:8px">'
        f'<tr><td style="padding:8px 16px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0">{rows}</table></td></tr></table>'
        if rows
        else ""
    )
    paragraphs = "".join(f'<p style="margin:0 0 12px;font-size:15px;line-height:1.55;color:{TEXT}">{escape(l)}</p>' for l in lines)
    if code:
        # A one-time code (D127): large, spaced and selectable; nothing else in the box.
        paragraphs += (
            f'<table role="presentation" cellpadding="0" cellspacing="0" bgcolor="{BACKGROUND}" '
            f'style="margin:8px 0 16px;background:{BACKGROUND};border:1px solid {BORDER};border-radius:8px"><tr>'
            f'<td style="padding:14px 24px;font-family:Consolas,Menlo,monospace;font-size:30px;font-weight:700;'
            f'letter-spacing:8px;color:{NAVY}">{escape(code)}</td></tr></table>'
        )
    paragraphs += "".join(
        f'<p style="margin:0 0 12px;font-size:15px;line-height:1.55;color:{TEXT}">{escape(l)}</p>' for l in after or []
    )
    button = ""
    if action:
        label, url = action
        # A table cell carries the colour: Outlook ignores padding and radius on links.
        button = (
            '<table role="presentation" cellpadding="0" cellspacing="0" style="margin:20px 0 4px"><tr>'
            f'<td bgcolor="{BLUE}" style="background:{BLUE};border-radius:8px">'
            f'<a href="{escape(url, quote=True)}" target="_blank" '
            f'style="display:inline-block;padding:12px 24px;color:#ffffff;text-decoration:none;font-weight:600;font-size:15px">'
            f"{escape(label)}</a></td></tr></table>"
            f'<p style="margin:8px 0 0;font-size:12px;line-height:1.5;color:{MUTED}">'
            f'Or open this address: <a href="{escape(url, quote=True)}" style="color:{BLUE};word-break:break-all">{escape(url)}</a>'
            f"{'<br>' + escape(note) if note else ''}</p>"
        )
    footer_html = escape(footer) if footer else _default_footer()[0]
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="light"><meta name="supported-color-schemes" content="light">'
        f"<title>{escape(heading)}</title></head>"
        f'<body style="margin:0;padding:0;background:{BACKGROUND};font-family:Segoe UI,Helvetica,Arial,sans-serif">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="{BACKGROUND}" style="background:{BACKGROUND}">'
        '<tr><td align="center" style="padding:24px 12px">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px">'
        f'<tr><td style="padding:0 4px 12px;font-size:17px;font-weight:700;color:{NAVY}">{BRAND}</td></tr>'
        f'<tr><td bgcolor="#ffffff" style="background:#ffffff;border:1px solid {BORDER};border-top:4px solid {BLUE};'
        'border-radius:10px;padding:24px 24px 28px">'
        f'<h1 style="margin:0 0 16px;font-size:20px;line-height:1.3;color:{NAVY}">{escape(heading)}</h1>'
        f'<p style="margin:0 0 12px;font-size:15px;color:{TEXT}">{escape(greeting)}</p>'
        f"{paragraphs}{facts_html}{button}</td></tr>"
        f'<tr><td style="padding:16px 4px 0;font-size:12px;line-height:1.5;color:{MUTED}">{footer_html}</td></tr>'
        "</table></td></tr></table></body></html>"
    )


def _text(*, heading: str, greeting: str, lines: list[str], facts: list[tuple[str, str]], status: str | None,
          action: tuple[str, str] | None, note: str | None = _SIGN_IN_NOTE, footer: str | None = None,
          code: str | None = None, after: list[str] | None = None) -> str:
    parts = [heading, "", greeting, "", *lines]
    if code:
        parts += ["", f"    {code}", ""]
    parts += after or []
    facts = [*facts, *([("Status", STATUS[status][0])] if status in STATUS else [])]
    if facts:
        parts += ["", *(f"{k}: {v}" for k, v in facts)]
    if action:
        parts += ["", f"{action[0]}{' (sign-in required)' if note == _SIGN_IN_NOTE else ''}: {action[1]}"]
    parts += ["", f"Thank you,\n{BRAND}", "", "--", footer or _default_footer()[1]]
    return "\n".join(parts) + "\n"


def _render(subject: str, *, name: str | None, lines: list[str], facts: list[tuple[str, str]],
            action: tuple[str, str] | None, status: str | None = None, heading: str | None = None) -> Rendered:
    greeting = f"Hello {name}," if name else "Hello,"
    parts = dict(heading=heading or subject, greeting=greeting, lines=lines, facts=facts, status=status, action=action)
    return Rendered(subject=f"{subject} — {BRAND}", text=_text(**parts), html=_layout(**parts))


def _view(link: str | None, label: str = "View appointment") -> tuple[str, str] | None:
    url = app_url(link)
    return (label, url) if url else None


def _booked(ctx: dict, name: str | None, facts: list[tuple[str, str]]) -> Rendered:
    status = ctx.get("status")
    if status == "confirmed":
        subject, line = "Your appointment is confirmed", "Your appointment has been booked and confirmed."
    elif status == "requested":
        subject, line = "Your appointment request was received", "Your appointment request was received. The clinic will confirm it."
    else:
        subject, line = "Your appointment is booked", "Your appointment has been successfully scheduled."
    return _render(subject, name=name, lines=[line], facts=facts, status=status, action=_view(ctx.get("link")))


def render(kind: str, ctx: dict) -> Rendered:
    """`ctx`: name, when, date, time, doctor, department, status, link, and per kind old_when / due_date."""
    name = ctx.get("name")
    status = ctx.get("status")
    date_time = [("Date", ctx.get("date", "")), ("Time", ctx.get("time", ""))] if ctx.get("date") else [("When", ctx.get("when", ""))]
    facts = [(k, v) for k, v in [("Doctor", ctx.get("doctor", "")), *date_time, ("Department", ctx.get("department", ""))] if v]
    view = _view(ctx.get("link"))
    if kind == "appointment_booked":
        return _booked(ctx, name, facts)
    if kind == "appointment_confirmed":
        return _render("Your appointment is confirmed", name=name, lines=["The clinic has confirmed your appointment."], facts=facts, status=status, action=view)
    if kind == "appointment_rescheduled":
        return _render(
            "Your appointment was rescheduled", name=name,
            lines=[f"Your appointment on {ctx.get('old_when', '')} was rescheduled. The new time is below."],
            facts=facts, status=status, action=view,
        )
    if kind == "appointment_cancelled":
        return _render(
            "Your appointment was cancelled", name=name,
            lines=["This appointment was cancelled. If you still need a visit, you can book a new time."],
            facts=facts, status="cancelled", action=_view("/appointments/book", "Book an appointment"),
        )
    if kind == "appointment_reminder":
        return _render(
            f"Reminder: your appointment on {ctx.get('when', '')}", name=name, heading="Your upcoming appointment",
            lines=["This is a reminder of your upcoming appointment."], facts=facts, status=status, action=view,
        )
    if kind == "doctor_appointment_booked":
        return _render(
            "New appointment booked with you", name=name,
            lines=[f"A new appointment was booked with you for {ctx.get('when', '')}."],
            facts=[f for f in facts if f[0] != "Doctor"], status=status, action=view,
        )
    if kind == "doctor_appointment_rescheduled":
        return _render(
            "An appointment with you was rescheduled", name=name,
            lines=[f"The appointment on {ctx.get('old_when', '')} was moved. The new time is below."],
            facts=[f for f in facts if f[0] != "Doctor"], status=status, action=view,
        )
    if kind == "doctor_appointment_cancelled":
        return _render(
            "An appointment with you was cancelled", name=name,
            lines=[f"The appointment on {ctx.get('when', '')} was cancelled. The time is free again."],
            facts=[f for f in facts if f[0] != "Doctor"], status="cancelled", action=view,
        )
    if kind == "follow_up_due":
        return _render(
            "Your follow-up visit is due soon", name=name,
            lines=[
                f"Your follow-up appointment is due by {ctx.get('due_date', '')}.",
                "It is not booked yet. You can review available appointment times.",
            ],
            facts=[], action=_view(ctx.get("link"), "See available times"),
        )
    if kind == "doctor_application_submitted":
        return _render(
            "A doctor application is waiting for review", name=name,
            lines=["A new doctor registered and is waiting for credential review."],
            facts=[], action=_view("/admin/doctors", "Review applications"),
        )
    if kind == "doctor_application_approved":
        return _render(
            "Your doctor application was approved", name=name,
            lines=["Your doctor application was approved. You can now complete your profile and working hours."],
            facts=[], action=_view("/doctor/profile", "Open your profile"),
        )
    if kind == "doctor_application_rejected":
        return _render(
            "Your doctor application was reviewed", name=name,
            lines=["Your doctor application was not approved. The reason is shown on your application."],
            facts=[], action=_view("/doctor/application", "View your application"),
        )
    raise ValueError(f"Unknown email kind: {kind}")


# ---- account security (D126) --------------------------------------------------------------
# Sent whatever the notification preferences say: the owner asked for them.

_SECURITY_FOOTER = (
    f"You receive this because a password reset was requested for a {BRAND} account with this email address. "
    "Please do not reply to this email."
)


def _security(subject: str, *, lines: list[str], action: tuple[str, str] | None = None,
              code: str | None = None, after: list[str] | None = None, footer: str = _SECURITY_FOOTER) -> Rendered:
    parts = dict(heading=subject, greeting="Hello,", lines=lines, facts=[], status=None, action=action,
                 note=None, footer=footer, code=code, after=after)
    return Rendered(subject=f"{subject} — {BRAND}", text=_text(**parts), html=_layout(**parts))


def password_reset_code(code: str, minutes: int) -> Rendered:
    """The 6-digit reset code (D127): a credential, so it is sent at once and never queued."""
    return _security(
        "Your password reset code",
        lines=["We received a request to reset your password.", "Your verification code is:"],
        code=code,
        after=[
            f"This code expires in {minutes} minutes.",
            "If you did not request this, you can ignore this email. Your password stays the same.",
        ],
    )


def password_reset_google_only() -> Rendered:
    """For an account without a password: it signs in with Google (D123)."""
    return _security(
        "Reset your password",
        lines=[
            f"We received a request to reset the password for your {BRAND} account.",
            "Your account doesn't use a password: you sign in with Google. On the sign-in page, choose Continue with Google.",
            "Once signed in, you can add a password under Change password in your account menu.",
            "If you didn't request this, you can safely ignore this email.",
        ],
        action=("Go to sign in", f"{settings.frontend_base_url}/login"),
    )


# ---- linking Google at sign-in (D128) ------------------------------------------------------

_LINK_FOOTER = (
    f"You receive this because someone signed in with Google using this email address at {BRAND}. "
    "Please do not reply to this email."
)


def google_link_code(code: str, minutes: int) -> Rendered:
    """Proves the person linking Google controls this account's mailbox. Sent at once, never queued."""
    return _security(
        "Your code to connect Google sign-in",
        lines=["Someone asked to connect Google sign-in to your account.", "Your verification code is:"],
        code=code,
        after=[
            f"This code expires in {minutes} minutes.",
            "If this wasn't you, don't share the code and ignore this email. Your account stays as it is.",
        ],
        footer=_LINK_FOOTER,
    )


def google_linked_notice() -> Rendered:
    """After linking: the owner hears about the new sign-in method, whoever did it."""
    return _security(
        "Google sign-in was connected to your account",
        lines=[
            "Google sign-in is now connected to your account. You can sign in with Google or with your usual method.",
            "If this wasn't you, change your password now and remove Google under Account › Connected accounts, "
            "or contact the clinic.",
        ],
        action=("Open your account", f"{settings.frontend_base_url}/account"),
        footer=_LINK_FOOTER,
    )
