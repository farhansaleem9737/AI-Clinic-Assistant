"""The medical catalog (D118): seeding, specializations, doctor links, and
resolving a person's words ("thyroid problem", "children's neurologist") to
catalog entries.

Resolution only ever returns catalog rows (curated data, never model output),
and doctors are always looked up afterwards in the real directory.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from dataclasses import dataclass, field

from sqlalchemy import Text, cast, delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog import data
from app.core.config import settings
from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError
from app.core.permissions import Principal
from app.models.catalog import (
    DepartmentSpecialization,
    DoctorSpecialization,
    MedicalTopic,
    MedicalTopicSpecialization,
    Specialization,
)
from app.models.department import Department
from app.models.doctor import Doctor
from app.models.user import User
from app.services.audit_service import AuditAction, record
from app.services.search_text import simplify

logger = logging.getLogger(__name__)


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", simplify(text).replace("&", " and ")).strip("-")[:120] or "item"


def clean_aliases(values) -> list[str]:
    """Lower case, simplified, unique, in the given order; blanks dropped."""
    out: list[str] = []
    for value in values or ():
        alias = simplify(value)
        if alias and alias not in out:
            out.append(alias)
    return out


# ---- seeding ---------------------------------------------------------------------------


@dataclass
class SeedReport:
    departments_created: list[str] = field(default_factory=list)
    departments_matched: list[str] = field(default_factory=list)  # existing rows given the catalog slug
    specializations_created: int = 0
    department_links_created: int = 0
    topics_created: int = 0
    topic_links_created: int = 0
    doctor_links_created: list[tuple[str, str]] = field(default_factory=list)  # (doctor specialization text, catalog name)

    def as_dict(self) -> dict:
        return {
            "departments_created": self.departments_created,
            "departments_matched": self.departments_matched,
            "specializations_created": self.specializations_created,
            "department_links_created": self.department_links_created,
            "topics_created": self.topics_created,
            "topic_links_created": self.topic_links_created,
            "doctor_links_created": len(self.doctor_links_created),
        }


async def seed(db: AsyncSession, *, actor_id: uuid.UUID | None = None, commit: bool = True) -> SeedReport:
    """Load the reference catalog. Idempotent: run it any number of times.

    Never deletes, renames or merges anything. An existing department whose
    name is the catalog's name or one of its aliases ("General Medicine" for
    General & Family Medicine) becomes that catalog entry: it gets the slug,
    keeps its own name, description, icon and status. Existing
    specializations, topics and links are left as they are (an administrator
    may have edited them). Doctors are linked to a specialization only when
    the specialization text on their approved profile is exactly that
    specialization's name or alias, and it belongs to their department.
    """
    report = SeedReport()

    # A handful of round trips whatever the catalog's size: ids are made here,
    # rows are added together, and links go in one multi-row INSERT each.

    # Departments
    departments: dict[str, uuid.UUID] = {}
    existing = (await db.scalars(select(Department))).all()
    by_slug = {d.slug: d for d in existing if d.slug}
    by_name = {simplify(d.name): d for d in existing}
    new_rows: list = []
    for slug, name, aliases, icon, color, description in data.DEPARTMENTS:
        department = by_slug.get(slug)
        if department is None:
            names = [simplify(name), *clean_aliases(aliases)]
            department = next((by_name[n] for n in names if n in by_name and not by_name[n].slug), None)
            if department is not None:
                department.slug = slug
                department.aliases = department.aliases or clean_aliases(aliases)
                report.departments_matched.append(department.name)
            else:
                department = Department(
                    id=uuid.uuid7(), name=name, slug=slug, aliases=clean_aliases(aliases), description=description,
                    timezone=settings.clinic_timezone, icon=icon, color=color, is_active=True,
                )
                new_rows.append(department)
                report.departments_created.append(name)
            by_slug[slug] = department
        departments[slug] = department.id

    # Specializations
    specs: dict[str, uuid.UUID] = {}
    current = (await db.scalars(select(Specialization))).all()
    spec_by_slug = {x.slug: x for x in current}
    spec_by_name = {simplify(x.name): x for x in current}
    for slug, name, _, aliases in data.SPECIALIZATIONS:
        spec = spec_by_slug.get(slug) or spec_by_name.get(simplify(name))
        if spec is None:
            spec = Specialization(id=uuid.uuid7(), name=name, slug=slug, aliases=clean_aliases(aliases), is_active=True)
            new_rows.append(spec)
            report.specializations_created += 1
            spec_by_slug[slug] = spec
        specs[slug] = spec.id

    # Conditions and symptoms
    topics: dict[str, uuid.UUID] = {}
    topic_rows = {t.slug: t for t in (await db.scalars(select(MedicalTopic))).all()}
    for slug, name, topic_type, aliases, _, urgent in data.TOPICS:
        topic = topic_rows.get(slug)
        if topic is None:
            topic = MedicalTopic(
                id=uuid.uuid7(), canonical_name=name, slug=slug, topic_type=topic_type,
                aliases=clean_aliases(aliases), urgent=urgent, is_active=True,
            )
            new_rows.append(topic)
            report.topics_created += 1
        topics[slug] = topic.id
    db.add_all(new_rows)
    await db.flush()

    # Links: only the missing ones, one statement per table.
    have = set((await db.execute(select(DepartmentSpecialization.department_id, DepartmentSpecialization.specialization_id))).all())
    wanted = list(dict.fromkeys(
        (departments[d], specs[slug]) for slug, _, department_slugs, _ in data.SPECIALIZATIONS for d in department_slugs
    ))
    missing = [{"department_id": d, "specialization_id": x} for d, x in wanted if (d, x) not in have]
    if missing:
        await db.execute(insert(DepartmentSpecialization).values(missing).on_conflict_do_nothing())
    report.department_links_created = len(missing)

    have = set((await db.execute(select(MedicalTopicSpecialization.topic_id, MedicalTopicSpecialization.specialization_id))).all())
    missing, seen = [], set()
    for slug, _, _, _, links, _ in data.TOPICS:
        for spec_slug, relevance in links:
            key = (topics[slug], specs[spec_slug])
            if key in have or key in seen:
                continue
            seen.add(key)
            missing.append({"topic_id": key[0], "specialization_id": key[1], "relevance": relevance, "source": data.SOURCE, "review_status": "curated"})
    if missing:
        await db.execute(insert(MedicalTopicSpecialization).values(missing).on_conflict_do_nothing())
    report.topic_links_created = len(missing)

    # Doctors: only from the exact specialization text on their profile.
    report.doctor_links_created = await _link_doctors_from_profiles(db)

    if report.departments_created or report.specializations_created or report.topics_created or report.doctor_links_created:
        record(db, AuditAction.catalog_seeded, actor_id=actor_id, target_type="catalog", target_id=None, details=report.as_dict())
    if commit:
        await db.commit()
    invalidate()
    logger.info("catalog_seeded", extra=report.as_dict())
    return report


async def _link_doctors_from_profiles(db: AsyncSession) -> list[tuple[str, str]]:
    allowed = set(
        (await db.execute(select(DepartmentSpecialization.department_id, DepartmentSpecialization.specialization_id))).all()
    )
    names: dict[str, Specialization] = {}
    for spec in (await db.scalars(select(Specialization).where(Specialization.is_active.is_(True)))).all():
        for phrase in [simplify(spec.name), *spec.aliases]:
            names.setdefault(phrase, spec)
    linked = {(d, s) for d, s in (await db.execute(select(DoctorSpecialization.doctor_id, DoctorSpecialization.specialization_id))).all()}
    created: list[tuple[str, str]] = []
    for doctor_id, department_id, text in (await db.execute(select(Doctor.id, Doctor.department_id, Doctor.specialization))).all():
        spec = names.get(simplify(text))
        if spec is None or (department_id, spec.id) not in allowed or (doctor_id, spec.id) in linked:
            continue
        db.add(DoctorSpecialization(doctor_id=doctor_id, specialization_id=spec.id))
        created.append((text, spec.name))
    await db.flush()
    return created


# ---- reading -------------------------------------------------------------------------------


@dataclass(frozen=True)
class SpecializationRow:
    specialization: Specialization
    department_ids: list[uuid.UUID]
    doctor_count: int


def _practising_public():
    return (Doctor.is_active.is_(True), User.is_active.is_(True), Department.is_active.is_(True))


async def list_specializations(
    db: AsyncSession,
    *,
    department_id: uuid.UUID | None = None,
    q: str | None = None,
    active_only: bool = True,
    public_counts: bool = True,
) -> list[SpecializationRow]:
    """Specializations by name, optionally of one department, each with its
    departments and the number of doctors linked to it (publicly listed ones
    for the directory, every doctor profile for staff). Three queries."""
    query = select(Specialization).order_by(func.lower(Specialization.name), Specialization.id)
    if active_only:
        query = query.where(Specialization.is_active.is_(True))
    if department_id is not None:
        query = query.join(DepartmentSpecialization, DepartmentSpecialization.specialization_id == Specialization.id).where(
            DepartmentSpecialization.department_id == department_id
        )
    if q and q.strip():
        pattern = f"%{simplify(q)}%"
        query = query.where(
            func.lower(Specialization.name).like(pattern) | cast(Specialization.aliases, Text).ilike(pattern)
        )
    specs = (await db.scalars(query)).all()
    if not specs:
        return []
    ids = [s.id for s in specs]
    departments: dict[uuid.UUID, list[uuid.UUID]] = {i: [] for i in ids}
    for dep_id, spec_id in (
        await db.execute(
            select(DepartmentSpecialization.department_id, DepartmentSpecialization.specialization_id).where(
                DepartmentSpecialization.specialization_id.in_(ids)
            )
        )
    ).all():
        departments[spec_id].append(dep_id)
    counts_query = (
        select(DoctorSpecialization.specialization_id, func.count(DoctorSpecialization.doctor_id))
        .join(Doctor, Doctor.id == DoctorSpecialization.doctor_id)
        .where(DoctorSpecialization.specialization_id.in_(ids))
        .group_by(DoctorSpecialization.specialization_id)
    )
    if public_counts:
        counts_query = (
            counts_query.join(User, User.id == Doctor.user_id)
            .join(Department, Department.id == Doctor.department_id)
            .where(*_practising_public())
        )
        if department_id is not None:
            counts_query = counts_query.where(Doctor.department_id == department_id)
    counts = dict((await db.execute(counts_query)).all())
    return [SpecializationRow(s, departments[s.id], counts.get(s.id, 0)) for s in specs]


async def specialization_counts(db: AsyncSession, department_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    """Active specializations per department, for the department lists."""
    if not department_ids:
        return {}
    rows = await db.execute(
        select(DepartmentSpecialization.department_id, func.count())
        .join(Specialization, Specialization.id == DepartmentSpecialization.specialization_id)
        .where(DepartmentSpecialization.department_id.in_(department_ids), Specialization.is_active.is_(True))
        .group_by(DepartmentSpecialization.department_id)
    )
    return dict(rows.all())


async def doctor_specializations(db: AsyncSession, doctor_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[Specialization]]:
    """Each doctor's catalog specializations, by name: one query for the list."""
    if not doctor_ids:
        return {}
    rows = await db.execute(
        select(DoctorSpecialization.doctor_id, Specialization)
        .join(Specialization, Specialization.id == DoctorSpecialization.specialization_id)
        .where(DoctorSpecialization.doctor_id.in_(doctor_ids))
        .order_by(func.lower(Specialization.name))
    )
    out: dict[uuid.UUID, list[Specialization]] = {i: [] for i in doctor_ids}
    for doctor_id, spec in rows.all():
        out[doctor_id].append(spec)
    return out


