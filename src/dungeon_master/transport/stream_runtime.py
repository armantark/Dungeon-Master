from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator, Callable, Generator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Literal, TypeVar

from dungeon_master.application.cancellation import CancellationToken, RequestCancelledError
from dungeon_master.domain.models import GameState
from dungeon_master.llm.narration import CompletionDelta
from dungeon_master.llm.planning import TurnPlanningError

logger = logging.getLogger(__name__)

type SessionStatus = Literal["running", "completed", "failed", "cancelled"]
type PayloadKind = Literal[
    "character_quiz",
    "character_draft",
    "explanation",
]

PayloadResult = TypeVar("PayloadResult")


class StreamSessionNotFoundError(LookupError):
    """Raised when a request has no retained stream session."""


class StreamSessionSaveMismatchError(ValueError):
    """Raised when a retained stream belongs to another active save."""


@dataclass(frozen=True)
class _Subscriber:
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue[str | None]


class StreamSession:
    """One request's cancellation token, replay buffer, and live subscribers."""

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

    def mark_cancelled(self) -> None:
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
    """Own cancellation and retained stream lifecycle by request id."""

    def __init__(self, *, retention_seconds: int = 120) -> None:
        self._retention_seconds = retention_seconds
        self._sessions: dict[str, StreamSession] = {}
        self._lock = Lock()

    def register(
        self,
        request_id: str,
        *,
        route: str,
        save_id: str | None,
    ) -> StreamSession:
        self.sweep_expired()
        session = StreamSession(
            request_id=request_id,
            route=route,
            save_id=save_id,
            cancel_token=CancellationToken(request_id),
        )
        with self._lock:
            self._sessions[request_id] = session
        return session

    def get(self, request_id: str) -> StreamSession | None:
        self.sweep_expired()
        with self._lock:
            return self._sessions.get(request_id)

    def cancel(self, request_id: str) -> bool:
        session = self.get(request_id)
        if session is None or session.status != "running":
            return False
        session.cancel_token.cancel()
        return True

    def has_active_requests(self) -> bool:
        self.sweep_expired()
        with self._lock:
            sessions = list(self._sessions.values())
        return any(session.status == "running" for session in sessions)

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


