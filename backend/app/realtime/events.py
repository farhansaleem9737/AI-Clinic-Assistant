"""The real-time event contract (D122).

An event says *what changed*, never the changed data: a type, the resource
and a few ids or dates the page needs to decide what to re-read through the
REST API (which checks permissions again). No names, reasons, notes,
diagnoses or documents travel over the socket.

Each event is addressed to channels. A connection is subscribed by the
server, from its principal's verified identity and permissions
(``channels_for``); the client cannot choose them.
"""

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.core import clock
from app.core.permissions import Perm, Principal

VERSION = 1

# Channels. Ids are the patient's / doctor's / user's own row ids.
STAFF = "staff"  # every appointment and schedule (reception, admin): appointment:read_any
CLINIC = "clinic"  # coarse "doctor X's free times or queue changed": anyone who may see availability
REVIEWERS = "reviewers"  # doctor applications to review: doctor_application:review


def user_channel(user_id: uuid.UUID) -> str:
    return f"user:{user_id}"


def patient_channel(patient_id: uuid.UUID) -> str:
    return f"patient:{patient_id}"


def doctor_channel(doctor_id: uuid.UUID) -> str:
    return f"doctor:{doctor_id}"


def record_channel(patient_id: uuid.UUID) -> str:
    """One patient's health record, for treating doctors who asked to watch it
    (each watch is authorized like a read of the record: see endpoints/realtime.py)."""
    return f"record:{patient_id}"


def channels_for(principal: Principal) -> frozenset[str]:
    """What this signed-in user may hear, from their verified identity."""
    channels = {user_channel(principal.user_id)}  # their own notifications
    if principal.patient_id and principal.has(Perm.appointment_read_own):
        channels.add(patient_channel(principal.patient_id))
    if principal.doctor_id and principal.has(Perm.appointment_read_assigned):
        channels.add(doctor_channel(principal.doctor_id))
    if principal.has(Perm.appointment_read_any):
        channels.add(STAFF)
    if principal.has(Perm.availability_read):
        channels.add(CLINIC)
    if principal.has(Perm.doctor_application_review):
        channels.add(REVIEWERS)
    return frozenset(channels)


@dataclass(frozen=True)
class Event:
    type: str  # e.g. "appointment.created"
    resource: str  # "appointment", "schedule", "queue", "notification", "availability"
    resource_id: str | None
    channels: frozenset[str]
    payload: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=clock.utcnow)

    @property
    def key(self) -> tuple:
        """Same change reported twice in one transaction (two flushes) → one event."""
        return (self.type, self.resource, self.resource_id, tuple(sorted(self.payload.items())))

    def to_json(self) -> str:
        return json.dumps(
            {
                "version": VERSION,
                "event_id": self.event_id,
                "type": self.type,
                "resource": self.resource,
                "resource_id": self.resource_id,
                "timestamp": self.timestamp.isoformat().replace("+00:00", "Z"),
                "payload": self.payload,
            },
            separators=(",", ":"),
            default=str,
        )
