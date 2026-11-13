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

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.config import settings
from app.core.exceptions import DomainError
from app.core.permissions import Perm, Principal
from app.models.appointment import AppointmentStatus
from app.services import (
    appointment_service,
    availability_service,
    catalog_service,
    dashboard_service,
    department_service,
    doctor_service,
    patient_service,
)
from app.services.ai import specialties
from app.services.ai.provider import ToolSpec
from app.services.doctor_service import DoctorFilters, DoctorSort
from app.services.pagination import PageParams

logger = logging.getLogger(__name__)


class _Args(BaseModel):
    model_config = ConfigDict(extra="ignore")


class SearchDoctorsArgs(_Args):
    doctor_name: str | None = Field(
        default=None, max_length=100,
        description="A doctor's name exactly as the user gave it ('Dr. Emily Carter', 'emily carter', 'Dr Emily'). "
        "Always use this for a name, even if a doctor list was shown before.",
    )
    intent: Literal["find", "book", "profile"] | None = Field(
        default=None, description="'book' when the user wants an appointment ('book me with ...', 'I want to see ...')"
    )
    query: str | None = Field(default=None, max_length=100, description="Other words to search (not a doctor's name)")
    department_id: uuid.UUID | None = None
    specialization: str | None = Field(default=None, max_length=150)
    condition: str | None = Field(
        default=None, max_length=150,
        description="The disease, condition or symptom in the user's own words ('thyroid problem', 'migraines', 'kidney stones')",
    )
    min_years_experience: int | None = Field(default=None, ge=0, le=80)
    sort: Literal["relevance", "most_experienced", "lowest_fee"] | None = Field(
        default=None, description="'most_experienced' or 'lowest_fee' when the user asks for that; otherwise leave empty"
    )


class AvailabilityArgs(_Args):
    doctor_id: uuid.UUID
    date_from: date
    date_to: date | None = None
    part_of_day: Literal["morning", "afternoon", "evening"] | None = Field(
        default=None, description="Only slots in this part of the day (morning before 12:00, afternoon 12-17, evening from 17:00)"
    )


# Local hours [from, to) of each part of the day.
PART_OF_DAY = {"morning": (0, 12), "afternoon": (12, 17), "evening": (17, 24)}

ORDINALS = ("first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth")


class PickArgs(_Args):
    entity: Literal["doctor", "slot"] = Field(description="doctor = the doctors last listed; slot = the free times last shown")
    selector: Literal[
        "first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth", "last",
        "most_experienced", "least_experienced", "lowest_fee", "highest_fee", "earliest_available",
        "earliest", "latest", "by_name",
    ] = Field(description="Which one the user means. by_name: a doctor's name, or a time such as '5:30 pm', given in `name`")
    name: str | None = Field(default=None, max_length=100, description="For by_name: the doctor's name or the time the user said")


class ProposeCancellationArgs(_Args):
    appointment_id: uuid.UUID


class ProposeRescheduleArgs(_Args):
    appointment_id: uuid.UUID
    new_starts_at: AwareDatetime


class ProposeBookingArgs(_Args):
    doctor_id: uuid.UUID
    starts_at: AwareDatetime | None = Field(
        default=None, description="A free time (starts_at) from get_doctor_availability, when the user asked for a specific time"
    )
    earliest_on: date | None = Field(
        default=None,
        description="Automatic token booking: the date on which the clinic assigns the earliest free time "
        "('the next available appointment tomorrow'). Use instead of starts_at; never guess a time yourself.",
    )
    reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def one_way_of_choosing(self):
        if (self.starts_at is None) == (self.earliest_on is None):
            raise ValueError("Give exactly one of starts_at (a specific free time) or earliest_on (next available on a date)")
        return self


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
    # More cards after `card` (a chosen doctor and their free times).
    extra_cards: tuple[dict, ...] = ()


Executor = Callable[[AsyncSession, Principal, BaseModel], Awaitable[ToolOutcome]]


@dataclass(frozen=True)
class Tool:
    spec: ToolSpec
    args: type[BaseModel]
    run: Executor
    # Medical-document tools (D101) also receive the request's ToolContext (storage, active document).
    needs_storage: bool = False
    # Tools that read or remember what this conversation last showed (doctors, free slots).
    needs_context: bool = False


