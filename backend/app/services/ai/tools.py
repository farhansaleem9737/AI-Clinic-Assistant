"""The assistant's tools (D96): thin, validated wrappers over existing services.

The model only ever chooses a tool and its arguments. Every tool runs with
the signed-in user's own `Principal`, so the same RBAC and visibility rules
as the rest of the API apply; a tool the user may not use is never offered.
Arguments are validated by Pydantic; results are small JSON objects with
only what the answer needs. Nothing here books or changes anything: booking
is a *proposal* the user confirms in the UI (agent_service.confirm_action),
and every proposal expires after AI_ACTION_TTL_MINUTES.

Two outputs per tool (D100): `result` goes to the model; `card` is shown to
the user as a result card. Patient names and MRNs reach the model only when
AI_PHI_ALLOWED; staff still see them on cards, which never leave the server
except to the signed-in user who is entitled to them.
"""

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.config import settings
from app.core.exceptions import DomainError
from app.core.permissions import Perm, Principal
from app.models.appointment import AppointmentStatus
from app.services import (
    appointment_service,
    availability_service,
    dashboard_service,
    department_service,
    doctor_service,
    patient_service,
)
from app.services.ai.provider import ToolSpec
from app.services.doctor_service import DoctorFilters
from app.services.pagination import PageParams

logger = logging.getLogger(__name__)


class _Args(BaseModel):
    model_config = ConfigDict(extra="ignore")


class SearchDoctorsArgs(_Args):
    query: str | None = Field(default=None, max_length=100, description="Name, specialization or department words")
    department_id: uuid.UUID | None = None
    specialization: str | None = Field(default=None, max_length=150)
    min_years_experience: int | None = Field(default=None, ge=0, le=80)


class AvailabilityArgs(_Args):
    doctor_id: uuid.UUID
    date_from: date
    date_to: date | None = None


class ProposeCancellationArgs(_Args):
    appointment_id: uuid.UUID


class ProposeRescheduleArgs(_Args):
    appointment_id: uuid.UUID
    new_starts_at: AwareDatetime


class ProposeBookingArgs(_Args):
    doctor_id: uuid.UUID
    starts_at: AwareDatetime
    reason: str | None = Field(default=None, max_length=500)


class ProposeBookingForPatientArgs(ProposeBookingArgs):
    patient_id: uuid.UUID = Field(description="patient_id from find_patient")


class DoctorProfileArgs(_Args):
    doctor_id: uuid.UUID


HELP_TOPICS = (
    "booking", "rescheduling", "cancelling", "profile", "doctors", "departments", "documents", "account", "navigation",
    "schedule", "management",
)


class HelpArgs(_Args):
    topic: Literal[HELP_TOPICS] = Field(description="What the user needs help with")  # type: ignore[valid-type]


class AppointmentListArgs(_Args):
    date_from: date
    date_to: date | None = None
    status: Literal["requested", "confirmed", "checked_in", "in_progress", "completed", "cancelled", "no_show"] | None = None
    doctor_id: uuid.UUID | None = None


class FindPatientArgs(_Args):
    query: str = Field(min_length=2, max_length=100, description="Name or MRN")


@dataclass(frozen=True)
class ToolOutcome:
    result: dict
    # A booking the user must confirm, attached to the assistant's message.
    action: dict | None = None
    # Shown to the user as a result card (D100), e.g. {"kind": "doctors", "items": [...]}.
    card: dict | None = None
    # A factual answer composed from the database, shown to the user as part of the
    # assistant's reply and never sent to the model (D103).
    reply: str | None = None


Executor = Callable[[AsyncSession, Principal, BaseModel], Awaitable[ToolOutcome]]


@dataclass(frozen=True)
class Tool:
    spec: ToolSpec
    args: type[BaseModel]
    run: Executor
    # Medical-document tools (D101) also receive the request's ToolContext (storage, active document).
    needs_storage: bool = False


def _when(instant: datetime, tz: str) -> str:
    return instant.astimezone(ZoneInfo(tz)).strftime("%a %d %b %Y, %I:%M %p")


