"""The assistant and hybrid scheduling (D117): the same rules as the app, a
walk-in token only after the user confirms, and no way to overbook."""

from datetime import timedelta

from app.main import app
from app.services.ai.provider import get_provider
from tests.test_ai_agent import ScriptedProvider, call, text_reply, tool_results
from tests.test_hybrid_scheduling import POLICY

BASE = "/api/v1/ai"


async def ask(client, headers, provider, text, *replies, conversation_id=None):
    provider.replies = list(replies)
    body = {"text": text, **({"conversation_id": conversation_id} if conversation_id else {})}
    response = await client.post(f"{BASE}/messages", json=body, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def test_a_walk_in_token_is_issued_only_after_confirmation(client, clinic, freeze_clock):
    provider = ScriptedProvider()
    app.dependency_overrides[get_provider] = lambda: provider
    doctor = await clinic.headers_for(clinic.doctor_a.user_id)
    await client.put(f"/api/v1/doctors/{clinic.doctor_a.id}/scheduling-policy", json=POLICY, headers=doctor)
    freeze_clock(clinic.slot(1, "09:30"))
    patient = await clinic.headers_for(clinic.patient_a.user_id)

    sent = await ask(client, patient, provider, "Can I get a walk-in token?",
                     call("request_walk_in_token", doctor_id=str(clinic.doctor_a.id)), text_reply("(ignored)"))
    action = sent["assistant_message"]["action"]
    assert action["type"] == "walk_in_token" and action["status"] == "pending"
    assert (await client.get("/api/v1/queue/me", headers=patient)).json() == []  # nothing issued yet

    confirmed = await ask(client, patient, provider, "yes", conversation_id=sent["conversation"]["id"])
    assert "token" in confirmed["assistant_message"]["content"] and "#1" in confirmed["assistant_message"]["content"]
    [mine] = (await client.get("/api/v1/queue/me", headers=patient)).json()
    assert mine["token_number"] == 1 and mine["state"] == "registered"

    status = await ask(client, patient, provider, "What is my queue position?", call("get_my_queue_status"), text_reply("ok"))
    assert "#1" in status["assistant_message"]["content"] and "estimate" in status["assistant_message"]["content"]


async def test_the_assistant_never_books_a_fifo_doctor_or_overbooks(client, clinic):
    provider = ScriptedProvider()
    app.dependency_overrides[get_provider] = lambda: provider
    doctor = await clinic.headers_for(clinic.doctor_a.user_id)
    await client.put(f"/api/v1/doctors/{clinic.doctor_a.id}/scheduling-policy", json={**POLICY, "mode": "fifo"}, headers=doctor)
    patient = await clinic.headers_for(clinic.patient_a.user_id)
    await ask(client, patient, provider, "Book me tomorrow at 11:15",
              call("propose_booking", doctor_id=str(clinic.doctor_a.id), starts_at=clinic.slot(1, "11:15").isoformat(), double_booking=True),
              text_reply("ok"))
    result = tool_results(provider.calls[1])["propose_booking"]
    assert "arrival order" in result["error"]
    assert "double_booking" not in str(provider.calls[0]["tools"])  # no override argument is ever offered


async def test_fifteen_minute_times_reach_the_assistant(client, clinic):
    provider = ScriptedProvider()
    app.dependency_overrides[get_provider] = lambda: provider
    doctor = await clinic.headers_for(clinic.doctor_a.user_id)
    await client.put(f"/api/v1/doctors/{clinic.doctor_a.id}/scheduling-policy", json=POLICY, headers=doctor)
    patient = await clinic.headers_for(clinic.patient_a.user_id)
    day = (clinic.today + timedelta(days=2)).isoformat()
    sent = await ask(client, patient, provider, "Book me at 11:15",
                     call("get_doctor_availability", doctor_id=str(clinic.doctor_a.id), date_from=day),
                     call("propose_booking", doctor_id=str(clinic.doctor_a.id), starts_at=clinic.slot(2, "11:15").isoformat()),
                     text_reply("(ignored)"))
    times = [s["local_time"][-8:] for s in tool_results(provider.calls[1])["get_doctor_availability"]["free_slots"]]
    assert "11:15 AM" in times
    assert sent["assistant_message"]["action"]["starts_at"] == clinic.slot(2, "11:15").isoformat()