def _when(instant: datetime, tz: str) -> str:
    return instant.astimezone(ZoneInfo(tz)).strftime("%a %d %b %Y, %I:%M %p")


def friendly(instant: datetime, tz: str) -> str:
    """"Friday, November 6 at 3:00 PM PKT": exact backend time, in the clinic's time zone."""
    local = instant.astimezone(ZoneInfo(tz))
    return f"{local:%A, %B} {local.day} at {local:%I:%M %p}".replace(" at 0", " at ") + f" {local:%Z}"


def confirmation_question(action: dict) -> str:
    """The one-line question shown with Confirm / Cancel (D104): backend values only, no model call."""
    doctor, when = action["doctor_name"], action["when_text"]
    if action["type"] == "walk_in_token":
        return f"Get a walk-in token for {doctor} on {when}? You'll be seen in arrival order after checking in at reception."
    if action["type"] == "book_appointment":
        # D120: an automatically assigned time says so, with its estimated place in the day.
        place = f" (estimated queue no. {action['queue_position']})" if action.get("queue_position") else ""
        assigned = "the next available time, " if action.get("booking_mode") == "auto" else ""
        if action.get("patient_name"):
            return f"Book {action['patient_name']} with {doctor} at {assigned}{when}{place}?"
        return f"Confirm your appointment with {doctor} at {assigned}{when}{place}?"
    if action["type"] == "cancel_appointment":
        return f"Cancel your appointment with {doctor} on {when}?"
    return f"Move your appointment with {doctor} from {when} to {action['new_when_text']}?"


def _expiry() -> str:
    return (clock.utcnow() + timedelta(minutes=settings.ai_action_ttl_minutes)).isoformat()


def _doctor_name(title: str | None, name: str) -> str:
    return " ".join(filter(None, [title, name]))


def _doctor_item(r) -> dict:
    return {
        "doctor_id": str(r.doctor.id),
        "name": " ".join(filter(None, [r.doctor.title, r.name])),
        "specialization": r.doctor.specialization,
        "department": r.department_name,
        "years_of_experience": r.doctor.years_of_experience,
        "consultation_fee": str(r.doctor.consultation_fee) if r.doctor.consultation_fee is not None else None,
        "availability": r.availability.status.value,
        "next_available": r.availability.next_available.isoformat() if r.availability.next_available else None,
    }


_SORTS = {
    "most_experienced": DoctorSort.experience_desc,
    "lowest_fee": DoctorSort.fee_asc,
}

ROUTING_NOTE = (
    "These are the specialties that commonly see this; it is routing guidance, not a diagnosis. "
    "Say so briefly, and that a general physician can also assess it first."
)


