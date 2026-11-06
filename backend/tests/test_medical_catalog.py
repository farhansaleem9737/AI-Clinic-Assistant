"""The medical catalog (D118): seeding, specializations under departments,
doctor links, directory filters and resolving conditions for the assistant."""

from collections import Counter
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.catalog import data
from app.core.permissions import RoleCode
from app.models.catalog import DoctorSpecialization, Specialization
from app.models.department import Department
from app.models.doctor import Doctor
from app.services import catalog_service
from app.services.ai import tools
from app.services.search_text import simplify

PUBLIC_SPECS = "/api/v1/public/specializations/"
PUBLIC_DOCTORS = "/api/v1/public/doctors/"
ADMIN_SPECS = "/api/v1/specializations/"


@pytest.fixture(autouse=True)
def fresh_index():
    catalog_service.invalidate()
    yield
    catalog_service.invalidate()


@pytest.fixture
async def catalog(db_session):
    report = await catalog_service.seed(db_session)
    # Plain values, not ORM rows: requests commit the shared session, which would expire them.
    specs = {s.slug: SimpleNamespace(id=s.id, name=s.name) for s in (await db_session.scalars(select(Specialization))).all()}
    departments = {
        d.slug: SimpleNamespace(id=d.id, name=d.name)
        for d in (await db_session.scalars(select(Department).where(Department.slug.is_not(None)))).all()
    }
    return SimpleNamespace(report=report, specs=specs, departments=departments)


# ---- the data itself ------------------------------------------------------------------------


def test_catalog_data_is_consistent():
    department_slugs = {d[0] for d in data.DEPARTMENTS}
    spec_slugs = {s[0] for s in data.SPECIALIZATIONS}
    assert len(department_slugs) == len(data.DEPARTMENTS) == 24
    assert len(spec_slugs) == len(data.SPECIALIZATIONS)
    assert all(d in department_slugs for s in data.SPECIALIZATIONS for d in s[2])
    assert all(link in spec_slugs for t in data.TOPICS for link, _ in t[4])
    per_department = Counter(d for s in data.SPECIALIZATIONS for d in s[2])
    assert set(per_department) == department_slugs and min(per_department.values()) >= 3
    # No alias is shared by two entries of the same kind (synonyms are one record).
    for rows, name_at, aliases_at in ((data.DEPARTMENTS, 1, 2), (data.SPECIALIZATIONS, 1, 3), (data.TOPICS, 1, 3)):
        phrases = Counter(p for r in rows for p in {simplify(r[name_at]), *map(simplify, r[aliases_at])})
        assert [p for p, n in phrases.items() if n > 1] == []
    shared = [s[0] for s in data.SPECIALIZATIONS if len(s[2]) > 1]
    assert "pediatric-cardiology" in shared and "sleep-medicine" in shared


# ---- seeding ---------------------------------------------------------------------------------


async def test_seeding_keeps_existing_departments_and_doctors_and_is_repeatable(db_session, make_department, make_doctor):
    general = await make_department("General Medicine")
    cardio = await make_department("Cardiology")
    clinic_only = await make_department("Dentistry")  # not in the catalog: kept as it is
    linked = await make_doctor(name="Ia Cardio", department=cardio, specialization="Interventional Cardiologist")
    wrong_department = await make_doctor(name="Wd Derm", department=general, specialization="Cardiologist")
    free_text = await make_doctor(name="Ft Heart", department=cardio, specialization="Heart expert")
    before = await db_session.scalar(select(func.count(Department.id)))

    report = await catalog_service.seed(db_session)
    assert sorted(report.departments_matched) == ["Cardiology", "General Medicine"]
    assert len(report.departments_created) == 22
    assert await db_session.scalar(select(func.count(Department.id))) == before + 22

    general = await db_session.get(Department, general.id)
    clinic_only = await db_session.get(Department, clinic_only.id)
    assert general.name == "General Medicine" and general.slug == "general-family-medicine"  # matched, not renamed
    assert clinic_only.slug is None and clinic_only.is_active

    links = set((await db_session.execute(select(DoctorSpecialization.doctor_id, Specialization.slug).join(Specialization))).all())
    assert (linked.id, "interventional-cardiology") in links
    assert not [d for d, _ in links if d in (wrong_department.id, free_text.id)]  # no evidence: not linked
    assert await db_session.get(Doctor, free_text.id) is not None

    again = await catalog_service.seed(db_session)
    assert again.as_dict() == {
        "departments_created": [], "departments_matched": [], "specializations_created": 0,
        "department_links_created": 0, "topics_created": 0, "topic_links_created": 0, "doctor_links_created": 0,
    }
    assert await db_session.scalar(select(func.count(Specialization.id))) == len(data.SPECIALIZATIONS)


# ---- specializations by department ---------------------------------------------------------------