# ---- administration --------------------------------------------------------------------------


async def _check_unique(db: AsyncSession, name: str, aliases: list[str], exclude_id: uuid.UUID | None = None) -> None:
    """No two specializations share a name, and no alias is another one's name or alias."""
    others = (await db.scalars(select(Specialization).where(Specialization.id != exclude_id) if exclude_id else select(Specialization))).all()
    taken: dict[str, str] = {}
    for other in others:
        for phrase in [simplify(other.name), *other.aliases]:
            taken.setdefault(phrase, other.name)
    if simplify(name) in taken:
        raise ConflictError(f"“{name}” is already in the catalog as {taken[simplify(name)]}", code="SPECIALIZATION_EXISTS")
    for alias in aliases:
        if alias in taken:
            raise ConflictError(f"The alias “{alias}” already belongs to {taken[alias]}", code="ALIAS_TAKEN")


async def _set_departments(db: AsyncSession, spec_id: uuid.UUID, department_ids: list[uuid.UUID]) -> None:
    ids = list(dict.fromkeys(department_ids))
    if not ids:
        raise BusinessRuleError("Choose at least one department", code="DEPARTMENT_REQUIRED")
    found = set((await db.scalars(select(Department.id).where(Department.id.in_(ids)))).all())
    if missing := [i for i in ids if i not in found]:
        raise NotFoundError(f"Department not found: {missing[0]}")
    await db.execute(
        delete(DepartmentSpecialization).where(
            DepartmentSpecialization.specialization_id == spec_id, DepartmentSpecialization.department_id.not_in(ids)
        )
    .execution_options(synchronize_session=False))
    for department_id in ids:
        await db.execute(
            insert(DepartmentSpecialization).values(department_id=department_id, specialization_id=spec_id).on_conflict_do_nothing()
        )


