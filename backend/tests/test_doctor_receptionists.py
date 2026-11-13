"""Receptionists assigned by individual doctors, with per-doctor permissions (D131).

Scenario from the brief: doctors A, B, C; receptionists X, Y.
A employs X and Y; B employs X; C employs Y.
"""

import re
from datetime import time, timedelta
from email import policy
from email.parser import BytesParser

import pytest
from sqlalchemy import select

from app.core.permissions import RoleCode
from app.core.security import hash_token
from app.models.doctor_receptionist import DoctorReceptionist, ReceptionistInvitation
from app.models.schedule import ScheduleTemplate
from app.models.user import User
from tests.conftest import TEST_PASSWORD, login

API = "/api/v1"
APPTS = f"{API}/appointments/"
ACT = "X-Acting-Doctor-Id"
X_PASSWORD = "receptionist-x-pass"
Y_PASSWORD = "receptionist-y-pass"
FULL = ["appointments_view", "appointments_create", "appointments_update", "patients_view"]
LIMITED = ["appointments_view", "appointments_create"]


def iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


def last_token(outbox) -> str:
    newest = sorted(outbox.glob("*.eml"))[-1]
    text = BytesParser(policy=policy.default).parsebytes(newest.read_bytes()).get_body(("plain",)).get_content()
    return re.search(r"/accept-receptionist-invite#token=([A-Za-z0-9_-]+)", text).group(1)


async def invite(client, outbox, doctor_headers, email, permissions) -> str:
    response = await client.post(
        f"{API}/doctors/me/receptionist-invitations", json={"email": email, "permissions": permissions}, headers=doctor_headers
    )
    assert response.status_code == 201, response.text
    return last_token(outbox)


async def accept_new(client, token, name, password):
    response = await client.post(f"{API}/receptionist-invitations/accept", json={"token": token, "name": name, "password": password})
    assert response.status_code == 201, response.text


async def accept_existing(client, token, headers, password):
    response = await client.post(
        f"{API}/receptionist-invitations/accept-existing", json={"token": token, "current_password": password}, headers=headers
    )
    assert response.status_code == 200, response.text


@pytest.fixture
async def practice(client, db_session, clinic, make_doctor, isolated_side_channels):
    """Doctors A, B, C; X works for A (full) and B (limited); Y for A (full) and C (limited).
    One appointment each with A (Alice) and B (Bob), booked by the front desk."""
    outbox = isolated_side_channels
    doctor_c = await make_doctor(name="Doctor Gamma", department=clinic.department)
    for weekday in range(7):
        db_session.add(ScheduleTemplate(doctor_id=doctor_c.id, weekday=weekday, start_time=time(9, 0), end_time=time(17, 0),
                                        slot_minutes=30, valid_from=clinic.today - timedelta(days=30)))
    await db_session.commit()
    headers = {}
    for key, doctor in (("A", clinic.doctor_a), ("B", clinic.doctor_b), ("C", doctor_c)):
        headers[key] = await clinic.headers_for(doctor.user_id)

    token = await invite(client, outbox, headers["A"], "x@example.com", FULL)
    await accept_new(client, token, "Xena Desk", X_PASSWORD)
    token = await invite(client, outbox, headers["A"], "y@example.com", FULL)
    await accept_new(client, token, "Yusuf Desk", Y_PASSWORD)
    x = await login(client, "x@example.com", X_PASSWORD)
    y = await login(client, "y@example.com", Y_PASSWORD)
    await accept_existing(client, await invite(client, outbox, headers["B"], "x@example.com", LIMITED), x, X_PASSWORD)
    await accept_existing(client, await invite(client, outbox, headers["C"], "y@example.com", LIMITED), y, Y_PASSWORD)

    front_desk = await clinic.headers_for(clinic.receptionist.id)
    booked = {}
    for key, doctor, patient in (("A", clinic.doctor_a, clinic.patient_a), ("B", clinic.doctor_b, clinic.patient_b)):
        r = await client.post(APPTS, json={"doctor_id": str(doctor.id), "patient_id": str(patient.id), "starts_at": iso(clinic.slot(3, "10:00"))},
                              headers=front_desk)
        assert r.status_code == 201, r.text
        booked[key] = r.json()["id"]
    ids = {"A": str(clinic.doctor_a.id), "B": str(clinic.doctor_b.id), "C": str(doctor_c.id)}
    return clinic, headers, ids, x, y, booked, outbox


def acting(headers, doctor_id):
    return {**headers, ACT: doctor_id}


