"""One-time tickets for opening the socket (D122).

A browser cannot put the access token in a WebSocket handshake's headers,
and the token must not go in a URL (logged by proxies). So the page asks
``POST /realtime/ticket`` with its normal ``Authorization: Bearer`` header,
gets a random ticket valid for ``ws_ticket_ttl_seconds``, and sends it as the
socket's first message. The ticket is stored only as a hash, works once,
and only identifies the user: everything they may hear is re-read from the
database when it is redeemed.

In process memory, like the connections it opens (single process: see hub.py).
"""

import hashlib
import secrets
import time
import uuid
from threading import Lock

from app.core.config import settings

MAX_OUTSTANDING = 10_000  # bound on memory if tickets are requested and never used


def _digest(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class TicketStore:
    def __init__(self) -> None:
        self._tickets: dict[str, tuple[uuid.UUID, float]] = {}
        self._lock = Lock()

    def issue(self, user_id: uuid.UUID, ttl_seconds: float | None = None) -> str:
        raw = secrets.token_urlsafe(32)
        expires = time.monotonic() + (ttl_seconds if ttl_seconds is not None else settings.ws_ticket_ttl_seconds)
        with self._lock:
            self._prune()
            if len(self._tickets) >= MAX_OUTSTANDING:
                self._tickets.pop(next(iter(self._tickets)))  # oldest first (insertion order)
            self._tickets[_digest(raw)] = (user_id, expires)
        return raw

    def redeem(self, raw: object) -> uuid.UUID | None:
        """The ticket's user, once; None if unknown, used or expired."""
        if not isinstance(raw, str) or not 20 <= len(raw) <= 100:
            return None
        with self._lock:
            found = self._tickets.pop(_digest(raw), None)
        if found is None:
            return None
        user_id, expires = found
        return user_id if time.monotonic() < expires else None

    def _prune(self) -> None:
        now = time.monotonic()
        for key in [k for k, (_, expires) in self._tickets.items() if expires <= now]:
            del self._tickets[key]

    def clear(self) -> None:
        with self._lock:
            self._tickets.clear()

    def __len__(self) -> int:
        return len(self._tickets)


tickets = TicketStore()
