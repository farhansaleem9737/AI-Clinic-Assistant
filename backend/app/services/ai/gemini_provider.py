"""Google Gemini through the official `google-genai` SDK (D100).

One streamed generateContent request per agent step. Function calling is
manual: the SDK's automatic function calling is switched off, so the agent's
own validated tools (services.ai.tools) are the only code a model can reach.
The model's parts, thought signatures included, are sent back unchanged on
the next step, as Gemini requires for function calling.

Errors map to the assistant's own codes; the provider's error text is never
shown (it can echo the request) and the API key is never logged.
"""

import asyncio
import logging
from typing import Any

import httpx
from google import genai
from google.genai import errors, types

from app.core.config import settings
from app.services.ai.provider import AiUnavailableError, OnText, Reply, ToolCall, ToolSpec, Turn, Usage

logger = logging.getLogger(__name__)

BLOCKED = "I can't help with that request."
TRUNCATED = "My answer was cut short by the configured output limit. Please ask a narrower question."


def gemini_failure(exc: Exception) -> AiUnavailableError:
    """The assistant's error for a failed Gemini call. Only the status is logged."""
    status = getattr(exc, "code", None)
    text = f"{getattr(exc, 'status', '')} {getattr(exc, 'message', '')}".lower()
    logger.warning("ai_provider_failed", extra={"provider": "gemini", "status": status, "what": type(exc).__name__})
    if isinstance(exc, (asyncio.TimeoutError, httpx.TimeoutException)):
        return AiUnavailableError("The AI service took too long to answer. Please try again.", code="AI_TIMEOUT")
    if status == 429:
        if "quota" in text or "resource_exhausted" in text:
            return AiUnavailableError(
                "The AI service's usage quota for this server is used up. Please try again later.", code="AI_QUOTA_EXHAUSTED"
            )
        return AiUnavailableError("The AI service is busy (rate limit). Please try again shortly.", code="AI_RATE_LIMITED")
    # Gemini answers 400 INVALID_ARGUMENT "API key not valid" for a bad key.
    if status in (401, 403) or (status == 400 and "api key" in text):
        return AiUnavailableError("The AI service rejected the server's credentials.", code="AI_AUTH_FAILED")
    if status == 404:
        return AiUnavailableError(
            "The configured AI model is not available to this server's API project.", code="AI_MODEL_UNAVAILABLE"
        )
    return AiUnavailableError("The AI service did not answer. Please try again.")


def _parts(turn: Turn) -> list[types.Part]:
    parts = [types.Part(text=turn.text or "")]
    parts += [types.Part(inline_data=types.Blob(mime_type=a.mime_type, data=a.data)) for a in turn.attachments]
    return parts


def to_contents(turns: list[Turn]) -> list[types.Content]:
    """Provider-neutral turns as Gemini contents. Consecutive tool results
    become one user turn of function responses, as Gemini expects."""
    contents: list[types.Content] = []
    for t in turns:
        if t.role == "user":
            contents.append(types.Content(role="user", parts=_parts(t)))
        elif t.role == "assistant":
            if isinstance(t.raw, types.Content):
                contents.append(t.raw)
            else:
                parts = [types.Part(text=t.text)] if t.text else []
                parts += [types.Part(function_call=types.FunctionCall(id=c.id, name=c.name, args=c.arguments)) for c in t.tool_calls]
                contents.append(types.Content(role="model", parts=parts or [types.Part(text="")]))
        elif t.role == "tool":
            part = types.Part(
                function_response=types.FunctionResponse(id=t.tool_call_id, name=t.tool_name, response=t.tool_result or {})
            )
            if contents and contents[-1].role == "user" and all(p.function_response for p in contents[-1].parts or []):
                contents[-1].parts.append(part)
            else:
                contents.append(types.Content(role="user", parts=[part]))
    return contents


