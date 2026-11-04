"""The patient's own appointment history through the assistant (D103), with a
scripted (mocked) model and synthetic appointments: two completed, one
cancelled, one upcoming, with two doctors."""

import json
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core import clock
from app.models import Appointment
from app.models.appointment import AppointmentStatus, CancellationReason
from app.services.ai.provider import AiUnavailableError, Reply
from tests.test_ai_agent import BASE, call, provider, text_reply, tool_results  # noqa: F401  (provider is a fixture)


async def book(client, clinic, patient, doctor, days, hhmm="10:00"):
    made = await client.post(
        "/api/v1/appointments/", json={"doctor_id": str(doctor.id), "starts_at": clinic.slot(days, hhmm).isoformat()},
        headers=await clinic.headers_for(patient.user_id),
    )
    assert made.status_code == 201, made.text
    return made.json()["id"]


@pytest.fixture
async def history(client, db_session, clinic):
    """Alice: completed with Alpha (20 days ago), completed with Beta (10 days ago),
    cancelled with Alpha (5 days ago), upcoming with Beta."""
    ids = {
        "alpha_done": await book(client, clinic, clinic.patient_a, clinic.doctor_a, 3, "09:00"),
        "beta_done": await book(client, clinic, clinic.patient_a, clinic.doctor_b, 3, "11:00"),
        "alpha_cancelled": await book(client, clinic, clinic.patient_a, clinic.doctor_a, 4, "09:00"),
        "beta_upcoming": await book(client, clinic, clinic.patient_a, clinic.doctor_b, 5, "10:00"),
    }
    now = clock.utcnow()
    for key, days_ago, status in (("alpha_done", 20, AppointmentStatus.completed), ("beta_done", 10, AppointmentStatus.completed),
                                  ("alpha_cancelled", 5, AppointmentStatus.cancelled)):
        row = await db_session.scalar(select(Appointment).where(Appointment.id == ids[key]))
        length = row.ends_at - row.starts_at
        row.starts_at = (now - timedelta(days=days_ago)).replace(minute=0, second=0, microsecond=0)
        row.ends_at = row.starts_at + length
        row.status = status
        if status is AppointmentStatus.cancelled:
            row.cancellation_reason = CancellationReason.patient_request
    await db_session.commit()
    return ids