def friendly(instant: datetime, tz: str) -> str:
    """"Friday, November 6 at 3:00 PM PKT": exact backend time, in the clinic's time zone."""
    local = instant.astimezone(ZoneInfo(tz))
    return f"{local:%A, %B} {local.day} at {local:%I:%M %p}".replace(" at 0", " at ") + f" {local:%Z}"


def confirmation_question(action: dict) -> str:
    """The one-line question shown with Confirm / Cancel (D104): backend values only, no model call."""
    doctor, when = action["doctor_name"], action["when_text"]
    if action["type"] == "book_appointment":
        if action.get("patient_name"):
            return f"Book {action['patient_name']} with {doctor} on {when}?"
        return f"Confirm your appointment with {doctor} on {when}?"
    if action["type"] == "cancel_appointment":
        return f"Cancel your appointment with {doctor} on {when}?"
    return f"Move your appointment with {doctor} from {when} to {action['new_when_text']}?"


def _expiry() -> str:
    return (clock.utcnow() + timedelta(minutes=settings.ai_action_ttl_minutes)).isoformat()


def _doctor_name(title: str | None, name: str) -> str:
    return " ".join(filter(None, [title, name]))


async def _search_doctors(db: AsyncSession, principal: Principal, a: SearchDoctorsArgs) -> ToolOutcome:
    filters = DoctorFilters(
        department_id=a.department_id, specialization=a.specialization, q=a.query, min_experience=a.min_years_experience
    )
    rows, total = await doctor_service.list_doctors(db, PageParams(page=1, page_size=10), filters, public=True)
    doctors = [
        {
            "doctor_id": str(r.doctor.id),
            "name": " ".join(filter(None, [r.doctor.title, r.name])),
            "specialization": r.doctor.specialization,
            "department": r.department_name,
            "years_of_experience": r.doctor.years_of_experience,
            "consultation_fee": str(r.doctor.consultation_fee) if r.doctor.consultation_fee is not None else None,
            "availability": r.availability.status.value,
            "next_available": r.availability.next_available.isoformat() if r.availability.next_available else None,
        }
        for r in rows
    ]
    card = {"kind": "doctors", "total": total, "items": doctors} if doctors else None
    return ToolOutcome({"total_matches": total, "doctors": doctors}, card=card)


async def _doctor_profile(db: AsyncSession, principal: Principal, a: DoctorProfileArgs) -> ToolOutcome:
    try:
        profile = await doctor_service.get_public_profile(db, a.doctor_id)
    except DomainError as exc:
        return ToolOutcome({"error": exc.message})
    d = profile.row.doctor
    result = {
        "doctor_id": str(d.id),
        "name": _doctor_name(d.title, profile.row.name),
        "specialization": d.specialization,
        "department": profile.row.department_name,
        "years_of_experience": d.years_of_experience,
        "consultation_fee": str(d.consultation_fee) if d.consultation_fee is not None else None,
        "languages": d.languages,
        "qualifications": d.qualifications,
        "bio": d.bio,
        "education": [f"{e.qualification}, {e.institution}" for e in profile.education[:5]],
        "experience": [f"{e.title}, {e.organization}" for e in profile.experience[:5]],
        "availability": profile.row.availability.status.value,
    }
    card_item = {k: result[k] for k in ("doctor_id", "name", "specialization", "department", "years_of_experience", "availability")}
    return ToolOutcome(result, card={"kind": "doctors", "total": 1, "items": [card_item]})


# Fixed, non-personal answers: no model reasoning is needed to produce them.
HELP = {
    "booking": ("Book from Appointments > Book Appointment: choose a doctor, a free time and confirm. "
                "I can also find a free slot and prepare the booking for you to confirm.", "/appointments/book"),
    "rescheduling": ("Open the appointment and choose Reschedule, then pick a new free time with the same doctor. "
                     "Whether it can still be moved depends on clinic policy and how soon it is.", "/appointments"),
    "cancelling": ("Open the appointment and choose Cancel appointment. You can add a note for the clinic. "
                   "Appointments that have started or finished cannot be cancelled.", "/appointments"),
    "profile": ("My Profile shows your personal and contact details; use Edit on each section to change them. "
                "Your medical record number is assigned by the clinic.", "/profile"),
    "doctors": ("Doctors lists every listed doctor with specialty, department, experience and next availability; "
                "open a doctor to see their full profile and book.", "/doctors"),
    "departments": ("Departments lists the clinic's departments and the doctors in each.", "/departments"),
    "documents": ("Your documents are on My Profile > Medical Information.", "/profile"),
    "account": ("Account settings (password, sign-in email) are under Account in the menu at the top right.", "/account"),
    "schedule": ("Doctors set their weekly hours and days off under My Schedule; the front desk sees every doctor's "
                 "hours under Doctor Schedules.", "/schedule"),
    "management": ("Administrators manage users, doctors, departments and patients from the Admin section: "
                   "Users (/admin/users), Doctors (/admin/doctors), Departments (/admin/departments), "
                   "Patients (/patients) and Settings (/admin/settings). Each page has search, filters and actions.", "/admin"),
    "navigation": ("Use the menu on the left: Dashboard, Appointments, Doctors, Departments and your profile. "
                   "Staff also see their worklists and management pages.", "/dashboard"),
}


