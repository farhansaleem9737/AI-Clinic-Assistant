"""Open sockets of this process and who hears what (D122).

In memory: it reaches only the connections this process owns. The API runs
as one uvicorn process (backend/Dockerfile, no --workers), so that is every
connection. With several processes or instances, ``publish`` would have to
go through a shared broker (Postgres LISTEN/NOTIFY, Redis) instead; the
callers (``capture``) and the browser would not change.

Sending never blocks the publisher: each connection has a bounded outbox
drained by its own task. A client that falls ``ws_queue_size`` messages
behind, or takes longer than ``ws_send_timeout_seconds`` for one, is closed
and reconnects (re-reading everything), instead of slowing anyone else.
"""

import asyncio
import logging
import uuid
from collections import defaultdict

from app.core.config import settings
from app.realtime.events import Event

logger = logging.getLogger(__name__)

# Close codes (4000-4999 are the application's own).
UNAUTHORIZED = 4401  # no or bad ticket, account deactivated or signed out everywhere
TOO_MANY = 4429  # over the per-user or per-process connection limit
TOO_SLOW = 4408  # could not keep up
GOING_AWAY = 1012  # server restarting: reconnect shortly
POLICY = 1008  # forbidden origin, message too large or too frequent
RECONNECT = 4000  # roles changed: reconnect now to be subscribed afresh


class Connection:
    """One browser tab's socket. ``closed`` is set with a code when it must go."""

    def __init__(self, user_id: uuid.UUID, channels: frozenset[str], queue_size: int | None = None) -> None:
        self.id = uuid.uuid4()
        self.user_id = user_id
        self.channels = channels
        self.outbox: asyncio.Queue[str] = asyncio.Queue(maxsize=queue_size or settings.ws_queue_size)
        self.closed = asyncio.Event()
        self.close_code: int | None = None
        self.close_reason = ""
        self.watched: set[uuid.UUID] = set()  # patients whose record this connection was authorized to watch

    def offer(self, message: str) -> None:
        """Queue a message without waiting. A full outbox means too slow."""
        if self.closed.is_set():
            return
        try:
            self.outbox.put_nowait(message)
        except asyncio.QueueFull:
            logger.warning("realtime_client_too_slow", extra={"connection": str(self.id)})
            self.close(TOO_SLOW, "too slow")

    def close(self, code: int, reason: str = "") -> None:
        if not self.closed.is_set():
            self.close_code, self.close_reason = code, reason
            self.closed.set()


class Hub:
    def __init__(self) -> None:
        self._connections: set[Connection] = set()
        self._by_user: dict[uuid.UUID, set[Connection]] = defaultdict(set)
        self._by_channel: dict[str, set[Connection]] = defaultdict(set)

    # ---- registry ----------------------------------------------------------------

    def register(self, conn: Connection) -> bool:
        """Add a connection; False when a limit is reached (it is not added)."""
        if len(self._connections) >= settings.ws_max_connections:
            return False
        if len(self._by_user[conn.user_id]) >= settings.ws_max_connections_per_user:
            if not self._by_user[conn.user_id]:
                del self._by_user[conn.user_id]
            return False
        self._connections.add(conn)
        self._by_user[conn.user_id].add(conn)
        for channel in conn.channels:
            self._by_channel[channel].add(conn)
        return True

    def unregister(self, conn: Connection) -> None:
        self._connections.discard(conn)
        self._discard(self._by_user, conn.user_id, conn)
        for channel in conn.channels:
            self._discard(self._by_channel, channel, conn)

    def watch(self, conn: Connection, channel: str) -> None:
        """Add one extra channel the caller was authorized for (a patient's record)."""
        if conn in self._connections and channel not in conn.channels:
            conn.channels = conn.channels | {channel}
            self._by_channel[channel].add(conn)

    def unwatch(self, conn: Connection, channel: str) -> None:
        if channel in conn.channels:
            conn.channels = conn.channels - {channel}
            self._discard(self._by_channel, channel, conn)

    def resubscribe(self, conn: Connection, channels: frozenset[str]) -> None:
        """Permissions changed (re-read on revalidation): move the connection."""
        if conn not in self._connections:
            return
        for channel in conn.channels - channels:
            self._discard(self._by_channel, channel, conn)
        for channel in channels - conn.channels:
            self._by_channel[channel].add(conn)
        conn.channels = channels

    @staticmethod
    def _discard(index: dict, key, conn: Connection) -> None:
        bucket = index.get(key)
        if bucket is not None:
            bucket.discard(conn)
            if not bucket:
                del index[key]  # no empty buckets left behind

    # ---- delivery ----------------------------------------------------------------

    def publish(self, event: Event) -> int:
        """Hand an event to every connection on its channels (each once).
        Synchronous and non-blocking: safe to call from a commit hook."""
        targets: set[Connection] = set()
        for channel in event.channels:
            targets |= self._by_channel.get(channel, set())
        if not targets:
            return 0
        message = event.to_json()
        for conn in targets:
            conn.offer(message)
        return len(targets)

    def close_user(self, user_id: uuid.UUID, code: int = UNAUTHORIZED, reason: str = "signed out") -> None:
        for conn in list(self._by_user.get(user_id, ())):
            conn.close(code, reason)

    async def shutdown(self, wait_seconds: float = 2) -> None:
        """Ask every connection to close (clients reconnect to the next process)."""
        for conn in list(self._connections):
            conn.close(GOING_AWAY, "server restarting")
        deadline = asyncio.get_running_loop().time() + wait_seconds
        while self._connections and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.05)

    # ---- introspection (tests, health) -------------------------------------------

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    def connections_of(self, user_id: uuid.UUID) -> int:
        return len(self._by_user.get(user_id, ()))

    def channel_count(self) -> int:
        return len(self._by_channel)


hub = Hub()
