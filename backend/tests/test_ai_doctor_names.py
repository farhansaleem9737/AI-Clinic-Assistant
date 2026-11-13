"""Named-doctor booking, internal-data leakage and a regulation read as lab results (D133).

The conversations run through the real stream endpoint, agent loop, tools,
database and google-genai SDK; only Gemini's HTTP answers are scripted
(tests/test_ai_booking_pipeline.py). The names are synthetic test doctors.

    python -m pytest tests/test_ai_doctor_names.py -q -k "not db"     # no database needed: -k unit
"""

from datetime import time, timedelta

import pytest

from app.services.ai import medical_reports
from app.services.ai.redaction import StreamRedactor, internal_free
from app.services.doctor_resolution import _fits, name_words
from tests.test_ai_agent import BASE
from tests.test_ai_booking_pipeline import _sse, call_part, cardiologist, gemini, stream, text_part  # noqa: F401  (fixtures)

LEAKED = (
    "Here are the dermatologists.\n[Shown to the user: list of 3 doctors]\n"
    "Shown to the user: doctors in this order: 1. Dr. Emily Carter (doctor_id 01a0f29d-c6b3-72cb-b652-0e8508aca522, "
    "Dermatology, 9 yrs); 2. Dr. Omar Shah (doctor_id 01a0f29d-c6b3-72cb-b652-0e8508aca523, Dermatology, 4 yrs)\n"
    "Would you like to book with one of them?"
)


# ---- unit: names and redaction -------------------------------------------------------------------


@pytest.mark.parametrize("said", ["Dr. Emily Carter", "dr emily carter", "Doctor Emily Carter", "Emily Carter", "  DR.  Emily   CARTER "])
def test_unit_titles_case_and_spacing_are_ignored(said):
    assert name_words(said) == ["emily", "carter"]


def test_unit_partial_names_fit_only_their_doctor():
    assert _fits(["emily"], ["emily", "carter"]) and _fits(["carter", "emily"], ["emily", "carter"])
    assert not _fits(["emily", "stone"], ["emily", "carter"]) and not _fits(["em", "em"], ["emily", "carter"])


def test_unit_internal_notes_and_ids_never_survive():
    clean = internal_free(LEAKED)
    assert "Shown to the user" not in clean and "doctor_id" not in clean and "01a0f29d" not in clean
    assert clean.startswith("Here are the dermatologists.") and clean.endswith("Would you like to book with one of them?")
    ordinary = "I found three dermatologists. You can choose one below (or ask for the earliest time)."
    assert internal_free(ordinary) == ordinary  # ordinary answers are untouched


@pytest.mark.parametrize("size", [1, 3, 7, 20, 64, 500])
def test_unit_streamed_text_never_shows_a_note_even_in_pieces(size):
    redactor, shown = StreamRedactor(), ""
    for i in range(0, len(LEAKED), size):
        shown += redactor.feed(LEAKED[i:i + size])
        assert "Shown to the user" not in shown and "01a0f29d" not in shown and "[Shown" not in shown
    shown += redactor.flush()
    assert shown == internal_free(LEAKED)  # what streamed is exactly what is saved


def test_unit_ordinary_text_streams_unchanged():
    text = "Dr. Emily Carter's next free time is tomorrow at 10:00 AM. Which day or time suits you?"
    redactor = StreamRedactor()
    out = "".join(redactor.feed(text[i:i + 5]) for i in range(0, len(text), 5)) + redactor.flush()
    assert out == text


def test_unit_a_regulation_with_a_lab_style_table_has_no_patient_results():
    from tests.ai_eval_data import DAIRY_REGULATION

    x = medical_reports.analyse(medical_reports.Reading(pages=[medical_reports.Page(1, DAIRY_REGULATION)]))
    assert x.content_class == "NON_MEDICAL_DOCUMENT" and x.measurements == [] and x.conditions == []
    assert "regulation" in x.content_note


# ---- database: the directory and the conversation -----------------------------------------------


async def _derm(db_session, make_doctor, department, today, name, years):
    from app.models.schedule import ScheduleTemplate

    doctor = await make_doctor(name=name, department=department, specialization="Dermatology", years_of_experience=years)
    for weekday in range(7):
        db_session.add(ScheduleTemplate(doctor_id=doctor.id, weekday=weekday, start_time=time(9, 0), end_time=time(17, 0),
                                        slot_minutes=30, valid_from=today - timedelta(days=30)))
    await db_session.commit()
    return doctor


@pytest.fixture
async def dermatologists(db_session, clinic, make_doctor, make_department):
    department = await make_department("Dermatology")
    return {
        "carter": await _derm(db_session, make_doctor, department, clinic.today, "Emily Carter", 9),
        "shah": await _derm(db_session, make_doctor, department, clinic.today, "Omar Shah", 4),
    }


async def test_db_every_way_of_writing_the_name_finds_the_one_doctor(db_session, dermatologists):
    from app.services import doctor_resolution

    for said in ("Dr. Emily Carter", "Emily Carter", "dr emily carter", "Doctor Emily Carter", "Dr Emily", "carter"):
        found = await doctor_resolution.resolve(db_session, said)
        assert found.status in ("exact", "confident") and found.chosen.doctor.id == dermatologists["carter"].id, said
    assert (await doctor_resolution.resolve(db_session, "Dr. Zara Nonexistent")).status == "none"
    typo = await doctor_resolution.resolve(db_session, "Emily Karter")
    assert typo.status == "close" and typo.chosen is None  # suggested, never chosen


