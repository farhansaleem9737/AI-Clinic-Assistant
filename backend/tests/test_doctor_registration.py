"""Registering as a doctor (D77): a restricted applicant, never a verified doctor.

Covers the public sign-up, what an unverified applicant can and cannot do,
completing the application later (details and private credentials), and the
administrator's approval or rejection.
"""

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.permissions import RoleCode
from app.models.doctor import Doctor
from app.models.doctor_application import ApplicationStatus, DoctorApplication
from app.models.patient import Patient
from app.models.user import User
from app.services import rbac_service
from tests.conftest import login
from tests.fakes import PDF_BYTES

REGISTER = "/api/v1/auth/register"
MINE = "/api/v1/doctor-applications/me"
APPLICATIONS = "/api/v1/doctor-applications/"
PASSWORD = "pw-123456"


def doctor(email: str, **extra) -> dict:
    return {"account_type": "doctor", "name": "Sara Malik", "email": email, "password": PASSWORD, **extra}


def pdf(name="pmdc-certificate.pdf", data=PDF_BYTES):
    return {"file": (name, data, "application/pdf")}


async def stored(db_session, email):
    """The user and application rows. Read what you need from them before a
    request that fails: its rollback expires them."""
    user = await db_session.scalar(select(User).where(User.email == email))
    application = (
        await db_session.scalar(select(DoctorApplication).where(DoctorApplication.user_id == user.id)) if user else None
    )
    return user, application


async def applicant(client, email="applicant@example.com", **extra) -> dict[str, str]:
    """Register a doctor applicant through the API and sign in."""
    response = await client.post(REGISTER, json=doctor(email, **extra))
    assert response.status_code == 201, response.text
    return await login(client, email, PASSWORD)


async def upload(client, headers, document_type="registration_certificate", files=None):
    return await client.post(
        f"{MINE}/documents", files=files or pdf(), data={"document_type": document_type}, headers=headers
    )


# ---- registration ----------------------------------------------------------------


async def test_patient_registration_still_works_with_and_without_account_type(client, db_session):
    base = {"first_name": "Pat", "last_name": "Example", "date_of_birth": "1990-05-17", "password": PASSWORD}
    old_client = await client.post(REGISTER, json={**base, "email": "old@example.com"})
    new_client = await client.post(REGISTER, json={**base, "email": "new@example.com", "account_type": "patient"})
    assert old_client.status_code == new_client.status_code == 201
    assert old_client.json()["roles"] == new_client.json()["roles"] == ["patient"]
    user = await db_session.scalar(select(User).where(User.email == "new@example.com"))
    assert await db_session.scalar(select(Patient.mrn).where(Patient.user_id == user.id))


async def test_doctor_registers_with_basic_account_information_only(client, db_session):
    response = await client.post(REGISTER, json=doctor("basic@example.com"))
    assert response.status_code == 201, response.text
    assert response.json()["roles"] == ["doctor_applicant"]

    user, application = await stored(db_session, "basic@example.com")
    assert user.name == "Sara Malik"
    assert await rbac_service.role_codes_for(db_session, user.id) == {"doctor_applicant"}
    assert application.status == ApplicationStatus.pending_review and application.submitted_at is not None
    assert application.reviewed_at is None and application.doctor_id is None
    for field in ("license_number", "specialization", "department_id", "years_of_experience", "consultation_fee"):
        assert getattr(application, field) is None  # nothing invented
    # No doctor profile, so nothing public and nothing bookable.
    assert await db_session.scalar(select(Doctor.id).where(Doctor.user_id == user.id)) is None
    assert await db_session.scalar(select(Patient.id).where(Patient.user_id == user.id)) is None


async def test_optional_professional_details_are_stored_as_given(client, db_session, make_department):
    department = await make_department("Cardiology")
    details = {
        "license_number": " PMC-12345 ",
        "registration_authority": "PMDC",
        "specialization": "Cardiologist",
        "department_id": str(department.id),
        "years_of_experience": 7,
        "qualifications": "MBBS, FCPS",
        "institution": "King Edward Medical University",
        "bio": "Interventional cardiology.",
        "consultation_fee": "1500.00",
        "languages": "English, Urdu",
        "phone": "0300-0000000",
    }
    response = await client.post(REGISTER, json=doctor("details@example.com", **details))
    assert response.status_code == 201, response.text
    _, application = await stored(db_session, "details@example.com")
    assert application.license_number == "PMC-12345"  # trimmed
    assert application.department_id == department.id
    assert application.years_of_experience == 7 and application.consultation_fee == Decimal("1500.00")
    assert application.institution == "King Edward Medical University"


