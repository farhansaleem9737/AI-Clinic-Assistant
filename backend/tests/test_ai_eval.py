"""The assistant's evaluation suite (D129), over tests/ai_eval_data.py.

Offline (always, no model, no database): document classification and the
findings each class may carry, reference values never read as results, the
file name never deciding, urgent-symptom routing with no false alarms, what
the model is told about non-medical files, and the dataset itself.

Live (opt-in, uses provider quota): every conversation scenario against the
configured model, with the tools replaced by the scenario's mocked results so
no real record is read or changed. Each scenario is its own test; a run
prints the answers and a pass rate.

    cd backend
    python -m pytest tests/test_ai_eval.py --noconftest -q               # offline
    RUN_LIVE_AI=1 python -m pytest tests/test_ai_eval.py -k live -q      # all scenarios, live
    RUN_LIVE_AI=1 AI_EVAL_IDS=d01,d03,a05 python -m pytest tests/test_ai_eval.py -k live -q
"""

import os
import re
import uuid
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from app.core.permissions import Perm, Principal
from app.services.ai import guardrails, medical_reports, medical_tools
from app.services.ai import tools as agent_tools
from tests.ai_eval_data import DOCUMENTS, SCENARIOS

MEDICAL = set(medical_reports.MEDICAL_CLASSES)


def _read(text: str) -> medical_reports.MedicalExtraction:
    return medical_reports.analyse(medical_reports.Reading(pages=[medical_reports.Page(1, text)] if text.strip() else []))


# ---- documents ---------------------------------------------------------------------------------


@pytest.mark.parametrize("doc_id, name, text, expected, note", DOCUMENTS, ids=[d[0] for d in DOCUMENTS])
def test_document_class_comes_from_the_content(doc_id, name, text, expected, note):
    x = _read(text)
    assert x.content_class == expected, f"{doc_id} ({note}): {x.content_class}"
    if expected not in MEDICAL and expected != "MIXED_CONTENT":
        # Invoice lines, stray numbers and leaflet thresholds are never test results.
        assert x.measurements == [] and x.conditions == [] and x.symptoms == []
    assert x.content_note


def test_the_file_name_never_decides():
    by_text = {}
    for doc_id, name, text, expected, _ in DOCUMENTS:
        by_text.setdefault(text, set()).add(_read(text).content_class)
    assert all(len(classes) == 1 for classes in by_text.values())
    names = {d[1] for d in DOCUMENTS if d[3] == "NON_MEDICAL_DOCUMENT"}
    assert "medical_report.pdf" in names  # named like a report, still not medical


def test_reference_values_are_not_patient_results():
    from tests.ai_eval_data import LIPIDS_REFERENCE_ONLY

    x = _read(LIPIDS_REFERENCE_ONLY)
    assert x.content_class == "MEDICAL_INFORMATION" and x.measurements == []
    assert "no patient results" in x.document_kind


def test_a_real_report_keeps_its_findings():
    from tests.ai_eval_data import CBC

    x = _read(CBC)
    hb = next(m for m in x.measurements if m.test.lower().startswith("hemoglobin"))
    assert (hb.value, hb.out_of_range) == ("10.9", "low") and x.content_class == "MEDICAL_REPORT"
    assert x.excerpt is None  # medical records go to the model as findings, not raw text


def test_unreadable_files_are_not_guessed():
    x = medical_reports.analyse(medical_reports.Reading(problem="The PDF could not be opened."))
    assert x.content_class == "UNREADABLE_DOCUMENT" and x.measurements == []


def _model_view(text: str, *, shareable: bool, monkeypatch) -> dict:
    monkeypatch.setattr(medical_tools, "_shareable", lambda _x: shareable)
    d = SimpleNamespace(
        id=uuid.uuid4(), patient_id=uuid.uuid4(), title="test", document_type=SimpleNamespace(value="lab_report"),
        document_date=date(2026, 1, 1), created_at=datetime(2026, 1, 2, tzinfo=UTC), file=SimpleNamespace(content_type="application/pdf"),
    )
    return medical_tools._model_view(d, _read(text), "summary")


