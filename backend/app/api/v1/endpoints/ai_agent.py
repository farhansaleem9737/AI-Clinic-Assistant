"""Clinic AI Assistant (D96): status, conversations, messages, documents and
confirming proposed actions. Every route needs a signed-in user and only ever
touches that user's own conversations and documents."""

import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import get_current_principal
from app.core.config import settings
from app.core.exceptions import BusinessRuleError, DomainError, PermissionDeniedError
from app.core.permissions import Principal
from app.core.storage import Storage, get_optional_storage, get_storage
from app.db.session import get_db
from app.models.ai import AiConversation, AiDocument, AiMessage
from app.schemas.ai import (
    ActionDecision,
    AiDocumentRead,
    AiMessageRead,
    AiStatus,
    AiUsageRead,
    ConversationDetail,
    ConversationRead,
    SendMessage,
    SendResultRead,
)
from app.services.ai import agent_service, tools as agent_tools, usage_service
from app.services.ai.document_processor import EXTENSIONS
from app.services.ai.provider import Provider, get_provider

router = APIRouter(prefix="/ai", tags=["ai assistant"])
logger = logging.getLogger(__name__)


def _message(m: AiMessage) -> AiMessageRead:
    return AiMessageRead(
        id=m.id, role=m.role, content=m.content, document_ids=m.document_ids or [], action=m.action,
        results=m.results or [], created_at=m.created_at,
    )


def _conversation(c: AiConversation) -> ConversationRead:
    return ConversationRead(id=c.id, title=c.title, created_at=c.created_at, updated_at=c.updated_at)


def _document(d: AiDocument) -> AiDocumentRead:
    return AiDocumentRead(
        id=d.id, filename=d.filename, content_type=d.content_type, size_bytes=d.size_bytes, status=d.status,
        page_count=d.page_count, conversation_id=d.conversation_id, created_at=d.created_at,
    )


# Tool -> capability the UI offers a suggestion for (only when this user has the tool).
CAPABILITIES = (
    ("search_doctors", "find_doctors"),
    ("get_clinic_help", "clinic_help"),
    ("get_dashboard_figures", "dashboard_figures"),
    ("get_my_appointments", "my_appointments"),
    ("propose_booking", "book_appointment"),
    ("list_appointments", "appointments_overview"),
    ("find_patient", "find_patient"),
    ("propose_booking_for_patient", "book_for_patient"),
    ("list_medical_documents", "medical_documents"),
)


@router.get("/status", response_model=AiStatus)
async def assistant_status(principal: Principal = Depends(get_current_principal)):
    """What the assistant offers this user right now (the UI shows only these)."""
    tools = agent_tools.available_tools(principal) if settings.ai_configured else {}
    capabilities = [capability for tool, capability in CAPABILITIES if tool in tools]
    if settings.ai_documents_enabled:
        capabilities.append("documents")
    return AiStatus(
        configured=settings.ai_configured,
        provider=settings.ai_provider.value,
        model=settings.ai_model_name if settings.ai_configured else None,
        roles=sorted(principal.roles),
        documents_enabled=settings.ai_documents_enabled,
        max_files=settings.ai_max_files_per_message,
        max_file_bytes=settings.ai_max_file_bytes,
        accepted_types=sorted(set(EXTENSIONS.values())),
        capabilities=capabilities,
    )