async def test_many_to_many_with_independent_permissions(client, db_session, practice):
    clinic, doctors, ids, x, y, booked, _ = practice

    mine = (await client.get(f"{API}/receptionists/me/doctors", headers=x)).json()
    assert {d["doctor_id"]: d["permissions"] for d in mine} == {
        ids["A"]: sorted(FULL), ids["B"]: sorted(LIMITED + ["patients_view"]),  # booking needs patients: implied
    }
    names = lambda r: sorted(a["email"] for a in r.json())  # noqa: E731
    assert names(await client.get(f"{API}/doctors/me/receptionists", headers=doctors["A"])) == ["x@example.com", "y@example.com"]
    assert names(await client.get(f"{API}/doctors/me/receptionists", headers=doctors["B"])) == ["x@example.com"]
    assert names(await client.get(f"{API}/doctors/me/receptionists", headers=doctors["C"])) == ["y@example.com"]

    # One global account each, with the doctor-receptionist role only, and no doctor on the user.
    user_x = await db_session.scalar(select(User).where(User.email == "x@example.com"))
    rows = (await db_session.scalars(select(DoctorReceptionist).where(DoctorReceptionist.receptionist_user_id == user_x.id))).all()
    assert len(rows) == 2
    # Tokens are stored hashed only.
    stored = (await db_session.scalars(select(ReceptionistInvitation.token_hash))).all()
    assert all(len(h) == 64 for h in stored)


async def test_receptionist_sees_and_acts_only_for_the_doctor_named_and_assigned(client, practice):
    clinic, doctors, ids, x, y, booked, _ = practice

    # Without naming a doctor: no appointment or patient rights at all.
    assert (await client.get(APPTS, headers=x)).status_code == 403
    # Naming an unassigned doctor (or garbage): refused.
    for bad in (ids["C"], "not-a-uuid"):
        r = await client.get(APPTS, headers=acting(x, bad))
        assert r.status_code == 403 and r.json()["error"]["code"] == "NOT_ASSIGNED_TO_DOCTOR"

    for_a = acting(x, ids["A"])
    listed = {a["id"] for a in (await client.get(APPTS, headers=for_a)).json()["items"]}
    assert booked["A"] in listed and booked["B"] not in listed
    # Another doctor's appointment and patient do not exist from A's desk.
    assert (await client.get(f"{APPTS}{booked['B']}", headers=for_a)).status_code == 404
    assert (await client.get(f"{API}/patients/{clinic.patient_b.id}", headers=for_a)).status_code == 404
    assert (await client.get(f"{API}/patients/{clinic.patient_a.id}", headers=for_a)).status_code == 200
    # Nor can A's desk book with B, whatever the body says.
    r = await client.post(APPTS, json={"doctor_id": ids["B"], "patient_id": str(clinic.patient_a.id),
                                       "starts_at": iso(clinic.slot(4, "11:00"))}, headers=for_a)
    assert r.status_code == 404
    # A allows updates: X confirms A's appointment.
    r = await client.post(f"{APPTS}{booked['A']}/status", json={"status": "confirmed"}, headers=for_a)
    assert r.status_code == 200, r.text

    # B's desk: sees B's appointment, may book with B, but B did not allow updates.
    for_b = acting(x, ids["B"])
    assert (await client.get(f"{APPTS}{booked['B']}", headers=for_b)).status_code == 200
    assert (await client.get(f"{APPTS}{booked['A']}", headers=for_b)).status_code == 404
    r = await client.post(f"{APPTS}{booked['B']}/status", json={"status": "confirmed"}, headers=for_b)
    assert r.status_code == 403
    r = await client.post(APPTS, json={"doctor_id": ids["B"], "patient_id": str(clinic.patient_b.id),
                                       "starts_at": iso(clinic.slot(5, "11:00"))}, headers=for_b)
    assert r.status_code == 201, r.text
    # Never clinical content.
    assert (await client.get(f"{API}/patients/{clinic.patient_b.id}/documents/", headers=for_b)).status_code in (403, 404)


