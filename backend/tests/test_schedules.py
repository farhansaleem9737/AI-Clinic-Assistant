from datetime import date, datetime, time, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.core.permissions import RoleCode
from app.services.availability_service import expand_templates

SCHEDULES = "/api/v1/schedules"
EXCEPTIONS = "/api/v1/schedule-exceptions"


def availability_url(doctor_id):
    return f"/api/v1/doctors/{doctor_id}/availability"


async def slots_on(client, headers, doctor_id, day: date) -> list[str]:
    response = await client.get(
        availability_url(doctor_id), params={"date_from": day.isoformat(), "date_to": day.isoformat()}, headers=headers
    )
    assert response.status_code == 200, response.text
    return [s["starts_at"] for s in response.json()["slots"]]


def iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


# ---- pure slot expansion ------------------------------------------------------------


def test_templates_keep_local_wall_clock_across_dst():
    """New York moves its clocks on 2026-03-08: 09:00 local must stay 09:00
    local, so the UTC instant shifts by an hour."""
    tz = ZoneInfo("America/New_York")
    template = SimpleNamespace(
        weekday=None, start_time=time(9, 0), end_time=time(10, 0), slot_minutes=30,
        valid_from=date(2026, 1, 1), valid_until=None,
    )
    before, after = date(2026, 3, 7), date(2026, 3, 9)
    slots = []
    for day in (before, after):
        template.weekday = day.weekday()
        slots += expand_templates([template], tz, day, day)
    assert [s.starts_at.astimezone(tz).strftime("%H:%M") for s in slots] == ["09:00", "09:30", "09:00", "09:30"]
    assert slots[0].starts_at.hour == 14 and slots[2].starts_at.hour == 13  # UTC


def test_trailing_partial_slot_is_dropped():
    tz = ZoneInfo("UTC")
    day = date(2026, 6, 1)
    template = SimpleNamespace(
        weekday=day.weekday(), start_time=time(9, 0), end_time=time(10, 10), slot_minutes=30,
        valid_from=day, valid_until=None,
    )
    assert len(expand_templates([template], tz, day, day)) == 2


# ---- availability -----------------------------------------------------------------------


async def test_availability_lists_template_slots(client, clinic):
    headers = await clinic.headers_for(clinic.patient_a.user_id)
    day = clinic.today + timedelta(days=3)
    slots = await slots_on(client, headers, clinic.doctor_a.id, day)
    assert len(slots) == 16  # 09:00-17:00 in 30-minute slots
    assert slots[0] == iso(clinic.slot(3, "09:00"))


async def test_patients_see_availability_but_not_schedule_internals(client, clinic):
    headers = await clinic.headers_for(clinic.patient_a.user_id)
    assert (await client.get(SCHEDULES, params={"doctor_id": str(clinic.doctor_a.id)}, headers=headers)).status_code == 403
    assert (await client.get(EXCEPTIONS, params={"doctor_id": str(clinic.doctor_a.id)}, headers=headers)).status_code == 403
    assert (await client.get(availability_url(clinic.doctor_a.id), params={
        "date_from": clinic.today.isoformat(), "date_to": clinic.today.isoformat()}, headers=headers)).status_code == 200


async def test_availability_range_is_limited(client, clinic):
    headers = await clinic.headers_for(clinic.patient_a.user_id)
    response = await client.get(
        availability_url(clinic.doctor_a.id),
        params={"date_from": clinic.today.isoformat(), "date_to": (clinic.today + timedelta(days=40)).isoformat()},
        headers=headers,
    )
    assert response.json()["error"]["code"] == "RANGE_TOO_LARGE"


async def test_inactive_doctor_has_no_availability(client, clinic, make_doctor):
    inactive = await make_doctor(is_active=False)
    headers = await clinic.headers_for(clinic.patient_a.user_id)
    response = await client.get(
        availability_url(inactive.id),
        params={"date_from": clinic.today.isoformat(), "date_to": clinic.today.isoformat()},
        headers=headers,
    )
    assert response.status_code == 404


async def test_leave_removes_slots_and_extra_availability_adds_them(client, clinic):
    doctor_headers = await clinic.headers_for(clinic.doctor_a.user_id)
    day = clinic.today + timedelta(days=4)

    leave = await client.post(EXCEPTIONS, json={
        "doctor_id": str(clinic.doctor_a.id), "kind": "leave",
        "starts_at": iso(clinic.slot(4, "09:00")), "ends_at": iso(clinic.slot(4, "12:00")), "reason": "Conference",
    }, headers=doctor_headers)
    assert leave.status_code == 201

    extra = await client.post(EXCEPTIONS, json={
        "doctor_id": str(clinic.doctor_a.id), "kind": "extra_availability",
        "starts_at": iso(clinic.slot(4, "18:00")), "ends_at": iso(clinic.slot(4, "19:00")),
    }, headers=doctor_headers)
    assert extra.status_code == 201

    slots = await slots_on(client, doctor_headers, clinic.doctor_a.id, day)
    assert iso(clinic.slot(4, "09:00")) not in slots and iso(clinic.slot(4, "11:30")) not in slots
    assert iso(clinic.slot(4, "12:00")) in slots
    assert iso(clinic.slot(4, "18:00")) in slots and iso(clinic.slot(4, "18:30")) in slots

    # Deleting the leave restores the morning.
    assert (await client.delete(f"{EXCEPTIONS}/{leave.json()['id']}", headers=doctor_headers)).status_code == 204
    assert iso(clinic.slot(4, "09:00")) in await slots_on(client, doctor_headers, clinic.doctor_a.id, day)


