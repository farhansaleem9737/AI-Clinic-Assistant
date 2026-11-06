"""Assistant tools for documents in the patient record (D101, v2 D102).

Access: every lookup goes through document_service with the signed-in
user's own Principal, so the record's rules apply unchanged (patients their
own documents; doctors only through one of their appointments; reception
and administrators nothing). A guessed id is "not found". Authorization is
re-checked on every call, including follow-ups about the active document.

Extraction: documents are read on this server (medical_reports) only when
a tool is called, and each file is extracted once per content hash and
extraction version (an in-process cache). A new extraction version never
reuses older results; nothing is persisted.

Questions: `focus` says what the user asked (summary, conditions,
symptoms, measurements, abnormal, follow-up); the card leads with that part
and the model answers that question. The conversation's active document
(the last one read) is used when the user says "it" / "that report".

Privacy: the model receives a document's extracted findings only when the
provider is approved for patient data (AI_PHI_ALLOWED), or when
AI_ALLOW_SYNTHETIC_DOCUMENTS is on and the document itself declares it is
synthetic / fictional test data. Otherwise it gets ids and counts only, and
the server's own extraction is what the user sees.
"""

import logging
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from fastapi.concurrency import run_in_threadpool
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import DomainError, NotFoundError
from app.core.permissions import Perm, Principal
from app.core.storage import Storage, StorageError
from app.models.patient_document import PatientDocument
from app.services import appointment_service, document_service, patient_service
from app.services.ai import medical_reports

logger = logging.getLogger(__name__)

MAX_DOCUMENTS_PER_SUMMARY = 10
MAX_FILE_BYTES = 20 * 1024 * 1024
CACHE_SIZE = 64
TYPE_LABELS = {
    "lab_report": "Lab report",
    "imaging": "Imaging report",
    "prescription": "Prescription",
    "referral": "Referral",
    "discharge_summary": "Discharge summary",
    "other": "Other document",
}
WITHHELD = (
    "The contents were not shared with you: the configured AI service is not approved for this patient data. "
    "Do not guess, repeat or interpret any values, names or diagnoses. Say the findings the user asked about are "
    "shown below, read directly from the document by the clinic's system, and suggest discussing them with their doctor."
)
TypeName = Literal["lab_report", "imaging", "prescription", "referral", "discharge_summary", "other"]
Focus = Literal["summary", "conditions", "symptoms", "measurements", "abnormal", "follow_up"]
Which = Literal["active", "latest_upload", "latest_report_date"]


@dataclass
class ToolContext:
    """Per-request context for tools: file storage, the conversation's active
    document and the appointments last shown (D103). Ids only: every use
    re-reads the records with the caller's own access rules."""

    storage: Storage | None = None
    active_document_id: uuid.UUID | None = None
    last_appointment_ids: list[uuid.UUID] = field(default_factory=list)
    # Doctors last listed, in the order shown ("the second one", "the most experienced").
    last_doctor_ids: list[uuid.UUID] = field(default_factory=list)
    # Free slots last shown and their doctor ("the earliest one", "take the 5 pm").
    last_slots: list[dict] = field(default_factory=list)
    last_slots_doctor_id: uuid.UUID | None = None


def _args_base():
    # Imported here to avoid a cycle with tools.py, which imports this module.
    from app.services.ai.tools import _Args

    return _Args


class _Scoped(_args_base()):
    appointment_id: uuid.UUID | None = Field(
        default=None, description="Doctors only: one of your appointments, to reach that patient's documents"
    )


class ListDocumentsArgs(_Scoped):
    document_type: TypeName | None = None


class ExplainDocumentArgs(_Scoped):
    document_id: uuid.UUID | None = Field(default=None, description="A document_id from list_medical_documents")
    which: Which | None = Field(
        default=None,
        description="Without document_id: 'active' = the document this conversation is about (for 'it', 'that report'); "
        "'latest_upload' = most recently uploaded; 'latest_report_date' = newest report date. Default: active, else latest_upload.",
    )
    document_type: TypeName | None = Field(default=None, description="With latest_*: only this type")
    focus: Focus = Field(
        default="summary",
        description="What the user asked: summary, conditions (disease/diagnosis), symptoms, measurements (the full test table), "
        "abnormal (results outside range), follow_up (recommendations)",
    )


