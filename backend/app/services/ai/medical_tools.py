"""Assistant tools for documents in the patient record (D101).

Every lookup goes through document_service with the signed-in user's own
Principal, so the record's existing rules apply unchanged: a patient reaches
only their own documents; a doctor only patients they have appointments
with (reached through one of their appointments); reception and
administrators get nothing. Ids the model passes are only ever looked up
inside that scope, so another patient's document is simply "not found".

The tools run only when the model calls them for a request about documents;
nothing is loaded in advance or kept between messages. Content is read on
this server (medical_reports) and shown to the user as cards. The AI
provider receives document contents only when AI_PHI_ALLOWED says it is
approved for them; otherwise it gets counts and ids, never titles, values or text.
"""

import logging
import uuid
from datetime import date
from typing import Literal

from fastapi.concurrency import run_in_threadpool
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import DomainError, NotFoundError
from app.core.permissions import Perm, Principal
from app.core.storage import Storage, StorageError
from app.models.patient_document import DocumentType, PatientDocument
from app.services import appointment_service, document_service, patient_service
from app.services.ai import medical_reports

logger = logging.getLogger(__name__)

MAX_DOCUMENTS_PER_SUMMARY = 10
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_TEXT_FOR_MODEL = 20_000
TYPE_LABELS = {
    "lab_report": "Lab report",
    "imaging": "Imaging report",
    "prescription": "Prescription",
    "referral": "Referral",
    "discharge_summary": "Discharge summary",
    "other": "Other document",
}
WITHHELD = (
    "The contents are shown to the user directly from the clinic's records. For privacy they were not "
    "shared with you: do not guess, repeat or interpret any values. Tell the user the details are shown below "
    "and suggest discussing them with their doctor."
)
TypeName = Literal["lab_report", "imaging", "prescription", "referral", "discharge_summary", "other"]


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
    document_id: uuid.UUID | None = Field(default=None, description="From list_medical_documents; omit for the latest")
    document_type: TypeName | None = Field(default=None, description="With no document_id: the latest of this type")


class SummarizeDocumentsArgs(_Scoped):
    document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=MAX_DOCUMENTS_PER_SUMMARY,
                                          description="Documents to summarise or compare; empty = all (most recent first)")
    document_type: TypeName | None = None


async def _patient_id(db: AsyncSession, principal: Principal, appointment_id: uuid.UUID | None) -> uuid.UUID:
    """Whose record: a doctor's appointment (visibility-checked), else the caller's own."""
    if appointment_id is not None:
        view = await appointment_service.get_view(db, principal, appointment_id)
        return view.appointment.patient_id
    if principal.patient_id is None:
        raise NotFoundError("No patient record to look in. Doctors: name one of your appointments.")
    return principal.patient_id


def _meta(d: PatientDocument) -> dict:
    return {
        "document_id": str(d.id),
        "patient_id": str(d.patient_id),
        "title": d.title,
        "type": d.document_type.value,
        "type_label": TYPE_LABELS[d.document_type.value],
        "report_date": d.document_date.isoformat() if d.document_date else None,
        "uploaded": d.created_at.date().isoformat(),
        "file_type": "PDF" if d.file.content_type == "application/pdf" else "Image",
    }


def _for_model(d: PatientDocument) -> dict:
    item = {"document_id": str(d.id), "type": d.document_type.value, "report_date": _meta(d)["report_date"] or _meta(d)["uploaded"]}
    if settings.ai_phi_allowed:
        item["title"] = d.title
    return item


def _day(d: PatientDocument) -> date:
    return d.document_date or d.created_at.date()


async def _documents(db, principal, a, types: tuple[DocumentType, ...] | None = None) -> list[PatientDocument]:
    patient_id = await _patient_id(db, principal, a.appointment_id)
    rows = await document_service.list_document(db, principal, patient_id)
    wanted = a.document_type or None
    rows = [d for d in rows if (wanted is None or d.document_type.value == wanted)]
    return sorted(rows, key=lambda d: (_day(d), d.created_at), reverse=True)


