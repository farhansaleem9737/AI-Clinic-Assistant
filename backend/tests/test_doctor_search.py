"""Doctor search ignores case, spacing, punctuation and the Dr./Doctor title,
ranks the best name matches first and tolerates small typos (D114)."""

import pytest
from sqlalchemy import literal, select

from app.core.permissions import RoleCode
from app.services.search_text import contains_pattern, normalize, normalized_sql, titled_name

PUBLIC = "/api/v1/public/doctors/"
STAFF = "/api/v1/doctors/"
SEARCH = "/api/v1/search"

QUERIES = [
    "Dr. Sarah Khan", "dr sarah khan", "DR SARAH KHAN", "Dr Sarah Khan", "Doctor Sarah Khan",
    "doctor sarah khan", "Sarah Khan", "sarah khan", "SARAH KHAN", "sarah   khan", "Dr.Sarah Khan",
    "sarah", "khan", "sarah kh", "sara khan", "sarah kahn", "khan sarah", "  dr.  sarah   khan  ",
]


@pytest.fixture
async def sarah(make_department, make_doctor):
    """Dr. Sarah Khan (title stored separately, as the app does) and an unrelated doctor."""
    department = await make_department("Search Cardiology")
    doctor = await make_doctor(name="Sarah Khan", title="Dr.", department=department, specialization="Cardiologist")
    await make_doctor(name="Imran Qureshi", department=department, specialization="Cardiologist")
    return doctor


