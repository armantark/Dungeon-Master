from __future__ import annotations

from threading import Event, Lock


class RequestCancelledError(RuntimeError):
    """Raised when an in-flight streamed request is cancelled."""


class CancellationToken:
    """Process-local token for cooperatively cancelling long-running work."""

    def __init__(self, request_id: str) -> None:
        self.request_id = request_id
        self._event = Event()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            message = f"Request cancelled: {self.request_id}"
            raise RequestCancelledError(message)


class CancellationRegistry:
    """Tracks the currently active streamed requests for this process."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._tokens: dict[str, CancellationToken] = {}

    def register(self, request_id: str) -> CancellationToken:
        token = CancellationToken(request_id)
        with self._lock:
            self._tokens[request_id] = token
        return token

    def cancel(self, request_id: str) -> bool:
        with self._lock:
            token = self._tokens.get(request_id)
        if token is None:
            return False
        token.cancel()
        return True

    def unregister(self, request_id: str) -> None:
        with self._lock:
            self._tokens.pop(request_id, None)