async def get_specialization(db: AsyncSession, spec_id: uuid.UUID) -> SpecializationRow:
    spec = await db.get(Specialization, spec_id)
    if spec is None:
        raise NotFoundError("Specialization not found")
    rows = await list_specializations(db, active_only=False, public_counts=False)
    return next(r for r in rows if r.specialization.id == spec_id)


async def create_specialization(db: AsyncSession, principal: Principal, data_in) -> SpecializationRow:
    aliases = clean_aliases(data_in.aliases)
    await _check_unique(db, data_in.name, aliases)
    slug, n = slugify(data_in.name), 1
    while await db.scalar(select(Specialization.id).where(Specialization.slug == slug)):
        n += 1
        slug = f"{slugify(data_in.name)[:110]}-{n}"
    spec = Specialization(name=data_in.name, slug=slug, description=data_in.description, aliases=aliases, is_active=data_in.is_active)
    db.add(spec)
    await db.flush()
    await _set_departments(db, spec.id, data_in.department_ids)
    spec_id = spec.id
    record(db, AuditAction.specialization_created, actor_id=principal.user_id, target_type="specialization", target_id=spec_id,
           details={"name": spec.name, "departments": [str(d) for d in data_in.department_ids]})
    await db.commit()
    invalidate()
    return await get_specialization(db, spec_id)


