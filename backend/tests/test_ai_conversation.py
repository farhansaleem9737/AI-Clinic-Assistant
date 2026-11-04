"""Conversational behaviour (D104), with a scripted (mocked) model: one-line
confirmations written from backend values, the medical disclaimer once and
first, and specific failure messages."""

from uuid import UUID

from sqlalchemy import func, select

from app.models import Appointment
from app.services.ai.agent_service import DISCLAIMER, SYSTEM_PROMPT
from app.services.ai.provider import Reply, ToolCall
from app.services.ai.tools import friendly
from tests.test_ai_agent import BASE, call, provider, text_reply, tool_results  # noqa: F401  (provider is a fixture)


async def ask(client, headers, provider, text, *replies):
    provider.calls.clear()
    provider.replies = list(replies)
    response = await client.post(f"{BASE}/messages", json={"text": text}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def test_a_booking_is_one_question_then_one_booking(client, db_session, clinic, provider):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    slot = clinic.slot(3, "15:00")
    sent = await ask(
        client, alice, provider, "book me with dr alpha at 3pm",
        # The model talks before and after the proposal: none of it is kept.
        Reply(text="Let me check that slot for you.", tool_calls=[ToolCall("c1", "propose_booking", {"doctor_id": str(clinic.doctor_a.id), "starts_at": slot.isoformat()})]),
        text_reply("Great! I have prepared your booking. Please review the details and press Confirm to book it."),
    )
    message = sent["assistant_message"]
    expected = f"Confirm your appointment with Doctor Alpha on {friendly(slot, 'Asia/Karachi')}?"
    assert message["content"] == expected and expected.endswith("3:00 PM PKT?")
    assert message["action"]["status"] == "pending"
    count = select(func.count()).select_from(Appointment).where(Appointment.patient_id == clinic.patient_a.id)
    assert await db_session.scalar(count) == 0  # nothing booked yet

    url = f"{BASE}/conversations/{sent['conversation']['id']}/messages/{message['id']}/decision"
    assert (await client.post(url, json={"confirm": True}, headers=alice)).json()["action"]["status"] == "booked"
    assert (await client.post(url, json={"confirm": True}, headers=alice)).status_code == 409  # no second booking
    assert await db_session.scalar(count) == 1


async def test_cancel_and_move_are_one_line_questions_and_declining_changes_nothing(client, db_session, clinic, provider):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    when = clinic.slot(4, "11:00")
    made = await client.post("/api/v1/appointments/", json={"doctor_id": str(clinic.doctor_a.id), "starts_at": when.isoformat()}, headers=alice)
    appointment_id = made.json()["id"]

    sent = await ask(client, alice, provider, "cancel it", call("propose_cancellation", appointment_id=appointment_id), text_reply("Sure."))
    assert sent["assistant_message"]["content"] == f"Cancel your appointment with Doctor Alpha on {friendly(when, 'Asia/Karachi')}?"
    url = f"{BASE}/conversations/{sent['conversation']['id']}/messages/{sent['assistant_message']['id']}/decision"
    assert (await client.post(url, json={"confirm": False}, headers=alice)).json()["action"]["status"] == "cancelled"
    stored = await db_session.get(Appointment, UUID(appointment_id))
    await db_session.refresh(stored)
    assert stored.status.value != "cancelled"  # declined: unchanged

    target = clinic.slot(5, "12:00")
    sent = await ask(client, alice, provider, "move it", call("propose_reschedule", appointment_id=appointment_id, new_starts_at=target.isoformat()))
    assert sent["assistant_message"]["content"] == (
        f"Move your appointment with Doctor Alpha from {friendly(when, 'Asia/Karachi')} to {friendly(target, 'Asia/Karachi')}?"
    )
    result = tool_results(provider.calls[1])["propose_reschedule"]
    assert "Do not write anything else" in result["note"]


async def test_the_disclaimer_is_set_once_and_first_and_only_where_the_model_put_it(client, clinic, provider):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    assert DISCLAIMER in SYSTEM_PROMPT.format(today="x", roles="patient", disclaimer=DISCLAIMER)
    answer = "Iron-deficiency anemia is usually treated with iron and by fixing the cause.\n\n" + DISCLAIMER
    sent = await ask(client, alice, provider, "how is iron deficiency anemia treated", text_reply(answer + " " + DISCLAIMER))
    content = sent["assistant_message"]["content"]
    assert content.startswith(DISCLAIMER + "\n\nIron-deficiency anemia") and content.count(DISCLAIMER) == 1

    sent = await ask(client, alice, provider, "hi", text_reply("Hello! How can I help?"))
    assert sent["assistant_message"]["content"] == "Hello! How can I help?"  # nothing added to other answers


async def test_failures_say_what_could_not_be_retrieved(client, clinic, provider, monkeypatch):
    from app.services import appointment_service

    async def broken(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(appointment_service, "list_appointments", broken)
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    sent = await ask(client, alice, provider, "my appointments", call("get_my_appointments"), Reply(text=None, tool_calls=[]))
    assert sent["assistant_message"]["content"] == "I couldn't retrieve your appointments right now. Please try again."