async def _clinic_help(db: AsyncSession, principal: Principal, a: HelpArgs) -> ToolOutcome:
    text, route = HELP[a.topic]
    return ToolOutcome({"topic": a.topic, "answer": text, "page": route})


async def _dashboard_figures(db: AsyncSession, principal: Principal, a: _Args) -> ToolOutcome:
    """The same role-scoped counts as the dashboard: numbers only."""
    summary = await dashboard_service.get_summary(db, principal)
    data = summary.model_dump(mode="json", exclude={"account"}, exclude_none=True)
    return ToolOutcome({"figures": data, "note": "Counts the user is entitled to, from the clinic database."})


def _appointment_item(v, *, with_patient: bool) -> dict:
    item = {
        "appointment_id": str(v.appointment.id),
        "doctor_id": str(v.appointment.doctor_id),
        "doctor": _doctor_name(v.doctor_title, v.doctor_name),
        "department": v.department_name,
        "when": _when(v.appointment.starts_at, v.timezone),
        "starts_at": v.appointment.starts_at.isoformat(),
        "status": v.appointment.status.value,
        "can_cancel": "cancelled" in v.allowed_transitions,
        "can_reschedule": v.can_reschedule,
    }
    if with_patient:
        item["patient"] = v.patient_name
        item["mrn"] = v.patient_mrn
    return item


async def _list_appointments(db: AsyncSession, principal: Principal, a: AppointmentListArgs) -> ToolOutcome:
    """Appointments the user may see (the API's own visibility rules: a doctor
    sees their own, the front desk all), at most 14 days at a time."""
    date_to = a.date_to or a.date_from
    if date_to < a.date_from or (date_to - a.date_from).days > 13:
        return ToolOutcome({"error": "Ask for at most 14 days, with date_to on or after date_from."})
    filters = appointment_service.AppointmentFilters(
        doctor_id=a.doctor_id,
        date_from=a.date_from,
        date_to=date_to,
        statuses=(AppointmentStatus(a.status),) if a.status else (),
    )
    views, total = await appointment_service.list_appointments(db, principal, PageParams(page=1, page_size=20), filters)
    items = [_appointment_item(v, with_patient=True) for v in views]
    for_model = [_appointment_item(v, with_patient=settings.ai_phi_allowed) for v in views]
    card = {"kind": "appointments", "total": total, "items": items} if items else None
    return ToolOutcome({"total": total, "shown": len(items), "appointments": for_model}, card=card)


async def _find_patient(db: AsyncSession, principal: Principal, a: FindPatientArgs) -> ToolOutcome:
    rows, total = await patient_service.list_patients(db, principal, PageParams(page=1, page_size=5), q=a.query, is_active=True)
    return ToolOutcome(
        {
            "total": total,
            "patients": [
                {"patient_id": str(p.id), "name": f"{p.first_name} {p.last_name}", "mrn": p.mrn, "date_of_birth": p.date_of_birth.isoformat()}
                for p in rows
            ],
        }
    )


async def _list_departments(db: AsyncSession, principal: Principal, a: _Args) -> ToolOutcome:
    rows, _ = await department_service.list_departments(db, PageParams(page=1, page_size=100), active_only=True)
    return ToolOutcome({"departments": [{"department_id": str(d.id), "name": d.name, "description": d.description} for d in rows]})