async def update_specialization(db: AsyncSession, principal: Principal, spec_id: uuid.UUID, data_in) -> SpecializationRow:
    spec = await db.get(Specialization, spec_id)
    if spec is None:
        raise NotFoundError("Specialization not found")
    changes = data_in.model_dump(exclude_unset=True)
    name = changes.get("name") or spec.name
    aliases = clean_aliases(changes["aliases"]) if "aliases" in changes else spec.aliases
    await _check_unique(db, name, aliases, exclude_id=spec.id)
    if changes.get("is_active") is False and await db.scalar(
        select(func.count()).select_from(DoctorSpecialization).where(DoctorSpecialization.specialization_id == spec.id)
    ):
        # Kept on the doctors who have it: retiring only hides it from new choices and filters.
        logger.info("specialization_retired_with_doctors", extra={"specialization_id": str(spec.id)})
    spec.name, spec.aliases = name, aliases
    if "description" in changes:
        spec.description = changes["description"]
    if changes.get("is_active") is not None:
        spec.is_active = changes["is_active"]
    if changes.get("department_ids") is not None:
        await _set_departments(db, spec.id, changes["department_ids"])
    record(db, AuditAction.specialization_updated, actor_id=principal.user_id, target_type="specialization", target_id=spec_id,
           details={k: (v if not isinstance(v, list) else [str(x) for x in v]) for k, v in changes.items()})
    await db.commit()
    invalidate()
    return await get_specialization(db, spec_id)


async def set_doctor_specializations(
    db: AsyncSession, principal: Principal, doctor_id: uuid.UUID, specialization_ids: list[uuid.UUID]
) -> list[Specialization]:
    """Replace a doctor's catalog specializations (authorised staff only).
    Each must be active and belong to the doctor's department."""
    doctor = await db.get(Doctor, doctor_id)
    if doctor is None:
        raise NotFoundError("Doctor not found")
    ids = list(dict.fromkeys(specialization_ids))
    allowed = set(
        (
            await db.scalars(
                select(DepartmentSpecialization.specialization_id)
                .join(Specialization, Specialization.id == DepartmentSpecialization.specialization_id)
                .where(DepartmentSpecialization.department_id == doctor.department_id, Specialization.is_active.is_(True))
            )
        ).all()
    )
    current = set((await db.scalars(select(DoctorSpecialization.specialization_id).where(DoctorSpecialization.doctor_id == doctor_id))).all())
    # A retired or moved specialization the doctor already has may stay; new ones must fit.
    if bad := [i for i in ids if i not in allowed and i not in current]:
        raise BusinessRuleError(
            "Choose specializations of the doctor's department", code="SPECIALIZATION_NOT_IN_DEPARTMENT",
            details={"specialization_ids": [str(b) for b in bad]},
        )
    await db.execute(delete(DoctorSpecialization).where(DoctorSpecialization.doctor_id == doctor_id, DoctorSpecialization.specialization_id.not_in(ids)).execution_options(synchronize_session=False))
    for spec_id in ids:
        if spec_id not in current:
            db.add(DoctorSpecialization(doctor_id=doctor_id, specialization_id=spec_id))
    if set(ids) != current:
        record(db, AuditAction.doctor_specializations_changed, actor_id=principal.user_id, target_type="doctor", target_id=doctor_id,
               details={"added": [str(i) for i in ids if i not in current], "removed": [str(i) for i in current if i not in ids]})
    await db.commit()
    return (await doctor_specializations(db, [doctor_id]))[doctor_id]