def test_the_model_is_told_what_a_non_medical_file_is(monkeypatch):
    from tests.ai_eval_data import INVOICE

    view = _model_view(INVOICE, shareable=True, monkeypatch=monkeypatch)
    assert view["content_class"] == "NON_MEDICAL_DOCUMENT" and view["content_label"] == "an invoice or bill"
    assert "no medical findings" in view["content_note"] and "findings" not in view
    assert "never suggest a doctor" in view["instructions"].lower()
    assert "<<<DOCUMENT" in view["excerpt"] and "INVOICE" in view["excerpt"]


def test_a_test_file_is_quoted_only_when_sharing_is_allowed(monkeypatch):
    shared = _model_view("test", shareable=True, monkeypatch=monkeypatch)
    assert shared["content_class"] == "INSUFFICIENT_CONTENT" and '"test"' in shared["content_note"]
    withheld = _model_view("test", shareable=False, monkeypatch=monkeypatch)
    assert '"test"' not in str(withheld) and "excerpt" not in withheld
    assert withheld["content_class"] == "INSUFFICIENT_CONTENT"


def test_a_medical_report_still_sends_findings_with_grounding_rules(monkeypatch):
    from tests.ai_eval_data import CBC

    view = _model_view(CBC, shareable=True, monkeypatch=monkeypatch)
    assert view["content_class"] == "MEDICAL_REPORT" and view["findings"]["measurements"]
    assert "not in this report" in view["instructions"] and "not the patient's results" in view["instructions"]


def test_injected_instructions_stay_fenced_data():
    from app.services.ai.agent_service import _fence
    from tests.ai_eval_data import INJECTION

    document = SimpleNamespace(filename="lab.pdf", content_type="application/pdf", page_count=1, status="ready")
    fenced = _fence(document, INJECTION, content="MEDICAL_REPORT")
    assert fenced.count("<<<END DOCUMENT>>>") == 1  # the fake end marker inside was neutralised
    assert 'content="MEDICAL_REPORT"' in fenced


# ---- urgent symptoms: always the fixed guidance, and no false alarms ---------------------------


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s["id"] for s in SCENARIOS])
def test_urgent_routing(scenario):
    assert guardrails.is_urgent(scenario["user"]) == (scenario["action"] == "urgent"), scenario["user"]


# ---- the dataset -------------------------------------------------------------------------------


def _all_tools(role: str) -> set[str]:
    user = SimpleNamespace(id=uuid.uuid4(), email="eval@example.com", name="Eval")
    principal = Principal(user=user, roles=frozenset({role}), permissions=frozenset(p.value for p in Perm),
                          doctor_id=uuid.uuid4() if role == "doctor" else None, patient_id=uuid.uuid4() if role == "patient" else None)
    return set(agent_tools.available_tools(principal))


def test_the_dataset_is_complete_and_consistent(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "ai_phi_allowed", True)  # every tool listed, so every name can be checked
    assert len(SCENARIOS) >= 100 and len({s["id"] for s in SCENARIOS}) == len(SCENARIOS)
    categories = {s["category"] for s in SCENARIOS}
    for needed in ("documents", "doctor_search", "followup", "appointments", "booking", "medical", "urgent", "scope",
                   "permissions", "injection", "errors", "ambiguous", "multi", "roles"):
        assert needed in categories, needed
    known = set().union(*(_all_tools(r) for r in ("patient", "doctor", "receptionist", "admin")))
    for s in SCENARIOS:
        for name in (*s["tools"], *s["not_tools"], *s["mocked"]):
            assert name in known, f"{s['id']}: unknown tool {name}"
        for pattern in (*s["required"], *s["forbidden"]):
            re.compile(pattern)


# ---- live: each scenario against the configured model --------------------------------------------

