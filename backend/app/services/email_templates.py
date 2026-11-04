"""Notification email templates (D109).

One shared layout: white, navy (#102A56) and blue (#1677FF), table-based with
inline styles so mail clients render it, readable on phones, with a plain-text
version of everything. Only what the recipient needs: when, with whom, where
to look. Never a reason for the visit, notes, diagnoses, documents or links to
them. Every value is HTML-escaped; links are built from FRONTEND_BASE_URL and
a known app path only.
"""

from dataclasses import dataclass
from html import escape

from app.core.config import settings
from app.services.notification_service import safe_link

BRAND = "Clinic AI Assistant"
NAVY = "#102A56"
BLUE = "#1677FF"
MUTED = "#667085"
BORDER = "#E4EAF2"


@dataclass(frozen=True)
class Rendered:
    subject: str
    text: str
    html: str


def app_url(path: str | None) -> str | None:
    path = safe_link(path)
    return f"{settings.frontend_base_url}{path}" if path else None


def _layout(*, greeting: str, lines: list[str], facts: list[tuple[str, str]], action: tuple[str, str] | None) -> str:
    rows = "".join(
        f'<tr><td style="padding:6px 0;color:{MUTED};font-size:14px;width:120px;vertical-align:top">{escape(k)}</td>'
        f'<td style="padding:6px 0;color:{NAVY};font-size:15px;font-weight:600">{escape(v)}</td></tr>'
        for k, v in facts
    )
    facts_html = (
        f'<table role="presentation" cellpadding="0" cellspacing="0" style="width:100%;margin:16px 0;'
        f'border-top:1px solid {BORDER};border-bottom:1px solid {BORDER}">{rows}</table>'
        if facts
        else ""
    )
    paragraphs = "".join(f'<p style="margin:0 0 12px;font-size:15px;line-height:1.55;color:{NAVY}">{escape(l)}</p>' for l in lines)
    button = ""
    if action:
        label, url = action
        button = (
            f'<p style="margin:20px 0 8px"><a href="{escape(url, quote=True)}" '
            f'style="display:inline-block;background:{BLUE};color:#ffffff;text-decoration:none;font-weight:600;'
            f'font-size:15px;padding:12px 22px;border-radius:8px">{escape(label)}</a></p>'
        )
    settings_url = escape(f"{settings.frontend_base_url}/dashboard", quote=True)
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"></head>'
        '<body style="margin:0;padding:0;background:#ffffff;font-family:Segoe UI,Helvetica,Arial,sans-serif">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:24px 16px">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px">'
        f'<tr><td style="padding-bottom:16px;border-bottom:3px solid {BLUE};font-size:18px;font-weight:700;color:{NAVY}">{BRAND}</td></tr>'
        f'<tr><td style="padding-top:20px"><p style="margin:0 0 12px;font-size:15px;color:{NAVY}">{escape(greeting)}</p>'
        f"{paragraphs}{facts_html}{button}</td></tr>"
        f'<tr><td style="padding-top:24px;font-size:12px;line-height:1.5;color:{MUTED}">'
        f"You receive this because you have an account at {BRAND}. "
        f'Choose which emails you get under Notifications › Settings in the <a href="{settings_url}" style="color:{BLUE}">app</a>. '
        "Please do not reply to this email.</td></tr>"
        "</table></td></tr></table></body></html>"
    )


def _text(*, greeting: str, lines: list[str], facts: list[tuple[str, str]], action: tuple[str, str] | None) -> str:
    parts = [greeting, "", *lines]
    if facts:
        parts += ["", *(f"{k}: {v}" for k, v in facts)]
    if action:
        parts += ["", f"{action[0]}: {action[1]}"]
    parts += [
        "",
        "--",
        f"You receive this because you have an account at {BRAND}.",
        f"Choose which emails you get under Notifications > Settings in the app: {settings.frontend_base_url}/dashboard",
    ]
    return "\n".join(parts) + "\n"


def _render(subject: str, *, name: str | None, lines: list[str], facts: list[tuple[str, str]], action: tuple[str, str] | None) -> Rendered:
    greeting = f"Hello {name}," if name else "Hello,"
    parts = dict(greeting=greeting, lines=lines, facts=facts, action=action)
    return Rendered(subject=subject, text=_text(**parts), html=_layout(**parts))


def _view(link: str | None, label: str = "View appointment") -> tuple[str, str] | None:
    url = app_url(link)
    return (label, url) if url else None


def render(kind: str, ctx: dict) -> Rendered:
    """`ctx`: name, when, doctor, department, link, and per kind old_when / due_date."""
    name = ctx.get("name")
    appointment = [("When", ctx.get("when", "")), ("Doctor", ctx.get("doctor", "")), ("Department", ctx.get("department", ""))]
    appointment = [(k, v) for k, v in appointment if v]
    if kind == "appointment_booked":
        return _render("Your appointment is booked", name=name, lines=["Your appointment is booked."], facts=appointment, action=_view(ctx.get("link")))
    if kind == "appointment_confirmed":
        return _render("Your appointment is confirmed", name=name, lines=["The clinic has confirmed your appointment."], facts=appointment, action=_view(ctx.get("link")))
    if kind == "appointment_rescheduled":
        return _render(
            "Your appointment was rescheduled", name=name,
            lines=[f"Your appointment on {ctx.get('old_when', '')} was moved to a new time."], facts=appointment, action=_view(ctx.get("link")),
        )
    if kind == "appointment_cancelled":
        return _render(
            "Your appointment was cancelled", name=name,
            lines=["This appointment was cancelled. If you still need a visit, you can book a new time."],
            facts=appointment, action=_view("/appointments/book", "Book an appointment"),
        )
    if kind == "appointment_reminder":
        return _render(
            f"Reminder: your appointment on {ctx.get('when', '')}", name=name,
            lines=["This is a reminder of your upcoming appointment."], facts=appointment, action=_view(ctx.get("link")),
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
