"""Live updates from the real booking path (D122), on PostgreSQL.

A booking publishes its events after it commits; a refused booking
(the slot was taken) publishes nothing. tests/test_realtime.py covers the
socket itself without a database.
"""

import pytest

from app.core.permissions import Principal
from app.realtime import capture
from app.realtime.events import CLINIC, STAFF, doctor_channel, patient_channel, record_channel
from app.realtime.hub import UNAUTHORIZED
from app.services import health_record_service, rbac_service
from tests.test_appointments import as_, book, status  # noqa: F401  (fixtures)


class Published(list):
    closed: list  # (user_id, close code) of sockets closed after commit


@pytest.fixture
def published(monkeypatch):
    sent = Published()
    sent.closed = []
    monkeypatch.setattr(capture.hub, "publish", sent.append)
    monkeypatch.setattr(capture.hub, "close_user", lambda user_id, code, reason: sent.closed.append((user_id, code)))
    return sent


async def test_a_booking_is_announced_after_commit_and_a_refused_one_is_not(clinic, book, as_, client, published):
    response = await book("alice")
    assert response.status_code == 201, response.text
    appointment_id = response.json()["id"]

    created = [e for e in published if e.type == "appointment.created"]
    assert len(created) == 1 and created[0].resource_id == appointment_id
    assert created[0].channels == {
        patient_channel(clinic.patient_a.id),
        doctor_channel(clinic.doctor_a.id),
        STAFF,
    }
    assert set(created[0].payload) == {"doctor_id", "patient_id", "date", "status"}  # no reason, no names
    assert any(e.type == "availability.changed" and e.channels == {CLINIC} for e in published)
    # The doctor's notification of the new booking reaches the doctor's own user channel.
    assert any(e.type == "notification.created" for e in published)

    published.clear()
    refused = await book("bob")  # the same slot
    assert refused.status_code == 409
    assert [e for e in published if e.resource == "appointment"] == []

    cancelled = await status(client, await as_("alice"), appointment_id, "cancelled", cancellation_reason="patient_request")
    assert cancelled.status_code == 200, cancelled.text
    assert [e.type for e in published if e.resource == "appointment"] == ["appointment.cancelled"]


async def test_record_changes_and_who_may_watch_them(clinic, book, as_, client, db_session, published):
    assert (await book("alice")).status_code == 201  # Dr. A now treats Alice; Dr. B does not
    alice = clinic.patient_a.id
    dr_a = await rbac_service.load_principal_by_id(db_session, clinic.doctor_a.user_id)
    dr_b = await rbac_service.load_principal_by_id(db_session, clinic.doctor_b.user_id)
    assert isinstance(dr_a, Principal)
    assert await health_record_service.may_read(db_session, dr_a, alice) is True
    assert await health_record_service.may_read(db_session, dr_b, alice) is False

    published.clear()
    added = await client.post(
        f"/api/v1/patients/{alice}/health-records/diagnoses", json={"condition": "Asthma"}, headers=await as_("dr_a")
    )
    assert added.status_code == 201, added.text
    (event,) = [e for e in published if e.type == "health_record.updated"]
    assert event.channels == {patient_channel(alice), record_channel(alice)}
    assert event.payload == {"patient_id": str(alice), "kind": "diagnoses"}  # never "Asthma"


async def test_deactivation_closes_the_users_sockets_after_commit(clinic, as_, client, published):
    response = await client.post(f"/api/v1/users/{clinic.patient_a.user_id}/deactivate", headers=await as_("admin"))
    assert response.status_code == 200, response.text
    assert (clinic.patient_a.user_id, UNAUTHORIZED) in published.closed
