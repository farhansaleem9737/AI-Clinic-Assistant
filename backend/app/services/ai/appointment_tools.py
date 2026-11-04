"""The patient's own appointment history as an assistant tool (D103).

Always offered to a patient with a record: "which doctors did I see", "my
last appointment", "doctors I booked before" are about their own records,
never the public directory. Rows come from appointment_service with the
caller's Principal and the patient filter (one query, doctor details joined),
so only their own appointments are ever returned.

Privacy: unless AI_PHI_ALLOWED, the model receives no doctor names, dates or
reasons, only opaque ids, statuses and order. The factual answer (doctor,
specialty, date, time, status) is composed here and shown to the user
directly (`reply`), plus a card. Follow-ups ("which one was the latest?",
"that doctor's profile") work on the ids of the appointments last shown,
re-read with access checks.
"""

import uuid
from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import DomainError
from app.core.permissions import Principal
from app.models.appointment import AppointmentStatus
from app.services import appointment_service
from app.services.pagination import PageParams

Scope = Literal["all", "past", "upcoming", "visited", "cancelled"]
Pick = Literal["all", "latest", "earliest"]
MAX_ROWS = 20
STATUS_LABEL = {
    "requested": "requested", "scheduled": "scheduled", "confirmed": "confirmed", "checked_in": "checked in",
    "in_progress": "in progress", "completed": "completed (attended)", "cancelled": "cancelled", "no_show": "missed (no-show)",
}
NOT_HELD = {"cancelled", "no_show"}


def _args_base():
    from app.services.ai.tools import _Args

    return _Args


class MyAppointmentsArgs(_args_base()):
    scope: Scope = Field(
        default="all",
        description="past = appointment time has passed (any status, incl. cancelled/missed; also 'earlier', 'before', "
        "'previous', 'booked before'); visited = completed visits only ('doctors I visited', 'who treated me'); upcoming "
        "('next', 'coming'); cancelled; all",
    )
    pick: Pick = Field(default="all", description="latest / earliest = only the most recent / first one in the scope")
    doctor_id: uuid.UUID | None = Field(default=None, description="Only appointments with this doctor")
    date_from: date | None = None
    date_to: date | None = None
    from_previous: bool = Field(
        default=False, description="Only the appointments shown in the previous answer (for 'which of them', 'which one was the latest')"
    )


def _when(instant: datetime, tz: str) -> tuple[str, str]:
    local = instant.astimezone(ZoneInfo(tz))
    return local.strftime("%a %d %b %Y"), local.strftime("%I:%M %p").lstrip("0")


