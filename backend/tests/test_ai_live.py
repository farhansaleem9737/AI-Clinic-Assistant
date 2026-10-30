"""Live Gemini smoke tests (D100): the real configured provider, synthetic
fixture data in the test database only. Skipped unless RUN_LIVE_AI=1 and
backend/.env configures the assistant. Each test sends one message; keep the
count small to stay within free-tier quotas.

    cd backend
    RUN_LIVE_AI=1 python -m pytest tests/test_ai_live.py -v
"""

import os
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.core.config import Settings, settings
from app.models import Appointment
from app.models.ai import AiUsage

BASE = "/api/v1/ai"

pytestmark = pytest.mark.skipif(os.environ.get("RUN_LIVE_AI") != "1", reason="live AI tests are opt-in (RUN_LIVE_AI=1)")


@pytest.fixture(autouse=True)
def real_provider(monkeypatch):
    """Undo the suite's AI-off defaults: use backend/.env as configured,
    except that patient data stays withheld from the provider."""
    configured = Settings()
    for name in type(settings).model_fields:
        if name.startswith(("ai_", "gemini_", "anthropic_")):
            monkeypatch.setattr(settings, name, getattr(configured, name))
    monkeypatch.setattr(settings, "ai_phi_allowed", False)
    if not settings.ai_configured:
        pytest.skip("backend/.env does not configure the AI assistant")


async def test_live_doctor_search_uses_the_tool_and_real_records(client, db_session, clinic):
    headers = await clinic.headers_for(clinic.patient_a.user_id)
    response = await client.post(f"{BASE}/messages", json={"text": "Find me a doctor named Doctor Alpha."}, headers=headers)
    assert response.status_code == 200, response.text
    message = response.json()["assistant_message"]
    print("\nANSWER:", message["content"])
    doctors = [d["name"] for card in message["results"] if card["kind"] == "doctors" for d in card["items"]]
    assert "Doctor Alpha" in doctors  # found through search_doctors, from the database
    [usage] = (await db_session.scalars(select(AiUsage).where(AiUsage.user_id == clinic.patient_a.user_id))).all()
    print("USAGE:", usage.model, usage.input_tokens, "in /", usage.output_tokens, "out,", usage.model_requests, "requests,", usage.tool_calls, "tool calls")
    assert usage.status == "ok" and usage.input_tokens > 0 and usage.tool_calls >= 1


async def test_live_booking_is_proposed_then_confirmed_by_the_user(client, db_session, clinic):
    headers = await clinic.headers_for(clinic.patient_a.user_id)
    slot = clinic.slot(3, "10:00")
    local = slot.astimezone(ZoneInfo(settings.clinic_timezone))
    text = (
        f"Book me an appointment with Doctor Alpha (doctor_id {clinic.doctor_a.id}) "
        f"starting at {local.isoformat()} for a routine check-up."
    )
    response = await client.post(f"{BASE}/messages", json={"text": text}, headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    message = body["assistant_message"]
    print("\nANSWER:", message["content"])
    action = message["action"]
    assert action and action["type"] == "book_appointment" and action["status"] == "pending"
    # Proposing booked nothing.
    assert await db_session.scalar(select(Appointment.id).where(Appointment.patient_id == clinic.patient_a.id)) is None

    url = f"{BASE}/conversations/{body['conversation']['id']}/messages/{message['id']}/decision"
    decided = (await client.post(url, json={"confirm": True}, headers=headers)).json()
    print("DECISION:", decided["action"]["status"])
    assert decided["action"]["status"] == "booked"
    booked = await db_session.scalar(select(Appointment).where(Appointment.patient_id == clinic.patient_a.id))
    assert booked is not None and booked.starts_at == slot


async def test_live_emergency_message_never_reaches_the_model(client, db_session, clinic):
    headers = await clinic.headers_for(clinic.patient_a.user_id)
    response = await client.post(f"{BASE}/messages", json={"text": "My father has crushing chest pain right now"}, headers=headers)
    assert response.status_code == 200
    assert "emergency" in response.json()["assistant_message"]["content"].lower()
    assert (await db_session.scalars(select(AiUsage))).all() == []
