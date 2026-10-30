"""Reception's Appointments page (D84): All / Today / Upcoming / Past counts,
search across patient, doctor and reason, filters, column sorting, and the
actions the state machine gives the front desk."""

from datetime import datetime, timedelta

import pytest

BASE = "/api/v1/appointments/"
COUNTS = "/api/v1/appointments/counts"


def iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


@pytest.fixture
async def scene(client, clinic, make_patient):
    """Reception books: Alice with Dr Alpha today+1 10:00 (reason "Chest pain"),
    Bob with Dr Beta today+1 09:00, Walker with Dr Alpha today+2 11:00."""
    reception = await clinic.headers_for(clinic.receptionist.id)

    async def book(patient, doctor, days, hhmm, reason=None):
        body = {"doctor_id": str(doctor.id), "patient_id": str(patient.id), "starts_at": iso(clinic.slot(days, hhmm))}
        if reason:
            body["reason"] = reason
        response = await client.post(BASE, json=body, headers=reception)
        assert response.status_code == 201, response.text
        return response.json()["id"]

    return {
        "reception": reception,
        "alice": await book(clinic.patient_a, clinic.doctor_a, 1, "10:00", "Chest pain"),
        "bob": await book(clinic.patient_b, clinic.doctor_b, 1, "09:00"),
        "walker": await book(clinic.walk_in, clinic.doctor_a, 2, "11:00"),
    }


async def ids(client, headers, **params):
    response = await client.get(BASE, params={"page_size": 50, **params}, headers=headers)
    assert response.status_code == 200, response.text
    return [a["id"] for a in response.json()["items"]]


async def test_counts_include_today_only_when_asked(client, clinic, scene, freeze_clock):
    freeze_clock(clinic.slot(1, "08:00"))  # day+1 is "today"
    reception = scene["reception"]
    plain = (await client.get(COUNTS, headers=reception)).json()
    assert plain == {"upcoming": 3, "past": 0, "all": 3}  # unchanged contract for other pages
    body = (await client.get(COUNTS, params={"include_today": "true"}, headers=reception)).json()
    assert body["today"] == 2 and body["today_date"] == clinic.slot(1, "08:00").astimezone(clinic.tz).date().isoformat()
    # Counts follow the other filters too.
    filtered = (
        await client.get(COUNTS, params={"include_today": "true", "doctor_id": str(clinic.doctor_a.id)}, headers=reception)
    ).json()
    assert (filtered["all"], filtered["today"]) == (2, 1)


async def test_search_covers_patient_doctor_and_reason(client, clinic, scene):
    reception = scene["reception"]
    assert await ids(client, reception, q="alice") == [scene["alice"]]
    assert await ids(client, reception, q="beta") == [scene["bob"]]  # the doctor's name
    assert await ids(client, reception, q="CHEST") == [scene["alice"]]
    assert await ids(client, reception, q="nobody-matches") == []


async def test_filters_combine(client, clinic, scene):
    reception = scene["reception"]
    day1 = (clinic.today + timedelta(days=1)).isoformat()
    assert await ids(client, reception, doctor_id=str(clinic.doctor_a.id), date_from=day1, date_to=day1) == [scene["alice"]]
    assert await ids(client, reception, department_id=str(clinic.department.id), status="scheduled", q="walker") == [scene["walker"]]


@pytest.mark.parametrize(
    "sort, expected",
    [
        ("time_asc", ["bob", "alice", "walker"]),
        ("time_desc", ["walker", "alice", "bob"]),
        ("doctor_asc", ["alice", "walker", "bob"]),  # Alpha (by time), then Beta
        ("doctor_desc", ["bob", "alice", "walker"]),
    ],
)
async def test_sorting_is_done_by_the_server(client, scene, sort, expected):
    assert await ids(client, scene["reception"], sort=sort) == [scene[k] for k in expected]


async def test_sorting_by_patient_and_status(client, clinic, scene):
    reception = scene["reception"]
    cancel = await client.post(
        f"{BASE}{scene['bob']}/status", json={"status": "cancelled", "cancellation_reason": "clinic_decision"}, headers=reception
    )
    assert cancel.status_code == 200
    by_status = await ids(client, reception, sort="status_asc")
    assert by_status[-1] == scene["bob"]  # cancelled comes after scheduled in the lifecycle
    names = [a["patient"]["name"] for a in (await client.get(BASE, params={"sort": "patient_desc"}, headers=reception)).json()["items"]]
    last_names = [n.split()[-1] for n in names]
    assert last_names == sorted(last_names, reverse=True)


async def test_unknown_sort_is_rejected(client, scene):
    response = await client.get(BASE, params={"sort": "patients.mrn; drop table"}, headers=scene["reception"])
    assert response.status_code == 422


async def test_rows_carry_what_the_table_shows(client, clinic, scene):
    [row] = (await client.get(BASE, params={"q": "alice"}, headers=scene["reception"])).json()["items"]
    assert row["patient"]["mrn"].startswith("MRN") and row["patient"]["date_of_birth"]
    assert row["patient"]["sex_at_birth"] == "unknown"
    assert row["doctor"]["name"] == "Doctor Alpha" and row["doctor"]["department_name"]
    for private in ("password_hash", "clinical_notes"):
        assert private not in str(row)


async def test_reception_actions_follow_the_state_machine(client, clinic, scene, freeze_clock):
    reception = scene["reception"]
    [row] = (await client.get(BASE, params={"q": "alice"}, headers=reception)).json()["items"]
    # Before the day: confirm, cancel and reschedule; no check-in yet, never "complete".
    assert set(row["allowed_transitions"]) == {"confirmed", "cancelled"}
    assert row["can_reschedule"] is True
    confirmed = await client.post(f"{BASE}{scene['alice']}/status", json={"status": "confirmed"}, headers=reception)
    assert confirmed.status_code == 200

    freeze_clock(clinic.slot(1, "09:50"))  # the morning of the visit
    [row] = (await client.get(BASE, params={"q": "alice"}, headers=reception)).json()["items"]
    assert "checked_in" in row["allowed_transitions"]
    assert (await client.post(f"{BASE}{scene['alice']}/status", json={"status": "checked_in"}, headers=reception)).status_code == 200
    # Starting and completing the consultation is the doctor's.
    refused = await client.post(f"{BASE}{scene['alice']}/status", json={"status": "in_progress"}, headers=reception)
    assert refused.status_code == 403


async def test_a_cancelled_appointment_cannot_be_confirmed_or_checked_in(client, scene):
    reception = scene["reception"]
    url = f"{BASE}{scene['walker']}/status"
    assert (await client.post(url, json={"status": "cancelled", "cancellation_reason": "patient_request"}, headers=reception)).status_code == 200
    for target in ("confirmed", "checked_in"):
        response = await client.post(url, json={"status": target}, headers=reception)
        assert response.status_code == 409 and response.json()["error"]["code"] == "INVALID_TRANSITION"


async def test_others_only_see_their_own(client, clinic, scene):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    assert await ids(client, alice) == [scene["alice"]]
    dr_b = await clinic.headers_for(clinic.doctor_b.user_id)
    assert await ids(client, dr_b, sort="patient_asc") == [scene["bob"]]
