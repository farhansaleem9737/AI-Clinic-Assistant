from types import SimpleNamespace

import pytest

from app.core.config import settings
from tests.fakes import PDF_BYTES

FORM = {"document_type": "lab_report", "title": "Complete blood count", "document_date": "2026-10-01"}


def url(patient, document_id=None, suffix=""):
    base = f"/api/v1/patients/{patient.id}/documents/"
    return base if document_id is None else f"{base}{document_id}{suffix}"


def pdf(data=PDF_BYTES, name="cbc-results.pdf", content_type="application/pdf"):
    return {"file": (name, data, content_type)}


async def upload(client, headers, patient, *, files=None, **form):
    return await client.post(url(patient), files=files or pdf(), data={**FORM, **form}, headers=headers)


@pytest.fixture
async def cast(client, clinic):
    """Alice has an appointment with Doctor Alpha. Nobody else is related to her."""
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    booked = await client.post(
        "/api/v1/appointments/",
        json={"doctor_id": str(clinic.doctor_a.id), "starts_at": clinic.slot().isoformat()},
        headers=alice,
    )
    assert booked.status_code == 201, booked.text
    return SimpleNamespace(
        alice=alice,
        bob=await clinic.headers_for(clinic.patient_b.user_id),
        dr_a=await clinic.headers_for(clinic.doctor_a.user_id),
        dr_b=await clinic.headers_for(clinic.doctor_b.user_id),
        reception=await clinic.headers_for(clinic.receptionist.id),
        admin=await clinic.headers_for(clinic.admin.id),
        appointment_id=booked.json()["id"],
    )


async def test_treating_doctor_uploads_and_patient_reads(client, storage, clinic, cast):
    response = await upload(client, cast.dr_a, clinic.patient_a, appointment_id=cast.appointment_id)
    assert response.status_code == 201, response.text
    doc = response.json()
    assert doc["content_type"] == "application/pdf" and doc["filename"] == "cbc-results.pdf"
    assert doc["uploaded_by_me"] is True
    [key] = storage.objects
    assert key.startswith(f"patient-documents/{clinic.patient_a.id}/") and key.endswith(".pdf")

    listing = (await client.get(url(clinic.patient_a), headers=cast.alice)).json()
    assert [d["id"] for d in listing] == [doc["id"]] and listing[0]["uploaded_by_me"] is False


async def test_download_link_is_short_lived_and_has_no_phi_in_the_name(client, storage, clinic, cast):
    doc = (await upload(client, cast.alice, clinic.patient_a)).json()
    response = await client.get(url(clinic.patient_a, doc["id"], "/download"), headers=cast.alice)
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    [signed] = storage.presigned
    assert signed["expires_in"] == settings.document_url_ttl_seconds
    assert signed["download_name"] == "lab_report-2026-10-01.pdf"
    assert signed["content_type"] == "application/pdf"


@pytest.mark.parametrize("who", ["bob", "dr_b"])
async def test_unrelated_users_get_404_everywhere(client, storage, clinic, cast, who):
    doc = (await upload(client, cast.alice, clinic.patient_a)).json()
    headers = getattr(cast, who)
    for target in (
        url(clinic.patient_a),
        url(clinic.patient_a, doc["id"]),
        url(clinic.patient_a, doc["id"], "/download"),
    ):
        assert (await client.get(target, headers=headers)).status_code == 404, target
    assert (await upload(client, headers, clinic.patient_a)).status_code == 404
    assert len(storage.objects) == 1 and storage.presigned == []


async def test_document_is_unreachable_through_another_patients_url(client, storage, clinic, cast):
    doc = (await upload(client, cast.alice, clinic.patient_a)).json()
    response = await client.get(url(clinic.patient_b, doc["id"], "/download"), headers=cast.bob)
    assert response.status_code == 404 and storage.presigned == []