async def test_blank_optional_fields_are_saved_as_missing_not_empty(client, db_session):
    response = await client.post(REGISTER, json=doctor("blank@example.com", license_number="  ", specialization=""))
    assert response.status_code == 201
    _, application = await stored(db_session, "blank@example.com")
    assert application.license_number is None and application.specialization is None


@pytest.mark.parametrize("account_type", ["admin", "receptionist", "doctor_applicant", "superuser", "", 1])
async def test_unknown_account_types_are_rejected(client, db_session, account_type):
    body = {**doctor("bad@example.com"), "account_type": account_type}
    response = await client.post(REGISTER, json=body)
    assert response.status_code == 422
    assert await db_session.scalar(select(User.id).where(User.email == "bad@example.com")) is None


async def test_a_doctor_cannot_smuggle_in_a_role_or_a_verified_status(client, db_session):
    body = doctor("sneaky@example.com", role="admin", roles=["admin"], status="approved", is_verified=True)
    response = await client.post(REGISTER, json=body)
    assert response.status_code == 201
    assert response.json()["roles"] == ["doctor_applicant"]
    _, application = await stored(db_session, "sneaky@example.com")
    assert application.status == ApplicationStatus.pending_review


async def test_doctor_registration_rejects_a_taken_email(client, make_user):
    existing = await make_user(email="taken@example.com")
    response = await client.post(REGISTER, json=doctor(existing.email))
    assert response.status_code == 409 and response.json()["error"]["code"] == "EMAIL_TAKEN"


async def test_common_account_rules_still_apply_to_doctors(client):
    assert (await client.post(REGISTER, json=doctor("short@example.com", password="short"))).status_code == 422
    assert (await client.post(REGISTER, json=doctor("blank-name@example.com", name="   "))).status_code == 422
    assert (await client.post(REGISTER, json=doctor("not-an-email"))).status_code == 422
    assert (await client.post(REGISTER, json=doctor("x@example.com", years_of_experience=81))).status_code == 422


async def test_a_failed_doctor_registration_leaves_nothing_behind(client, db_session, make_department):
    closed = await make_department(is_active=False)
    response = await client.post(REGISTER, json=doctor("rollback@example.com", department_id=str(closed.id)))
    assert response.status_code == 400 and response.json()["error"]["code"] == "DEPARTMENT_UNAVAILABLE"
    assert await db_session.scalar(select(User.id).where(User.email == "rollback@example.com")) is None
    # The email is still free.
    assert (await client.post(REGISTER, json=doctor("rollback@example.com"))).status_code == 201


# ---- an unverified applicant is restricted ---------------------------------------


async def test_applicant_holds_only_their_own_application_permission(client):
    headers = await applicant(client)
    me = (await client.get("/api/v1/auth/me", headers=headers)).json()
    assert me["roles"] == ["doctor_applicant"]
    assert me["permissions"] == ["doctor_application:manage_own"]
    assert me["doctor_id"] is None and me["patient_id"] is None


async def test_applicant_cannot_use_doctor_or_clinical_features(client):
    headers = await applicant(client)
    assert (await client.get("/api/v1/doctors/me", headers=headers)).status_code == 403
    assert (await client.patch("/api/v1/doctors/me", json={"bio": "x"}, headers=headers)).status_code == 403
    assert (await client.get("/api/v1/appointments/", headers=headers)).status_code == 403
    assert (await client.get("/api/v1/patients/", headers=headers)).status_code == 403
    schedule = {"weekday": 1, "start_time": "09:00", "end_time": "12:00", "slot_minutes": 30}
    assert (await client.post("/api/v1/schedules", json=schedule, headers=headers)).status_code in (403, 422)
    summary = (await client.get("/api/v1/dashboard/summary", headers=headers)).json()
    assert summary["doctor"] is None and summary["patient"] is None and summary["front_desk"] is None


async def test_applicant_is_not_listed_or_bookable(client, make_department):
    department = await make_department()
    await applicant(client, specialization="Dermatologist", department_id=str(department.id))
    listing = (await client.get("/api/v1/public/doctors/", params={"q": "Sara Malik"})).json()
    assert listing["total"] == 0
    assert "Dermatologist" not in (await client.get("/api/v1/public/doctors/specializations")).json()


