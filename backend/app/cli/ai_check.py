"""Check the configured Gemini model before turning the assistant on (D100).

    cd backend
    python -m app.cli.ai_check            # model metadata only: no prompt, no generation tokens
    python -m app.cli.ai_check --smoke    # also one tiny synthetic prompt (uses a little quota)

Reads AI_PROVIDER=gemini, GEMINI_MODEL and GEMINI_API_KEY from backend/.env.
Prints what the API reports about the model: whether it exists for this
project and supports generateContent, and its token limits. It cannot tell
whether the model is free for this project: that is set per project in
Google AI Studio (Rate limits / Billing), so check there; nothing here turns
on billing or switches to another model. The key is never printed.
"""

import argparse
import asyncio
import sys

from app.core.config import AiProvider, settings
from app.services.ai.provider import AiUnavailableError, Turn


def _fail(message: str) -> None:
    print(f"Error: {message}", file=sys.stderr)
    sys.exit(1)


async def _run(smoke: bool) -> None:
    from app.services.ai.gemini_provider import GeminiProvider, check_model

    model, key = settings.ai_model_name, settings.ai_key.get_secret_value()
    try:
        info = await check_model(model, key)
    except AiUnavailableError as exc:
        _fail(f"{exc.message} ({exc.code})")
    print(f"Model:            {info['name']} ({info['display_name']})")
    print(f"generateContent:  {'yes' if info['supports_generate_content'] else 'NO'}")
    print(f"Token limits:     input {info['input_token_limit']}, output {info['output_token_limit']}")
    print(f"Thinking model:   {info['thinking']}")
    print("Free tier:        not reported by the API; check the project's rate limits in Google AI Studio.")
    if not info["supports_generate_content"]:
        _fail("this model cannot be used for chat; choose another GEMINI_MODEL.")
    if smoke:
        reply = await GeminiProvider(model=model, api_key=key).complete(
            system="Reply with the single word OK.", turns=[Turn(role="user", text="Synthetic connectivity test.")], tools=[]
        )
        tokens = reply.usage
        print(f"Smoke test:       answered {reply.text!r} ({tokens.input_tokens} in / {tokens.output_tokens} out tokens)")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli.ai_check", description="Check the configured Gemini model.")
    parser.add_argument("--smoke", action="store_true", help="send one tiny synthetic prompt")
    args = parser.parse_args(argv)
    if settings.ai_provider is not AiProvider.gemini:
        _fail("AI_PROVIDER is not gemini.")
    if not settings.ai_model_name or settings.ai_key is None:
        _fail("Set GEMINI_MODEL and GEMINI_API_KEY in backend/.env first.")
    asyncio.run(_run(args.smoke))


if __name__ == "__main__":
    main()