async def _search_doctors(db: AsyncSession, principal: Principal, a: SearchDoctorsArgs, ctx) -> ToolOutcome:
    """Doctors for a name, specialty, department or condition (D118).

    The user's words are resolved against the curated catalog (specializations,
    departments, conditions and symptoms; never model-made mappings), then real
    doctors are fetched in tiers: those linked to a specialization the user
    named, then to the condition's main specializations, then its other ones,
    then doctors of the matching departments. A literal search on names and
    the profile text adds anything else. Every doctor comes from the directory.
    """
    if a.doctor_name:
        # D133: a doctor the user names is looked up by that name first, and takes
        # precedence over any list shown earlier in the conversation.
        return await _by_name(db, principal, a, ctx)
    page = PageParams(page=1, page_size=10)
    sort = _SORTS.get(a.sort or "", DoctorSort.name_asc)
    base = {"department_id": a.department_id, "min_experience": a.min_years_experience, "sort": sort}
    words = " ".join(filter(None, [a.specialization, a.condition, a.query]))
    found = await catalog_service.resolve(db, words)
    ctx.last_slots, ctx.last_slots_doctor_id = [], None

    if found.urgent:
        ctx.last_doctor_ids = []
        return ToolOutcome({
            "urgent": True,
            "conditions": [t.name for t in found.topics if t.urgent],
            "note": "This can be an emergency. Tell the user to seek emergency care now (call the local emergency number "
                    "or go to the nearest emergency department) rather than wait for an appointment. Do not offer booking first.",
        })

    rows: list = []
    reasons: dict = {}

    def take(batch, reason: str) -> None:
        for r in batch:
            if r.doctor.id not in reasons:
                reasons[r.doctor.id] = reason
                rows.append(r)

    named = [x for x in found.specializations if x.via == "named"]
    for via, label in (("named", "specialization"), ("primary", "specialization"), ("secondary", "related specialization")):
        group = [x for x in found.specializations if x.via == via]
        if not group or len(rows) >= 10:
            continue
        batch, _ = await doctor_service.list_doctors(
            db, page, DoctorFilters(**base, specialization_ids=tuple(x.id for x in group)), public=True
        )
        wanted = {x.id for x in group}
        links = await catalog_service.doctor_specializations(db, [r.doctor.id for r in batch])
        for r in batch:
            matched = [x.name for x in links.get(r.doctor.id, []) if x.id in wanted]
            take([r], f"{label}: {', '.join(matched)}")
    department_ids = found.department_ids()
    if department_ids and len(rows) < 10:
        batch, _ = await doctor_service.list_doctors(db, page, DoctorFilters(**base, department_ids=tuple(department_ids)), public=True)
        take(batch, "department")
    # Literal search on names and profile text (also the only search when the
    # catalog knows none of the words).
    literal_q = a.query if (a.query and not found.found) or (a.query and not rows) else None
    literal_spec = a.specialization if not found.found else None
    if literal_q or literal_spec:
        batch, _ = await doctor_service.list_doctors(
            db, page, DoctorFilters(**base, specialization=literal_spec, q=literal_q), public=True
        )
        take(batch, "name or profile")
    widened = None
    if not found.found and not rows:
        # Words the catalog does not know (or no catalog loaded): the word-stem widening (D115).
        terms = specialties.search_terms(words)
        for stem in terms:
            batch, _ = await doctor_service.list_doctors(db, page, DoctorFilters(**base, q=stem), public=True)
            take(batch, "specialty words")
        widened = terms or None

    if sort is DoctorSort.experience_desc:
        rows.sort(key=lambda r: -r.doctor.years_of_experience)
    elif sort is DoctorSort.fee_asc:
        rows.sort(key=lambda r: (r.doctor.consultation_fee is None, r.doctor.consultation_fee or 0))
    rows = rows[:10]
    specs = await catalog_service.doctor_specializations(db, [r.doctor.id for r in rows])
    doctors = [
        {**_doctor_item(r), "specializations": [x.name for x in specs.get(r.doctor.id, [])], "matched_by": reasons[r.doctor.id]}
        for r in rows
    ]
    ctx.last_doctor_ids = [r.doctor.id for r in rows]
    card = {"kind": "doctors", "total": len(doctors), "items": [_doctor_item(r) for r in rows]} if doctors else None
    result: dict = {"total_matches": len(doctors), "doctors": [{"n": i + 1, **d} for i, d in enumerate(doctors)]}
    if found.found:
        result["understood"] = {
            "conditions": [t.name for t in found.topics],
            "specializations": [x.name for x in (named or found.specializations)][:6],
            "departments": [n for _, n in found.departments],
        }
    if found.topics:
        result["guidance"] = ROUTING_NOTE
    if found.ambiguous:
        result["clarify"] = ("Several specialties can help with this. If it is unclear which, ask one short question "
                             "(for example how long, or where it hurts) or suggest General & Family Medicine first.")
    if widened:
        result["note"] = "Matched by the specialty the user's words describe."
    if not doctors:
        wanted_names = [x.name for x in found.specializations][:4] or [n for _, n in found.departments]
        result["note"] = (
            f"No listed doctor currently practises {', '.join(wanted_names)}. Say so; offer General & Family Medicine or list_departments."
            if wanted_names else "No listed doctor matches. Say so and offer the departments (list_departments) or a broader search."
        )
    return ToolOutcome(result, card=card)