class SummarizeDocumentsArgs(_Scoped):
    document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=MAX_DOCUMENTS_PER_SUMMARY,
                                          description="Documents to summarise or compare; empty = all (most recent first)")
    document_type: TypeName | None = None


# ---- lookups (always through document_service, with the caller's Principal) ------------------


async def _patient_id(db: AsyncSession, principal: Principal, appointment_id: uuid.UUID | None) -> uuid.UUID:
    """Whose record: a doctor's appointment (visibility-checked), else the caller's own."""
    if appointment_id is not None:
        view = await appointment_service.get_view(db, principal, appointment_id)
        return view.appointment.patient_id
    if principal.patient_id is None:
        raise NotFoundError("No patient record to look in. Doctors: name one of your appointments.")
    return principal.patient_id


def _by_upload(rows):
    return sorted(rows, key=lambda d: (d.created_at, d.id), reverse=True)


def _by_report_date(rows):
    return sorted(rows, key=lambda d: (d.document_date or d.created_at.date(), d.created_at), reverse=True)


async def _documents(db, principal, a) -> list[PatientDocument]:
    """Newest upload first."""
    patient_id = await _patient_id(db, principal, a.appointment_id)
    rows = await document_service.list_document(db, principal, patient_id)
    wanted = getattr(a, "document_type", None)
    return _by_upload([d for d in rows if wanted is None or d.document_type.value == wanted])


def _meta(d: PatientDocument) -> dict:
    return {
        "document_id": str(d.id),
        "patient_id": str(d.patient_id),
        "title": d.title,
        "type": d.document_type.value,
        "type_label": TYPE_LABELS[d.document_type.value],
        "report_date": d.document_date.isoformat() if d.document_date else None,
        "uploaded": d.created_at.date().isoformat(),
        "uploaded_at": d.created_at.isoformat(),
        "file_type": "PDF" if d.file.content_type == "application/pdf" else "Image",
    }


def _day(d: PatientDocument) -> date:
    return d.document_date or d.created_at.date()


# ---- extraction, once per content and version ----------------------------------------------------

_CACHE: "OrderedDict[tuple[str, str], medical_reports.MedicalExtraction]" = OrderedDict()


def clear_cache() -> None:
    _CACHE.clear()


async def _extract(storage: Storage | None, d: PatientDocument) -> medical_reports.MedicalExtraction:
    key = (d.file.sha256, medical_reports.EXTRACTION_VERSION)
    if d.file.sha256 and key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key]
    problem = None
    if storage is None:
        problem = "File storage is not available on this server right now."
    else:
        try:
            info = await storage.head(d.file.object_key)
            if info is None:
                problem = "The file for this document is missing; please contact the clinic."
            elif info.size > MAX_FILE_BYTES:
                problem = "The file is too large to read here."
            else:
                data = await storage.get(d.file.object_key)
        except StorageError:
            problem = "File storage did not answer; please try again."
    if problem:
        # Not cached: storage problems are usually temporary.
        return medical_reports.analyse(medical_reports.Reading(problem=problem))
    reading = await run_in_threadpool(medical_reports.read, data, d.file.content_type)
    del data  # the file itself is never kept
    extraction = await run_in_threadpool(medical_reports.analyse, reading)
    if d.file.sha256:
        _CACHE[key] = extraction
        while len(_CACHE) > CACHE_SIZE:
            _CACHE.popitem(last=False)
    logger.info("ai_document_extracted", extra={"document_id": str(d.id), "status": extraction.status,
                                                "measurements": len(extraction.measurements), "version": extraction.version})
    return extraction


