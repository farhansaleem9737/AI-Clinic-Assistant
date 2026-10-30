"""Anthropic Claude provider (D97), through the official `anthropic` SDK.

One streamed Messages request per agent step: answer text is passed to
`on_text` as it arrives, and the final message gives the tool calls. The SDK
release in use sends API version 2026-10-21, so no sampling parameters are
sent. Thinking is left at the model's default (adaptive). For the models that
support it, the server-side refusal fallback is enabled (`fallbacks:
"default"`): a classifier decline is retried on the model Anthropic
recommends for that category, inside the same call.

The key comes from AI_API_KEY or ANTHROPIC_API_KEY and stays on the server;
nothing here logs prompts, document text or the key.
"""

import base64
import json
import logging

import anthropic

from app.core.config import settings
from app.services.ai.provider import (
    AiUnavailableError,
    OnText,
    Reply,
    ToolCall,
    ToolSpec,
    Turn,
    Usage,
    provider_failure,
)

logger = logging.getLogger(__name__)

# Models that accept `fallbacks: "default"` (beta) on the Claude API.
FALLBACK_MODELS = {"claude-sonnet-5-5", "claude-opus-5-5", "claude-opus-5", "claude-fable-5-1"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"
# Re-issue a step whose streamed tool input could not be parsed at all.
MAX_JSON_RETRIES = 2


def to_messages(turns: list[Turn]) -> list[dict]:
    """Provider-neutral turns -> Messages API `messages`. Tool results of one
    step go back together in a single user message."""
    messages: list[dict] = []
    results: list[dict] = []

    def flush_results() -> None:
        if results:
            messages.append({"role": "user", "content": list(results)})
            results.clear()

    for turn in turns:
        if turn.role == "tool":
            result = turn.tool_result or {}
            block = {"type": "tool_result", "tool_use_id": turn.tool_call_id, "content": json.dumps(result)}
            if "error" in result:
                block["is_error"] = True
            results.append(block)
            continue
        flush_results()
        if turn.role == "user":
            content: list[dict] = []
            for attachment in turn.attachments:
                data = base64.standard_b64encode(attachment.data).decode()
                source = {"type": "base64", "media_type": attachment.mime_type, "data": data}
                if attachment.mime_type == "application/pdf":
                    content.append({"type": "document", "source": source})
                elif attachment.mime_type.startswith("image/"):
                    content.append({"type": "image", "source": source})
            content.append({"type": "text", "text": turn.text or ""})
            messages.append({"role": "user", "content": content})
        elif turn.role == "assistant":
            if turn.raw is not None:
                # This step's own response, sent back unchanged (thinking and fallback blocks included).
                messages.append({"role": "assistant", "content": turn.raw})
            elif turn.text:
                messages.append({"role": "assistant", "content": turn.text})
    flush_results()
    return messages


class AnthropicProvider:
    supports_images = True
    supports_pdf = True

    def __init__(self, *, model: str, api_key: str | None = None, client: anthropic.AsyncAnthropic | None = None) -> None:
        self.model = model
        self._client = client or anthropic.AsyncAnthropic(api_key=api_key, timeout=float(settings.ai_timeout_seconds))

    def _request(self, *, system: str, turns: list[Turn], tools: list[ToolSpec]) -> dict:
        request: dict = {
            "model": self.model,
            "max_tokens": settings.ai_max_output_tokens,
            "system": system,
            "messages": to_messages(turns),
        }
        if tools:
            request["tools"] = [
                {
                    "name": spec.name,
                    "description": spec.description,
                    "input_schema": spec.parameters,
                    # Inputs stream as generated; they are validated by the
                    # agent's own schemas before any tool runs.
                    "eager_input_streaming": True,
                }
                for spec in tools
            ]
        return request

    async def _stream_once(self, request: dict, on_text: OnText | None):
        if self.model in FALLBACK_MODELS:
            stream_manager = self._client.beta.messages.stream(**request, betas=[FALLBACK_BETA], fallbacks="default")
        else:
            stream_manager = self._client.messages.stream(**request)
        async with stream_manager as stream:
            async for event in stream:
                if event.type == "text" and on_text is not None:
                    await on_text(event.text)
            return await stream.get_final_message()

    async def complete(
        self, *, system: str, turns: list[Turn], tools: list[ToolSpec], on_text: OnText | None = None
    ) -> Reply:
        request = self._request(system=system, turns=turns, tools=tools)
        json_retries = 0
        while True:
            try:
                message = await self._stream_once(request, on_text)
                break
            except ValueError:
                # A streamed tool input the SDK could not parse at all: no
                # tool_use id to answer, so re-issue the step (bounded).
                json_retries += 1
                if json_retries > MAX_JSON_RETRIES:
                    raise AiUnavailableError("The AI service returned an unreadable answer. Please try again.") from None
            except anthropic.RateLimitError as exc:
                raise provider_failure(429, "anthropic") from exc
            except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
                raise provider_failure(401, "anthropic") from exc
            except anthropic.APIStatusError as exc:
                raise provider_failure(exc.status_code, "anthropic") from exc
            except anthropic.APIConnectionError as exc:
                raise provider_failure(None, type(exc).__name__) from exc

        text = "".join(block.text for block in message.content if block.type == "text").strip() or None
        used = getattr(message, "usage", None)
        tokens = Usage(
            input_tokens=getattr(used, "input_tokens", 0) or 0, output_tokens=getattr(used, "output_tokens", 0) or 0
        )
        if message.stop_reason == "refusal":
            # The whole fallback chain declined: never run tools from a refused turn.
            return Reply(text="I can't help with that request.", tool_calls=[], usage=tokens)
        tool_uses = [block for block in message.content if block.type == "tool_use"]
        if message.stop_reason == "max_tokens" and tool_uses:
            # A truncated tool input parses as a partial object: do not run it.
            return Reply(text=(text or "") + "\n\n(The answer was cut off. Please ask again more specifically.)", tool_calls=[], usage=tokens)
        calls = [
            ToolCall(id=block.id, name=block.name, arguments=block.input if isinstance(block.input, dict) else {})
            for block in tool_uses
        ]
        return Reply(text=text, tool_calls=calls, raw=message.content, usage=tokens)