async def _read(storage: Storage | None, d: PatientDocument) -> tuple[medical_reports.Reading, list]:
    if storage is None:
        return medical_reports.Reading(problem="File storage is not available on this server right now."), []
    try:
        if (info := await storage.head(d.file.object_key)) is None:
            return medical_reports.Reading(problem="The file for this document is missing; please contact the clinic."), []
        if info.size > MAX_FILE_BYTES:
            return medical_reports.Reading(problem="The file is too large to read here."), []
        data = await storage.get(d.file.object_key)
    except StorageError:
        return medical_reports.Reading(problem="File storage did not answer; please try again."), []
    reading = await run_in_threadpool(medical_reports.read, data, d.file.content_type)
    del data  # request-scoped: nothing is kept
    return reading, medical_reports.measurements(reading)


def _report_card(d: PatientDocument, reading, rows) -> dict:
    meta = _meta(d)
    pages = sorted({m.page for m in rows}) or [p.number for p in reading.pages]
    return {
        "kind": "medical_report",
        "document": {**meta, "printed_date": medical_reports.report_date(reading), "laboratory": medical_reports.laboratory(reading)},
        "measurements": [{**m.as_dict(), "about": medical_reports.explain(m.test)} for m in rows],
        "problem": reading.problem,
        "notes": reading.notes,
        "has_text": bool(reading.pages),
        "sources": [{"document_id": meta["document_id"], "title": d.title, "pages": pages}],
        "shared_with_ai": settings.ai_phi_allowed,
    }


def _model_view(d: PatientDocument, reading, rows) -> dict:
    result = {
        **_for_model(d),
        "readable": bool(reading.pages),
        "problem": reading.problem,
        "measurements": len(rows),
        "outside_printed_range": sum(1 for m in rows if m.out_of_range),
    }
    if settings.ai_phi_allowed:
        # Approved provider (or synthetic data): the model may explain the text itself.
        body = reading.text[:MAX_TEXT_FOR_MODEL].replace("<<<", "‹‹‹").replace(">>>", "›››")
        result["measurements_found"] = [m.as_dict() for m in rows]
        result["text"] = f'<<<DOCUMENT name="{d.title}">>>\n{body}\n<<<END DOCUMENT>>>'
    return result


async def list_medical_documents(db: AsyncSession, principal: Principal, a: ListDocumentsArgs, storage) -> "ToolOutcome":
    from app.services.ai.tools import ToolOutcome

    try:
        rows = await _documents(db, principal, a)
    except DomainError as exc:
        return ToolOutcome({"error": exc.message})
    card = {"kind": "medical_documents", "total": len(rows), "items": [_meta(d) for d in rows]}
    result = {"total": len(rows), "documents": [_for_model(d) for d in rows], "shown_to_user": True}
    if not rows:
        result["note"] = "There are no documents in this record (of that type)."
    return ToolOutcome(result, card=card)


async def explain_medical_document(db: AsyncSession, principal: Principal, a: ExplainDocumentArgs, storage) -> "ToolOutcome":
    from app.services.ai.tools import ToolOutcome

    try:
        if a.document_id is not None:
            patient_id = await _patient_id(db, principal, a.appointment_id)
            document = await document_service.get_document(db, principal, patient_id, a.document_id)
        else:
            rows = await _documents(db, principal, a)
            if not rows:
                return ToolOutcome({"error": "There are no documents in this record (of that type)."})
            document = rows[0]
    except DomainError as exc:
        return ToolOutcome({"error": exc.message})
    reading, rows = await _read(storage, document)
    logger.info("ai_document_read", extra={"document_id": str(document.id), "by": str(principal.user_id), "measurements": len(rows)})
    result = _model_view(document, reading, rows)
    result.update(shown_to_user=True)
    if not settings.ai_phi_allowed:
        result["note"] = WITHHELD
    return ToolOutcome(result, card=_report_card(document, reading, rows))