async def drop_links_outside_department(db: AsyncSession, doctor_id: uuid.UUID, department_id: uuid.UUID) -> None:
    """After a doctor moves department: links that do not fit the new one go
    (the caller commits and audits the move)."""
    fits = select(DepartmentSpecialization.specialization_id).where(DepartmentSpecialization.department_id == department_id)
    await db.execute(
        delete(DoctorSpecialization).where(DoctorSpecialization.doctor_id == doctor_id, DoctorSpecialization.specialization_id.not_in(fits))
    .execution_options(synchronize_session=False))


# ---- resolving a person's words ------------------------------------------------------------------

_CACHE_SECONDS = 300
_cache: dict = {"at": 0.0, "index": None}


def invalidate() -> None:
    _cache["index"] = None


@dataclass(frozen=True)
class _Entry:
    phrase: str
    kind: str  # "specialization" | "department" | "topic"
    id: uuid.UUID


@dataclass
class _Index:
    entries: list[_Entry]
    specializations: dict[uuid.UUID, tuple[str, list[uuid.UUID]]]  # id -> (name, department ids)
    departments: dict[uuid.UUID, str]
    topics: dict[uuid.UUID, tuple[str, str, bool, list[tuple[uuid.UUID, str]]]]  # id -> (name, type, urgent, links)


_KIND_ORDER = {"specialization": 0, "department": 1, "topic": 2}


async def _index(db: AsyncSession) -> _Index:
    if _cache["index"] is not None and time.monotonic() - _cache["at"] < _CACHE_SECONDS:
        return _cache["index"]
    entries: list[_Entry] = []
    specs: dict = {}
    for spec in (await db.scalars(select(Specialization).where(Specialization.is_active.is_(True)))).all():
        specs[spec.id] = (spec.name, [])
        entries += [_Entry(p, "specialization", spec.id) for p in {simplify(spec.name), *spec.aliases}]
    for dep_id, spec_id in (await db.execute(select(DepartmentSpecialization.department_id, DepartmentSpecialization.specialization_id))).all():
        if spec_id in specs:
            specs[spec_id][1].append(dep_id)
    departments: dict = {}
    for dep in (await db.scalars(select(Department).where(Department.is_active.is_(True)))).all():
        departments[dep.id] = dep.name
        entries += [_Entry(p, "department", dep.id) for p in {simplify(dep.name), *dep.aliases}]
    topics: dict = {}
    for topic in (await db.scalars(select(MedicalTopic).where(MedicalTopic.is_active.is_(True)))).all():
        topics[topic.id] = (topic.canonical_name, topic.topic_type, topic.urgent, [])
        entries += [_Entry(p, "topic", topic.id) for p in {simplify(topic.canonical_name), *topic.aliases}]
    for topic_id, spec_id, relevance in (
        await db.execute(select(MedicalTopicSpecialization.topic_id, MedicalTopicSpecialization.specialization_id, MedicalTopicSpecialization.relevance))
    ).all():
        if topic_id in topics and spec_id in specs:
            topics[topic_id][3].append((spec_id, relevance))
    entries = [e for e in entries if e.phrase]
    entries.sort(key=lambda e: (-len(e.phrase), _KIND_ORDER[e.kind]))
    index = _Index(entries, specs, departments, topics)
    _cache.update(at=time.monotonic(), index=index)
    return index


@dataclass(frozen=True)
class SpecializationMatch:
    id: uuid.UUID
    name: str
    via: str  # "named" (the person named it) | "primary" | "secondary" (from a condition)
    department_ids: tuple[uuid.UUID, ...]


@dataclass(frozen=True)
class TopicMatch:
    id: uuid.UUID
    name: str
    topic_type: str
    urgent: bool