async def _availability(db: AsyncSession, principal: Principal, a: AvailabilityArgs) -> ToolOutcome:
    date_to = a.date_to or a.date_from
    if date_to < a.date_from or (date_to - a.date_from).days > 6:
        return ToolOutcome({"error": "Ask for at most 7 days, with date_to on or after date_from."})
    try:
        bookable, slots = await availability_service.available_slots(
            db, a.doctor_id, a.date_from, date_to, now=clock.utcnow(), min_lead=appointment_service.booking_lead(principal)
        )
    except DomainError as exc:
        return ToolOutcome({"error": exc.message})
    tz = str(bookable.timezone)
    return ToolOutcome(
        {
            "timezone": tz,
            "free_slots": [{"starts_at": s.starts_at.isoformat(), "local_time": _when(s.starts_at, tz)} for s in slots[:30]],
            "more": max(0, len(slots) - 30),
        }
    )


async def _propose_booking(db: AsyncSession, principal: Principal, a: ProposeBookingArgs) -> ToolOutcome:
    """Checks the slot is really free now; books nothing."""
    patient = None
    try:
        if isinstance(a, ProposeBookingForPatientArgs):
            patient = await patient_service.get_patient(db, principal, a.patient_id)
        doctor = await doctor_service.get_doctor(db, a.doctor_id, public=True)
        bookable = await availability_service.bookable_doctor(db, a.doctor_id)
        slot = await appointment_service._find_free_slot(db, principal, a.doctor_id, a.starts_at)
    except DomainError as exc:
        return ToolOutcome({"error": f"Cannot propose this booking: {exc.message}"})
    tz = str(bookable.timezone)
    action = {
        "type": "book_appointment",
        "status": "pending",
        "doctor_id": str(a.doctor_id),
        "doctor_name": " ".join(filter(None, [doctor.doctor.title, doctor.name])),
        "department": doctor.department_name,
        "specialization": doctor.doctor.specialization,
        "starts_at": slot.starts_at.isoformat(),
        "local_time": _when(slot.starts_at, tz),
        "when_text": friendly(slot.starts_at, tz),
        "timezone": tz,
        "consultation_fee": str(doctor.doctor.consultation_fee) if doctor.doctor.consultation_fee is not None else None,
        "reason": a.reason,
        "expires_at": _expiry(),
    }
    if patient is not None:
        action.update(patient_id=str(patient.id), patient_name=f"{patient.first_name} {patient.last_name}", patient_mrn=patient.mrn)
    return ToolOutcome(
        {"proposed": True, "note": "The confirmation question with Confirm / Cancel buttons is already shown to the user. Do not write anything else: no summary, no instructions."}, action=action, reply=confirmation_question(action)
    )


def _appointment_summary(view) -> dict:
    return {
        "appointment_id": str(view.appointment.id),
        "doctor_name": " ".join(filter(None, [view.doctor_title, view.doctor_name])),
        "department": view.department_name,
        "local_time": _when(view.appointment.starts_at, view.timezone),
        "when_text": friendly(view.appointment.starts_at, view.timezone),
        "timezone": view.timezone,
    }


async def _propose_cancellation(db: AsyncSession, principal: Principal, a: ProposeCancellationArgs) -> ToolOutcome:
    """Checks the user may cancel this appointment now; cancels nothing."""
    try:
        view = await appointment_service.get_view(db, principal, a.appointment_id)
    except DomainError as exc:
        return ToolOutcome({"error": exc.message})
    if "cancelled" not in view.allowed_transitions:
        return ToolOutcome({"error": "This appointment can no longer be cancelled here; contact the clinic."})
    action = {"type": "cancel_appointment", "status": "pending", **_appointment_summary(view), "expires_at": _expiry()}
    return ToolOutcome({"proposed": True, "note": "The confirmation question with Confirm / Cancel buttons is already shown to the user. Do not write anything else: no summary, no instructions."}, action=action, reply=confirmation_question(action))


