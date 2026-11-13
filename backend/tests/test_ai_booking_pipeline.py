"""The assistant's booking path end to end with the REAL Gemini provider and SDK (D132).

Every other assistant test uses a scripted provider that hands tool results
straight back, so it never exercises what production does between steps: the
google-genai SDK serialising the function responses into the next request.
Here only Gemini's HTTP answers are scripted (httpx.MockTransport, the
streamGenerateContent SSE format); the endpoint, agent loop, tools, database
and SDK are all real. Synthetic test records only; nothing reaches Google.
"""

import json
from datetime import time, timedelta

import httpx
import pytest
from google import genai
from google.genai import types

from app.main import app
from app.services.ai.gemini_provider import GeminiProvider
from app.services.ai.provider import get_provider
from tests.test_ai_agent import BASE, parse_sse


def _sse(*parts, finish="STOP"):
    body = {
        "candidates": [{"content": {"role": "model", "parts": list(parts)}, "finishReason": finish, "index": 0}],
        "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 10, "totalTokenCount": 110},
        "modelVersion": "gemini-test",
    }
    return f"data: {json.dumps(body)}\r\n\r\n"


def call_part(tool, /, **args):
    # Gemini 3 returns a thought signature with each function call; it must come back unchanged.
    return {"functionCall": {"name": tool, "args": args}, "thoughtSignature": "c2lnbmF0dXJl"}


def text_part(text):
    return {"text": text}


class FakeGemini:
    """Answers streamGenerateContent with scripted steps; keeps every request body."""

    def __init__(self, *steps):
        self.steps, self.requests = list(steps), []

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert ":streamGenerateContent" in request.url.path, request.url
        self.requests.append(json.loads(request.content))
        step = self.steps.pop(0)
        if isinstance(step, httpx.Response):
            return step
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content="".join(step).encode())

    def provider(self) -> GeminiProvider:
        client = genai.Client(
            api_key="test-key-not-real",
            http_options=types.HttpOptions(httpx_async_client=httpx.AsyncClient(transport=httpx.MockTransport(self.handler))),
        )
        return GeminiProvider(model="gemini-test", api_key="unused", client=client)


@pytest.fixture
def gemini(client):
    def install(*steps) -> FakeGemini:
        fake = FakeGemini(*steps)
        provider = fake.provider()
        app.dependency_overrides[get_provider] = lambda: provider
        return fake

    return install


@pytest.fixture
async def cardiologist(db_session, clinic, make_doctor):
    from app.models.schedule import ScheduleTemplate

    doctor = await make_doctor(name="Heart Expert", department=clinic.department, specialization="Cardiology")
    for weekday in range(7):
        db_session.add(ScheduleTemplate(doctor_id=doctor.id, weekday=weekday, start_time=time(9, 0), end_time=time(17, 0),
                                        slot_minutes=30, valid_from=clinic.today - timedelta(days=30)))
    await db_session.commit()
    return doctor


async def stream(client, headers, text, conversation_id=None):
    body = {"text": text, **({"conversation_id": conversation_id} if conversation_id else {})}
    response = await client.post(f"{BASE}/messages/stream", json=body, headers=headers)
    assert response.status_code == 200, response.text
    return parse_sse(response.text)


async def test_book_me_with_a_cardiologist_through_the_real_sdk(client, clinic, cardiologist, gemini):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    fake = gemini(
        [_sse(call_part("search_doctors", specialization="cardiology"))],
        [_sse(text_part("Dr. Heart Expert is a cardiologist. Which day suits you?"))],
    )
    events = await stream(client, alice, "Book me with a cardiologist")
    kinds = [k for k, _ in events]
    assert kinds[-1] == "done", events[-1]
    done = events[-1][1]
    [card] = done["assistant_message"]["results"]
    assert card["kind"] == "doctors" and [d["name"] for d in card["items"]] == ["Heart Expert"]
    # The second request carried the doctor list back as a function response.
    sent_back = [p for c in fake.requests[1]["contents"] for p in c["parts"] if "functionResponse" in p]
    assert sent_back and sent_back[0]["functionResponse"]["name"] == "search_doctors"