async def test_leave_over_a_booked_appointment_is_refused(client, clinic):
    reception = await clinic.headers_for(clinic.receptionist.id)
    booked = await client.post("/api/v1/appointments/", json={
        "doctor_id": str(clinic.doctor_a.id), "patient_id": str(clinic.walk_in.id), "starts_at": iso(clinic.slot(5, "10:00")),
    }, headers=reception)
    assert booked.status_code == 201

    response = await client.post(EXCEPTIONS, json={
        "doctor_id": str(clinic.doctor_a.id), "kind": "leave",
        "starts_at": iso(clinic.slot(5, "09:00")), "ends_at": iso(clinic.slot(5, "17:00")),
    }, headers=reception)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "APPOINTMENTS_IN_PERIOD"


# ---- template management ---------------------------------------------------------------


async def test_doctor_manages_only_own_schedule(client, clinic):
    headers = await clinic.headers_for(clinic.doctor_a.user_id)
    body = {"weekday": 0, "start_time": "18:00", "end_time": "20:00", "slot_minutes": 20,
            "valid_from": clinic.today.isoformat()}
    own = await client.post(SCHEDULES, json={**body, "doctor_id": str(clinic.doctor_a.id)}, headers=headers)
    assert own.status_code == 201
    other = await client.post(SCHEDULES, json={**body, "doctor_id": str(clinic.doctor_b.id)}, headers=headers)
    assert other.status_code == 403

    reception = await clinic.headers_for(clinic.receptionist.id)
    staff = await client.post(SCHEDULES, json={**body, "doctor_id": str(clinic.doctor_b.id)}, headers=reception)
    assert staff.status_code == 201


async def test_overlapping_templates_are_rejected(client, clinic):
    headers = await clinic.headers_for(clinic.doctor_a.user_id)
    response = await client.post(SCHEDULES, json={
        "doctor_id": str(clinic.doctor_a.id), "weekday": 2, "start_time": "16:00", "end_time": "18:00",
        "valid_from": clinic.today.isoformat(),
    }, headers=headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SCHEDULE_OVERLAP"


async def test_invalid_template_is_422(client, clinic):
    headers = await clinic.headers_for(clinic.doctor_a.user_id)
    response = await client.post(SCHEDULES, json={
        "doctor_id": str(clinic.doctor_a.id), "weekday": 7, "start_time": "10:00", "end_time": "09:00",
        "valid_from": clinic.today.isoformat(),
    }, headers=headers)
    assert response.status_code == 422


async def test_deactivating_a_template_removes_its_slots(client, clinic):
    headers = await clinic.headers_for(clinic.doctor_a.user_id)
    day = clinic.today + timedelta(days=6)
    templates = (await client.get(SCHEDULES, params={"doctor_id": str(clinic.doctor_a.id)}, headers=headers)).json()
    template = next(t for t in templates if t["weekday"] == day.weekday())
    assert (await client.post(f"{SCHEDULES}/{template['id']}/deactivate", headers=headers)).status_code == 200
    assert await slots_on(client, headers, clinic.doctor_a.id, day) == []


async def test_naive_exception_times_are_rejected(client, clinic):
    headers = await clinic.headers_for(clinic.doctor_a.user_id)
    response = await client.post(EXCEPTIONS, json={
        "doctor_id": str(clinic.doctor_a.id), "kind": "block",
        "starts_at": "2026-12-01T09:00:00", "ends_at": "2026-12-01T10:00:00",
    }, headers=headers)
    assert response.status_code == 422


async def test_schedule_endpoints_require_login(client, clinic):
    assert (await client.get(SCHEDULES, params={"doctor_id": str(clinic.doctor_a.id)})).status_code == 401
    assert (await client.get(availability_url(clinic.doctor_a.id), params={
        "date_from": clinic.today.isoformat(), "date_to": clinic.today.isoformat()})).status_code == 401


async def test_role_without_schedule_permission(client, auth_headers, clinic):
    body = {"doctor_id": str(clinic.doctor_a.id), "weekday": 0, "start_time": "18:00", "end_time": "19:00",
            "valid_from": clinic.today.isoformat()}
    assert (await client.post(SCHEDULES, json=body, headers=await auth_headers(RoleCode.patient))).status_code == 403
