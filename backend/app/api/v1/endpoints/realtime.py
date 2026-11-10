"""Live updates (D122): a one-time ticket, then the WebSocket.

1. ``POST /realtime/ticket`` (normal Bearer auth) → a ticket valid for seconds.
2. ``GET /ws`` (upgrade): the origin is checked before accepting; the first
   message must be ``{"type": "auth", "ticket": "..."}`` within a few seconds.
   The ticket's user is re-read from the database (active, roles, ids) and the
   connection is subscribed to the channels that account may hear.
3. The server then sends ``{"type": "ready"}`` and events. The client may send
   ``{"type": "ping"}`` (answered with ``pong``), and ``{"type": "watch" |
   "unwatch", "patient_id": ...}``: a treating doctor's open patient page asks
   for that patient's record changes. Each watch is authorized exactly like a
   read of the record (health_record_service.may_read) and re-checked on
   revalidation. Nothing else is accepted; channels are otherwise the server's.
   Every ``ws_revalidate_seconds`` the account is read again: deactivated or
   signed out everywhere closes the socket (4401); changed roles move it.
   Deactivation, a password change or reset, and role changes also act at
   once, when they commit (capture.end_sessions / roles changed).

Events only name what changed; pages re-read through the REST API.
"""

import asyncio
import json
import logging
import time
import uuid
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, WebSocket
from pydantic import BaseModel
from sqlalchemy import exists, select
from starlette.websockets import WebSocketDisconnect, WebSocketState

from app.api.deps.auth import get_current_principal
from app.core import clock
from app.core.config import Environment, settings
from app.core.exceptions import NotFoundError
from app.core.permissions import Principal
from app.core.rate_limit import rate_limit
from app.db.database import AsyncSessionLocal
from app.models.refresh_token import RefreshToken
from app.realtime.events import channels_for, record_channel
from app.realtime.hub import POLICY, TOO_MANY, TOO_SLOW, UNAUTHORIZED, Connection, hub
from app.realtime.tickets import tickets
from app.services import health_record_service, rbac_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["realtime"])

AUTH_TIMEOUT_SECONDS = 10
MAX_MESSAGE_BYTES = 1024
MAX_MESSAGES_PER_WINDOW = 30  # pings come every ~25 s; this is generous
MESSAGE_WINDOW_SECONDS = 10
MAX_WATCHES = 10  # patient records one connection may watch at once


class Ticket(BaseModel):
    ticket: str
    expires_in: int


@router.post("/realtime/ticket", response_model=Ticket, dependencies=[Depends(rate_limit("ws_ticket", lambda: settings.ws_tickets_per_minute))])
async def issue_ticket(principal: Principal = Depends(get_current_principal)) -> Ticket:
    if not settings.realtime_enabled:
        raise NotFoundError("Live updates are switched off", code="REALTIME_DISABLED")
    return Ticket(ticket=tickets.issue(principal.user_id), expires_in=settings.ws_ticket_ttl_seconds)


# ---- the socket ----------------------------------------------------------------------------


def origin_allowed(origin: str | None, host: str | None) -> bool:
    """Cross-site WebSocket hijacking guard: browsers always send Origin."""
    if settings.environment is Environment.development:
        return True  # Vite proxy, a phone on the LAN; the ticket is still required
    if not origin:
        return False
    origin = origin.rstrip("/")
    if origin in (settings.ws_allowed_origins or settings.cors_origins):
        return True
    return bool(host) and urlsplit(origin).netloc == host  # served from the API's own origin


async def load_principal(user_id: uuid.UUID, *, require_session: bool = False) -> Principal | None:
    """The account behind a connection, read fresh. None = it may no longer listen."""
    async with AsyncSessionLocal() as db:
        principal = await rbac_service.load_principal_by_id(db, user_id)
        if principal is None or not principal.user.is_active:
            return None
        if require_session:
            # Signed out everywhere (every refresh token revoked or expired): stop listening too.
            live = await db.scalar(
                select(
                    exists().where(
                        RefreshToken.user_id == user_id,
                        RefreshToken.revoked_at.is_(None),
                        RefreshToken.expires_at > clock.utcnow(),
                    )
                )
            )
            if not live:
                return None
        return principal


async def may_watch(user_id: uuid.UUID, patient_id: uuid.UUID) -> bool:
    """May this account read (and so watch) the patient's health record now?"""
    async with AsyncSessionLocal() as db:
        principal = await rbac_service.load_principal_by_id(db, user_id)
        if principal is None or not principal.user.is_active:
            return False
        return await health_record_service.may_read(db, principal, patient_id)


def _patient_id(message: dict) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(message.get("patient_id")))
    except ValueError:
        return None


