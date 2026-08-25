from __future__ import annotations

from threading import Event


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