def _shareable(x: medical_reports.MedicalExtraction | None) -> bool:
    """May the AI provider see this document's findings?"""
    if settings.ai_phi_allowed:
        return True
    return bool(settings.ai_allow_synthetic_documents and x is not None and x.synthetic)


# ---- what the user sees (cards) and what the model receives ----------------------------------------


def _measurement(m) -> dict:
    return {**m.as_dict(), "about": medical_reports.explain(m.test)}


def _report_card(d: PatientDocument, x: medical_reports.MedicalExtraction, focus: str) -> dict:
    meta = _meta(d)
    rows = [_measurement(m) for m in x.measurements]
    return {
        "kind": "medical_report",
        "version": 2,
        "focus": focus,
        "document": {**meta, "printed_date": x.printed_date, "laboratory": x.laboratory, "document_kind": x.document_kind},
        "status": x.status,
        "measurements": rows,
        "conditions": [{**c.__dict__, "about": medical_reports.CONDITION_INFO.get(c.name)} for c in x.conditions],
        "symptoms": [s.__dict__ for s in x.symptoms],
        "sections": [s.__dict__ for s in x.sections if s.kind in ("interpretation", "follow_up")],
        "problem": x.problem,
        "notes": x.warnings,
        "has_text": bool(x.pages),
        "sources": [{"document_id": meta["document_id"], "title": d.title, "pages": sorted({m.page for m in x.measurements}) or x.pages}],
        "shared_with_ai": _shareable(x),
    }


def _fenced(text: str, name: str) -> str:
    body = text.replace("<<<", "‹‹‹").replace(">>>", "›››")
    return f'<<<DOCUMENT name="{name}">>>\n{body}\n<<<END DOCUMENT>>>'


def _model_view(d: PatientDocument, x: medical_reports.MedicalExtraction, focus: str) -> dict:
    meta = _meta(d)
    result = {
        "document_id": meta["document_id"],
        "type": meta["type"],
        "uploaded_at": meta["uploaded_at"],
        "report_date": meta["report_date"],
        "focus": focus,
        "extraction_status": x.status,
        "problem": x.problem,
        "measurements": len(x.measurements),
        "abnormal": sum(1 for m in x.measurements if m.out_of_range),
        "conditions": len(x.conditions),
        "symptoms": len(x.symptoms),
        "shown_to_user": True,
    }
    if not _shareable(x):
        result["note"] = WITHHELD
        return result
    # Findings already extracted and validated on the server: the model explains them, it does not re-read the file.
    result.update(
        title=d.title,
        synthetic_document=x.synthetic,
        document_kind=x.document_kind,
        printed_date=x.printed_date,
        findings={
            "conditions": [{"name": c.name, "role": c.role, "evidence": c.evidence_type, "source": c.source_text, "page": c.page}
                           for c in x.conditions],
            "symptoms": [{"name": s.name, "source": s.source_text, "page": s.page} for s in x.symptoms],
            "measurements": [{k: getattr(m, k) for k in ("test", "value", "unit", "reference_range", "report_flag", "out_of_range", "page")}
                             for m in x.measurements],
            # Text from the file is data, fenced like any document content.
            "report_text": [{"heading": s.heading, "kind": s.kind, "page": s.page, "text": _fenced(s.text[:1500], d.title)}
                            for s in x.sections],
            "warnings": x.warnings,
        },
        instructions="Answer the user's question (focus) from these findings only. Cite the document title and page. "
        "Separate what the report states from your general explanation. Do not add values, dates or diagnoses.",
    )
    return result


# ---- tools --------------------------------------------------------------------------------------------


def _outcome(*args, **kwargs):
    from app.services.ai.tools import ToolOutcome

    return ToolOutcome(*args, **kwargs)


