import logging
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import request_id_var

logger = logging.getLogger("app.request")

REQUEST_ID_HEADER = "X-Request-ID"


class RequestContextMiddleware:
    """Assign a request id, return it as a header, and log one line per request.

    The log line has method, path, status and duration only — no query string,
    headers or body, since those can carry tokens or patient search terms.
    Written as plain ASGI middleware so the context variable is visible to the
    exception handlers.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = uuid.uuid4().hex
        # Deliberately not reset afterwards: Starlette's catch-all 500 handler
        # runs *outside* user middleware and still needs the id. Each request is
        # served in its own context, so the value cannot leak between requests.
        request_id_var.set(request_id)
        started = time.perf_counter()
        status_code = 500

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                message.setdefault("headers", [])
                message["headers"].append((REQUEST_ID_HEADER.lower().encode(), request_id.encode()))
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            logger.info(
                "request",
                extra={
                    "method": scope["method"],
                    "path": scope["path"],
                    "status": status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                },
            )