async def summarize_medical_documents(db: AsyncSession, principal: Principal, a: SummarizeDocumentsArgs, storage) -> "ToolOutcome":
    from app.services.ai.tools import ToolOutcome

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
        return ToolOutcome({"error": exc.message})
    if not documents:
        return ToolOutcome({"error": "There are no documents in this record (of that type)."})

    processed, skipped, by_test = [], [], {}
    for d in sorted(documents, key=lambda d: (_day(d), d.created_at)):  # oldest first
        reading, rows = await _read(storage, d)
        meta = _meta(d)
        if reading.problem or not reading.pages:
            skipped.append({**meta, "reason": reading.problem or "No readable text."})
            continue
        processed.append({**meta, "measurements": len(rows), "outside_printed_range": [m.test for m in rows if m.out_of_range],
                          "notes": reading.notes, "pages": [p.number for p in reading.pages]})
        for m in rows:
            # Only the same test in the same unit is ever compared.
            by_test.setdefault((m.test.lower(), (m.unit or "").lower()), []).append(
                {"date": meta["report_date"] or meta["uploaded"], "value": m.value, "reference_range": m.reference_range,
                 "out_of_range": m.out_of_range, "document_id": meta["document_id"], "title": d.title, "page": m.page, "test": m.test, "unit": m.unit}
            )
    series = [
        {"test": points[0]["test"], "unit": points[0]["unit"], "points": points, "about": medical_reports.explain(points[0]["test"])}
        for points in by_test.values()
        if len({p["document_id"] for p in points}) >= 2
    ]
    not_included = total - len(documents)
    card = {
        "kind": "medical_summary",
        "processed": processed,
        "skipped": skipped,
        "series": series,
        "not_included": not_included,
        "shared_with_ai": settings.ai_phi_allowed,
    }
    result = {
        "shown_to_user": True,
        "documents_read": len(processed),
        "documents_unreadable": len(skipped),
        "documents_not_included_over_limit": not_included,
        "repeated_tests": len(series),
    }
    if settings.ai_phi_allowed:
        result["summary"] = {"processed": processed, "series": series, "skipped": skipped}
    else:
        result["note"] = WITHHELD
    logger.info("ai_documents_summarised", extra={"by": str(principal.user_id), "read": len(processed), "skipped": len(skipped)})
    return ToolOutcome(result, card=card)


async def show_my_profile(db: AsyncSession, principal: Principal, a, storage) -> "ToolOutcome":
    from app.services.ai.tools import ToolOutcome

    try:
        p = await patient_service.get_own(db, principal)
    except DomainError as exc:
        return ToolOutcome({"error": exc.message})
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
    return ToolOutcome(result, card=card)


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
             f"List documents in {who} medical record (lab reports, imaging, prescriptions...). Use only when the user asks about their documents.",
             ListDocumentsArgs),
        ListDocumentsArgs, list_medical_documents, needs_storage=True,
    )
    tools["explain_medical_document"] = Tool(
        spec("explain_medical_document",
             "Read one document from the medical record on this server and show its findings (values, units, reference ranges, "
             "pages) to the user. Omit document_id for the latest (optionally of document_type). Only when the user asks.",
             ExplainDocumentArgs),
        ExplainDocumentArgs, explain_medical_document, needs_storage=True,
    )
    tools["summarize_medical_documents"] = Tool(
        spec("summarize_medical_documents",
             f"Summarise or compare several documents (by document_ids, or all; at most {MAX_DOCUMENTS_PER_SUMMARY}), oldest first, "
             "with repeated tests side by side. Only when the user asks.",
             SummarizeDocumentsArgs),
        SummarizeDocumentsArgs, summarize_medical_documents, needs_storage=True,
    )