def _row(v) -> dict:
    a = v.appointment
    day, start = _when(a.starts_at, v.timezone)
    _, end = _when(a.ends_at, v.timezone)
    return {
        "appointment_id": str(a.id),
        "doctor_id": str(a.doctor_id),
        "doctor": " ".join(filter(None, [v.doctor_title, v.doctor_name])),
        "specialization": v.specialization,
        "department": v.department_name,
        "date": day,
        "start": start,
        "end": end,
        "duration_minutes": int((a.ends_at - a.starts_at).total_seconds() // 60),
        "starts_at": a.starts_at.isoformat(),
        "status": a.status.value,
        "status_label": STATUS_LABEL.get(a.status.value, a.status.value),
        "room": v.doctor_room,
        "timezone": v.timezone,
        "reason": a.reason,
        "can_cancel": "cancelled" in v.allowed_transitions,
        "can_reschedule": v.can_reschedule,
    }


NOUNS = {"past": ("past appointment", "past appointments"), "visited": ("completed visit", "completed visits"),
         "upcoming": ("upcoming appointment", "upcoming appointments"), "cancelled": ("cancelled appointment", "cancelled appointments"),
         "all": ("appointment", "appointments")}


def _reply(rows: list[dict], a: MyAppointmentsArgs, total: int, attended: dict | None = None) -> str:
    """The factual answer, from the database rows only."""
    one, many = NOUNS[a.scope]
    if not rows:
        return f"You have no {many}" + (" matching that" if a.doctor_id or a.date_from or a.date_to else "") + "."
    line = lambda r: f"**{r['doctor']}** ({r['specialization']}, {r['department']}): {r['date']}, {r['start']}–{r['end']}, {r['status_label']}"
    if a.pick != "all":
        r = rows[0]
        text = f"Your {'most recent' if a.pick == 'latest' else 'first'} {one} was with {line(r)}."
        if r["status"] in NOT_HELD and attended is not None:
            # "My last doctor": the last booking did not take place, so also name the last visit that did.
            text += f"\n\nThat appointment did not take place. Your most recent completed visit was with {line(attended)}."
        return text
    doctors: dict[str, int] = {}
    for r in rows:
        doctors[r["doctor"]] = doctors.get(r["doctor"], 0) + 1
    names = ", ".join(f"{d} ({n})" if n > 1 else d for d, n in doctors.items())
    text = f"You have {total} {one if total == 1 else many}" + (f" (showing the latest {len(rows)})" if total > len(rows) else "") + f", with {names}:\n"
    text += "\n".join(f"- {line(r)}" for r in rows)
    held_not = [r for r in rows if r["status"] in NOT_HELD]
    if held_not and a.scope in ("past", "all"):
        text += f"\n\n{len(held_not)} of these did not take place (cancelled or missed)."
    return text


async def get_my_appointments(db: AsyncSession, principal: Principal, a: MyAppointmentsArgs, ctx):
    from app.services.ai.tools import ToolOutcome

    scope = {"past": "past", "visited": "past", "cancelled": "all", "upcoming": "upcoming", "all": "all"}[a.scope]
    statuses = {"visited": (AppointmentStatus.completed,), "cancelled": (AppointmentStatus.cancelled,)}.get(a.scope, ())
    filters = appointment_service.AppointmentFilters(
        patient_id=principal.patient_id,  # always the caller's own record
        doctor_id=a.doctor_id,
        statuses=statuses,
        date_from=a.date_from,
        date_to=a.date_to,
        scope=appointment_service.AppointmentScope(scope),
        newest_first=a.scope != "upcoming",
    )
    try:
        views, total = await appointment_service.list_appointments(
            db, principal, PageParams(page=1, page_size=50 if a.from_previous else MAX_ROWS), filters
        )
    except DomainError as exc:
        return ToolOutcome({"error": exc.message, "error_code": "TOOL_EXECUTION_FAILED"})
    rows = [_row(v) for v in views]
    if a.from_previous:
        previous = [str(i) for i in ctx.last_appointment_ids]
        rows = [r for r in rows if r["appointment_id"] in previous]
        total = len(rows)
    attended = None
    if a.pick != "all" and rows:
        ordered = sorted(rows, key=lambda r: r["starts_at"], reverse=a.pick == "latest")
        attended = next((r for r in ordered if r["status"] == "completed"), None)
        rows = ordered[:1]
    ctx.last_appointment_ids = [uuid.UUID(r["appointment_id"]) for r in rows]

    card = {"kind": "appointment_history", "scope": a.scope, "pick": a.pick, "total": total, "items": rows}
    result: dict = {
        "total": total,
        "shown": len(rows),
        "by_status": {s: sum(1 for r in rows if r["status"] == s) for s in {r["status"] for r in rows}},
        "answer_shown_to_user": True,
    }
    if settings.ai_phi_allowed:
        result["appointments"] = rows
    else:
        # Opaque ids and order only: enough to act on a follow-up, nothing that describes the patient's care.
        result["appointments"] = [
            {"n": i + 1, "appointment_id": r["appointment_id"], "doctor_id": r["doctor_id"], "status": r["status"],
             "can_cancel": r["can_cancel"], "can_reschedule": r["can_reschedule"]}
            for i, r in enumerate(rows)
        ]
        result["note"] = (
            "The appointment details (doctors, dates, times, statuses) were shown to the user directly. For privacy they "
            "were not shared with you: do not repeat, guess or invent them. Add at most one short sentence, e.g. offering to "
            "show a doctor's profile (get_doctor_profile with the doctor_id) or to cancel/reschedule an upcoming one."
        )
    if not rows:
        result["error_code"] = "DATA_NOT_FOUND"
    return ToolOutcome(result, card=card if rows else None, reply=_reply(rows, a, total, attended))
