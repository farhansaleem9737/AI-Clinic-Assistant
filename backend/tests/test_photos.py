import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.permissions import RoleCode
from app.main import app
from app.models.stored_file import FileStatus, StoredFile
from tests.conftest import login_as
from tests.fakes import image_bytes

DOCTORS = "/api/v1/doctors"
PATIENTS = "/api/v1/patients"


def photo(data=None, name="me.png", content_type="image/png"):
    return {"file": (name, data if data is not None else image_bytes(), content_type)}


async def statuses(db_session):
    return sorted((await db_session.scalars(select(StoredFile.status))).all())


@pytest.fixture
async def doctor_headers(client, db_session, make_doctor):
    doctor = await make_doctor()
    return doctor, await login_as(client, db_session, doctor.user_id)


async def test_doctor_uploads_own_photo(client, storage, doctor_headers):
    doctor, headers = doctor_headers
    response = await client.put(f"{DOCTORS}/me/photo", files=photo(), headers=headers)
    assert response.status_code == 200, response.text
    [key] = storage.objects
    assert key.startswith(f"doctor-photos/{doctor.id}/") and key.endswith(".webp")
    assert storage.objects[key][1] == "image/webp"
    assert response.json()["photo_url"].startswith(f"https://fake-r2.test/{key}")

    public = await client.get(f"/api/v1/public/doctors/{doctor.id}")
    assert public.json()["photo_url"] is not None
    assert "object_key" not in public.text


async def test_replacing_a_photo_deletes_the_old_object(client, storage, doctor_headers, db_session):
    _, headers = doctor_headers
    await client.put(f"{DOCTORS}/me/photo", files=photo(), headers=headers)
    assert (await client.put(f"{DOCTORS}/me/photo", files=photo(), headers=headers)).status_code == 200
    assert len(storage.objects) == 1
    assert await statuses(db_session) == [FileStatus.active, FileStatus.deleted]


async def test_failed_delete_is_deferred_not_fatal(client, storage, doctor_headers, db_session):
    _, headers = doctor_headers
    await client.put(f"{DOCTORS}/me/photo", files=photo(), headers=headers)
    storage.fail_on.add("delete")
    assert (await client.put(f"{DOCTORS}/me/photo", files=photo(), headers=headers)).status_code == 200
    assert len(storage.objects) == 2
    assert await statuses(db_session) == [FileStatus.active, FileStatus.pending_deletion]


async def test_removing_a_photo(client, storage, doctor_headers):
    _, headers = doctor_headers
    await client.put(f"{DOCTORS}/me/photo", files=photo(), headers=headers)
    response = await client.delete(f"{DOCTORS}/me/photo", headers=headers)
    assert response.status_code == 200 and response.json()["photo_url"] is None
    assert storage.objects == {}


async def test_patients_cannot_upload_doctor_photos(client, storage, auth_headers):
    response = await client.put(f"{DOCTORS}/me/photo", files=photo(), headers=await auth_headers(RoleCode.patient))
    assert response.status_code == 403 and storage.objects == {}


async def test_admin_sets_any_doctor_photo_but_reception_cannot(client, storage, auth_headers, make_doctor):
    url = f"{DOCTORS}/{(await make_doctor()).id}/photo"
    assert (await client.put(url, files=photo(), headers=await auth_headers(RoleCode.receptionist))).status_code == 403
    assert (await client.put(url, files=photo(), headers=await auth_headers(RoleCode.admin))).status_code == 200


async def test_patient_sets_own_photo_but_not_someone_elses(client, storage, make_patient, db_session):
    alice = await make_patient(first_name="Alice", with_account=True)
    bob = await make_patient(first_name="Bob", with_account=True)
    headers = await login_as(client, db_session, alice.user_id)
    mine = await client.put(f"{PATIENTS}/me/photo", files=photo(), headers=headers)
    assert mine.status_code == 200 and mine.json()["photo_url"]
    assert (await client.put(f"{PATIENTS}/{bob.id}/photo", files=photo(), headers=headers)).status_code == 403
    [key] = storage.objects
    assert key.startswith(f"patient-photos/{alice.id}/")


async def test_reception_sets_a_patient_photo(client, storage, make_patient, auth_headers):
    patient = await make_patient()
    response = await client.put(
        f"{PATIENTS}/{patient.id}/photo", files=photo(), headers=await auth_headers(RoleCode.receptionist)
    )
    assert response.status_code == 200 and response.json()["photo_url"]


@pytest.mark.parametrize(
    ("data", "name", "content_type", "code"),
    [
        (
            b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>",
            "x.svg",
            "image/svg+xml",
            "UNSUPPORTED_FILE",
        ),
        (b"MZ\x90\x00 definitely not a picture", "cat.jpg", "image/jpeg", "UNSUPPORTED_FILE"),
        (b"", "empty.png", "image/png", "EMPTY_FILE"),
    ],
)
async def test_invalid_photos_are_rejected(client, storage, doctor_headers, db_session, data, name, content_type, code):
    _, headers = doctor_headers
    response = await client.put(f"{DOCTORS}/me/photo", files=photo(data, name, content_type), headers=headers)
    assert response.status_code == 415 and response.json()["error"]["code"] == code
    assert storage.objects == {} and await statuses(db_session) == []


async def test_oversized_photo_is_413(client, storage, doctor_headers, monkeypatch):
    monkeypatch.setattr(settings, "max_photo_bytes", 10_000)
    _, headers = doctor_headers
    big = image_bytes(size=(300, 300), noise=True)
    response = await client.put(f"{DOCTORS}/me/photo", files=photo(big), headers=headers)
    assert response.status_code == 413 and response.json()["error"]["code"] == "FILE_TOO_LARGE"


async def test_r2_outage_is_503_and_leaves_no_row(client, storage, doctor_headers, db_session):
    _, headers = doctor_headers
    storage.fail_on.add("put")
    response = await client.put(f"{DOCTORS}/me/photo", files=photo(), headers=headers)
    assert response.status_code == 503 and response.json()["error"]["code"] == "STORAGE_UNAVAILABLE"
    assert await statuses(db_session) == []


async def test_without_storage_uploads_are_503_and_profiles_still_load(client, doctor_headers):
    _, headers = doctor_headers  # no `storage` fixture: storage is unconfigured
    response = await client.put(f"{DOCTORS}/me/photo", files=photo(), headers=headers)
    assert response.status_code == 503 and response.json()["error"]["code"] == "STORAGE_NOT_CONFIGURED"
    profile = await client.get(f"{DOCTORS}/me", headers=headers)
    assert profile.status_code == 200 and profile.json()["photo_url"] is None


async def test_database_failure_after_upload_removes_the_object(client, storage, doctor_headers, db_session, monkeypatch):
    _, headers = doctor_headers  # logged in before the database "fails"

    async def broken_commit():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(db_session, "commit", broken_commit)
    # This client returns the 500 instead of re-raising the error in the test.
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test") as raw:
        response = await raw.put(f"{DOCTORS}/me/photo", files=photo(), headers=headers)
    assert response.status_code == 500
    assert storage.objects == {}  # the uploaded object was deleted again