async def test_choosing_cardiology_lists_only_cardiology_specializations(client, catalog):
    cardiology = catalog.departments["cardiology"]
    names = [s["name"] for s in (await client.get(PUBLIC_SPECS, params={"department_id": str(cardiology.id)})).json()]
    assert {"General Cardiology", "Interventional Cardiology", "Cardiac Electrophysiology", "Heart Failure", "Pediatric Cardiology"} <= set(names)
    assert "General Neurology" not in names and "Epilepsy" not in names
    assert names == sorted(names, key=str.lower)
    everything = (await client.get(PUBLIC_SPECS)).json()
    assert len(everything) == len(data.SPECIALIZATIONS)


async def test_directory_filters_by_one_or_several_specializations(client, catalog, make_doctor, auth_headers):
    cardiology = catalog.departments["cardiology"]
    ep, hf = catalog.specs["electrophysiology"], catalog.specs["heart-failure"]
    admin = await auth_headers(RoleCode.admin)
    rhythm = await make_doctor(name="Ep Rhythm", department=cardiology)
    failure = await make_doctor(name="Hf Pump", department=cardiology)
    await make_doctor(name="Plain Cardio", department=cardiology)
    for doctor, spec in ((rhythm, ep), (failure, hf)):
        r = await client.put(f"/api/v1/doctors/{doctor.id}/specializations", json={"specialization_ids": [str(spec.id)]}, headers=admin)
        assert r.status_code == 200, r.text

    async def names(**params):
        r = await client.get(PUBLIC_DOCTORS, params={"page_size": 50, **params})
        assert r.status_code == 200, r.text
        return sorted(d["name"] for d in r.json()["items"])

    assert await names(specializations=str(ep.id)) == ["Ep Rhythm"]
    assert await names(specializations=f"{ep.id},{hf.id}", department_id=str(cardiology.id)) == ["Ep Rhythm", "Hf Pump"]
    assert await names(specializations=str(catalog.specs["epilepsy"].id)) == []  # empty, not an error
    assert (await client.get(PUBLIC_DOCTORS, params={"specializations": "not-an-id"})).status_code == 422
    counts = {s["slug"]: s["doctor_count"] for s in (await client.get(PUBLIC_SPECS, params={"department_id": str(cardiology.id)})).json()}
    assert counts["electrophysiology"] == 1 and counts["heart-failure"] == 1 and counts["preventive-cardiology"] == 0


async def test_only_staff_assign_specializations_and_only_of_the_doctors_department(client, catalog, make_doctor, auth_headers):
    cardiology = catalog.departments["cardiology"]
    doctor = await make_doctor(name="Assign Me", department=cardiology)
    url = f"/api/v1/doctors/{doctor.id}/specializations"
    body = {"specialization_ids": [str(catalog.specs["heart-failure"].id)]}
    assert (await client.put(url, json=body, headers=await auth_headers(RoleCode.doctor))).status_code == 403
    assert (await client.put(url, json=body, headers=await auth_headers(RoleCode.patient))).status_code == 403
    admin = await auth_headers(RoleCode.admin)
    wrong = await client.put(url, json={"specialization_ids": [str(catalog.specs["epilepsy"].id)]}, headers=admin)
    assert wrong.status_code == 400 and wrong.json()["error"]["code"] == "SPECIALIZATION_NOT_IN_DEPARTMENT"
    ok = await client.put(url, json=body, headers=admin)
    assert [s["slug"] for s in ok.json()] == ["heart-failure"]
    # Moving the doctor drops the links the new department does not have.
    moved = await client.patch(f"/api/v1/doctors/{doctor.id}", json={"department_id": str(catalog.departments["neurology"].id)}, headers=admin)
    assert moved.status_code == 200, moved.text
    assert (await client.get(url, headers=admin)).json() == []


async def test_admins_manage_specializations_without_duplicate_names_or_aliases(client, catalog, auth_headers):
    admin = await auth_headers(RoleCode.admin)
    cardiology = str(catalog.departments["cardiology"].id)
    created = await client.post(ADMIN_SPECS, json={"name": "Cardio-Oncology", "aliases": ["Cardio oncologist"], "department_ids": [cardiology]}, headers=admin)
    assert created.status_code == 201, created.text
    assert created.json()["aliases"] == ["cardio oncologist"] and created.json()["department_ids"] == [cardiology]
    dup_name = await client.post(ADMIN_SPECS, json={"name": "general cardiology", "department_ids": [cardiology]}, headers=admin)
    assert dup_name.status_code == 409 and dup_name.json()["error"]["code"] == "SPECIALIZATION_EXISTS"
    dup_alias = await client.post(ADMIN_SPECS, json={"name": "Heart Doctors", "aliases": ["cardiologist"], "department_ids": [cardiology]}, headers=admin)
    assert dup_alias.status_code == 409 and dup_alias.json()["error"]["code"] == "ALIAS_TAKEN"
    spec_id = created.json()["id"]
    both = [cardiology, str(catalog.departments["hematology-oncology"].id)]
    edited = await client.patch(f"{ADMIN_SPECS}{spec_id}", json={"department_ids": both, "is_active": False}, headers=admin)
    assert sorted(edited.json()["department_ids"]) == sorted(both) and edited.json()["is_active"] is False
    public = [s["name"] for s in (await client.get(PUBLIC_SPECS, params={"department_id": cardiology})).json()]
    assert "Cardio-Oncology" not in public  # retired: hidden from the directory
    assert (await client.post(ADMIN_SPECS, json={"name": "X", "department_ids": [cardiology]}, headers=await auth_headers(RoleCode.doctor))).status_code == 403
    departments = (await client.get("/api/v1/departments/", params={"page_size": 100}, headers=admin)).json()["items"]
    card = next(d for d in departments if d["slug"] == "cardiology")
    assert card["specialization_count"] == 7  # the six catalog ones under Cardiology + Pediatric Cardiology; the retired one not counted


