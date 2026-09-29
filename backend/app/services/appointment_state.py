"""The appointment state machine (architecture §8).

One table says which transitions exist and who may perform each: a
permission plus the *scope* it applies in — any appointment, one's own
(the patient), or one's assigned (the doctor). Routers never compare
statuses; everything goes through ``authorize_transition``.

    requested ─► scheduled ─► confirmed ─► checked_in ─► in_progress ─► completed
        │            │  │          │
        └────────────┴──┴──────────┴──► cancelled        (before check-in)
                     └──────────┴──► no_show            (after start + grace)
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.core.exceptions import BusinessRuleError, ConflictError, PermissionDeniedError
from app.core.permissions import Perm, Principal
from app.models.appointment import Appointment, AppointmentStatus

S = AppointmentStatus

# Statuses from which an appointment can still be cancelled or rescheduled.
PRE_CHECK_IN = (S.requested, S.scheduled, S.confirmed)


class Scope(Enum):
    ANY = "any"
    OWN = "own"  # the caller is the appointment's patient
    ASSIGNED = "assigned"  # the caller is the appointment's doctor


@dataclass(frozen=True)
class Context:
    principal: Principal
    appointment: Appointment
    now: datetime
    timezone: ZoneInfo  # the doctor's department timezone


Guard = Callable[[Context], None]


@dataclass(frozen=True)
class Grant:
    permission: Perm
    scope: Scope
    # Extra condition for this grant only (e.g. patients must cancel early).
    guard: Guard | None = None


# ---- guards --------------------------------------------------------------------


def before_patient_cutoff(ctx: Context) -> None:
    cutoff = ctx.appointment.starts_at - timedelta(minutes=settings.patient_cancellation_cutoff_minutes)
    if ctx.now > cutoff:
        raise BusinessRuleError(
            "It is too late to change this appointment online; please contact the clinic",
            code="PAST_PATIENT_CUTOFF",
        )


def on_appointment_day(ctx: Context) -> None:
    appt = ctx.appointment
    if appt.starts_at.astimezone(ctx.timezone).date() != ctx.now.astimezone(ctx.timezone).date():
        raise BusinessRuleError("Patients can only be checked in on the day of the appointment", code="NOT_APPOINTMENT_DAY")
    if ctx.now >= appt.ends_at:
        raise BusinessRuleError("The appointment time has already passed", code="APPOINTMENT_OVER")


def after_no_show_grace(ctx: Context) -> None:
    if ctx.now < ctx.appointment.starts_at + timedelta(minutes=settings.no_show_grace_minutes):
        raise BusinessRuleError(
            f"No-show can only be recorded {settings.no_show_grace_minutes} minutes after the start time",
            code="TOO_EARLY_FOR_NO_SHOW",
        )


# ---- the table -------------------------------------------------------------------

_cancel = [
    Grant(Perm.appointment_cancel_any, Scope.ANY),
    Grant(Perm.appointment_cancel_assigned, Scope.ASSIGNED),
    Grant(Perm.appointment_cancel_own, Scope.OWN, guard=before_patient_cutoff),
]
_no_show = [Grant(Perm.appointment_manage, Scope.ANY), Grant(Perm.appointment_consult, Scope.ASSIGNED)]
_check_in = [Grant(Perm.appointment_check_in, Scope.ANY)]

TRANSITIONS: dict[tuple[AppointmentStatus, AppointmentStatus], list[Grant]] = {
    (S.requested, S.scheduled): [Grant(Perm.appointment_manage, Scope.ANY)],
    (S.scheduled, S.confirmed): [
        Grant(Perm.appointment_manage, Scope.ANY),
        Grant(Perm.appointment_confirm_own, Scope.OWN),
    ],
    (S.scheduled, S.checked_in): _check_in,
    (S.confirmed, S.checked_in): _check_in,
    (S.checked_in, S.in_progress): [Grant(Perm.appointment_consult, Scope.ASSIGNED)],
    (S.in_progress, S.completed): [Grant(Perm.appointment_consult, Scope.ASSIGNED)],
    (S.scheduled, S.no_show): _no_show,
    (S.confirmed, S.no_show): _no_show,
    **{(status, S.cancelled): _cancel for status in PRE_CHECK_IN},
}

# Conditions on the transition itself, whoever performs it.
TRANSITION_GUARDS: dict[AppointmentStatus, Guard] = {
    S.checked_in: on_appointment_day,
    S.no_show: after_no_show_grace,
}

RESCHEDULE_GRANTS = [
    Grant(Perm.appointment_manage, Scope.ANY),
    Grant(Perm.appointment_reschedule_own, Scope.OWN, guard=before_patient_cutoff),
]


def _in_scope(grant: Grant, ctx: Context) -> bool:
    principal, appt = ctx.principal, ctx.appointment
    if not principal.has(grant.permission):
        return False
    if grant.scope is Scope.OWN:
        return principal.patient_id is not None and principal.patient_id == appt.patient_id
    if grant.scope is Scope.ASSIGNED:
        return principal.doctor_id is not None and principal.doctor_id == appt.doctor_id
    return True


def _authorize(grants: list[Grant], ctx: Context) -> None:
    """Pass if any grant applies. A grant whose own guard fails is remembered
    so the caller gets the specific reason instead of a bare 403."""
    guard_error: BusinessRuleError | None = None
    for grant in grants:
        if not _in_scope(grant, ctx):
            continue
        if grant.guard is None:
            return
        try:
            grant.guard(ctx)
            return
        except BusinessRuleError as exc:
            guard_error = exc
    if guard_error is not None:
        raise guard_error
    raise PermissionDeniedError("You are not allowed to make this change")


def authorize_transition(ctx: Context, target: AppointmentStatus) -> None:
    current = ctx.appointment.status
    grants = TRANSITIONS.get((current, target))
    if grants is None:
        raise ConflictError(
            f"Cannot change an appointment from {current.value} to {target.value}",
            code="INVALID_TRANSITION",
            details={"from": current.value, "to": target.value},
        )
    _authorize(grants, ctx)
    if (guard := TRANSITION_GUARDS.get(target)) is not None:
        guard(ctx)


def authorize_reschedule(ctx: Context) -> None:
    if ctx.appointment.status not in PRE_CHECK_IN:
        raise ConflictError(
            "Only appointments that have not started can be rescheduled", code="INVALID_TRANSITION"
        )
    _authorize(RESCHEDULE_GRANTS, ctx)


def allowed_actions(ctx: Context) -> tuple[list[str], bool]:
    """What the caller could do right now — lets the UI show only valid
    buttons. The same checks run again when an action is submitted."""
    allowed = []
    for (current, target) in TRANSITIONS:
        if current is not ctx.appointment.status:
            continue
        try:
            authorize_transition(ctx, target)
            allowed.append(target.value)
        except (BusinessRuleError, PermissionDeniedError, ConflictError):
            pass
    try:
        authorize_reschedule(ctx)
        can_reschedule = True
    except (BusinessRuleError, PermissionDeniedError, ConflictError):
        can_reschedule = False
    return allowed, can_reschedule