def _config(system: str, tools: list[ToolSpec]) -> types.GenerateContentConfig:
    config: dict[str, Any] = {
        "system_instruction": system,
        "max_output_tokens": settings.ai_max_output_tokens,
        # The agent runs tools itself, after validating the arguments.
        "automatic_function_calling": types.AutomaticFunctionCallingConfig(disable=True),
    }
    if tools:
        config["tools"] = [
            types.Tool(
                function_declarations=[
                    types.FunctionDeclaration(name=s.name, description=s.description, parameters_json_schema=s.parameters)
                    for s in tools
                ]
            )
        ]
    if settings.gemini_thinking_level:
        config["thinking_config"] = types.ThinkingConfig(thinking_level=settings.gemini_thinking_level)
    return types.GenerateContentConfig(**config)


class GeminiProvider:
    supports_images = True
    supports_pdf = True

    def __init__(self, *, model: str, api_key: str, client: Any = None) -> None:
        self.model = model
        # No SDK retry options are set: a failed call is reported, not repeated
        # silently against the project's quota.
        self._client = client or genai.Client(
            api_key=api_key, http_options=types.HttpOptions(timeout=settings.ai_timeout_seconds * 1000)
        )

    async def complete(
        self, *, system: str, turns: list[Turn], tools: list[ToolSpec], on_text: OnText | None = None
    ) -> Reply:
        parts: list[types.Part] = []
        texts: list[str] = []
        usage = None
        finish = None
        blocked = False
        try:
            async with asyncio.timeout(settings.ai_timeout_seconds):
                stream = await self._client.aio.models.generate_content_stream(
                    model=self.model, contents=to_contents(turns), config=_config(system, tools)
                )
                async for chunk in stream:
                    if chunk.usage_metadata is not None:
                        usage = chunk.usage_metadata
                    if chunk.prompt_feedback is not None and chunk.prompt_feedback.block_reason:
                        blocked = True
                    for candidate in chunk.candidates or []:
                        finish = candidate.finish_reason or finish
                        for part in (candidate.content.parts if candidate.content else None) or []:
                            parts.append(part)
                            if part.text and not part.thought:
                                texts.append(part.text)
                                if on_text is not None:
                                    await on_text(part.text)
        except errors.APIError as exc:
            raise gemini_failure(exc) from exc
        except (asyncio.TimeoutError, httpx.HTTPError) as exc:
            raise gemini_failure(exc) from exc

        calls = [
            ToolCall(id=p.function_call.id or f"call_{i}", name=p.function_call.name or "", arguments=dict(p.function_call.args or {}))
            for i, p in enumerate(parts)
            if p.function_call is not None
        ]
        text = "".join(texts).strip() or None
        finish_name = getattr(finish, "name", str(finish or ""))
        if not text and not calls:
            if blocked or finish_name in ("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION"):
                text = BLOCKED
            elif finish_name == "MAX_TOKENS":
                text = TRUNCATED
            if text and on_text is not None:
                await on_text(text)
        elif finish_name == "MAX_TOKENS" and calls:
            # A cut-off tool call may be incomplete: never run it.
            calls = []
            text = (text or "") + ("\n\n" if text else "") + TRUNCATED
        tokens = Usage(
            input_tokens=(usage.prompt_token_count or 0) if usage else 0,
            output_tokens=((usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)) if usage else 0,
        )
        return Reply(text=text, tool_calls=calls, raw=types.Content(role="model", parts=parts or [types.Part(text="")]), usage=tokens)


async def check_model(model: str, api_key: str, client: Any = None) -> dict:
    """What the API reports about one model, for app.cli.ai_check. Free-tier
    eligibility is not part of this metadata: it is set per project in Google AI Studio."""
    client = client or genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=settings.ai_timeout_seconds * 1000))
    try:
        info = await client.aio.models.get(model=model)
    except errors.APIError as exc:
        raise gemini_failure(exc) from exc
    actions = list(info.supported_actions or [])
    return {
        "name": info.name,
        "display_name": info.display_name,
        "input_token_limit": info.input_token_limit,
        "output_token_limit": info.output_token_limit,
        "supported_actions": actions,
        "supports_generate_content": "generateContent" in actions,
        "thinking": info.thinking,
    }