async def _by_name(db: AsyncSession, principal: Principal, a: SearchDoctorsArgs, ctx) -> ToolOutcome:
    """A named doctor (D133): exactly one match continues (with free times when booking);
    several are listed for the user to choose; similar names are only suggested; nobody
    by that name is said plainly, with a specialty's doctors as labelled alternatives only
    when the user also named one. Never a silent substitute."""
    from app.services import doctor_resolution

    found = await doctor_resolution.resolve(db, a.doctor_name)
    said = " ".join(a.doctor_name.split())
    ctx.last_slots, ctx.last_slots_doctor_id = [], None
    if found.chosen is not None:
        doctor = _doctor_item(found.chosen)
        if a.intent == "book":
            return await _selected(db, principal, ctx, doctor, "the doctor the user named")
        ctx.last_doctor_ids = [found.chosen.doctor.id]
        card = {"kind": "doctors", "total": 1, "items": [doctor]}
        return ToolOutcome({"total_matches": 1, "matched_by": "name", "doctors": [{"n": 1, **doctor}], "shown_to_user": True}, card=card)
    items = [_doctor_item(r) for r in found.doctors]
    card = {"kind": "doctors", "total": len(items), "items": items} if items else None
    if found.status == "ambiguous":
        ctx.last_doctor_ids = [r.doctor.id for r in found.doctors]
        return ToolOutcome({
            "ambiguous": True, "candidates": [{"n": i + 1, **d} for i, d in enumerate(items)],
            "note": f"Several listed doctors match '{said}'. Ask which one the user means, naming each with their specialty. Do not choose.",
        }, card=card)
    if found.status == "close":
        ctx.last_doctor_ids = [r.doctor.id for r in found.doctors]
        return ToolOutcome({
            "requested_doctor_found": False, "similar_names": [{"n": i + 1, **d} for i, d in enumerate(items)],
            "note": f"No listed doctor is named '{said}'. Say so, and ask whether they meant one of these similar names. "
                    "Do not choose or book one for them.",
        }, card=card)
    ctx.last_doctor_ids = []
    if a.specialization or a.condition or a.query:
        alternatives = await _search_doctors(db, principal, a.model_copy(update={"doctor_name": None}), ctx)
        alternatives.result.update(
            requested_doctor_found=False,
            note=f"No listed doctor is named '{said}'. Say that first. The doctors here are ALTERNATIVES for what else the user "
                 "asked: present them as alternatives, and never book one unless the user picks it.",
        )
        return alternatives
    return ToolOutcome({
        "requested_doctor_found": False, "total_matches": 0,
        "note": f"No doctor named '{said}' is listed at this clinic. Say so plainly and offer to search by specialty. "
                "Do not suggest other doctors on your own.",
    })


async def _selected(db: AsyncSession, principal: Principal, ctx, doctor: dict, reason: str) -> ToolOutcome:
    """One chosen doctor and their next free times: the step before choosing a time."""
    doctor = {k: v for k, v in doctor.items() if k != "n"}
    doctor_id = uuid.UUID(doctor["doctor_id"])
    try:
        tz, slots = await _fresh_slots(db, principal, doctor_id)
    except DomainError:
        tz, slots = None, []
    ctx.last_doctor_ids = [doctor_id]
    ctx.last_slots, ctx.last_slots_doctor_id = slots, doctor_id
    result = {
        "selected_doctor": doctor,
        "why": reason,
        "next_free_slots": [{"n": i + 1, **x} for i, x in enumerate(slots)],
        "timezone": tz,
        "note": "The doctor and these free times are shown to the user as cards. In one or two sentences, say who was chosen "
        "and the next free time (or that there is none this week), and ask which day or time suits them. Do not list every "
        "time, and do not propose a booking until the user picks a time.",
    }
    card = {"kind": "doctors", "total": 1, "items": [{**doctor, "selected": True}]}
    return ToolOutcome(result, card=card, extra_cards=(_slots_card(doctor, tz, slots),) if slots else ())


def _same(values: list, value) -> list:
    return [i for i, v in enumerate(values) if v == value]