async def ask(client, headers, provider, text, *replies, conversation_id=None):
    provider.calls.clear()
    provider.replies = list(replies)
    body = {"text": text, **({"conversation_id": conversation_id} if conversation_id else {})}
    response = await client.post(f"{BASE}/messages", json=body, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def test_doctors_from_past_appointments_then_the_latest_then_its_doctor(client, clinic, history, provider):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    sent = await ask(client, alice, provider, "Could you tell me the names and schedules of doctors with whome I got appointments in the past?",
                     call("get_my_appointments", scope="past"), text_reply("Would you like to see a doctor's profile?"))
    assert "get_my_appointments" in provider.calls[0]["tools"]  # offered, even with AI_PHI_ALLOWED off
    answer = sent["assistant_message"]["content"]
    assert "Doctor Alpha" in answer and "Doctor Beta" in answer
    assert "completed (attended)" in answer and "cancelled" in answer and "did not take place" in answer
    [card] = sent["assistant_message"]["results"]
    assert card["kind"] == "appointment_history" and [i["appointment_id"] for i in card["items"]] == [
        history["alpha_cancelled"], history["beta_done"], history["alpha_done"]]  # newest first; the upcoming one is not "past"
    assert {i["status"] for i in card["items"]} == {"completed", "cancelled"}
    assert all(i["date"] and i["start"] and i["specialization"] for i in card["items"])
    # Free tier: the model saw ids and statuses only, no names or dates.
    seen = json.dumps(tool_results(provider.calls[1])["get_my_appointments"])
    assert "Doctor Alpha" not in seen and "Doctor Beta" not in seen and card["items"][0]["date"] not in seen
    conversation = sent["conversation"]["id"]

    # "Which one was the latest?" works on the appointments just shown.
    sent = await ask(client, alice, provider, "Which one was the latest?",
                     call("get_my_appointments", from_previous=True, pick="latest"), text_reply("Anything else?"),
                     conversation_id=conversation)
    answer = sent["assistant_message"]["content"]
    assert answer.startswith("Your most recent appointment was with **Doctor Alpha**") and "cancelled" in answer
    # The last booking was cancelled, so the last visit that took place is named too.
    assert "Your most recent completed visit was with **Doctor Beta**" in answer
    [card] = sent["assistant_message"]["results"]
    assert [i["appointment_id"] for i in card["items"]] == [history["alpha_cancelled"]]

    # "Show that doctor's profile": the doctor id came from the previous result.
    doctor_id = tool_results(provider.calls[1])["get_my_appointments"]["appointments"][0]["doctor_id"]
    sent = await ask(client, alice, provider, "show that doctor's profile",
                     call("get_doctor_profile", doctor_id=doctor_id), text_reply("Here is the profile."), conversation_id=conversation)
    assert sent["assistant_message"]["results"][0]["items"][0]["name"] == "Doctor Alpha"


async def test_visited_means_completed_and_upcoming_is_separate(client, clinic, history, provider):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    sent = await ask(client, alice, provider, "which doctors did i visit", call("get_my_appointments", scope="visited"), Reply(text=None, tool_calls=[]))
    items = sent["assistant_message"]["results"][0]["items"]
    assert [i["status"] for i in items] == ["completed", "completed"] and {i["doctor"] for i in items} == {"Doctor Alpha", "Doctor Beta"}
    sent = await ask(client, alice, provider, "my next appointment", call("get_my_appointments", scope="upcoming", pick="earliest"),
                     Reply(text=None, tool_calls=[]))
    assert [i["appointment_id"] for i in sent["assistant_message"]["results"][0]["items"]] == [history["beta_upcoming"]]


async def test_no_history_is_said_plainly(client, clinic, provider):
    bob = await clinic.headers_for(clinic.patient_b.user_id)
    sent = await ask(client, bob, provider, "who was my last doctor", call("get_my_appointments", scope="past", pick="latest"),
                     Reply(text=None, tool_calls=[]))
    assert sent["assistant_message"]["content"] == "You have no past appointments."
    assert sent["assistant_message"]["results"] == []


async def test_only_ones_own_appointments_are_ever_returned(client, clinic, history, provider):
    bob = await clinic.headers_for(clinic.patient_b.user_id)
    sent = await ask(client, bob, provider, "show all appointments", call("get_my_appointments", scope="all", patient_id=str(clinic.patient_a.id)),
                     Reply(text=None, tool_calls=[]))
    assert "Doctor Alpha" not in sent["assistant_message"]["content"]  # the extra patient_id argument is ignored
    assert sent["assistant_message"]["results"] == []


async def test_a_failed_lookup_is_explained_not_blamed_on_the_user(client, clinic, history, provider, monkeypatch):
    from app.services import appointment_service

    async def broken(*args, **kwargs):
        raise RuntimeError("database went away")

    monkeypatch.setattr(appointment_service, "list_appointments", broken)
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    sent = await ask(client, alice, provider, "my appointments", call("get_my_appointments"), Reply(text=None, tool_calls=[]))
    answer = sent["assistant_message"]["content"]
    assert answer == "I couldn't retrieve your appointments right now. Please try again." and "database went away" not in answer
    assert tool_results(provider.calls[1])["get_my_appointments"]["error_code"] == "TOOL_EXECUTION_FAILED"


async def test_a_transient_model_failure_is_retried_once(client, clinic, provider):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    sent = await ask(client, alice, provider, "hello", AiUnavailableError("down", code="AI_UNAVAILABLE"), text_reply("Hello!"))
    assert sent["assistant_message"]["content"] == "Hello!"
    provider.calls.clear()
    provider.replies = [AiUnavailableError("down"), AiUnavailableError("down")]
    response = await client.post(f"{BASE}/messages", json={"text": "hello"}, headers=alice)
    assert response.status_code == 503  # bounded: one retry only