async def test_db_two_doctors_with_the_name_must_be_chosen_between(db_session, clinic, make_doctor, dermatologists):
    from app.services import doctor_resolution

    await _derm(db_session, make_doctor, None, clinic.today, "Emily Stone", 3)
    found = await doctor_resolution.resolve(db_session, "Dr Emily")
    assert found.status == "ambiguous" and found.chosen is None and len(found.doctors) == 2
    assert (await doctor_resolution.resolve(db_session, "Dr. Emily Carter")).status == "exact"


async def test_db_book_me_with_dr_emily_carter_continues_to_her_free_times(client, clinic, cardiologist, dermatologists, gemini):
    """The reported failure: a list of OTHER doctors was on screen, then the user named one (D133)."""
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    fake = gemini(
        [_sse(call_part("search_doctors", specialization="cardiology"))], [_sse(text_part("I found one cardiologist."))],
        [_sse(call_part("search_doctors", doctor_name="Dr. Emily Carter", intent="book"))],
        [_sse(text_part("Dr. Emily Carter is available tomorrow at 9:00 AM. Which day or time suits you?"))],
    )
    first = await stream(client, alice, "Book me with a cardiologist")
    conversation_id = first[-1][1]["conversation"]["id"]
    events = await stream(client, alice, "Book me an appointment with Dr. Emily Carter.", conversation_id)
    assert events[-1][0] == "done", events[-1]
    message = events[-1][1]["assistant_message"]
    kinds = [c["kind"] for c in message["results"]]
    assert kinds == ["doctors", "slots"]  # the named doctor, selected, and her real free times
    assert message["results"][0]["items"][0]["name"] == "Emily Carter" and message["results"][0]["items"][0]["selected"]
    assert "not sure what you'd like" not in message["content"]
    # The earlier list reached the model as app state, not as text in an earlier answer.
    second_request = fake.requests[2]
    system = second_request["systemInstruction"]["parts"][0]["text"]
    assert "# On screen in this conversation" in system and str(cardiologist.id) in system
    earlier = [p.get("text", "") for c in second_request["contents"] if c["role"] == "model" for p in c["parts"]]
    assert not any("Shown to the user" in t or str(cardiologist.id) in t for t in earlier)


async def test_db_a_name_not_in_the_shown_list_is_looked_up_in_the_directory(client, clinic, cardiologist, dermatologists, gemini):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    gemini(
        [_sse(call_part("search_doctors", specialization="cardiology"))], [_sse(text_part("Here is one cardiologist."))],
        # The model reaches for the old list; the name is not in it.
        [_sse(call_part("pick_from_previous", entity="doctor", selector="by_name", name="Emily Carter"))], [_sse(text_part("ok"))],
    )
    first = await stream(client, alice, "Book me with a cardiologist")
    events = await stream(client, alice, "Book me with Emily Carter", first[-1][1]["conversation"]["id"])
    [doctor_card, *_] = events[-1][1]["assistant_message"]["results"]
    assert doctor_card["items"][0]["name"] == "Emily Carter"


async def test_db_named_booking_then_a_time_then_confirm_books_once(client, db_session, clinic, dermatologists, gemini):
    from sqlalchemy import func, select

    from app.models import Appointment

    alice = await clinic.headers_for(clinic.patient_a.user_id)
    gemini(
        [_sse(call_part("search_doctors", doctor_name="dr emily carter", intent="book"))], [_sse(text_part("Which time suits you?"))],
        [_sse(call_part("pick_from_previous", entity="slot", selector="first"))], [_sse(text_part("Press Confirm."))],
    )
    first = await stream(client, alice, "Book me with dr emily carter")
    conversation_id = first[-1][1]["conversation"]["id"]
    second = await stream(client, alice, "the first time", conversation_id)
    message = second[-1][1]["assistant_message"]
    assert message["action"]["status"] == "pending" and message["action"]["doctor_id"] == str(dermatologists["carter"].id)
    url = f"{BASE}/conversations/{conversation_id}/messages/{message['id']}/decision"
    assert (await client.post(url, json={"confirm": True}, headers=alice)).json()["action"]["status"] == "booked"
    assert (await client.post(url, json={"confirm": True}, headers=alice)).status_code == 409
    count = select(func.count()).select_from(Appointment).where(Appointment.doctor_id == dermatologists["carter"].id)
    assert await db_session.scalar(count) == 1


async def test_db_an_unknown_name_is_said_plainly_and_nobody_is_substituted(client, clinic, dermatologists, gemini):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    fake = gemini([_sse(call_part("search_doctors", doctor_name="Dr. Zara Nonexistent", intent="book"))],
                  [_sse(text_part("I couldn't find a Dr. Zara Nonexistent at this clinic."))])
    events = await stream(client, alice, "Book me with Dr. Zara Nonexistent")
    assert events[-1][1]["assistant_message"]["results"] in (None, [])  # no other doctor offered on its own
    [response] = [p["functionResponse"]["response"] for c in fake.requests[1]["contents"] for p in c["parts"] if "functionResponse" in p]
    assert response["requested_doctor_found"] is False and response["total_matches"] == 0


async def test_db_a_leaking_model_answer_is_cleaned_before_the_patient_sees_it(client, clinic, dermatologists, gemini):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    gemini([_sse(call_part("search_doctors", specialization="dermatology"))], [_sse(text_part(LEAKED))])
    events = await stream(client, alice, "Book me with a dermatologist")
    streamed = "".join(e[1]["text"] for e in events if e[0] == "delta")
    saved = events[-1][1]["assistant_message"]["content"]
    for text in (streamed, saved):
        assert "Shown to the user" not in text and "doctor_id" not in text and "01a0f29d" not in text, text
    assert events[-1][1]["assistant_message"]["results"][0]["kind"] == "doctors"  # the cards still carry the doctors