async def _fresh_slots(db: AsyncSession, principal: Principal, doctor_id: uuid.UUID, days: int = 7, limit: int = 8):
    """The doctor's next free slots from now (never a stale list), in the clinic's time zone."""
    today = clock.utcnow().date()
    bookable, slots = await availability_service.available_slots(
        db, doctor_id, today, today + timedelta(days=days - 1), now=clock.utcnow(), min_lead=appointment_service.booking_lead(principal)
    )
    tz = str(bookable.timezone)
    return tz, [{"starts_at": s.starts_at.isoformat(), "local_time": _when(s.starts_at, tz)} for s in slots[:limit]]


def _slots_card(doctor: dict, tz: str, slots: list[dict], total: int | None = None) -> dict:
    return {
        "kind": "slots", "doctor_id": doctor["doctor_id"], "doctor_name": doctor["name"], "timezone": tz,
        "total": total if total is not None else len(slots), "items": slots,
    }


async def _pick_doctor(db: AsyncSession, principal: Principal, a: "PickArgs", ctx) -> ToolOutcome:
    if not ctx.last_doctor_ids:
        return ToolOutcome({"error": "No doctors have been listed in this conversation yet. Ask which doctor or specialty the user wants.",
                            "error_code": "DATA_NOT_FOUND"})
    shown = []
    for n, doctor_id in enumerate(ctx.last_doctor_ids, start=1):
        try:  # re-read now: fresh experience, fee and availability, and still listed
            shown.append({"n": n, **_doctor_item(await doctor_service.get_doctor(db, doctor_id, public=True))})
        except DomainError:
            continue
    if not shown:
        return ToolOutcome({"error": "The doctors shown earlier are no longer listed. Search again.", "error_code": "DATA_NOT_FOUND"})

    s = a.selector
    if s in ORDINALS or s == "last":
        index = len(ctx.last_doctor_ids) - 1 if s == "last" else ORDINALS.index(s)
        chosen = [d for d in shown if d["n"] == index + 1]
        if not chosen:
            return ToolOutcome({"error": f"Only {len(ctx.last_doctor_ids)} doctor(s) were shown.", "error_code": "DATA_NOT_FOUND"})
        reason = f"number {index + 1} in the list shown"
    elif s in COMPARISONS:
        key, best, label = COMPARISONS[s]
        known = [d for d in shown if d[key] is not None]
        if not known:
            return ToolOutcome({"error": f"None of the doctors shown has a known {key.replace('_', ' ')}.", "error_code": "DATA_NOT_FOUND"})
        values = [float(d[key]) if key == "consultation_fee" else d[key] for d in known]
        target = best(values)
        chosen = [known[i] for i in _same(values, target)]
        reason = f"{label} of the {len(shown)} doctors shown" + (f" ({target} years)" if key == "years_of_experience" else "")
    elif s == "by_name" and a.name:
        from app.services.doctor_resolution import _fits, name_words

        words = name_words(a.name)
        chosen = [d for d in shown if words and _fits(words, name_words(d["name"]))]
        if not chosen:
            # D133: a name that is not in the list shown is a new request: look it up in the directory.
            return await _by_name(db, principal, SearchDoctorsArgs(doctor_name=a.name, intent="book"), ctx)
        reason = "named by the user"
    else:
        return ToolOutcome({"error": "That selector does not apply to doctors.", "error_code": "INVALID_ARGUMENTS"})

    if not chosen:
        return ToolOutcome({"error": "No doctor shown matches that.", "doctors_shown": shown, "error_code": "DATA_NOT_FOUND"})
    if len(chosen) > 1:
        return ToolOutcome({"ambiguous": True, "candidates": chosen,
                            "note": "Several doctors match equally: ask the user which one, naming them. Do not choose."})
    return await _selected(db, principal, ctx, chosen[0], reason)


# selector -> (field, which value wins, how to say it)
COMPARISONS = {
    "most_experienced": ("years_of_experience", max, "the most experienced"),
    "least_experienced": ("years_of_experience", min, "the least experienced"),
    "lowest_fee": ("consultation_fee", min, "the lowest consultation fee"),
    "highest_fee": ("consultation_fee", max, "the highest consultation fee"),
    "earliest_available": ("next_available", min, "the earliest next free time"),
}


