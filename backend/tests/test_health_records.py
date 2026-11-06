from types import SimpleNamespace

import pytest


def url(patient, kind=None, entry_id=None):
    base = f"/api/v1/patients/{patient.id}/health-records"
    if kind is None:
        return base
    return f"{base}/{kind}" if entry_id is None else f"{base}/{kind}/{entry_id}"


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
    )


async def test_patient_reports_allergies_and_medicines_but_not_diagnoses(client, clinic, cast):
    patient = clinic.patient_a
    added = await client.post(url(patient, "allergies"), json={"substance": "  Penicillin ", "reaction": "Rash", "severity": "severe"}, headers=cast.alice)
    assert added.status_code == 201, added.text
    allergy = added.json()
    assert allergy["substance"] == "Penicillin" and allergy["source"] == "patient" and allergy["can_edit"] is True
    assert allergy["recorded_by"] is None and allergy["recorded_by_me"] is True
    medicine = await client.post(url(patient, "medications"), json={"name": "Vitamin D", "frequency": "Weekly"}, headers=cast.alice)
    assert medicine.status_code == 201 and medicine.json()["source"] == "patient"
    refused = await client.post(url(patient, "diagnoses"), json={"condition": "Asthma"}, headers=cast.alice)
    assert refused.status_code == 403

    records = (await client.get(url(patient), headers=cast.alice)).json()
    assert [a["substance"] for a in records["allergies"]] == ["Penicillin"]
    assert records["can_add_allergies"] and records["can_add_medications"] and not records["can_add_diagnoses"]


async def test_treating_doctor_records_all_three_and_the_patient_reads_them(client, clinic, cast):
    patient = clinic.patient_a
    diagnosis = await client.post(
        url(patient, "diagnoses"), json={"condition": "Type 2 diabetes", "diagnosed_on": "2026-10-01", "notes": "HbA1c 7.9%"}, headers=cast.dr_a
    )
    assert diagnosis.status_code == 201, diagnosis.text
    medication = await client.post(
        url(patient, "medications"),
        json={"name": "Metformin", "dosage": "500 mg", "frequency": "Twice daily", "start_date": "2026-10-01"},
        headers=cast.dr_a,
    )
    assert medication.status_code == 201 and medication.json()["source"] == "clinician"

    records = (await client.get(url(patient), headers=cast.alice)).json()
    [shown] = records["diagnoses"]
    assert shown["condition"] == "Type 2 diabetes" and shown["recorded_by"] == "Dr. Doctor Alpha"
    assert shown["can_edit"] is False and records["medications"][0]["can_edit"] is False
    # The patient can neither change nor remove the doctor's entries.
    entry_id = shown["id"]
    assert (await client.put(url(patient, "diagnoses", entry_id), json={"condition": "None"}, headers=cast.alice)).status_code == 403
    med_id = records["medications"][0]["id"]
    assert (await client.delete(url(patient, "medications", med_id), headers=cast.alice)).status_code == 403


async def test_patient_edits_only_their_own_entries_and_the_doctor_can_correct_them(client, clinic, cast):
    patient = clinic.patient_a
    mine = (await client.post(url(patient, "allergies"), json={"substance": "Peanuts"}, headers=cast.alice)).json()
    doctors = (await client.post(url(patient, "allergies"), json={"substance": "Latex", "severity": "mild"}, headers=cast.dr_a)).json()
    assert doctors["can_edit"] is True and doctors["source"] == "clinician"

    edited = await client.put(url(patient, "allergies", mine["id"]), json={"substance": "Peanuts", "severity": "severe"}, headers=cast.alice)
    assert edited.status_code == 200 and edited.json()["severity"] == "severe"
    assert (await client.put(url(patient, "allergies", doctors["id"]), json={"substance": "X"}, headers=cast.alice)).status_code == 403

    # The doctor corrects the patient's entry; it stays marked as reported by the patient.
    corrected = await client.put(
        url(patient, "allergies", mine["id"]), json={"substance": "Peanuts", "reaction": "Swelling", "severity": "severe"}, headers=cast.dr_a
    )
    assert corrected.status_code == 200 and corrected.json()["source"] == "patient"

    assert (await client.delete(url(patient, "allergies", mine["id"]), headers=cast.alice)).status_code == 204
    records = (await client.get(url(patient), headers=cast.alice)).json()
    assert [a["substance"] for a in records["allergies"]] == ["Latex"]
    # Removed means hidden, so it can be reported again.
    again = await client.post(url(patient, "allergies"), json={"substance": "peanuts"}, headers=cast.alice)
    assert again.status_code == 201


async def test_the_same_allergy_twice_is_a_conflict(client, clinic, cast):
    patient = clinic.patient_a
    assert (await client.post(url(patient, "allergies"), json={"substance": "Aspirin"}, headers=cast.alice)).status_code == 201
    duplicate = await client.post(url(patient, "allergies"), json={"substance": "ASPIRIN"}, headers=cast.dr_a)
    assert duplicate.status_code == 409 and duplicate.json()["error"]["code"] == "ALLERGY_EXISTS"


@pytest.mark.parametrize("who", ["bob", "dr_b"])
async def test_unrelated_users_get_404(client, clinic, cast, who):
    entry = (await client.post(url(clinic.patient_a, "allergies"), json={"substance": "Sulfa"}, headers=cast.alice)).json()
    headers = getattr(cast, who)
    assert (await client.get(url(clinic.patient_a), headers=headers)).status_code == 404
    assert (await client.post(url(clinic.patient_a, "allergies"), json={"substance": "X"}, headers=headers)).status_code == 404
    assert (await client.delete(url(clinic.patient_a, "allergies", entry["id"]), headers=headers)).status_code == 404


async def test_an_entry_is_unreachable_through_another_patients_url(client, clinic, cast):
    entry = (await client.post(url(clinic.patient_a, "allergies"), json={"substance": "Sulfa"}, headers=cast.alice)).json()
    bobs = url(clinic.patient_b, "allergies", entry["id"])
    assert (await client.put(bobs, json={"substance": "Sulfa"}, headers=cast.bob)).status_code == 404


@pytest.mark.parametrize("who", ["reception", "admin"])
async def test_staff_without_clinical_access_are_refused(client, clinic, cast, who):
    assert (await client.get(url(clinic.patient_a), headers=getattr(cast, who))).status_code == 403


@pytest.mark.parametrize(
    ("kind", "body"),
    [
        ("allergies", {"substance": "   "}),
        ("allergies", {"substance": "Dust", "severity": "deadly"}),
        ("medications", {"name": "X", "start_date": "2026-10-02", "end_date": "2026-10-01"}),
        ("diagnoses", {"condition": "X", "status": "maybe"}),
    ],
)
async def test_invalid_entries_are_422(client, clinic, cast, kind, body):
    assert (await client.post(url(clinic.patient_a, kind), json=body, headers=cast.dr_a)).status_code == 422
