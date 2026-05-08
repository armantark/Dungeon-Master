from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Literal

from dungeon_master.cancel import CancellationToken

type SessionStatus = Literal["running", "completed", "failed", "cancelled"]


@dataclass(frozen=True)
class _Subscriber:
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue[str | None]


class StreamSession:
    """Buffered stream plus live tail for one request.

    The producer thread owns canonical progress for an in-flight request and
    appends already-serialized NDJSON lines here. HTTP clients are merely
    subscribers: they replay the buffered lines, then tail the live queue.
    That separation is what lets a browser refresh drop the subscriber without
    cancelling the underlying model work.
    """

    def __init__(
        self,
        *,
        request_id: str,
        route: str,
        save_id: str | None,
        cancel_token: CancellationToken,
    ) -> None:
        self.request_id = request_id
        self.route = route
        self.save_id = save_id
        self.cancel_token = cancel_token
        self.created_at = datetime.now(tz=UTC)
        self._ended_at: datetime | None = None
        self._status: SessionStatus = "running"
        self._events: list[str] = []
        self._subscribers: dict[int, _Subscriber] = {}
        self._next_subscriber_id = 0
        self._lock = Lock()

    @property
    def status(self) -> SessionStatus:
        with self._lock:
            return self._status

    @property
    def ended_at(self) -> datetime | None:
        with self._lock:
            return self._ended_at

    def publish(self, line: str) -> None:
        with self._lock:
            self._events.append(line)
            subscribers = list(self._subscribers.values())
        for subscriber in subscribers:
            subscriber.loop.call_soon_threadsafe(subscriber.queue.put_nowait, line)

    def complete(self) -> None:
        self._finish("completed")

    def fail(self) -> None:
        self._finish("failed")

    def cancel(self) -> None:
        self._finish("cancelled")

    def attach(self) -> AsyncIterator[str]:
        async def iterator() -> AsyncIterator[str]:
            loop = asyncio.get_running_loop()
            queue: asyncio.Queue[str | None] = asyncio.Queue()
            subscriber_id: int | None = None
            with self._lock:
                snapshot = list(self._events)
                terminal = self._status != "running"
                if not terminal:
                    subscriber_id = self._next_subscriber_id
                    self._next_subscriber_id += 1
                    self._subscribers[subscriber_id] = _Subscriber(loop=loop, queue=queue)
            try:
                for line in snapshot:
                    yield line
                if terminal:
                    return
                while True:
                    queued_line = await queue.get()
                    if queued_line is None:
                        return
                    yield queued_line
            finally:
                if subscriber_id is not None:
                    with self._lock:
                        self._subscribers.pop(subscriber_id, None)

        return iterator()

    def expired(self, *, now: datetime, retention_seconds: int) -> bool:
        with self._lock:
            if self._status == "running" or self._ended_at is None:
                return False
            return now - self._ended_at > timedelta(seconds=retention_seconds)

    def _finish(self, status: SessionStatus) -> None:
        with self._lock:
            if self._status != "running":
                return
            self._status = status
            self._ended_at = datetime.now(tz=UTC)
            subscribers = list(self._subscribers.values())
        for subscriber in subscribers:
            subscriber.loop.call_soon_threadsafe(subscriber.queue.put_nowait, None)


class SessionRegistry:
    """Thread-safe lookup table for detached stream sessions."""

    def __init__(self, *, retention_seconds: int = 120) -> None:
        self._retention_seconds = retention_seconds
        self._sessions: dict[str, StreamSession] = {}
        self._lock = Lock()

    def register(
        self,
        *,
        request_id: str,
        route: str,
        save_id: str | None,
        cancel_token: CancellationToken,
    ) -> StreamSession:
        self.sweep_expired()
        session = StreamSession(
            request_id=request_id,
            route=route,
            save_id=save_id,
            cancel_token=cancel_token,
        )
        with self._lock:
            self._sessions[request_id] = session
        return session

    def get(self, request_id: str) -> StreamSession | None:
        self.sweep_expired()
        with self._lock:
            return self._sessions.get(request_id)

    def sweep_expired(self) -> None:
        now = datetime.now(tz=UTC)
        with self._lock:
            expired = [
                request_id
                for request_id, session in self._sessions.items()
                if session.expired(now=now, retention_seconds=self._retention_seconds)
            ]
            for request_id in expired:
                self._sessions.pop(request_id, None)