async def test_suspend_and_remove_affect_only_that_doctor(client, db_session, practice):
    clinic, doctors, ids, x, y, booked, _ = practice
    listing = (await client.get(f"{API}/doctors/me/receptionists", headers=doctors["B"])).json()
    x_at_b = listing[0]["id"]

    r = await client.patch(f"{API}/doctors/me/receptionists/{x_at_b}/status", json={"status": "suspended"}, headers=doctors["B"])
    assert r.status_code == 200 and r.json()["status"] == "suspended"
    assert (await client.get(APPTS, headers=acting(x, ids["B"]))).status_code == 403
    assert (await client.get(APPTS, headers=acting(x, ids["A"]))).status_code == 200
    await client.patch(f"{API}/doctors/me/receptionists/{x_at_b}/status", json={"status": "active"}, headers=doctors["B"])
    assert (await client.get(APPTS, headers=acting(x, ids["B"]))).status_code == 200

    x_at_a = next(a["id"] for a in (await client.get(f"{API}/doctors/me/receptionists", headers=doctors["A"])).json()
                  if a["email"] == "x@example.com")
    assert (await client.delete(f"{API}/doctors/me/receptionists/{x_at_a}", headers=doctors["A"])).status_code == 204
    assert (await client.get(APPTS, headers=acting(x, ids["A"]))).status_code == 403
    assert (await client.get(APPTS, headers=acting(x, ids["B"]))).status_code == 200
    user_x = await db_session.scalar(select(User).where(User.email == "x@example.com"))
    assert user_x is not None and user_x.is_active
    assert (await client.post(f"{API}/auth/login", json={"email": "x@example.com", "password": X_PASSWORD})).status_code == 200
    # A removed X: it cannot simply be switched back on.
    r = await client.patch(f"{API}/doctors/me/receptionists/{x_at_a}/status", json={"status": "active"}, headers=doctors["A"])
    assert r.status_code == 409


async def test_nobody_manages_assignments_that_are_not_theirs(client, practice, auth_headers):
    clinic, doctors, ids, x, y, booked, outbox = practice
    x_at_a = next(a for a in (await client.get(f"{API}/doctors/me/receptionists", headers=doctors["A"])).json()
                  if a["email"] == "x@example.com")["id"]
    # Doctor B cannot see or change Doctor A's assignment.
    assert (await client.get(f"{API}/doctors/me/receptionists/{x_at_a}", headers=doctors["B"])).status_code == 404
    r = await client.patch(f"{API}/doctors/me/receptionists/{x_at_a}/permissions", json={"permissions": []}, headers=doctors["B"])
    assert r.status_code == 404
    assert (await client.delete(f"{API}/doctors/me/receptionists/{x_at_a}", headers=doctors["B"])).status_code == 404
    # A receptionist cannot change their own permissions, invite, or manage doctors.
    for headers in (x, acting(x, ids["A"])):
        r = await client.patch(f"{API}/doctors/me/receptionists/{x_at_a}/permissions",
                               json={"permissions": ["patients_update"]}, headers=headers)
        assert r.status_code == 403
        r = await client.post(f"{API}/doctors/me/receptionist-invitations", json={"email": "z@example.com"}, headers=headers)
        assert r.status_code == 403
        r = await client.post(f"{API}/doctors/", json={}, headers=headers)
        assert r.status_code == 403
    # Patients and the front desk are not doctors here either.
    for role in (RoleCode.patient, RoleCode.receptionist):
        assert (await client.get(f"{API}/doctors/me/receptionists", headers=await auth_headers(role))).status_code == 403


async def test_invitation_rules(client, practice, make_user):
    clinic, doctors, ids, x, y, booked, outbox = practice
    token = await invite(client, outbox, doctors["B"], "new-desk@example.com", ["appointments_view"])
    await accept_new(client, token, "New Desk", "new-desk-pass")
    # Single use.
    r = await client.post(f"{API}/receptionist-invitations/accept", json={"token": token, "name": "Again", "password": "whatever-pass"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "INVITATION_USED"
    # Unknown permission names are refused.
    r = await client.post(f"{API}/doctors/me/receptionist-invitations",
                          json={"email": "q@example.com", "permissions": ["records_delete"]}, headers=doctors["A"])
    assert r.status_code == 422
    # A patient's (or doctor's) login cannot be turned into a receptionist by a doctor.
    patient_user = await make_user(RoleCode.patient)
    r = await client.post(f"{API}/doctors/me/receptionist-invitations", json={"email": patient_user.email}, headers=doctors["A"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "ACCOUNT_NOT_ELIGIBLE"
    # Already working for this doctor.
    r = await client.post(f"{API}/doctors/me/receptionist-invitations", json={"email": "x@example.com"}, headers=doctors["B"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "ALREADY_ASSIGNED"
    # Pending invitations can be listed and revoked; a revoked link no longer works.
    token = await invite(client, outbox, doctors["C"], "later@example.com", [])
    pending = (await client.get(f"{API}/doctors/me/receptionist-invitations", headers=doctors["C"])).json()
    later = next(i for i in pending if i["email"] == "later@example.com")
    assert later["status"] == "pending"
    assert (await client.delete(f"{API}/doctors/me/receptionist-invitations/{later['id']}", headers=doctors["A"])).status_code == 404
    assert (await client.delete(f"{API}/doctors/me/receptionist-invitations/{later['id']}", headers=doctors["C"])).status_code == 200
    r = await client.post(f"{API}/receptionist-invitations/accept", json={"token": token, "name": "Later", "password": "later-pass1"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "INVITATION_REVOKED"
    assert hash_token(token) != token
