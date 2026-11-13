"""Conversational follow-ups (D115): everyday specialty words, references to what
was shown earlier ("the most experienced one", "the earliest"), multi-turn
booking with a typed "yes", and no stale cards or links in answers. A scripted
provider stands in for the model; ids and values always come from the tools."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.permissions import RoleCode
from app.main import app
from app.models import Appointment
from app.services.ai.provider import get_provider
from app.services.ai.specialties import search_terms
from tests.test_ai_agent import ScriptedProvider, call, text_reply, tool_results

BASE = "/api/v1/ai"


@pytest.fixture
def provider(client):
    fake = ScriptedProvider()
    app.dependency_overrides[get_provider] = lambda: fake
    return fake


async def ask(client, headers, text, conversation_id=None):
    body = {"text": text, **({"conversation_id": conversation_id} if conversation_id else {})}
    response = await client.post(f"{BASE}/messages", json=body, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize(
    ("words", "stem"),
    [
        ("give me heart doctors", "cardi"),
        ("find a cardiologist", "cardi"),
        ("show skin specialists", "dermat"),
        ("find children's doctors", "pediatr"),
        ("show brain specialists", "neuro"),
        ("I need a bone doctor", "ortho"),
        ("cardiolgist", "cardi"),  # misspelled
    ],
)
def test_everyday_words_name_a_specialty(words, stem):
    assert search_terms(words)[0] == stem


def test_no_specialty_is_invented():
    assert search_terms("show me doctors") == [] and search_terms("Dr. Sarah Khan") == []


@pytest.fixture
async def cardiologists(make_department, make_doctor):
    heart = await make_department("AI Heart Centre")
    skin = await make_department("AI Skin Centre")
    made = [
        await make_doctor(name="Sarah Khan", department=heart, specialization="Cardiologist", years_of_experience=10),
        await make_doctor(name="Hannah Fischer", department=heart, specialization="Cardiology", years_of_experience=11),
        await make_doctor(name="Layla Hassan", department=heart, specialization="Interventional Cardiology", years_of_experience=18),
    ]
    await make_doctor(name="Derma Person", department=skin, specialization="Dermatologist", years_of_experience=30)
    return made


async def test_heart_doctors_finds_cardiologists(client, auth_headers, provider, cardiologists):
    provider.replies = [call("search_doctors", specialization="heart doctors"), text_reply("Here are the cardiologists.")]
    sent = await ask(client, await auth_headers(RoleCode.patient), "give me heart doctors")
    names = [d["name"] for d in tool_results(provider.calls[1])["search_doctors"]["doctors"]]
    assert sorted(names) == ["Hannah Fischer", "Layla Hassan", "Sarah Khan"]
    assert sent["assistant_message"]["results"][0]["kind"] == "doctors"


async def test_most_experienced_resolves_from_the_previous_list(client, auth_headers, provider, cardiologists):
    headers = await auth_headers(RoleCode.patient)
    provider.replies = [call("search_doctors", specialization="cardiologist"), text_reply("I found three cardiologists.")]
    first = await ask(client, headers, "find a cardiologist")
    conversation_id = first["conversation"]["id"]

    provider.replies = [
        call("pick_from_previous", entity="doctor", selector="most_experienced"),
        text_reply("Dr. Layla Hassan has the most experience (18 years)."),
    ]
    second = await ask(client, headers, "book me with the most experienced one", conversation_id)
    # The model was told what the user saw (numbered doctors with their real ids) as app
    # state in the system prompt, never inside an answer it could copy (D133).
    shown_ids = [d["doctor_id"] for d in first["assistant_message"]["results"][0]["items"]]
    screen = provider.calls[2]["system"].split("# On screen in this conversation", 1)[1]
    assert shown_ids and all(i in screen for i in shown_ids)
    assert not any("Shown to the user" in (t.text or "") or any(i in (t.text or "") for i in shown_ids)
                   for t in provider.calls[2]["turns"] if t.role == "assistant")
    picked = tool_results(provider.calls[3])["pick_from_previous"]
    assert picked["selected_doctor"]["name"] == "Layla Hassan"
    assert picked["selected_doctor"]["doctor_id"] == str(cardiologists[2].id)
    assert second["assistant_message"]["results"][0]["items"][0]["selected"] is True


@pytest.mark.parametrize(("selector", "expected"), [("first", 0), ("second", 1), ("last", 2), ("least_experienced", 0)])
async def test_ordinal_and_comparative_references(client, auth_headers, provider, cardiologists, selector, expected):
    headers = await auth_headers(RoleCode.patient)
    provider.replies = [call("search_doctors", specialization="Cardi"), text_reply("Three found.")]
    first = await ask(client, headers, "cardiologists")
    shown = [d["doctor_id"] for d in first["assistant_message"]["results"][0]["items"]]
    provider.replies = [call("pick_from_previous", entity="doctor", selector=selector), text_reply("ok")]
    await ask(client, headers, f"the {selector} one", first["conversation"]["id"])
    picked = tool_results(provider.calls[3])["pick_from_previous"]["selected_doctor"]
    if selector == "least_experienced":
        assert picked["name"] == "Sarah Khan"
    else:
        assert picked["doctor_id"] == shown[expected]


async def test_equal_matches_ask_instead_of_guessing(client, clinic, provider):
    headers = await clinic.headers_for(clinic.patient_a.user_id)  # Alpha and Beta: 5 years each
    provider.replies = [call("search_doctors", query="Doctor"), text_reply("Two doctors.")]
    first = await ask(client, headers, "doctors")
    provider.replies = [call("pick_from_previous", entity="doctor", selector="most_experienced"), text_reply("Which one?")]
    await ask(client, headers, "the most experienced", first["conversation"]["id"])
    result = tool_results(provider.calls[3])["pick_from_previous"]
    assert result["ambiguous"] is True and len(result["candidates"]) == 2


async def test_a_reference_without_a_list_is_not_guessed(client, auth_headers, provider):
    provider.replies = [call("pick_from_previous", entity="doctor", selector="first"), text_reply("Which doctor do you mean?")]
    await ask(client, await auth_headers(RoleCode.patient), "book the first one")
    assert tool_results(provider.calls[1])["pick_from_previous"]["error_code"] == "DATA_NOT_FOUND"


async def test_multi_turn_booking_with_a_typed_yes(client, db_session, clinic, provider):
    headers = await clinic.headers_for(clinic.patient_a.user_id)
    tomorrow = (clinic.today + timedelta(days=1)).isoformat()
    provider.replies = [call("search_doctors", query="Doctor Alpha"), text_reply("Dr. Alpha is available.")]
    conversation_id = (await ask(client, headers, "find doctor alpha"))["conversation"]["id"]

    provider.replies = [call("pick_from_previous", entity="doctor", selector="first"), text_reply("Dr. Alpha's next free time is ...")]
    await ask(client, headers, "book me with the first one", conversation_id)

    provider.replies = [
        call("get_doctor_availability", doctor_id=str(clinic.doctor_a.id), date_from=tomorrow, part_of_day="afternoon"),
        text_reply("Tomorrow afternoon is free from 12:00."),
    ]
    afternoon = await ask(client, headers, "tomorrow afternoon", conversation_id)
    slots = afternoon["assistant_message"]["results"][0]
    assert slots["kind"] == "slots" and slots["items"][0]["starts_at"] == clinic.slot(1, "12:00").isoformat()

    provider.replies = [call("pick_from_previous", entity="slot", selector="earliest"), text_reply("(ignored)")]
    proposed = await ask(client, headers, "take the earliest one", conversation_id)
    action = proposed["assistant_message"]["action"]
    assert action["status"] == "pending" and action["starts_at"] == clinic.slot(1, "12:00").isoformat()
    assert await db_session.scalar(select(Appointment.id).where(Appointment.patient_id == clinic.patient_a.id)) is None

    calls_before = len(provider.calls)
    confirmed = await ask(client, headers, "yes, confirm", conversation_id)
    assert len(provider.calls) == calls_before  # decided by the server, no model call
    assert "is booked" in confirmed["assistant_message"]["content"]
    assert confirmed["assistant_message"]["results"][0]["action"]["status"] == "booked"
    booked = await db_session.scalar(select(Appointment).where(Appointment.patient_id == clinic.patient_a.id))
    assert booked is not None and booked.doctor_id == clinic.doctor_a.id
    # The same proposal cannot be decided twice.
    again = await ask(client, headers, "yes", conversation_id)
    assert len(provider.calls) == calls_before + 1  # no pending question any more: the model answers


async def test_saying_no_books_nothing(client, db_session, clinic, provider):
    headers = await clinic.headers_for(clinic.patient_a.user_id)
    provider.replies = [call("propose_booking", doctor_id=str(clinic.doctor_a.id), starts_at=clinic.slot().isoformat()), text_reply("x")]
    conversation_id = (await ask(client, headers, "book alpha at 10"))["conversation"]["id"]
    declined = await ask(client, headers, "no thanks", conversation_id)
    assert declined["assistant_message"]["results"][0]["action"]["status"] == "cancelled"
    assert await db_session.scalar(select(Appointment.id).where(Appointment.patient_id == clinic.patient_a.id)) is None


async def test_failed_follow_up_shows_no_stale_cards(client, auth_headers, provider, cardiologists, monkeypatch):
    monkeypatch.setattr(settings, "ai_max_tool_steps", 3)
    headers = await auth_headers(RoleCode.patient)
    provider.replies = [call("search_doctors", specialization="heart"), text_reply("Three found.")]
    conversation_id = (await ask(client, headers, "heart doctors"))["conversation"]["id"]
    provider.replies = [call("search_doctors", specialization="heart")] + [call("list_departments") for _ in range(5)]
    failed = await ask(client, headers, "hmm", conversation_id)
    message = failed["assistant_message"]
    assert message["results"] == [] and message["action"] is None
    assert "those doctors" in message["content"]  # a specific question, not the generic fallback


async def test_answers_never_carry_app_urls(client, auth_headers, provider):
    provider.replies = [text_reply("Open [Dr Khan](http://localhost:5173/doctors/123) or http://localhost:5173/doctors to book.")]
    sent = await ask(client, await auth_headers(RoleCode.patient), "where")
    assert "http" not in sent["assistant_message"]["content"] and "Dr Khan" in sent["assistant_message"]["content"]


async def test_another_users_conversation_is_never_used_as_context(client, auth_headers, provider, cardiologists):
    alice = await auth_headers(RoleCode.patient)
    provider.replies = [call("search_doctors", specialization="heart"), text_reply("Three found.")]
    conversation_id = (await ask(client, alice, "heart doctors"))["conversation"]["id"]
    bob = await auth_headers(RoleCode.patient)
    response = await client.post(f"{BASE}/messages", json={"text": "the first one", "conversation_id": conversation_id}, headers=bob)
    assert response.status_code == 404