def _time_matches(local_time: str, said: str) -> bool:
    """'Thu 06 Nov 2026, 05:30 PM' against what the user said ('5:30 pm', '17:30', '5 pm')."""
    said = " ".join(said.lower().replace(".", "").split())
    stamp = datetime.strptime(local_time, "%a %d %b %Y, %I:%M %p")
    twelve = f"{stamp:%I:%M}".lstrip("0")
    meridiem = f"{stamp:%p}".lower()
    forms = {f"{stamp.hour}:{stamp.minute:02d}", f"{twelve} {meridiem}", f"{twelve}{meridiem}"}
    if stamp.minute == 0:
        hour = f"{stamp:%I}".lstrip("0")
        forms |= {f"{hour} {meridiem}", f"{hour}{meridiem}"}
    return any(f in said for f in forms)


async def _pick_slot(db: AsyncSession, principal: Principal, a: "PickArgs", ctx) -> ToolOutcome:
    slots, doctor_id = ctx.last_slots, ctx.last_slots_doctor_id
    if not slots or doctor_id is None:
        return ToolOutcome({"error": "No free times have been shown yet. Check availability (get_doctor_availability) first.",
                            "error_code": "DATA_NOT_FOUND"})
    s = a.selector
    if s == "earliest":
        chosen = [min(slots, key=lambda x: x["starts_at"])]
    elif s == "latest":
        chosen = [max(slots, key=lambda x: x["starts_at"])]
    elif s == "last":
        chosen = slots[-1:]
    elif s in ORDINALS:
        index = ORDINALS.index(s)
        chosen = slots[index:index + 1]
    elif s == "by_name" and a.name:
        chosen = [x for x in slots if _time_matches(x["local_time"], a.name)]
    else:
        return ToolOutcome({"error": "That selector does not apply to times.", "error_code": "INVALID_ARGUMENTS"})
    if not chosen:
        return ToolOutcome({"error": "None of the times shown matches that.", "times_shown": slots, "error_code": "DATA_NOT_FOUND"})
    if len(chosen) > 1:
        return ToolOutcome({"ambiguous": True, "candidates": chosen, "note": "Several times match: ask which one."})
    slot = chosen[0]
    if principal.patient_id and principal.has(Perm.appointment_create_own):
        # Straight to the confirmation question; the slot is checked now and again on Confirm.
        return await _propose_booking(db, principal, ProposeBookingArgs(doctor_id=doctor_id, starts_at=slot["starts_at"]))
    return ToolOutcome({"selected_slot": slot, "doctor_id": str(doctor_id),
                        "note": "Use this doctor_id and starts_at with the booking tool for the patient."})


async def _pick(db: AsyncSession, principal: Principal, a: "PickArgs", ctx) -> ToolOutcome:
    return await (_pick_doctor if a.entity == "doctor" else _pick_slot)(db, principal, a, ctx)


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


async def _availability(db: AsyncSession, principal: Principal, a: AvailabilityArgs, ctx) -> ToolOutcome:
    date_to = a.date_to or a.date_from
    if date_to < a.date_from or (date_to - a.date_from).days > 6:
        return ToolOutcome({"error": "Ask for at most 7 days, with date_to on or after date_from."})
    try:
        doctor = _doctor_item(await doctor_service.get_doctor(db, a.doctor_id, public=True))
        bookable, slots = await availability_service.available_slots(
            db, a.doctor_id, a.date_from, date_to, now=clock.utcnow(), min_lead=appointment_service.booking_lead(principal)
        )
    except DomainError as exc:
        return ToolOutcome({"error": exc.message})
    tz = str(bookable.timezone)
    if a.part_of_day:
        start, end = PART_OF_DAY[a.part_of_day]
        slots = [x for x in slots if start <= x.starts_at.astimezone(ZoneInfo(tz)).hour < end]
    free = [{"starts_at": x.starts_at.isoformat(), "local_time": _when(x.starts_at, tz)} for x in slots[:30]]
    ctx.last_doctor_ids = [a.doctor_id]
    ctx.last_slots, ctx.last_slots_doctor_id = free[:12], a.doctor_id
    result = {"doctor": doctor["name"], "timezone": tz, "free_slots": [{"n": i + 1, **x} for i, x in enumerate(free)],
              "more": max(0, len(slots) - 30)}
    if not free:
        result["note"] = "No free time matches. Say so plainly and offer another day or part of the day."
    return ToolOutcome(result, card=_slots_card(doctor, tz, free[:12], len(slots)) if free else None)