async def list_medical_documents(db: AsyncSession, principal: Principal, a: ListDocumentsArgs, ctx: ToolContext):
    try:
        rows = await _documents(db, principal, a)
    except DomainError as exc:
        return _outcome({"error": exc.message})
    card = {"kind": "medical_documents", "total": len(rows), "items": [_meta(d) for d in rows]}
    documents = []
    for i, d in enumerate(rows):
        item = {"document_id": str(d.id), "type": d.document_type.value, "uploaded_at": d.created_at.isoformat(),
                "report_date": d.document_date.isoformat() if d.document_date else None, "most_recent_upload": i == 0}
        # Titles only when sharing is allowed (synthetic: known once the file has been read).
        if _shareable(_CACHE.get((d.file.sha256, medical_reports.EXTRACTION_VERSION))):
            item["title"] = d.title
        documents.append(item)
    result = {"total": len(rows), "documents": documents, "order": "most recent upload first", "shown_to_user": True}
    if not rows:
        result["note"] = "There are no documents in this record (of that type)."
    if len(rows) == 1:
        ctx.active_document_id = rows[0].id
    return _outcome(result, card=card)


async def explain_medical_document(db: AsyncSession, principal: Principal, a: ExplainDocumentArgs, ctx: ToolContext):
    try:
        patient_id = await _patient_id(db, principal, a.appointment_id)
        if a.document_id is not None:
            document = await document_service.get_document(db, principal, patient_id, a.document_id)
        elif (a.which in (None, "active")) and ctx.active_document_id is not None:
            # Re-checked: the active document must still be one this user may read.
            document = await document_service.get_document(db, principal, patient_id, ctx.active_document_id)
        else:
            rows = await _documents(db, principal, a)
            if not rows:
                return _outcome({"error": "There are no documents in this record (of that type)."})
            document = (_by_report_date(rows) if a.which == "latest_report_date" else rows)[0]
    except DomainError as exc:
        return _outcome({"error": exc.message})
    x = await _extract(ctx.storage, document)
    ctx.active_document_id = document.id
    logger.info("ai_document_read", extra={"document_id": str(document.id), "by": str(principal.user_id),
                                          "focus": a.focus, "measurements": len(x.measurements)})
    return _outcome(_model_view(document, x, a.focus), card=_report_card(document, x, a.focus))


async def summarize_medical_documents(db: AsyncSession, principal: Principal, a: SummarizeDocumentsArgs, ctx: ToolContext):
    try:
        if a.document_ids:
            patient_id = await _patient_id(db, principal, a.appointment_id)
            documents = [await document_service.get_document(db, principal, patient_id, i) for i in dict.fromkeys(a.document_ids)]
            total = len(documents)
        else:
            documents = await _documents(db, principal, a)
            total = len(documents)
            documents = documents[:MAX_DOCUMENTS_PER_SUMMARY]
    except DomainError as exc:
        return _outcome({"error": exc.message})
    if not documents:
        return _outcome({"error": "There are no documents in this record (of that type)."})

    processed, skipped, by_test, shareable = [], [], {}, True
    for d in sorted(documents, key=lambda d: (_day(d), d.created_at)):  # oldest first
        x = await _extract(ctx.storage, d)
        shareable = shareable and _shareable(x)
        meta = _meta(d)
        if x.problem or not x.pages:
            skipped.append({**meta, "reason": x.problem or "No readable text."})
            continue
        if not x.measurements:
            skipped.append({**meta, "reason": "No laboratory table could be read from this document."})
        processed.append({**meta, "measurements": len(x.measurements), "outside_printed_range": [m.test for m in x.measurements if m.out_of_range],
                          "conditions": [c.name for c in x.conditions], "notes": x.warnings, "pages": x.pages})
        for m in x.measurements:
            by_test.setdefault(medical_reports.canonical(m.test), []).append(
                {"date": meta["report_date"] or meta["uploaded"], "value": m.value, "unit": m.unit, "reference_range": m.reference_range,
                 "out_of_range": m.out_of_range, "document_id": meta["document_id"], "title": d.title, "page": m.page, "test": m.test}
            )
    series = []
    for key, points in by_test.items():
        if len({p["document_id"] for p in points}) < 2:
            continue
        # Only the same test in the same unit is compared.
        comparable = all(medical_reports.same_unit(points[0]["unit"], p["unit"]) for p in points)
        series.append({"test": points[0]["test"], "key": key, "unit": points[0]["unit"], "comparable": comparable,
                       "points": points, "about": medical_reports.explain(points[0]["test"])})
    not_included = total - len(documents)
    card = {"kind": "medical_summary", "version": 2, "processed": processed, "skipped": skipped, "series": series,
            "not_included": not_included, "shared_with_ai": shareable}
    result = {
        "shown_to_user": True,
        "documents_read": len(processed),
        "documents_unreadable": len(skipped),
        "documents_not_included_over_limit": not_included,
        "repeated_tests": len(series),
    }
    if shareable:
        result["summary"] = {"processed": processed, "series": series, "skipped": skipped}
    else:
        result["note"] = WITHHELD
    logger.info("ai_documents_summarised", extra={"by": str(principal.user_id), "read": len(processed), "skipped": len(skipped)})
    return _outcome(result, card=card)