class StreamRuntime:
    """Run, retain, cancel, and reattach detached NDJSON streams."""

    def __init__(
        self,
        *,
        max_workers: int = 4,
        retention_seconds: int = 120,
    ) -> None:
        self.sessions = SessionRegistry(retention_seconds=retention_seconds)
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="dm-stream",
        )

    def start_game_state(
        self,
        *,
        route: str,
        save_id: str | None,
        generator_factory: Callable[
            [CancellationToken],
            Generator[CompletionDelta, None, GameState],
        ],
    ) -> StreamSession:
        session = self._new_session(route=route, save_id=save_id)
        service_generator = generator_factory(session.cancel_token)
        self._executor.submit(self._drive_game_state, session, service_generator)
        return session

    def start_payload(
        self,
        *,
        route: str,
        save_id: str | None,
        payload_kind: PayloadKind,
        generator_factory: Callable[
            [CancellationToken],
            Generator[CompletionDelta, None, PayloadResult],
        ],
        serializer: Callable[[PayloadResult], dict[str, object]],
    ) -> StreamSession:
        session = self._new_session(route=route, save_id=save_id)
        service_generator = generator_factory(session.cancel_token)
        self._executor.submit(
            self._drive_payload,
            session,
            service_generator,
            payload_kind,
            serializer,
        )
        return session

    def session_for_reattach(
        self,
        request_id: str,
        *,
        active_save_id: str | None,
    ) -> StreamSession:
        session = self.sessions.get(request_id)
        if session is None:
            raise StreamSessionNotFoundError(request_id)
        if session.save_id is not None and active_save_id != session.save_id:
            raise StreamSessionSaveMismatchError(request_id)
        return session

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=True)

    def _new_session(self, *, route: str, save_id: str | None) -> StreamSession:
        request_id = f"req_{uuid.uuid4().hex[:12]}"
        return self.sessions.register(request_id, route=route, save_id=save_id)

    def _drive_game_state(
        self,
        session: StreamSession,
        service_generator: Generator[CompletionDelta, None, GameState],
    ) -> None:
        last_thinking = ""
        session.publish(_meta_event(session.route, session.request_id))
        try:
            while True:
                delta = next(service_generator)
                _publish_delta(session, delta)
                last_thinking += delta.thinking
        except StopIteration as stop:
            final_state = stop.value
            if final_state is not None:
                persisted = _latest_event_thinking(final_state)
                session.publish(
                    _ndjson(
                        {
                            "type": "final_state",
                            "state": final_state.model_dump(mode="json"),
                            "thinking": persisted or last_thinking or None,
                        },
                    ),
                )
            session.complete()
        except RequestCancelledError:
            session.mark_cancelled()
        except TurnPlanningError as exc:
            session.publish(_error_event(str(exc), code="planning_failed"))
            session.fail()
        except ValueError as exc:
            session.publish(_error_event(str(exc), code="conflict"))
            session.fail()
        except Exception as exc:  # pragma: no cover - defensive envelope
            logger.exception("Streaming endpoint failed.")
            session.publish(_error_event(str(exc), code="internal_error"))
            session.fail()

    def _drive_payload(
        self,
        session: StreamSession,
        service_generator: Generator[CompletionDelta, None, PayloadResult],
        payload_kind: PayloadKind,
        serializer: Callable[[PayloadResult], dict[str, object]],
    ) -> None:
        session.publish(_meta_event(session.route, session.request_id))
        try:
            while True:
                delta = next(service_generator)
                _publish_delta(session, delta)
        except StopIteration as stop:
            result = stop.value
            payload = serializer(result)
            thinking = getattr(result, "thinking", "") or ""
            session.publish(
                _ndjson(
                    {
                        "type": "final_payload",
                        "kind": payload_kind,
                        "payload": payload,
                        "thinking": thinking or None,
                    },
                ),
            )
            session.complete()
        except RequestCancelledError:
            session.mark_cancelled()
        except ValueError as exc:
            session.publish(_error_event(str(exc), code="conflict"))
            session.fail()
        except Exception as exc:  # pragma: no cover - defensive envelope
            logger.exception("Streaming endpoint failed.")
            session.publish(_error_event(str(exc), code="internal_error"))
            session.fail()


def _publish_delta(session: StreamSession, delta: CompletionDelta) -> None:
    if delta.stage is not None:
        session.publish(
            _stage_event(
                delta.stage.stage_id,
                delta.stage.label,
                delta.stage.status.value,
            ),
        )
    if delta.thinking:
        session.publish(_ndjson({"type": "thinking_delta", "text": delta.thinking}))
    if delta.content:
        session.publish(_ndjson({"type": "content_delta", "text": delta.content}))


def _latest_event_thinking(state: GameState) -> str:
    for event in reversed(state.action_log):
        if event.thinking:
            return event.thinking
    return ""


def _ndjson(event: object) -> str:
    return json.dumps(event, separators=(",", ":")) + "\n"


def _meta_event(route: str, request_id: str) -> str:
    return _ndjson(
        {
            "type": "meta",
            "request_id": request_id,
            "route": route,
        },
    )


def _error_event(
    message: str,
    *,
    code: str | None,
    state: GameState | None = None,
) -> str:
    return _ndjson(
        {
            "type": "error",
            "message": message,
            "code": code,
            "state": state.model_dump(mode="json") if state is not None else None,
        },
    )


def _stage_event(stage_id: str, label: str, status: str) -> str:
    return _ndjson(
        {
            "type": "stage",
            "stage_id": stage_id,
            "label": label,
            "status": status,
        },
    )