class WalkInTokenArgs(_Args):
    doctor_id: uuid.UUID
    session_date: date | None = Field(default=None, description="The day the patient wants to come; today if not given")


async def _my_queue_status(db: AsyncSession, principal: Principal, a: _Args) -> ToolOutcome:
    """The patient's own tokens and place (D117): composed here, never by the model."""
    from app.services import queue_service

    entries = await queue_service.my_queue(db, principal)
    if not entries:
        return ToolOutcome({"tokens": 0, "answer_shown_to_user": True},
                           reply="You have no queue token right now. You get one when you check in at reception, or you can ask me for a walk-in token.")
    lines = []
    for e in entries:
        place = f"place {e.position} in the queue, estimated wait about {e.estimated_wait.min_minutes}–{e.estimated_wait.max_minutes} minutes" if e.position else e.state.value.replace("_", " ")
        booked = f", booked for {friendly(e.scheduled_at, e.timezone)}" if e.scheduled_at else ""
        lines.append(f"- Token **#{e.token_number}** with {e.doctor_name} on {e.session_date:%a %d %b}{booked}: {place}.")
    reply = "\n".join(lines) + "\n\nWaits are estimates: consultations vary, so the actual time can differ."
    return ToolOutcome({"tokens": len(entries), "answer_shown_to_user": True}, reply=reply)


async def _propose_walk_in_token(db: AsyncSession, principal: Principal, a: WalkInTokenArgs) -> ToolOutcome:
    """Checks the doctor takes walk-ins that day; issues nothing until the user confirms."""
    from app.services import scheduling_service

    try:
        doctor = await doctor_service.get_doctor(db, a.doctor_id, public=True)
        bookable = await availability_service.bookable_doctor(db, a.doctor_id)
    except DomainError as exc:
        return ToolOutcome({"error": exc.message})
    if not (await scheduling_service.effective_policy(db, a.doctor_id)).walk_ins_open:
        return ToolOutcome({"error": "This doctor sees booked appointments only: offer a time with get_doctor_availability instead."})
    tz = str(bookable.timezone)
    day = a.session_date or clock.utcnow().astimezone(ZoneInfo(tz)).date()
    name = " ".join(filter(None, [doctor.doctor.title, doctor.name]))
    action = {
        "type": "walk_in_token", "status": "pending", "doctor_id": str(a.doctor_id), "doctor_name": name,
        "session_date": day.isoformat(), "when_text": f"{day:%A, %B} {day.day}", "timezone": tz, "expires_at": _expiry(),
    }
    return ToolOutcome(
        {"proposed": True, "note": "The confirmation question with Confirm / Cancel buttons is already shown to the user. Do not write anything else."},
        action=action, reply=confirmation_question(action),
    )


