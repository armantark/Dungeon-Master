"""HTTP adaptation for retained backend stream sessions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi.responses import StreamingResponse

from dungeon_master.application.cancellation import CancellationToken
from dungeon_master.domain.models import GameState
from dungeon_master.llm.narration import CompletionDelta
from dungeon_master.persistence.save_library import SaveLibrary
from dungeon_master.transport.stream_runtime import (
    PayloadKind,
    StreamRuntime,
    StreamSession,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    from fastapi import FastAPI, Request


def active_save_id(app: FastAPI) -> str | None:
    library = getattr(app.state, "save_library", None)
    return library.active_save_id() if isinstance(library, SaveLibrary) else None


def streaming_response(session: StreamSession) -> StreamingResponse:
    return StreamingResponse(session.attach(), media_type="application/x-ndjson")


def start_game_state_stream(
    request: Request,
    *,
    generator_factory: Callable[
        [CancellationToken],
        Generator[CompletionDelta, None, GameState],
    ],
    route: str,
    stream_runtime: StreamRuntime,
) -> StreamingResponse:
    session = stream_runtime.start_game_state(
        route=route,
        save_id=active_save_id(request.app),
        generator_factory=generator_factory,
    )
    return streaming_response(session)


def start_setup_stream[SetupResult](  # noqa: PLR0913
    request: Request,
    *,
    generator_factory: Callable[
        [CancellationToken],
        Generator[CompletionDelta, None, SetupResult],
    ],
    route: str,
    payload_kind: PayloadKind,
    serialize: Callable[[SetupResult], dict[str, object]],
    stream_runtime: StreamRuntime,
) -> StreamingResponse:
    session = stream_runtime.start_payload(
        route=route,
        save_id=active_save_id(request.app),
        generator_factory=generator_factory,
        payload_kind=payload_kind,
        serializer=serialize,
    )
    return streaming_response(session)