async def test_the_whole_booking_conversation_then_confirm_books_exactly_once(client, db_session, clinic, cardiologist, gemini):
    from sqlalchemy import func, select

    from app.models import Appointment

    alice = await clinic.headers_for(clinic.patient_a.user_id)
    day = clinic.today + timedelta(days=3)
    slot = clinic.slot(3, "10:00")
    doctor_id = str(cardiologist.id)
    fake = gemini(
        [_sse(call_part("search_doctors", specialization="cardiology"))],
        [_sse(text_part("Which day suits you?"))],
        [_sse(call_part("get_doctor_availability", doctor_id=doctor_id, date_from=day.isoformat(), part_of_day="morning"))],
        [_sse(text_part("These morning times are free."))],
        [_sse(call_part("propose_booking", doctor_id=doctor_id, starts_at=slot.isoformat()))],
        [_sse(text_part("I have prepared it, press Confirm."))],
    )
    first = await stream(client, alice, "Book me with a cardiologist")
    conversation_id = first[-1][1]["conversation"]["id"]
    second = await stream(client, alice, f"{day:%A} morning please", conversation_id)
    assert second[-1][0] == "done" and second[-1][1]["assistant_message"]["results"][0]["kind"] == "slots"
    third = await stream(client, alice, "10 am", conversation_id)
    assert third[-1][0] == "done", third[-1]
    message = third[-1][1]["assistant_message"]
    assert message["action"]["status"] == "pending" and message["action"]["starts_at"] == slot.isoformat()
    assert not fake.steps

    count = select(func.count()).select_from(Appointment).where(Appointment.patient_id == clinic.patient_a.id)
    assert await db_session.scalar(count) == 0  # a proposal books nothing
    url = f"{BASE}/conversations/{conversation_id}/messages/{message['id']}/decision"
    assert (await client.post(url, json={"confirm": True}, headers=alice)).json()["action"]["status"] == "booked"
    assert (await client.post(url, json={"confirm": True}, headers=alice)).status_code == 409  # pressing again books nothing
    assert await db_session.scalar(count) == 1


async def test_automatic_earliest_time_booking_through_the_real_sdk(client, clinic, cardiologist, gemini):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    day = clinic.today + timedelta(days=2)
    gemini(
        [_sse(call_part("propose_booking", doctor_id=str(cardiologist.id), earliest_on=day.isoformat()))],
        [_sse(text_part("Prepared."))],
    )
    events = await stream(client, alice, "book the cardiologist's next available time on that day")
    assert events[-1][0] == "done", events[-1]
    action = events[-1][1]["assistant_message"]["action"]
    assert action["booking_mode"] == "auto" and action["queue_position"] >= 1


@pytest.mark.parametrize("arguments", [
    {"doctor_id": "Heart Expert"},                                   # a name where the id belongs
    {"doctor_id": None, "starts_at": None},                          # nulls for everything
    {"doctor_name": "Heart Expert", "date": "tomorrow"},             # an outdated / invented signature
    {"doctor_id": "00000000-0000-0000-0000-000000000000", "earliest_on": "2026-13-45"},
])
async def test_bad_booking_arguments_from_the_model_never_break_the_stream(client, clinic, cardiologist, gemini, arguments):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    fake = gemini([_sse(call_part("propose_booking", **arguments))], [_sse(text_part("Which doctor and time would you like?"))])
    events = await stream(client, alice, "Book me with a cardiologist")
    assert events[-1][0] == "done", events[-1]
    [response] = [p["functionResponse"] for c in fake.requests[1]["contents"] for p in c["parts"] if "functionResponse" in p]
    assert response["response"]["error_code"] in ("INVALID_ARGUMENTS", "TOOL_EXECUTION_FAILED", "TOOL_PERMISSION_DENIED")
    assert events[-1][1]["assistant_message"]["action"] is None


async def test_two_tool_calls_in_one_step_through_the_real_sdk(client, clinic, cardiologist, gemini):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    gemini(
        [_sse(call_part("search_doctors", specialization="cardiology"), call_part("list_departments"))],
        [_sse(text_part("Here are the cardiologists."))],
    )
    events = await stream(client, alice, "Book me with a cardiologist")
    assert events[-1][0] == "done", events[-1]


async def test_book_me_with_a_cardiologist_with_the_production_catalog(client, db_session, clinic, make_doctor, gemini):
    """As in production: "cardiologist" is resolved through the seeded catalog (D118)."""
    from sqlalchemy import select

    from app.models.department import Department
    from app.models.schedule import ScheduleTemplate
    from app.services import catalog_service

    catalog_service.invalidate()
    await catalog_service.seed(db_session)
    cardiology = await db_session.scalar(select(Department).where(Department.slug == "cardiology"))
    doctor = await make_doctor(name="Heart Expert", department=cardiology, specialization="Cardiology")
    for weekday in range(7):
        db_session.add(ScheduleTemplate(doctor_id=doctor.id, weekday=weekday, start_time=time(9, 0), end_time=time(17, 0),
                                        slot_minutes=30, valid_from=clinic.today - timedelta(days=30)))
    await db_session.commit()
    await catalog_service.seed(db_session)  # links the doctor to the Cardiology specialization
    catalog_service.invalidate()

    alice = await clinic.headers_for(clinic.patient_a.user_id)
    day = clinic.today + timedelta(days=2)
    try:
        for arguments in ({"specialization": "cardiology"}, {"query": "cardiologist"}, {"condition": "heart"}):
            fake = gemini([_sse(call_part("search_doctors", **arguments))], [_sse(text_part("Here they are. Which day?"))])
            events = await stream(client, alice, "Book me with a cardiologist")
            assert events[-1][0] == "done", (arguments, events[-1])
            [card] = events[-1][1]["assistant_message"]["results"]
            assert "Heart Expert" in [d["name"] for d in card["items"]], arguments
            [response] = [p["functionResponse"]["response"] for c in fake.requests[1]["contents"] for p in c["parts"] if "functionResponse" in p]
            understood = response["understood"]
            assert any("Cardiology" in n for n in understood["specializations"] + understood["departments"]), response
        fake = gemini([_sse(call_part("propose_booking", doctor_id=str(doctor.id), earliest_on=day.isoformat()))], [_sse(text_part("ok"))])
        events = await stream(client, alice, "book the first one, the earliest time on that day")
        assert events[-1][0] == "done" and events[-1][1]["assistant_message"]["action"]["status"] == "pending", events[-1]
    finally:
        catalog_service.invalidate()