async def _propose_booking(db: AsyncSession, principal: Principal, a: ProposeBookingArgs) -> ToolOutcome:
    """Checks the slot is really free now; books nothing. Never an override or double booking (D117)."""
    from app.services import scheduling_service

    patient = None
    if (await scheduling_service.effective_policy(db, a.doctor_id)).mode.value == "fifo":
        return ToolOutcome({"error": "This doctor sees patients in arrival order: there are no booked times. Offer a walk-in token (request_walk_in_token)."})
    try:
        if isinstance(a, ProposeBookingForPatientArgs):
            patient = await patient_service.get_patient(db, principal, a.patient_id)
        doctor = await doctor_service.get_doctor(db, a.doctor_id, public=True)
        bookable = await availability_service.bookable_doctor(db, a.doctor_id)
        if a.earliest_on is not None:
            # Automatic token booking (D120): the server assigns the time, never the model.
            found = await appointment_service.next_available(
                db, principal, a.doctor_id, a.earliest_on,
                patient_id=patient.id if patient is not None else principal.patient_id,
            )
            if found.slot is None:
                later = f" The next date with free times is {found.next_date.isoformat()}." if found.next_date else ""
                return ToolOutcome({"error": f"No free time on {a.earliest_on.isoformat()}.{later} Offer that date or another."})
            slot, mode, position = found.slot, "auto", found.queue_position
        else:
            slot = await appointment_service._find_free_slot(db, principal, a.doctor_id, a.starts_at)
            mode = "custom"
            position = await appointment_service.queue_position(db, a.doctor_id, slot.starts_at, bookable.timezone)
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
        "booking_mode": mode,
        "queue_position": position,
        "duration_minutes": int((slot.ends_at - slot.starts_at).total_seconds() // 60),
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
                  "Search the PUBLIC directory of the clinic's doctors to find a new doctor: by name, department, specialization, "
                  "or the disease/symptom the user mentions (pass it as `condition` in their own words: 'thyroid problem', "
                  "'migraines', 'kidney stones', 'child with fever'). Specialty words ('heart', 'skin', 'children's neurologist') go "
                  "in `specialization`. The clinic's catalog maps them to specialties; never guess a specialty yourself. "
                  "Use sort='most_experienced' or 'lowest_fee' when asked. NOT for the user's own appointments or the doctors "
                  "they have seen or booked: use get_my_appointments.",
                  SearchDoctorsArgs),
            SearchDoctorsArgs,
            _search_doctors,
            needs_context=True,
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
            _spec("get_doctor_availability",
                  "Free appointment slots of one doctor between two dates (max 7 days), optionally only morning, afternoon "
                  "or evening ('tomorrow evening'). Use real results only.", AvailabilityArgs),
            AvailabilityArgs,
            _availability,
            needs_context=True,
        ),
        "pick_from_previous": Tool(
            _spec("pick_from_previous",
                  "Resolve a reference to something shown earlier in THIS conversation: a doctor from the last doctor list "
                  "('the first one', 'the second doctor', 'the most experienced one', 'the cheapest', 'her', 'Dr Khan') "
                  "or a time from the last free times ('the earliest one', 'take 5:30', 'the last slot'). Picking a doctor "
                  "also returns their next free times; picking a time prepares the booking for the user to confirm. "
                  "Never guess ids yourself.", PickArgs),
            PickArgs,
            _pick,
            needs_context=True,
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
                    "Propose booking for a patient (patient_id from find_patient): a free slot (starts_at), or "
                    "earliest_on=<date> for the next available time. Does not book: the user must press Confirm.",
                    ProposeBookingForPatientArgs,
                ),
                ProposeBookingForPatientArgs,
                _propose_booking,
            )
    if principal.patient_id and principal.has(Perm.appointment_create_own):
        tools["propose_booking"] = Tool(
            _spec(
                "propose_booking",
                "Propose booking for the signed-in patient: either a free slot (starts_at from get_doctor_availability) "
                "or, for 'the next available' / 'earliest' appointment, earliest_on=<date> and the clinic assigns the "
                "earliest free time. This does not book: the user must press Confirm.",
                ProposeBookingArgs,
            ),
            ProposeBookingArgs,
            _propose_booking,
        )
        # The day's queue (D117): the patient's own tokens, and a walk-in token they confirm.
        tools["get_my_queue_status"] = Tool(
            _spec("get_my_queue_status", "The signed-in patient's own queue tokens today and later: token number, place and an estimated wait range. 'What is my queue position?', 'how long is the wait?'. The answer is shown to the user directly.", _Args),
            _Args,
            _my_queue_status,
        )
        tools["request_walk_in_token"] = Tool(
            _spec("request_walk_in_token", "Propose a walk-in token for one doctor and day (doctors who see patients in arrival order, or hybrid doctors). Does not issue it: the user must press Confirm.", WalkInTokenArgs),
            WalkInTokenArgs,
            _propose_walk_in_token,
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
            if tool.needs_storage or tool.needs_context:
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

