"""The staff Doctor Schedules view (D83): one doctor's day with every slot's
status, breaks between working blocks, exceptions, bookings and the week."""

from datetime import date, datetime, time, timedelta

from app.models.schedule import ExceptionKind, ScheduleException, ScheduleTemplate


def iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


async def board(client, headers, doctor_id, day: date):
    response = await client.get(f"/api/v1/doctors/{doctor_id}/day-schedule", params={"day": day.isoformat()}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def local_times(body, status, tz):
    return [datetime.fromisoformat(s["starts_at"]).astimezone(tz).strftime("%H:%M") for s in body["slots"] if s["status"] == status]


async def doctor_working(db_session, make_doctor, clinic, blocks, weekday):
    """A doctor in the clinic's department working `blocks` on one weekday."""
    doctor = await make_doctor(name="Doctor Blocks", department=clinic.department)
    for start, end in blocks:
        db_session.add(
            ScheduleTemplate(
                doctor_id=doctor.id, weekday=weekday, start_time=start, end_time=end,
                slot_minutes=30, valid_from=clinic.today - timedelta(days=1),
            )
        )
    await db_session.commit()
    return doctor


async def test_a_working_day_with_its_slots_and_week(client, clinic):
    reception = await clinic.headers_for(clinic.receptionist.id)
    day = clinic.today + timedelta(days=2)
    body = await board(client, reception, clinic.doctor_a.id, day)
    assert body["date"] == day.isoformat() and body["timezone"] == "Asia/Karachi"
    assert body["slot_minutes"] == 30
    assert body["working_hours"] == [{"start_time": "09:00:00", "end_time": "17:00:00"}]
    assert body["breaks"] == [] and body["total_slots"] == 16 and body["available_slots"] == 16
    week = body["week"]
    assert len(week) == 7 and day.isoformat() in [d["date"] for d in week]
    assert date.fromisoformat(week[0]["date"]).isoweekday() == 7  # Sunday first
    assert next(d for d in week if d["date"] == day.isoformat())["status"] == "available"


async def test_booked_slots_are_marked_without_saying_who(client, clinic):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    booked = await client.post(
        "/api/v1/appointments/",
        json={"doctor_id": str(clinic.doctor_a.id), "starts_at": iso(clinic.slot(2, "10:00")), "reason": "Chest pain"},
        headers=alice,
    )
    assert booked.status_code == 201
    reception = await clinic.headers_for(clinic.receptionist.id)
    response = await client.get(
        f"/api/v1/doctors/{clinic.doctor_a.id}/day-schedule",
        params={"day": (clinic.today + timedelta(days=2)).isoformat()},
        headers=reception,
    )
    body = response.json()
    assert local_times(body, "booked", clinic.tz) == ["10:00"]
    assert body["available_slots"] == 15 and body["total_slots"] == 16
    for secret in ("Alice", "Chest pain", "MRN", booked.json()["id"]):
        assert secret not in response.text


async def test_gaps_between_working_blocks_are_breaks(client, db_session, make_doctor, clinic):
    day = clinic.today + timedelta(days=3)
    doctor = await doctor_working(db_session, make_doctor, clinic, [(time(9), time(12)), (time(13), time(15))], day.weekday())
    body = await board(client, await clinic.headers_for(clinic.receptionist.id), doctor.id, day)
    assert body["working_hours"] == [
        {"start_time": "09:00:00", "end_time": "12:00:00"},
        {"start_time": "13:00:00", "end_time": "15:00:00"},
    ]
    assert body["breaks"] == [{"start_time": "12:00:00", "end_time": "13:00:00"}]
    assert local_times(body, "break", clinic.tz) == ["12:00", "12:30"]
    assert body["total_slots"] == 10  # breaks are not slots


async def test_a_day_off_and_a_day_on_leave(client, db_session, make_doctor, clinic):
    day = clinic.today + timedelta(days=3)
    doctor = await doctor_working(db_session, make_doctor, clinic, [(time(9), time(11))], day.weekday())
    reception = await clinic.headers_for(clinic.receptionist.id)
    off_day = await board(client, reception, doctor.id, day + timedelta(days=1))
    assert off_day["total_slots"] == 0 and off_day["working_hours"] == []
    assert next(d for d in off_day["week"] if d["date"] == (day + timedelta(days=1)).isoformat())["status"] == "off"

    db_session.add(
        ScheduleException(
            doctor_id=doctor.id, kind=ExceptionKind.leave,
            starts_at=datetime.combine(day, time.min, tzinfo=clinic.tz),
            ends_at=datetime.combine(day + timedelta(days=1), time.min, tzinfo=clinic.tz),
        )
    )
    await db_session.commit()
    leave = await board(client, reception, doctor.id, day)
    assert leave["available_slots"] == 0
    assert {s["status"] for s in leave["slots"]} == {"blocked"}
    assert next(d for d in leave["week"] if d["date"] == day.isoformat())["status"] == "unavailable"


async def test_custom_hours_replace_the_day(client, db_session, clinic):
    day = clinic.today + timedelta(days=4)
    db_session.add(
        ScheduleException(
            doctor_id=clinic.doctor_a.id, kind=ExceptionKind.custom_hours,
            starts_at=datetime.combine(day, time(10), tzinfo=clinic.tz),
            ends_at=datetime.combine(day, time(12), tzinfo=clinic.tz),
        )
    )
    await db_session.commit()
    body = await board(client, await clinic.headers_for(clinic.receptionist.id), clinic.doctor_a.id, day)
    assert body["working_hours"] == [{"start_time": "10:00:00", "end_time": "12:00:00"}]
    assert body["total_slots"] == 4


async def test_a_fully_booked_day(client, db_session, make_doctor, clinic):
    day = clinic.today + timedelta(days=3)
    doctor = await doctor_working(db_session, make_doctor, clinic, [(time(9), time(9, 30))], day.weekday())
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    when = datetime.combine(day, time(9), tzinfo=clinic.tz)
    assert (await client.post("/api/v1/appointments/", json={"doctor_id": str(doctor.id), "starts_at": iso(when)}, headers=alice)).status_code == 201
    body = await board(client, await clinic.headers_for(clinic.receptionist.id), doctor.id, day)
    assert next(d for d in body["week"] if d["date"] == day.isoformat())["status"] == "fully_booked"


async def test_slots_that_started_are_past(client, clinic, freeze_clock):
    freeze_clock(clinic.slot(0, "12:10"))
    body = await board(client, await clinic.headers_for(clinic.receptionist.id), clinic.doctor_a.id, clinic.today)
    past = local_times(body, "past", clinic.tz)
    assert past[0] == "09:00" and past[-1] == "12:00"  # 12:00 started at 12:00
    assert local_times(body, "available", clinic.tz)[0] == "12:30"
    if clinic.today.isoweekday() != 7:  # an earlier day this week is over
        assert body["week"][0]["status"] == "past"


async def test_only_staff_may_see_the_board(client, clinic):
    url = f"/api/v1/doctors/{clinic.doctor_a.id}/day-schedule"
    params = {"day": clinic.today.isoformat()}
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    assert (await client.get(url, params=params, headers=alice)).status_code == 403
    assert (await client.get(url, params=params)).status_code == 401


async def test_dates_far_away_are_refused(client, clinic):
    reception = await clinic.headers_for(clinic.receptionist.id)
    response = await client.get(
        f"/api/v1/doctors/{clinic.doctor_a.id}/day-schedule",
        params={"day": (clinic.today + timedelta(days=400)).isoformat()},
        headers=reception,
    )
    assert response.status_code == 400 and response.json()["error"]["code"] == "DATE_OUT_OF_RANGE"