LIVE = os.environ.get("RUN_LIVE_AI") == "1"
WANTED = {i.strip() for i in os.environ.get("AI_EVAL_IDS", "").split(",") if i.strip()}
LIVE_SCENARIOS = [s for s in SCENARIOS if (not WANTED or s["id"] in WANTED) and s["action"] != "urgent" and not s["document"]]


def score(scenario: dict, answer: str, called: list[str], action: dict | None) -> list[str]:
    """The reasons a scenario failed (empty: passed). Deterministic, from the answer and the tool calls."""
    problems = []
    if scenario["tools"] and not set(called) & set(scenario["tools"]):
        problems.append(f"expected one of {scenario['tools']}, called {called}")
    if set(called) & set(scenario["not_tools"]):
        problems.append(f"called a forbidden tool: {sorted(set(called) & set(scenario['not_tools']))}")
    for pattern in scenario["required"]:
        if not re.search(pattern, answer, re.I):
            problems.append(f"missing: {pattern}")
    for pattern in scenario["forbidden"]:
        if re.search(pattern, answer, re.I):
            problems.append(f"forbidden claim: {pattern}")
    if scenario["action"] == "propose" and not action:
        problems.append("no proposal was made")
    if scenario["action"] == "clarify" and "?" not in answer:
        problems.append("no clarifying question")
    return problems


@pytest.mark.skipif(not LIVE, reason="live AI evaluation is opt-in (RUN_LIVE_AI=1): it uses provider quota")
@pytest.mark.parametrize("scenario", LIVE_SCENARIOS, ids=[s["id"] for s in LIVE_SCENARIOS])
async def test_live(scenario, db_session, make_user, monkeypatch):
    from app.core.config import Settings, settings
    from app.models.ai import AiConversation, AiMessage
    from app.services import rbac_service
    from app.services.ai import agent_service, provider as provider_module

    configured = Settings()
    for name in type(settings).model_fields:
        if name.startswith(("ai_", "gemini_", "anthropic_")):
            monkeypatch.setattr(settings, name, getattr(configured, name))
    monkeypatch.setattr(settings, "ai_phi_allowed", True)  # mocked, synthetic tool results only: no real record is read
    if not settings.ai_configured:
        pytest.skip("backend/.env does not configure the AI assistant")

    user = await make_user(scenario["role"])
    principal = await rbac_service.load_principal_by_id(db_session, user.id)
    conversation = AiConversation(user_id=user.id, title="eval")
    db_session.add(conversation)
    await db_session.flush()
    for role, text in scenario["history"]:
        db_session.add(AiMessage(conversation_id=conversation.id, role=role, content=text))
        await db_session.flush()
    await db_session.commit()

    called: list[str] = []

    async def mocked_tool(db, principal, tools, name, arguments, context=None):
        called.append(name)
        if name not in tools:
            return agent_tools.ToolOutcome({"error": "That isn't available to this account.", "error_code": "TOOL_UNAVAILABLE"})
        result = scenario["mocked"].get(name)
        if result is None:
            return agent_tools.ToolOutcome({"error": "Nothing found.", "error_code": "DATA_NOT_FOUND"})
        action = None
        if name.startswith("propose_") or result.get("proposed"):
            action = {"type": "book_appointment", "status": "pending", "doctor_name": "Dr. Omar Shah", "when_text": "Wed 12 Nov, 10:30 AM"}
            return agent_tools.ToolOutcome(dict(result), action=action, reply="Shall I book this? Press Confirm to book it.")
        return agent_tools.ToolOutcome(dict(result))

    monkeypatch.setattr(agent_tools, "run_tool", mocked_tool)
    sent = await agent_service.send_message(
        db_session, principal, provider_module.get_provider(), None, conversation_id=conversation.id,
        text=scenario["user"], document_ids=[],
    )
    answer, action = sent.assistant_message.content, sent.assistant_message.action
    problems = score(scenario, answer, called, action)
    print(f"\n[{scenario['id']}] {scenario['user']}\n  tools: {called}\n  answer: {answer}\n  {'PASS' if not problems else 'FAIL: ' + '; '.join(problems)}")
    assert not problems, problems