def _failure_logs(caplog):
    return [r for r in caplog.records if r.getMessage() == "ai_request_failed"]


async def test_gemini_failing_mid_booking_says_where_and_saves_nothing(client, clinic, cardiologist, gemini, caplog):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    overloaded = httpx.Response(503, json={"error": {"code": 503, "message": "The model is overloaded.", "status": "UNAVAILABLE"}})
    # The second step fails twice: one transient failure is retried (D103), the second is reported.
    gemini([_sse(call_part("search_doctors", specialization="cardiology"))], overloaded, overloaded)
    events = await stream(client, alice, "Book me with a cardiologist")
    kind, error = events[-1]
    assert kind == "error" and error["code"] == "AI_UNAVAILABLE" and len(error["request_id"]) == 32
    [log] = _failure_logs(caplog)
    assert (log.code, log.stage, log.model_steps, log.tools) == ("AI_UNAVAILABLE", "model step 2", 2, ["search_doctors"])
    assert (await client.get(f"{BASE}/conversations", headers=alice)).json() == []  # "Not sent": nothing was kept


async def test_an_unexpected_server_error_mid_booking_is_reported_with_its_stage(client, clinic, cardiologist, gemini, caplog, monkeypatch):
    from app.services.ai import agent_service

    def broken(_text):
        raise RuntimeError("simulated")

    monkeypatch.setattr(agent_service, "_tidy", broken)
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    gemini([_sse(call_part("search_doctors", specialization="cardiology"))], [_sse(text_part("Which day?"))])
    events = await stream(client, alice, "Book me with a cardiologist")
    assert events[-1][0] == "error" and events[-1][1]["code"] == "AI_FAILED"
    [log] = _failure_logs(caplog)
    assert log.code == "AI_FAILED" and log.error == "RuntimeError" and log.tools == ["search_doctors"]
    assert (await client.get(f"{BASE}/conversations", headers=alice)).json() == []


async def test_a_gemini_timeout_mid_booking_is_a_timeout_not_unavailable(client, clinic, cardiologist, gemini, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "ai_first_token_timeout_seconds", 3)
    alice = await clinic.headers_for(clinic.patient_a.user_id)

    def slow(request):
        raise httpx.ReadTimeout("no answer", request=request)

    fake = gemini([_sse(call_part("search_doctors", specialization="cardiology"))])
    fake.steps += [None, None]
    original = fake.handler
    fake.handler = lambda request: slow(request) if not fake.steps or fake.steps[0] is None else original(request)
    app.dependency_overrides[get_provider] = (lambda p: (lambda: p))(fake.provider())
    events = await stream(client, alice, "Book me with a cardiologist")
    assert events[-1][0] == "error" and events[-1][1]["code"] == "AI_TIMEOUT"


async def test_second_message_picks_from_the_list_then_a_time(client, db_session, clinic, cardiologist, gemini):
    """The production failure was the second message of a booking conversation (2026-11-13 09:00:53 UTC)."""
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    gemini(
        [_sse(call_part("search_doctors", specialization="cardiology"))], [_sse(text_part("Which one?"))],
        [_sse(call_part("pick_from_previous", entity="doctor", selector="first"))], [_sse(text_part("Next free times below."))],
        [_sse(call_part("pick_from_previous", entity="doctor", selector="earliest_available"))], [_sse(text_part("ok"))],
        [_sse(call_part("pick_from_previous", entity="slot", selector="by_name", name="10 am"))], [_sse(text_part("Press Confirm."))],
    )
    first = await stream(client, alice, "Book me with a cardiologist")
    conversation_id = first[-1][1]["conversation"]["id"]
    for text in ("the first one", "whoever is free earliest", "10 am"):
        events = await stream(client, alice, text, conversation_id)
        assert events[-1][0] == "done", (text, events[-1])