@dataclass
class Resolution:
    topics: list[TopicMatch] = field(default_factory=list)
    specializations: list[SpecializationMatch] = field(default_factory=list)
    departments: list[tuple[uuid.UUID, str]] = field(default_factory=list)  # named by the person

    @property
    def found(self) -> bool:
        return bool(self.topics or self.specializations or self.departments)

    @property
    def urgent(self) -> bool:
        return any(t.urgent for t in self.topics)

    def ids(self, *vias: str) -> list[uuid.UUID]:
        return [s.id for s in self.specializations if s.via in vias]

    def department_ids(self) -> list[uuid.UUID]:
        """Departments named, then those of the named or primary specializations."""
        out = [d for d, _ in self.departments]
        for s in self.specializations:
            if s.via in ("named", "primary"):
                out += [d for d in s.department_ids if d not in out]
        return list(dict.fromkeys(out))

    @property
    def ambiguous(self) -> bool:
        """Only conditions or symptoms were recognised, and their main
        specializations sit in more than one department."""
        if self.departments or any(s.via == "named" for s in self.specializations):
            return False
        primary_departments = {d for s in self.specializations if s.via == "primary" for d in s.department_ids}
        return len(primary_departments) > 1


def _word_char(c: str) -> bool:
    """A character that continues a word: ASCII lowercase letters and digits,
    and any non-ASCII character in the Basic Multilingual Plane."""
    return "a" <= c <= "z" or "0" <= c <= "9" or "\u0080" <= c <= "￿"


def _find(text: str, phrase: str) -> tuple[int, int] | None:
    """The first whole-word occurrence of the phrase (or its plural) in text.

    Plain string search on purpose (D132). This runs for every catalog phrase
    on every doctor search, on the event loop. It used to build a regular
    expression per phrase, and with more phrases than re's cache holds, every
    search recompiled all of them. On a 0.1-CPU instance that took minutes
    and froze the server until the platform restarted it. Same matches as the
    old pattern: (?<![a-z0-9\\u0080-\\uffff])phrase(?![a-z0-9\\u0080-\\uffff]).
    """
    for candidate in (phrase, phrase + "s", phrase + "es"):
        size = len(candidate)
        start = text.find(candidate)
        while start != -1:
            end = start + size
            if (start == 0 or not _word_char(text[start - 1])) and (end == len(text) or not _word_char(text[end])):
                return start, end
            start = text.find(candidate, start + 1)
    return None


async def resolve(db: AsyncSession, text: str | None) -> Resolution:
    """Catalog entries a person's words name: specializations ("cardiologist",
    "child neurologist"), departments ("heart", "ENT") and conditions or
    symptoms ("thyroid problem", "migraines"). Longest phrases win, and a word
    is used once ("kidney stones" is the condition, not also "kidney")."""
    result = Resolution()
    plain = simplify(text)
    if not plain:
        return result
    index = await _index(db)
    taken: list[tuple[int, int]] = []
    named_specs: list[uuid.UUID] = []
    topic_ids: list[uuid.UUID] = []
    for entry in index.entries:
        span = _find(plain, entry.phrase)
        # A word is used once, except that the very same words may name both a
        # specialization and a condition ("diabetes"): both count.
        if span is None or any(span[0] < end and start < span[1] and (start, end) != span for start, end in taken):
            continue
        taken.append(span)
        if entry.kind == "specialization" and entry.id not in named_specs:
            named_specs.append(entry.id)
        elif entry.kind == "department" and entry.id not in [d for d, _ in result.departments]:
            result.departments.append((entry.id, index.departments[entry.id]))
        elif entry.kind == "topic" and entry.id not in topic_ids:
            topic_ids.append(entry.id)

    seen: set[uuid.UUID] = set()

    def add(spec_id: uuid.UUID, via: str) -> None:
        if spec_id in seen:
            return
        seen.add(spec_id)
        name, deps = index.specializations[spec_id]
        result.specializations.append(SpecializationMatch(spec_id, name, via, tuple(deps)))

    for spec_id in named_specs:
        add(spec_id, "named")
    for topic_id in topic_ids:
        name, topic_type, urgent, _ = index.topics[topic_id]
        result.topics.append(TopicMatch(topic_id, name, topic_type, urgent))
    for relevance in ("primary", "secondary"):
        for topic_id in topic_ids:
            for spec_id, rel in index.topics[topic_id][3]:
                if rel == relevance:
                    add(spec_id, relevance)
    # A department named alongside a condition narrows it ("diabetes in children"
    # -> Pediatric Endocrinology first): keep the specializations of that department first.
    if result.departments and topic_ids:
        named_departments = {d for d, _ in result.departments}
        result.specializations.sort(key=lambda s: (not set(s.department_ids) & named_departments, s.via != "named"))
    return result