@pytest.mark.parametrize("who", ["reception", "admin"])
async def test_staff_without_clinical_access_are_refused(client, storage, clinic, cast, who):
    assert (await client.get(url(clinic.patient_a), headers=getattr(cast, who))).status_code == 403


@pytest.mark.parametrize(
    ("files", "status", "code"),
    [
        (pdf(b"<svg xmlns='http://www.w3.org/2000/svg'/>", "scan.svg", "image/svg+xml"), 415, "UNSUPPORTED_FILE"),
        (pdf(b"MZ\x90\x00 renamed program"), 415, "UNSUPPORTED_FILE"),
        (pdf(PDF_BYTES[:-7], "cut.pdf"), 415, "UNSUPPORTED_FILE"),
    ],
)
async def test_invalid_documents_are_rejected(client, storage, clinic, cast, files, status, code):
    response = await upload(client, cast.alice, clinic.patient_a, files=files)
    assert response.status_code == status and response.json()["error"]["code"] == code
    assert storage.objects == {}


async def test_oversized_document_is_413(client, storage, clinic, cast, monkeypatch):
    monkeypatch.setattr(settings, "max_document_bytes", 1000)
    big = b"%PDF-1.4\n" + b"0" * 5000 + b"\n%%EOF\n"
    response = await upload(client, cast.alice, clinic.patient_a, files=pdf(big))
    assert response.status_code == 413 and storage.objects == {}


async def test_missing_form_fields_are_422(client, storage, clinic, cast):
    response = await client.post(url(clinic.patient_a), files=pdf(), data={"title": "x"}, headers=cast.alice)
    assert response.status_code == 422


async def test_another_patients_appointment_is_refused(client, storage, clinic, cast):
    response = await upload(client, cast.bob, clinic.patient_b, appointment_id=cast.appointment_id)
    assert response.status_code == 404 and storage.objects == {}


async def test_missing_object_is_reported_and_never_signed(client, storage, clinic, cast):
    doc = (await upload(client, cast.alice, clinic.patient_a)).json()
    storage.objects.clear()
    response = await client.get(url(clinic.patient_a, doc["id"], "/download"), headers=cast.alice)
    assert response.status_code == 404 and response.json()["error"]["code"] == "FILE_MISSING"
    assert storage.presigned == []


async def test_r2_outages_are_503(client, storage, clinic, cast):
    storage.fail_on.add("put")
    assert (await upload(client, cast.alice, clinic.patient_a)).status_code == 503
    assert (await client.get(url(clinic.patient_a), headers=cast.alice)).json() == []
    storage.fail_on = {"head"}
    doc = (await upload(client, cast.alice, clinic.patient_a)).json()
    assert (await client.get(url(clinic.patient_a, doc["id"], "/download"), headers=cast.alice)).status_code == 503


async def test_patient_retracts_own_upload_but_not_the_doctors(client, storage, clinic, cast):
    own = (await upload(client, cast.alice, clinic.patient_a)).json()
    doctors = (await upload(client, cast.dr_a, clinic.patient_a)).json()
    reason = {"reason": "Wrong file"}
    refused = await client.post(url(clinic.patient_a, doctors["id"], "/retract"), json=reason, headers=cast.alice)
    assert refused.status_code == 403
    accepted = await client.post(url(clinic.patient_a, own["id"], "/retract"), json=reason, headers=cast.alice)
    assert accepted.status_code == 200

    listing = (await client.get(url(clinic.patient_a), headers=cast.alice)).json()
    assert [d["id"] for d in listing] == [doctors["id"]]
    assert len(storage.objects) == 2  # retracted files are kept for retention


async def test_treating_doctor_retracts_any_document(client, storage, clinic, cast):
    doc = (await upload(client, cast.alice, clinic.patient_a)).json()
    response = await client.post(
        url(clinic.patient_a, doc["id"], "/retract"), json={"reason": "Wrong patient"}, headers=cast.dr_a
    )
    assert response.status_code == 200