@router.get("/usage/me", response_model=AiUsageRead)
async def my_usage(db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    """How many assistant messages this user has sent today, against the limits."""
    s = await usage_service.summary(db, principal)
    return AiUsageRead(**s.__dict__)


@router.get("/conversations", response_model=list[ConversationRead])
async def list_conversations(db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    return [_conversation(c) for c in await agent_service.list_conversations(db, principal)]


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: uuid.UUID, db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_current_principal)
):
    conversation, messages = await agent_service.get_messages(db, principal, conversation_id)
    return ConversationDetail(**_conversation(conversation).model_dump(), messages=[_message(m) for m in messages])


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
    storage: Storage | None = Depends(get_optional_storage),
):
    await agent_service.delete_conversation(db, storage, principal, conversation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/messages", response_model=SendResultRead)
async def send_message(
    body: SendMessage,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
    provider: Provider = Depends(get_provider),
    storage: Storage | None = Depends(get_optional_storage),
):
    """Sends the message (with any uploaded documents) and returns the
    assistant's answer. 503 AI_NOT_CONFIGURED when no provider is set up."""
    result = await agent_service.send_message(
        db, principal, provider, storage, conversation_id=body.conversation_id, text=body.text, document_ids=body.document_ids
    )
    return _result(result)


def _result(result: agent_service.SendResult) -> SendResultRead:
    return SendResultRead(
        conversation=_conversation(result.conversation),
        user_message=_message(result.user_message),
        assistant_message=_message(result.assistant_message),
    )


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/messages/stream")
async def stream_message(
    body: SendMessage,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
    provider: Provider = Depends(get_provider),
    storage: Storage | None = Depends(get_optional_storage),
):
    """Like POST /messages, as Server-Sent Events: `delta` events carry answer
    text as it is generated, then one `done` event with the saved messages, or
    one `error` event. Nothing is saved for a request that fails or is stopped."""
    queue: asyncio.Queue = asyncio.Queue()

    async def on_text(chunk: str) -> None:
        await queue.put(("delta", {"text": chunk}))

    async def run() -> None:
        try:
            result = await agent_service.send_message(
                db, principal, provider, storage,
                conversation_id=body.conversation_id, text=body.text, document_ids=body.document_ids, on_text=on_text,
            )
            await queue.put(("done", _result(result).model_dump(mode="json")))
        except DomainError as exc:
            await db.rollback()
            await queue.put(("error", {"code": exc.code, "message": exc.message}))
        except Exception:
            logger.exception("ai_stream_failed")
            await db.rollback()
            await queue.put(("error", {"code": "AI_FAILED", "message": "The assistant could not answer. Please try again."}))
        finally:
            await queue.put(None)

    async def events():
        task = asyncio.create_task(run())
        try:
            while (item := await queue.get()) is not None:
                yield _sse(*item)
        finally:
            # The browser went away (Stop): stop the agent; its work is not committed.
            if not task.done():
                task.cancel()

    return StreamingResponse(
        events(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"}
    )


@router.post("/conversations/{conversation_id}/messages/{message_id}/decision", response_model=AiMessageRead)
async def decide_action(
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    body: ActionDecision,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Confirm or cancel the action the assistant proposed (e.g. a booking)."""
    return _message(await agent_service.confirm_action(db, principal, conversation_id, message_id, confirm=body.confirm))


@router.get("/documents", response_model=list[AiDocumentRead])
async def list_documents(db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    return [_document(d) for d in await agent_service.list_documents(db, principal)]


@router.post("/documents", response_model=list[AiDocumentRead], status_code=status.HTTP_201_CREATED)
async def upload_documents(
    files: list[UploadFile] = File(...),
    conversation_id: uuid.UUID | None = Form(None),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
    storage: Storage = Depends(get_storage),
):
    """PDF, PNG, JPG, WEBP, DOCX or TXT; limits from AI_MAX_FILES_PER_MESSAGE
    and AI_MAX_FILE_BYTES. Stored privately; returns metadata only. Off unless
    AI_ENABLE_MEDICAL_DOCUMENT_UPLOAD and AI_PHI_ALLOWED are both set (D100)."""
    if not settings.ai_documents_enabled:
        raise PermissionDeniedError(
            "Document upload to the assistant is switched off on this server.", code="AI_DOCUMENTS_DISABLED"
        )
    if len(files) > settings.ai_max_files_per_message:
        raise BusinessRuleError(f"Attach at most {settings.ai_max_files_per_message} files at a time", code="TOO_MANY_FILES")
    # Read at most one byte over the limit, so a huge upload is refused without loading it all.
    payload = [(upload.filename, await upload.read(settings.ai_max_file_bytes + 1)) for upload in files]
    documents = await agent_service.upload_documents(db, storage, principal, payload, conversation_id)
    return [_document(d) for d in documents]


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
    storage: Storage | None = Depends(get_optional_storage),
):
    await agent_service.delete_document(db, storage, principal, document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