async def show_my_profile(db: AsyncSession, principal: Principal, a, ctx: ToolContext):
    try:
        p = await patient_service.get_own(db, principal)
    except DomainError as exc:
        return _outcome({"error": exc.message})
    card = {
        "kind": "profile",
        "items": [{
            "name": f"{p.first_name} {p.last_name}", "mrn": p.mrn,
            "date_of_birth": p.date_of_birth.isoformat() if p.date_of_birth else None,
            "sex_at_birth": p.sex_at_birth.value if p.sex_at_birth else None,
            "phone": p.phone, "email": p.email, "address": p.address, "preferred_language": p.preferred_language,
        }],
        "total": 1,
    }
    result = {"shown_to_user": True}
    if settings.ai_phi_allowed:
        result["profile"] = card["items"][0]
    else:
        result["note"] = "The profile is shown to the user directly; it was not shared with you. Do not guess its details."
    return _outcome(result, card=card)


def register(tools: dict, principal: Principal, Tool, spec) -> None:
    """Add the document tools this user may use (called by tools.available_tools)."""
    own = principal.patient_id is not None and principal.has(Perm.document_read_own)
    assigned = principal.has(Perm.document_read_assigned)
    if principal.patient_id is not None and principal.has(Perm.patient_read_own):
        tools["show_my_profile"] = Tool(
            spec("show_my_profile", "Show the signed-in patient their own profile details (only when they ask).", _args_base()),
            _args_base(), show_my_profile, needs_storage=True,
        )
    if not (own or assigned):
        return
    who = "the signed-in patient's" if own and not assigned else "the patient record's (patients: their own; doctors: pass appointment_id)"
    tools["list_medical_documents"] = Tool(
        spec("list_medical_documents",
             f"List documents in {who} medical record, most recent upload first (title, type, report date, upload time). "
             "Use for 'what have I uploaded' / 'my most recent report'. Only when the user asks about their documents.",
             ListDocumentsArgs),
        ListDocumentsArgs, list_medical_documents, needs_storage=True,
    )
    tools["explain_medical_document"] = Tool(
        spec("explain_medical_document",
             "Read ONE document from the medical record on this server and answer about it. Set focus to what the user asked "
             "(conditions/disease, symptoms, measurements = full test table, abnormal results, follow_up, or summary). For 'it' / "
             "'that report' omit document_id (the conversation's active document is used). Call it again for each new question.",
             ExplainDocumentArgs),
        ExplainDocumentArgs, explain_medical_document, needs_storage=True,
    )
    tools["summarize_medical_documents"] = Tool(
        spec("summarize_medical_documents",
             f"Summarise or compare several documents (document_ids, or all; at most {MAX_DOCUMENTS_PER_SUMMARY}), oldest first, "
             "with the same tests side by side when the units match. Use for 'compare my reports' / 'summarize all my reports'.",
             SummarizeDocumentsArgs),
        SummarizeDocumentsArgs, summarize_medical_documents, needs_storage=True,
    )
