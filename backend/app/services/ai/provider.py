"""AI providers behind one small interface (D96).

The agent speaks in `Turn`s and `ToolSpec`s; each provider translates them to
its own wire format. Adding a provider means adding one class here, nothing
else. The API key stays on the server and is never logged; prompts and
document text are never logged either.
"""

import base64
import json
import logging
from dataclasses import dataclass, field
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

import httpx

from app.core.config import AiProvider, settings
from app.core.exceptions import DomainError

logger = logging.getLogger(__name__)


class AiUnavailableError(DomainError):
    """No provider configured, or it failed / refused. Retrying later may work."""

    code = "AI_UNAVAILABLE"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    # JSON Schema (object). Kept to the subset every provider accepts.
    parameters: dict


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass(frozen=True)
class Attachment:
    """A file passed to the model as content (images, scanned PDFs)."""

    mime_type: str
    data: bytes


@dataclass
class Turn:
    """One message in provider-neutral form.

    role user: `text` (+ `attachments`); role assistant: `text` and/or
    `tool_calls` (+ `raw`, the provider's own message, sent back verbatim so
    providers that sign their tool calls accept the next request); role tool:
    the result of one call.
    """

    role: str
    text: str | None = None
    attachments: list[Attachment] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: Any = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    tool_result: dict | None = None


@dataclass(frozen=True)
class Usage:
    """Tokens one model request used, as the provider reported them (0 when not reported)."""

    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class Reply:
    text: str | None
    tool_calls: list[ToolCall]
    raw: Any = None
    usage: Usage | None = None


# Receives answer text as it is generated (streaming); providers that do not
# stream call it once with the whole text.
OnText = Callable[[str], Awaitable[None]]


class Provider(Protocol):
    supports_images: bool
    supports_pdf: bool

    async def complete(
        self, *, system: str, turns: list[Turn], tools: list[ToolSpec], on_text: OnText | None = None
    ) -> Reply: ...


def provider_failure(status: int | None, what: str) -> AiUnavailableError:
    # Provider error bodies can echo the request; only the status is kept.
    logger.warning("ai_provider_failed", extra={"provider": settings.ai_provider.value, "status": status, "what": what})
    if status == 429:
        return AiUnavailableError("The AI service is busy (rate limit). Please try again shortly.", code="AI_RATE_LIMITED")
    if status in (401, 403):
        return AiUnavailableError("The AI service rejected the server's credentials.", code="AI_AUTH_FAILED")
    return AiUnavailableError("The AI service did not answer. Please try again.")


class OpenAICompatibleProvider:
    """Any OpenAI-style /chat/completions API (Groq, OpenAI, local servers).
    Images go as data URLs (the model must support vision); PDFs are not
    accepted, so scanned PDFs need the Gemini or Anthropic provider."""

    supports_images = True
    supports_pdf = False

    def __init__(self, *, model: str, api_key: str, base_url: str, client: httpx.AsyncClient | None = None) -> None:
        self.model = model
        self._key = api_key
        self._base = base_url.rstrip("/")
        self._client = client

    @staticmethod
    def _messages(system: str, turns: list[Turn]) -> list[dict]:
        messages: list[dict] = [{"role": "system", "content": system}]
        for t in turns:
            if t.role == "user":
                if t.attachments:
                    content: Any = [{"type": "text", "text": t.text or ""}] + [
                        {"type": "image_url", "image_url": {"url": f"data:{a.mime_type};base64,{base64.b64encode(a.data).decode()}"}}
                        for a in t.attachments
                        if a.mime_type.startswith("image/")
                    ]
                else:
                    content = t.text or ""
                messages.append({"role": "user", "content": content})
            elif t.role == "assistant":
                message: dict[str, Any] = {"role": "assistant", "content": t.text or ""}
                if t.tool_calls:
                    message["tool_calls"] = [
                        {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": json.dumps(c.arguments)}}
                        for c in t.tool_calls
                    ]
                messages.append(message)
            elif t.role == "tool":
                messages.append({"role": "tool", "tool_call_id": t.tool_call_id, "content": json.dumps(t.tool_result or {})})
        return messages

    async def complete(
        self, *, system: str, turns: list[Turn], tools: list[ToolSpec], on_text: OnText | None = None
    ) -> Reply:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": self._messages(system, turns),
            "max_tokens": settings.ai_max_output_tokens,
            "temperature": 0.2,
        }
        if tools:
            body["tools"] = [
                {"type": "function", "function": {"name": s.name, "description": s.description, "parameters": s.parameters}}
                for s in tools
            ]
        try:
            client = self._client or httpx.AsyncClient(timeout=settings.ai_timeout_seconds)
            try:
                response = await client.post(
                    f"{self._base}/chat/completions", json=body, headers={"Authorization": f"Bearer {self._key}"}
                )
            finally:
                if self._client is None:
                    await client.aclose()
        except httpx.HTTPError as exc:
            raise provider_failure(None, type(exc).__name__) from exc
        if response.status_code != 200:
            raise provider_failure(response.status_code, "openai_compatible")
        data = response.json()
        choice = (data.get("choices") or [{}])[0].get("message", {})
        tokens = data.get("usage") or {}
        calls = []
        for c in choice.get("tool_calls") or []:
            try:
                args = json.loads(c.get("function", {}).get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append(ToolCall(id=c.get("id", ""), name=c.get("function", {}).get("name", ""), arguments=args if isinstance(args, dict) else {}))
        text = (choice.get("content") or "").strip() or None
        if text and on_text is not None:
            await on_text(text)
        return Reply(
            text=text,
            tool_calls=calls,
            usage=Usage(input_tokens=tokens.get("prompt_tokens") or 0, output_tokens=tokens.get("completion_tokens") or 0),
        )


def get_provider() -> Provider:
    """FastAPI dependency (overridden in tests). Raises when not configured."""
    if not settings.ai_configured:
        raise AiUnavailableError(
            "The AI assistant is not configured on this server yet (AI_PROVIDER, the model and the API key).",
            code="AI_NOT_CONFIGURED",
        )
    key = settings.ai_key.get_secret_value()
    model = settings.ai_model_name
    # SDKs are imported here so each server loads only the one it uses.
    if settings.ai_provider is AiProvider.gemini:
        from app.services.ai.gemini_provider import GeminiProvider

        return GeminiProvider(model=model, api_key=key)
    if settings.ai_provider is AiProvider.anthropic:
        from app.services.ai.anthropic_provider import AnthropicProvider

        return AnthropicProvider(model=model, api_key=key)
    return OpenAICompatibleProvider(model=model, api_key=key, base_url=settings.ai_base_url)