async def search(client, q, url=PUBLIC, headers=None, **params):
    response = await client.get(url, params={"q": q, "page_size": 50, **params}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def found(client, q, **kw) -> list[str]:
    return [d["name"] for d in (await search(client, q, **kw))["items"]]


# ---- the reported bug and its variants -------------------------------------------------


@pytest.mark.parametrize("q", QUERIES)
async def test_every_way_of_writing_the_name_finds_dr_sarah_khan(client, sarah, q):
    names = await found(client, q)
    assert "Sarah Khan" in names, q
    assert names[0] == "Sarah Khan", q  # best match first
    assert "Imran Qureshi" not in names, q


async def test_a_title_stored_inside_the_name_is_matched_and_shown_as_stored(client, make_doctor):
    await make_doctor(name="Dr. Hina Baig", title=None)
    for q in ("hina baig", "dr hina baig", "Doctor Hina Baig", "Dr.Hina Baig"):
        assert await found(client, q) == ["Dr. Hina Baig"], q


# ---- normalization ------------------------------------------------------------------------


def test_normalize_rules():
    assert normalize("  Dr.Sarah   KHAN ") == "sarah khan"
    assert normalize("Doctor sarah khan") == "sarah khan"
    assert normalize("doctor") == "doctor"  # a lone word is a search, not a title
    assert normalize("Doctorow Smith") == "doctorow smith"  # only the whole word "dr"/"doctor"
    assert normalize("Sarah Doctor") == "sarah doctor"  # never stripped after the first word
    assert normalize("O'Brien") == "obrien" and normalize("Abdul-Rahman") == "abdul rahman"
    assert normalize("%_") == "" and normalize(None) == ""
    assert normalize("Dr. محمد علی") == "محمد علی"
    assert titled_name("Dr.", "Sarah Khan") == "Dr. Sarah Khan"
    assert titled_name("Dr.", "Dr. Sarah Khan") == "Dr. Sarah Khan"  # not doubled
    assert titled_name(None, "Sarah Khan") == "Sarah Khan"
    assert contains_pattern("50%_off\\") == "%50\\%\\_off\\\\%"


@pytest.mark.parametrize(
    "text",
    ["Dr. Sarah Khan", "  Dr.Sarah   KHAN ", "Doctor Who", "doctor", "O'Brien-Smith", "a_b%c", "Dr. محمد علی", "Ali\tRaza\n"],
)
async def test_sql_and_python_normalize_the_same_way(db_session, text):
    assert await db_session.scalar(select(normalized_sql(literal(text)))) == normalize(text)


# ---- ranking, typos, edge cases ---------------------------------------------------------


async def test_exact_then_prefix_then_word_then_partial(client, make_department, make_doctor):
    department = await make_department("Rank Dept")
    for name in ("Hasarah Iqbal", "Ali Sarahan", "Sarah Khanum", "Sarah Khan"):
        await make_doctor(name=name, department=department, specialization="Rank")
    assert await found(client, "sarah khan") == ["Sarah Khan", "Sarah Khanum"]
    # exact/prefix, then a later word starting with it, then inside a word
    assert await found(client, "sarah") == ["Sarah Khan", "Sarah Khanum", "Ali Sarahan", "Hasarah Iqbal"]


async def test_typos_are_tolerated_only_when_nothing_else_matches(client, sarah, make_doctor):
    assert await found(client, "sarah kahn") == ["Sarah Khan"]  # typo fallback
    await make_doctor(name="Sarah Kahn")
    assert await found(client, "sarah kahn") == ["Sarah Kahn"]  # a real match wins; no fuzzy extras


async def test_unrelated_queries_find_nothing(client, sarah):
    for q in ("john smith", "zzzz", "%", "_", "\\", "'", "--", "Dr."):
        body = await search(client, q)
        assert "Sarah Khan" not in [d["name"] for d in body["items"]], q


async def test_doctor_inside_a_name_is_not_treated_as_a_title(client, make_doctor):
    await make_doctor(name="Lina Doctorova")
    assert await found(client, "doctorova") == ["Lina Doctorova"]
    assert "Lina Doctorova" in await found(client, "doctor")
    assert await found(client, "doctor lina") == ["Lina Doctorova"]


async def test_non_latin_names(client, make_doctor):
    await make_doctor(name="محمد علی")
    await make_doctor(name="Ольга Петрова")
    assert await found(client, "Dr. محمد علی") == ["محمد علی"]
    assert await found(client, "ольга петрова") == ["Ольга Петрова"]


async def test_several_matches_are_paginated_in_rank_order(client, make_department, make_doctor):
    department = await make_department("Page Dept")
    for name in ("Zain Malik", "Amna Malik", "Malika Shah", "Omar Malikzada"):
        await make_doctor(name=name, department=department, specialization="Paging")
    pages = [await search(client, "dr malik", page=p, page_size=2) for p in (1, 2)]
    assert pages[0]["total"] == 4
    order = [d["name"] for page in pages for d in page["items"]]
    # "Malika Shah" starts with the query; the rest have a later word starting with it (ties by name)
    assert order == ["Malika Shah", "Amna Malik", "Omar Malikzada", "Zain Malik"]


async def test_an_explicit_sort_is_kept(client, make_department, make_doctor):
    department = await make_department("Sort Dept")
    await make_doctor(name="Sarah Khan", department=department, years_of_experience=3)
    await make_doctor(name="Sarah Khanum", department=department, years_of_experience=20)
    assert await found(client, "sarah khan", sort="experience_desc") == ["Sarah Khanum", "Sarah Khan"]


# ---- every entry point, and who may see what -------------------------------------------


async def test_inactive_doctors_stay_hidden_from_the_public_search(client, make_doctor, auth_headers):
    await make_doctor(name="Sarah Khan", title="Dr.", is_active=False)
    assert await found(client, "dr sarah khan") == []
    admin = await auth_headers(RoleCode.admin)
    assert await found(client, "dr sarah khan", url=STAFF, headers=admin) == ["Sarah Khan"]
    assert (await client.get(STAFF, params={"q": "dr sarah khan"})).status_code == 401


async def test_global_search_finds_the_doctor_with_department(client, sarah, auth_headers):
    patient = await auth_headers(RoleCode.patient)
    body = (await client.get(SEARCH, params={"q": "dr sarah khan"}, headers=patient)).json()
    assert body["doctors"] == [
        {"id": str(sarah.id), "name": "Dr. Sarah Khan", "specialization": "Cardiologist", "department_name": "Search Cardiology"}
    ]


async def test_appointment_search_finds_the_doctor_however_written(client, clinic):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    starts = clinic.slot(2, "10:00").isoformat().replace("+00:00", "Z")
    booked = await client.post("/api/v1/appointments/", json={"doctor_id": str(clinic.doctor_a.id), "starts_at": starts}, headers=alice)
    assert booked.status_code == 201, booked.text
    reception = await clinic.headers_for(clinic.receptionist.id)
    for q in ("dr. alpha", "Doctor   ALPHA", "alpha"):  # the fixture's doctor is "Doctor Alpha"
        body = (await client.get(SEARCH, params={"q": q}, headers=reception)).json()
        assert len(body["appointments"]) == 1, q