async def _watch(conn: Connection, message: dict) -> None:
    patient_id = _patient_id(message)
    if patient_id is None:
        conn.offer(json.dumps({"type": "error", "code": "INVALID_MESSAGE"}))
        return
    if message.get("type") == "unwatch":
        conn.watched.discard(patient_id)
        hub.unwatch(conn, record_channel(patient_id))
        return
    if patient_id not in conn.watched and len(conn.watched) >= MAX_WATCHES:
        conn.offer(json.dumps({"type": "error", "code": "WATCH_LIMIT"}))
        return
    # Not allowed and no such patient look the same, like the API's 404.
    if not await may_watch(conn.user_id, patient_id):
        conn.offer(json.dumps({"type": "error", "code": "WATCH_DENIED", "patient_id": str(patient_id)}))
        return
    conn.watched.add(patient_id)
    hub.watch(conn, record_channel(patient_id))
    conn.offer(json.dumps({"type": "watching", "patient_id": str(patient_id)}))


async def _close(websocket: WebSocket, code: int, reason: str = "") -> None:
    if websocket.client_state == WebSocketState.CONNECTED:
        try:
            await asyncio.wait_for(websocket.close(code=code, reason=reason), timeout=2)
        except Exception:  # already gone
            pass


async def _authenticate(websocket: WebSocket) -> uuid.UUID | None:
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=AUTH_TIMEOUT_SECONDS)
    except (TimeoutError, WebSocketDisconnect, RuntimeError, KeyError):
        return None
    if len(raw) > MAX_MESSAGE_BYTES:
        return None
    try:
        message = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(message, dict) or message.get("type") != "auth":
        return None
    return tickets.redeem(message.get("ticket"))


async def _receive(websocket: WebSocket, conn: Connection) -> None:
    """Pings only. Oversized, too frequent or malformed traffic closes the socket."""
    window_start, count = time.monotonic(), 0
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return
        text = message.get("text")
        if text is None or len(text) > MAX_MESSAGE_BYTES:
            conn.close(POLICY, "message not allowed")
            return
        now = time.monotonic()
        if now - window_start >= MESSAGE_WINDOW_SECONDS:
            window_start, count = now, 0
        count += 1
        if count > MAX_MESSAGES_PER_WINDOW:
            conn.close(POLICY, "too many messages")
            return
        try:
            parsed = json.loads(text)
            kind = parsed.get("type")
        except (ValueError, AttributeError):
            parsed, kind = None, None
        if kind == "ping":
            conn.offer('{"type":"pong"}')
        elif kind in ("watch", "unwatch"):
            await _watch(conn, parsed)
        else:
            # Channels are assigned by the server; "subscribe" and anything else is refused.
            conn.offer(json.dumps({"type": "error", "code": "UNSUPPORTED_MESSAGE"}))


async def _send(websocket: WebSocket, conn: Connection) -> None:
    while True:
        message = await conn.outbox.get()
        try:
            await asyncio.wait_for(websocket.send_text(message), timeout=settings.ws_send_timeout_seconds)
        except TimeoutError:
            conn.close(TOO_SLOW, "too slow")
            return


async def _revalidate(conn: Connection) -> None:
    while True:
        await asyncio.sleep(settings.ws_revalidate_seconds)
        principal = await load_principal(conn.user_id, require_session=True)
        if principal is None:
            conn.close(UNAUTHORIZED, "session ended")
            return
        hub.resubscribe(conn, channels_for(principal))
        # Watches are re-authorized too (e.g. no longer this patient's doctor).
        for patient_id in list(conn.watched):
            if await may_watch(conn.user_id, patient_id):
                hub.watch(conn, record_channel(patient_id))
            else:
                conn.watched.discard(patient_id)


@router.websocket("/ws")
async def realtime_socket(websocket: WebSocket) -> None:
    if not settings.realtime_enabled or not origin_allowed(websocket.headers.get("origin"), websocket.headers.get("host")):
        await websocket.close(code=POLICY)  # before accept: the handshake is refused (403)
        return
    await websocket.accept()

    user_id = await _authenticate(websocket)
    principal = await load_principal(user_id) if user_id else None
    if principal is None:
        await _close(websocket, UNAUTHORIZED, "unauthorized")
        return

    conn = Connection(principal.user_id, channels_for(principal))
    if not hub.register(conn):
        await _close(websocket, TOO_MANY, "too many connections")
        return
    tasks: list[asyncio.Task] = []
    try:
        await websocket.send_text(json.dumps({"type": "ready", "version": 1}))
        tasks = [
            asyncio.create_task(_receive(websocket, conn)),
            asyncio.create_task(_send(websocket, conn)),
            asyncio.create_task(_revalidate(conn)),
            asyncio.create_task(conn.closed.wait()),
        ]
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            if not task.cancelled() and task.exception() is not None and not isinstance(task.exception(), WebSocketDisconnect):
                logger.warning("realtime_connection_error", extra={"error": type(task.exception()).__name__})
    except WebSocketDisconnect:
        pass
    finally:
        hub.unregister(conn)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await _close(websocket, conn.close_code or 1000, conn.close_reason)