# ---- resolving people's words -----------------------------------------------------------------------


async def resolved(db, text):
    r = await catalog_service.resolve(db, text)
    return r, [s.name for s in r.specializations], [t.name for t in r.topics]


async def test_conditions_symptoms_and_specialty_words_resolve_to_the_catalog(db_session, catalog):
    r, specs, topics = await resolved(db_session, "Which doctor treats thyroid disease?")
    assert topics == ["Thyroid disease"] and specs[:2] == ["Thyroid Disorders", "General Endocrinology"]
    r, specs, topics = await resolved(db_session, "Show doctors who treat migraines")
    assert topics == ["Migraine"] and specs == ["Headache Medicine", "General Neurology"]
    r, specs, _ = await resolved(db_session, "Find a children's neurologist")
    assert specs[0] == "Pediatric Neurology" and r.specializations[0].via == "named"
    r, specs, topics = await resolved(db_session, "Who treats kidney stones?")
    assert topics == ["Kidney stones"] and specs[0] == "Endourology & Kidney Stones"
    assert "General Nephrology" in specs and [s.via for s in r.specializations if s.name == "General Nephrology"] == ["secondary"]
    r, specs, _ = await resolved(db_session, "find heart doctors")
    assert specs == ["General Cardiology"]
    r, _, topics = await resolved(db_session, "eczema on my hands")
    assert topics == ["Eczema"] and r.specializations[0].name == "Medical Dermatology"
    r, _, _ = await resolved(db_session, "ENT specialist please")
    assert r.specializations[0].name == "General ENT"
    r, _, _ = await resolved(db_session, "zzz nothing medical")
    assert not r.found


async def test_ambiguous_and_urgent_routing(db_session, catalog):
    r, _, _ = await resolved(db_session, "I keep feeling dizzy")
    assert r.ambiguous  # Neurology and ENT both commonly see it
    r, _, _ = await resolved(db_session, "dizziness, need a neurologist")
    assert not r.ambiguous  # a specialty was named
    r, _, _ = await resolved(db_session, "sudden chest pain")
    assert r.urgent
    r, _, _ = await resolved(db_session, "diabetes")
    assert not r.urgent and not r.ambiguous


# ---- the assistant's tool ---------------------------------------------------------------------------


async def search(db, **args):
    ctx = SimpleNamespace(last_doctor_ids=[], last_slots=[], last_slots_doctor_id=None)
    outcome = await tools._search_doctors(db, None, tools.SearchDoctorsArgs(**args), ctx)
    return outcome.result, ctx


async def test_assistant_finds_real_doctors_for_a_condition_most_experienced_first(db_session, catalog, make_doctor):
    endo = catalog.departments["endocrinology"]
    diabetes = catalog.specs["diabetes"]
    junior = await make_doctor(name="Junior Sugar", department=endo, years_of_experience=4)
    senior = await make_doctor(name="Senior Sugar", department=endo, years_of_experience=21)
    general = await make_doctor(name="General Endo", department=endo, years_of_experience=30)
    for d in (junior, senior):
        db_session.add(DoctorSpecialization(doctor_id=d.id, specialization_id=diabetes.id))
    await db_session.commit()

    result, ctx = await search(db_session, condition="diabetes", sort="most_experienced")
    names = [d["name"] for d in result["doctors"]]
    assert set(names) == {"Junior Sugar", "Senior Sugar", "General Endo"}  # department doctors too
    assert names == ["General Endo", "Senior Sugar", "Junior Sugar"]  # most experienced first
    reasons = {d["name"]: d["matched_by"] for d in result["doctors"]}
    assert reasons["Senior Sugar"] == "specialization: Diabetes" and reasons["General Endo"] == "department"
    assert result["understood"]["conditions"] == ["Diabetes"] and "not a diagnosis" in result["guidance"]
    assert ctx.last_doctor_ids == [general.id, senior.id, junior.id]  # kept for "book the first one"

    result, _ = await search(db_session, condition="thyroid problem")
    assert result["doctors"] and {d["department"] for d in result["doctors"]} == {"Endocrinology"}


async def test_assistant_sends_urgent_symptoms_to_emergency_care_not_booking(db_session, catalog, make_doctor):
    await make_doctor(name="Er Doc", department=catalog.departments["emergency-critical-care"])
    result, ctx = await search(db_session, condition="appendicitis pain")
    assert result["urgent"] is True and "doctors" not in result and ctx.last_doctor_ids == []


async def test_assistant_says_when_no_listed_doctor_fits(db_session, catalog):
    result, _ = await search(db_session, condition="glaucoma")
    assert result["doctors"] == [] and "Glaucoma" in result["note"]