async def _propose_reschedule(db: AsyncSession, principal: Principal, a: ProposeRescheduleArgs) -> ToolOutcome:
    """Checks the move is allowed and the new slot is free now; moves nothing."""
    try:
        view = await appointment_service.get_view(db, principal, a.appointment_id)
        if not view.can_reschedule:
            return ToolOutcome({"error": "This appointment can no longer be rescheduled here; contact the clinic."})
        slot = await appointment_service._find_free_slot(
            db, principal, view.appointment.doctor_id, a.new_starts_at, exclude_appointment_id=view.appointment.id
        )
    except DomainError as exc:
        return ToolOutcome({"error": f"Cannot propose this change: {exc.message}"})
    action = {
        "type": "reschedule_appointment",
        "status": "pending",
        **_appointment_summary(view),
        "new_starts_at": slot.starts_at.isoformat(),
        "new_local_time": _when(slot.starts_at, view.timezone),
        "new_when_text": friendly(slot.starts_at, view.timezone),
        "expires_at": _expiry(),
    }
    return ToolOutcome({"proposed": True, "note": "The confirmation question with Confirm / Cancel buttons is already shown to the user. Do not write anything else: no summary, no instructions."}, action=action, reply=confirmation_question(action))


def _spec(name: str, description: str, args: type[BaseModel]) -> ToolSpec:
    schema = args.model_json_schema()
    def plain(value: dict) -> dict:
        kept = {k: v for k, v in value.items() if k in ("type", "description", "enum", "format")}
        if value.get("type") == "array":  # Gemini requires the item type of every array
            kept["items"] = {k: v for k, v in value.get("items", {}).items() if k in ("type", "format", "enum")} or {"type": "string"}
        return kept or {"type": "string"}

    properties = {key: plain(value) for key, value in schema.get("properties", {}).items()}
    for key, value in schema.get("properties", {}).items():
        if "anyOf" in value:  # Optional[...]: keep the non-null type
            kinds = [o for o in value["anyOf"] if o.get("type") != "null"]
            if kinds:
                properties[key] = {**{k: v for k, v in kinds[0].items() if k in ("type", "format", "enum")}, **({"description": value["description"]} if "description" in value else {})}
    return ToolSpec(name, description, {"type": "object", "properties": properties, "required": schema.get("required", [])})