async def test_applicant_cannot_review_or_approve_applications(client, db_session):
    headers = await applicant(client)
    _, application = await stored(db_session, "applicant@example.com")
    application_id = application.id
    assert (await client.get(APPLICATIONS, headers=headers)).status_code == 403
    assert (await client.get(f"{APPLICATIONS}{application_id}", headers=headers)).status_code == 403
    response = await client.post(f"{APPLICATIONS}{application_id}/approve", json={}, headers=headers)
    assert response.status_code == 403
    status = await db_session.scalar(select(DoctorApplication.status).where(DoctorApplication.id == application_id))
    assert status == ApplicationStatus.pending_review


# ---- completing the application later --------------------------------------------


async def test_applicant_reads_and_completes_their_application(client, make_department):
    department = await make_department("Neurology")
    headers = await applicant(client)
    mine = (await client.get(MINE, headers=headers)).json()
    assert mine["status"] == "pending_review" and mine["documents"] == []
    assert mine["missing_for_approval"] == ["specialization", "department_id"]

    response = await client.patch(
        MINE,
        json={"specialization": "Neurologist", "department_id": str(department.id), "languages": "English"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["department_name"] == "Neurology" and body["languages"] == "English"
    assert body["missing_for_approval"] == []

    cleared = (await client.patch(MINE, json={"languages": ""}, headers=headers)).json()
    assert cleared["languages"] is None and cleared["specialization"] == "Neurologist"


async def test_approval_requirements_come_from_settings(client, monkeypatch, make_department):
    monkeypatch.setattr(settings, "doctor_approval_requirements", ["license_number", "registration_certificate"])
    department = await make_department()
    headers = await applicant(client, specialization="GP", department_id=str(department.id))
    mine = (await client.get(MINE, headers=headers)).json()
    assert mine["missing_for_approval"] == ["license_number", "registration_certificate"]


async def test_credentials_are_optional_private_and_validated(client, storage, db_session):
    headers = await applicant(client)
    _, application = await stored(db_session, "applicant@example.com")

    response = await upload(client, headers)
    assert response.status_code == 201, response.text
    document = response.json()
    assert document["document_type"] == "registration_certificate"
    assert document["filename"] == "pmdc-certificate.pdf" and document["content_type"] == "application/pdf"
    assert "url" not in document  # no link of any kind for the applicant
    [key] = storage.objects
    assert key.startswith(f"doctor-credentials/{application.id}/") and key.endswith(".pdf")
    assert "pmdc" not in key  # ids only, never the uploader's file name

    mine = (await client.get(MINE, headers=headers)).json()
    assert [d["id"] for d in mine["documents"]] == [document["id"]]

    fake_pdf = {"file": ("degree.pdf", b"<html><script>alert(1)</script>", "application/pdf")}
    rejected = await upload(client, headers, "degree_certificate", files=fake_pdf)
    assert rejected.status_code == 415
    assert len(storage.objects) == 1


async def test_upload_reports_unconfigured_storage_honestly(client):
    headers = await applicant(client)
    response = await upload(client, headers)
    assert response.status_code == 503 and response.json()["error"]["code"] == "STORAGE_NOT_CONFIGURED"
    assert (await client.get(MINE, headers=headers)).json()["documents"] == []


async def test_applicant_can_remove_their_own_document_but_not_anyone_elses(client, storage):
    alice = await applicant(client, "alice@example.com")
    bob = await applicant(client, "bob@example.com")
    alices = (await upload(client, alice)).json()

    assert (await client.delete(f"{MINE}/documents/{alices['id']}", headers=bob)).status_code == 404
    assert len((await client.get(MINE, headers=alice)).json()["documents"]) == 1

    assert (await client.delete(f"{MINE}/documents/{alices['id']}", headers=alice)).status_code == 204
    assert (await client.get(MINE, headers=alice)).json()["documents"] == []
    assert storage.objects == {}


async def test_other_roles_have_no_application(client, auth_headers):
    patient = await auth_headers(RoleCode.patient)
    assert (await client.get(MINE, headers=patient)).status_code == 403


# ---- review ------------------------------------------------------------------------


async def test_admin_lists_and_reads_applications_and_gets_short_lived_links(client, storage, db_session, auth_headers):
    headers = await applicant(client)
    document = (await upload(client, headers)).json()
    _, application = await stored(db_session, "applicant@example.com")
    admin = await auth_headers(RoleCode.admin)

    listing = (await client.get(APPLICATIONS, params={"status": "pending_review"}, headers=admin)).json()
    [item] = [i for i in listing["items"] if i["id"] == str(application.id)]
    assert item["name"] == "Sara Malik" and item["document_count"] == 1

    link = await client.get(f"{APPLICATIONS}{application.id}/documents/{document['id']}/download", headers=admin)
    assert link.status_code == 200 and link.headers["cache-control"] == "no-store"
    assert storage.presigned[-1]["expires_in"] == settings.document_url_ttl_seconds
    assert storage.presigned[-1]["download_name"] == "registration_certificate.pdf"


async def test_document_links_check_that_the_document_belongs_to_the_application(
    client, storage, db_session, auth_headers
):
    alice = await applicant(client, "alice@example.com")
    await applicant(client, "bob@example.com")
    alices = (await upload(client, alice)).json()
    _, bobs_application = await stored(db_session, "bob@example.com")
    admin = await auth_headers(RoleCode.admin)
    response = await client.get(f"{APPLICATIONS}{bobs_application.id}/documents/{alices['id']}/download", headers=admin)
    assert response.status_code == 404


async def test_approval_needs_the_required_details(client, db_session, auth_headers):
    await applicant(client)
    _, application = await stored(db_session, "applicant@example.com")
    admin = await auth_headers(RoleCode.admin)
    response = await client.post(f"{APPLICATIONS}{application.id}/approve", json={}, headers=admin)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "APPLICATION_INCOMPLETE"
    assert response.json()["error"]["details"]["missing"] == ["specialization", "department_id"]


async def test_approval_creates_the_doctor_profile_and_swaps_the_role(client, db_session, auth_headers, make_department):
    department = await make_department()
    headers = await applicant(
        client,
        specialization="Cardiologist",
        department_id=str(department.id),
        license_number="PMC-777",
        consultation_fee="2000",
        languages="English",
    )
    user, application = await stored(db_session, "applicant@example.com")
    admin = await auth_headers(RoleCode.admin)

    response = await client.post(f"{APPLICATIONS}{application.id}/approve", json={"notes": "Verified"}, headers=admin)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "approved" and body["doctor_id"] and body["review_notes"] == "Verified"
    assert await rbac_service.role_codes_for(db_session, user.id) == {"doctor"}

    profile = await client.get("/api/v1/doctors/me", headers=headers)
    assert profile.status_code == 200, profile.text
    assert profile.json()["specialization"] == "Cardiologist" and profile.json()["languages"] == "English"
    assert profile.json()["years_of_experience"] == 0

    again = await client.post(f"{APPLICATIONS}{application.id}/approve", json={}, headers=admin)
    assert again.status_code == 409

    from app.models import AuditLog  # D90: approvals are audited

    audited = await db_session.scalars(select(AuditLog.action).where(AuditLog.target_id == body["id"]))
    assert list(audited) == ["doctor_application.approved"]


async def test_approval_refuses_a_licence_already_held_by_another_doctor(
    client, db_session, auth_headers, make_department, make_doctor
):
    await make_doctor(license_number="PMC-DUP")
    department = await make_department()
    await applicant(client, specialization="GP", department_id=str(department.id), license_number="PMC-DUP")
    user, application = await stored(db_session, "applicant@example.com")
    user_id, application_id = user.id, application.id
    admin = await auth_headers(RoleCode.admin)
    response = await client.post(f"{APPLICATIONS}{application_id}/approve", json={}, headers=admin)
    assert response.status_code == 409 and response.json()["error"]["code"] == "LICENSE_TAKEN"
    # Nothing of the approval was kept.
    assert await rbac_service.role_codes_for(db_session, user_id) == {"doctor_applicant"}
    assert await db_session.scalar(select(Doctor.id).where(Doctor.user_id == user_id)) is None


async def test_rejection_needs_a_reason_and_closes_the_application(client, db_session, auth_headers):
    headers = await applicant(client)
    user, application = await stored(db_session, "applicant@example.com")
    user_id = user.id
    admin = await auth_headers(RoleCode.admin)
    url = f"{APPLICATIONS}{application.id}/reject"
    assert (await client.post(url, json={"notes": "  "}, headers=admin)).status_code == 422

    response = await client.post(url, json={"notes": "Licence could not be verified"}, headers=admin)
    assert response.status_code == 200
    mine = (await client.get(MINE, headers=headers)).json()
    assert mine["status"] == "rejected" and mine["review_notes"] == "Licence could not be verified"
    closed = await client.patch(MINE, json={"bio": "x"}, headers=headers)
    assert closed.status_code == 409 and closed.json()["error"]["code"] == "APPLICATION_CLOSED"
    assert await rbac_service.role_codes_for(db_session, user_id) == {"doctor_applicant"}