def available_tools(principal: Principal) -> dict[str, Tool]:
    """Only what this user may do, and only patient data when allowed (AI_PHI_ALLOWED)."""
    tools = {
        "search_doctors": Tool(
            _spec("search_doctors",
                  "Search the PUBLIC directory of the clinic's doctors (by name words, department, specialization, experience) to find "
                  "a new doctor. NOT for the user's own appointments or the doctors they have seen or booked: use get_my_appointments.",
                  SearchDoctorsArgs),
            SearchDoctorsArgs,
            _search_doctors,
        ),
        "get_doctor_profile": Tool(
            _spec("get_doctor_profile", "One listed doctor's public profile: specialty, department, experience, education, fee, languages.", DoctorProfileArgs),
            DoctorProfileArgs,
            _doctor_profile,
        ),
        "list_departments": Tool(_spec("list_departments", "List the clinic's active departments.", _Args), _Args, _list_departments),
        "get_clinic_help": Tool(
            _spec("get_clinic_help", "How to do something in this application (booking, rescheduling, cancelling, profile, navigation...).", HelpArgs),
            HelpArgs,
            _clinic_help,
        ),
        "get_dashboard_figures": Tool(
            _spec("get_dashboard_figures",
                  "Counts only (appointments today, upcoming, totals) from the user's dashboard. For the appointments themselves "
                  "(which doctors, dates, statuses) use get_my_appointments (patients) or list_appointments (staff).", _Args),
            _Args,
            _dashboard_figures,
        ),
        "get_doctor_availability": Tool(
            _spec("get_doctor_availability", "Free appointment slots of one doctor between two dates (max 7 days). Use real results only.", AvailabilityArgs),
            AvailabilityArgs,
            _availability,
        ),
    }
    if principal.patient_id and principal.has(Perm.appointment_read_own):
        # D103: always offered; appointment_tools keeps the details from the model unless AI_PHI_ALLOWED.
        from app.services.ai import appointment_tools

        tools["get_my_appointments"] = Tool(
            _spec(
                "get_my_appointments",
                "The signed-in patient's OWN appointment history and bookings: which doctors they saw or booked, when, and the status "
                "(completed, cancelled, missed, upcoming). Use for 'my appointments', 'doctors I visited / had appointments with', "
                "'my last appointment', 'who treated me', 'my previous doctors', also when misspelled ('whome I got appointment'). "
                "The answer is shown to the user directly.",
                appointment_tools.MyAppointmentsArgs,
            ),
            appointment_tools.MyAppointmentsArgs,
            appointment_tools.get_my_appointments,
            needs_storage=True,
        )
        if principal.has(Perm.appointment_cancel_own):
            tools["propose_cancellation"] = Tool(
                _spec("propose_cancellation", "Propose cancelling one of the patient's appointments (id from get_my_appointments). Does not cancel: the user must press Confirm.", ProposeCancellationArgs),
                ProposeCancellationArgs,
                _propose_cancellation,
            )
        if principal.has(Perm.appointment_reschedule_own):
            tools["propose_reschedule"] = Tool(
                _spec("propose_reschedule", "Propose moving one of the patient's appointments to a free slot of the same doctor (from get_doctor_availability). Does not move it: the user must press Confirm.", ProposeRescheduleArgs),
                ProposeRescheduleArgs,
                _propose_reschedule,
            )
    if principal.has(Perm.appointment_read_assigned) or principal.has(Perm.appointment_read_any):
        tools["list_appointments"] = Tool(
            _spec(
                "list_appointments",
                "Appointments this staff user may see between two dates (max 14 days), optionally by status or doctor. "
                "A doctor sees their own schedule.",
                AppointmentListArgs,
            ),
            AppointmentListArgs,
            _list_appointments,
        )
    if settings.ai_phi_allowed and principal.has(Perm.patient_read_any):
        tools["find_patient"] = Tool(
            _spec("find_patient", "Find an active patient by name or MRN (front desk).", FindPatientArgs), FindPatientArgs, _find_patient
        )
        if principal.has(Perm.appointment_create):
            tools["propose_booking_for_patient"] = Tool(
                _spec(
                    "propose_booking_for_patient",
                    "Propose booking a free slot for a patient (patient_id from find_patient). Does not book: the user must press Confirm.",
                    ProposeBookingForPatientArgs,
                ),
                ProposeBookingForPatientArgs,
                _propose_booking,
            )
    if principal.patient_id and principal.has(Perm.appointment_create_own):
        tools["propose_booking"] = Tool(
            _spec(
                "propose_booking",
                "Propose booking a free slot (starts_at from get_doctor_availability) for the signed-in patient. "
                "This does not book: the user must press Confirm.",
                ProposeBookingArgs,
            ),
            ProposeBookingArgs,
            _propose_booking,
        )
    # Documents in the patient record (D101), under the record's own access rules.
    from app.services.ai import medical_tools

    medical_tools.register(tools, principal, Tool, _spec)
    return tools


async def run_tool(
    db: AsyncSession, principal: Principal, tools: dict[str, Tool], name: str, arguments: dict, context=None
) -> ToolOutcome:
    tool = tools.get(name)
    if tool is None:
        return ToolOutcome({"error": f"Tool {name!r} is not available.", "error_code": "TOOL_UNAVAILABLE"})
    try:
        args = tool.args.model_validate(arguments or {})
    except ValidationError as exc:
        return ToolOutcome({"error": "Invalid arguments", "error_code": "INVALID_ARGUMENTS", "details": [e["msg"] for e in exc.errors()[:5]]})
    try:
        # A savepoint: a failing tool undoes only its own work, never the conversation being saved.
        async with db.begin_nested():
            if tool.needs_storage:
                from app.services.ai.medical_tools import ToolContext

                return await tool.run(db, principal, args, context or ToolContext())
            return await tool.run(db, principal, args)
    except DomainError as exc:
        code = "TOOL_PERMISSION_DENIED" if exc.code in ("PERMISSION_DENIED", "NOT_FOUND") else "TOOL_EXECUTION_FAILED"
        return ToolOutcome({"error": exc.message, "error_code": code})
    except Exception:
        # Never a raw exception to the model or the user; logged without arguments (they may hold patient data).
        logger.exception("ai_tool_failed", extra={"tool": name})
        return ToolOutcome({"error": "This lookup failed on the server.", "error_code": "TOOL_EXECUTION_FAILED"})

