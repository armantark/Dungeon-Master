"""HTTP surface for the deterministic-oracle / LLM-narrative game.

The API is intentionally thin: every mutation funnels through `GameService`
and returns the entire `GameState`. Returning the whole state on every
request keeps the frontend trivially reconcilable (no diff protocol, no
optimistic state) and matches the personal-use single-writer assumption.
The Python side stays the single source of truth; the LLM never edits state.
"""

from __future__ import annotations

import json
import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal

from fastapi import APIRouter, Body, Depends, FastAPI, HTTPException, Request, status
from fastapi import Path as ApiPath
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from dungeon_master.campaign import CharacterDraftMode
from dungeon_master.cancel import CancellationRegistry, RequestCancelledError
from dungeon_master.models import (
    AttackStance,
    CairnAbility,
    CairnRestKind,
    CampaignEndReason,
    CharacterQuiz,
    CharacterQuizAnswer,
    CharacterSheet,
    GameState,
    Likelihood,
)
from dungeon_master.narrative import CompletionDelta
from dungeon_master.save_library import SaveLibrary, SaveSummary
from dungeon_master.service import GameService
from dungeon_master.settings import state_path_from_env
from dungeon_master.state_store import StateStore
from dungeon_master.turn_router import TurnPlanningError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Generator

logger = logging.getLogger(__name__)


class ChaosFactorRequest(BaseModel):
    value: int = Field(ge=1, le=9)


class NotesRequest(BaseModel):
    setting_notes: str = Field(min_length=1)
    player_notes: str = Field(min_length=1)


class DirectivesRequest(BaseModel):
    world_guidance: str = ""
    play_guidance: str = ""


class YesNoRequest(BaseModel):
    question: str = Field(min_length=1)
    likelihood: Likelihood


class SceneCheckRequest(BaseModel):
    expected_scene: str = Field(min_length=1)


class PlayerActionRequest(BaseModel):
    action: str = Field(min_length=1)


class PlayerTurnRequest(BaseModel):
    text: str = Field(min_length=1)


class ExplainRequest(BaseModel):
    question: str = Field(min_length=1)


class CairnSaveRequest(BaseModel):
    ability: CairnAbility
    reason: str = Field(min_length=1)


class CairnAttackRequest(BaseModel):
    target_name: str = Field(min_length=1)
    target_armor: int = Field(default=0, ge=0, le=3)
    weapon_item_id: str | None = None
    stance: AttackStance = AttackStance.NORMAL


class CairnHarmRequest(BaseModel):
    amount: int = Field(ge=0)
    source: str = Field(min_length=1)
    in_combat: bool = True
    armor_applies: bool = True


class CairnRecoveryRequest(BaseModel):
    kind: CairnRestKind


class CairnRetreatRequest(BaseModel):
    reason: str = Field(min_length=1)


class CairnAcquireRequest(BaseModel):
    text: str = Field(min_length=1)


class CairnEquipRequest(BaseModel):
    item_id: str = Field(min_length=1)
    equipped: bool = True


class CharacterDraftRequest(BaseModel):
    mode: CharacterDraftMode
    prompt: str | None = None
    template: CharacterSheet | None = None


class CharacterFinalizeRequest(BaseModel):
    character: CharacterSheet


class CampaignEndRequest(BaseModel):
    reason: CampaignEndReason
    summary: str | None = Field(default=None, min_length=1)


class CharacterTemplatesResponse(BaseModel):
    templates: list[CharacterSheet]
    thinking: str = ""


class CharacterDraftResponse(BaseModel):
    draft: CharacterSheet
    thinking: str = ""


class CharacterQuizRequest(BaseModel):
    concept: str = Field(min_length=1, max_length=2000)


class CharacterQuizResponse(BaseModel):
    quiz: CharacterQuiz
    thinking: str = ""


class ExplanationResponse(BaseModel):
    answer: str
    thinking: str = ""


class CreateSaveRequest(BaseModel):
    select: bool = True


class SelectSaveRequest(BaseModel):
    save_id: str = Field(min_length=1)


class SaveLibraryBootstrapResponse(BaseModel):
    active_save_id: str | None
    saves: list[SaveSummary]


class CharacterQuizzedDraftRequest(BaseModel):
    concept: str = Field(min_length=1, max_length=2000)
    answers: list[CharacterQuizAnswer] = Field(default_factory=list)
    final_note: str | None = None


class ServiceUnavailableError(RuntimeError):
    """Raised when a request lands before the lifespan has wired up the service."""


class CancelRequestResponse(BaseModel):
    cancelled: bool


def build_service(state_path: Path | None = None) -> GameService:
    """Construct a `GameService` bound to a single state file.

    Kept as a free function so tests can inject a tmp_path without
    monkey-patching environment variables.
    """
    path = state_path or state_path_from_env()
    return GameService(store=StateStore(path))


def build_save_library(legacy_state_path: Path | None = None) -> SaveLibrary:
    path = legacy_state_path or state_path_from_env()
    return SaveLibrary(path)


def get_service(request: Request) -> GameService:
    """FastAPI dependency that pulls the live `GameService` off app state.

    We resolve via `Request.app.state` rather than a closure so each route
    handler can live at module level (testable, mypy-friendly, and easy
    to grep for).
    """
    service = getattr(request.app.state, "service", None)
    if not isinstance(service, GameService):
        library = getattr(request.app.state, "save_library", None)
        if isinstance(library, SaveLibrary) and library.active_save_id() is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No active save selected.",
            )
        raise ServiceUnavailableError
    return service


def get_save_library(request: Request) -> SaveLibrary:
    library = getattr(request.app.state, "save_library", None)
    if not isinstance(library, SaveLibrary):
        raise ServiceUnavailableError
    return library


def get_cancellation_registry(request: Request) -> CancellationRegistry:
    registry = getattr(request.app.state, "cancellation_registry", None)
    if not isinstance(registry, CancellationRegistry):
        raise ServiceUnavailableError
    return registry


ServiceDep = Annotated[GameService, Depends(get_service)]
LibraryDep = Annotated[SaveLibrary, Depends(get_save_library)]
RegistryDep = Annotated[CancellationRegistry, Depends(get_cancellation_registry)]


def _service_seed(app: FastAPI) -> GameService | None:
    seeded = getattr(app.state, "service_template", None)
    if isinstance(seeded, GameService):
        return seeded
    live = getattr(app.state, "service", None)
    if isinstance(live, GameService):
        return live
    return None


def _bind_service_to_active_save(app: FastAPI, save_id: str) -> GameService:
    library = getattr(app.state, "save_library", None)
    if not isinstance(library, SaveLibrary):
        raise ServiceUnavailableError
    state_path = library.state_path_for(save_id)
    seed = _service_seed(app)
    if seed is not None:
        seed.bind_store(StateStore(state_path))
        app.state.service = seed
        return seed

    service = build_service(state_path)
    app.state.service = service
    return service


def _guard_save_library_idle(registry: CancellationRegistry) -> None:
    # F-12 keeps the backend single-active-save for v1. Switching the bound
    # store while a streamed request is still registered would let one request
    # start against save A and commit against save B. We therefore force the
    # conservative invariant: no save creation/selection that changes the
    # active slot while any streamed request is still alive in the registry.
    if registry.has_active_requests():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot switch saves while a request is still in flight.",
        )


router = APIRouter(prefix="/api")


# --- NDJSON streaming helpers ----------------------------------------------
#
# The wire contract is the frontend's discriminated union (see
# `web/src/lib/streaming-types.ts`): one JSON object per `\n`, every event
# carries a `type` discriminator. Why NDJSON over SSE:
#   - The frontend parses NDJSON via fetch+ReadableStream so it can keep
#     using POST bodies (every streamed endpoint takes JSON input).
#   - We avoid SSE's `event:`/`data:` framing entirely; the client never
#     wants resume hints or comments and has to ignore them anyway.
#   - One stream shape across setup and play means the frontend store
#     owns one transport and one error model — see #runStreaming.
#
# `_ndjson` returns a single line; callers compose lines into a
# Generator[str, ...]. `final_state` is for endpoints that mutate
# canonical state; `final_payload` is for setup artifacts (templates /
# quiz / draft). `meta` always fires first; `error` may fire instead of
# (or after) deltas to signal a backend-authored failure.

# Lifecycle order (per the streaming-types contract):
#   meta -> thinking_delta* -> content_delta* -> (final_state|final_payload|error)


def _ndjson(event: object) -> str:
    return json.dumps(event, separators=(",", ":")) + "\n"


def _new_request_id() -> str:
    return f"req_{uuid.uuid4().hex[:12]}"


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


def _stream_game_state(  # noqa: C901
    service_generator: Generator[CompletionDelta, None, GameState],
    *,
    route: str,
    request_id: str,
    cancellation_registry: CancellationRegistry,
) -> StreamingResponse:
    """Wrap a `Generator[CompletionDelta, None, GameState]` as NDJSON.

    The service generator yields `CompletionDelta`s as model output
    streams in and returns the final committed `GameState`. We translate
    each delta into a `thinking_delta`/`content_delta` line, then write a
    `final_state` line after StopIteration. Errors are captured as
    `error` lines so the frontend can branch on `result.kind === "error"`
    instead of having to reason about partial-state HTTP failures.

    Final-event `thinking` is pulled off the last narrative event when
    one exists. The frontend persists thinking on the `GameEvent` itself,
    so this duplicate field is purely a convenience for clients that
    want the full trace immediately rather than re-reading state.
    """

    def event_stream() -> Generator[str, None, None]:
        yield _meta_event(route, request_id)
        last_thinking = ""
        try:
            generator = service_generator
            while True:
                delta = next(generator)
                if delta.thinking:
                    last_thinking += delta.thinking
                    yield _ndjson({"type": "thinking_delta", "text": delta.thinking})
                if delta.content:
                    yield _ndjson({"type": "content_delta", "text": delta.content})
        except StopIteration as stop:
            final_state = stop.value
            if final_state is not None:
                # Prefer the persisted thinking on the latest narrative
                # event when present; that's the canonical record. Fall
                # back to the locally aggregated buffer if the service
                # didn't attach thinking to an event (e.g. campaign
                # start uses a system event, action uses a narrative).
                persisted = _latest_event_thinking(final_state)
                yield _ndjson(
                    {
                        "type": "final_state",
                        "state": final_state.model_dump(mode="json"),
                        "thinking": persisted or last_thinking or None,
                    },
                )
        except RequestCancelledError:
            return
        except TurnPlanningError as exc:
            yield _error_event(str(exc), code="planning_failed")
        except ValueError as exc:
            yield _error_event(str(exc), code="conflict")
        except Exception as exc:  # pragma: no cover - defensive envelope
            logger.exception("Streaming endpoint failed.")
            yield _error_event(str(exc), code="internal_error")
        finally:
            cancellation_registry.unregister(request_id)

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


def _latest_event_thinking(state: GameState) -> str:
    """Return the thinking trace on the latest narrative or system event.

    The frontend reads `event.thinking` off the persisted event, but we
    also surface it on `final_state` so a UI can show the trace before
    re-reading from `state.action_log[-1]`. Returns the empty string when
    no event carries a trace, keeping the JSON field conservative.
    """
    for event in reversed(state.action_log):
        if event.thinking:
            return event.thinking
    return ""


def _stream_setup_payload(  # noqa: PLR0913
    service_generator: Generator[CompletionDelta, None, object],
    *,
    route: Literal["character_quiz", "character_draft", "character_templates", "explanation"],
    payload_kind: Literal["character_quiz", "character_draft", "explanation"],
    serialize: object,
    request_id: str,
    cancellation_registry: CancellationRegistry,
) -> StreamingResponse:
    """Wrap a setup generator (quiz/draft) as NDJSON with `final_payload`.

    `serialize` is a callable `(result) -> dict` that turns the
    generator's terminal value (a `*Result` dataclass) into the
    endpoint-specific payload shape. The shape is the same one the unary
    endpoint returns, minus the `thinking` field — `thinking` is hoisted
    onto the envelope because the frontend stores it once for the whole
    final event, not on every nested key.
    """
    serializer: object = serialize  # narrow alias for the inner closure

    def event_stream() -> Generator[str, None, None]:
        yield _meta_event(route, request_id)
        try:
            while True:
                delta = next(service_generator)
                if delta.thinking:
                    yield _ndjson({"type": "thinking_delta", "text": delta.thinking})
                if delta.content:
                    yield _ndjson({"type": "content_delta", "text": delta.content})
        except StopIteration as stop:
            result = stop.value
            payload = serializer(result)  # type: ignore[operator]
            thinking = getattr(result, "thinking", "") or ""
            yield _ndjson(
                {
                    "type": "final_payload",
                    "kind": payload_kind,
                    "payload": payload,
                    "thinking": thinking or None,
                },
            )
        except RequestCancelledError:
            return
        except ValueError as exc:
            yield _error_event(str(exc), code="conflict")
        except Exception as exc:  # pragma: no cover - defensive envelope
            logger.exception("Streaming endpoint failed.")
            yield _error_event(str(exc), code="internal_error")
        finally:
            cancellation_registry.unregister(request_id)

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/requests/{request_id}/cancel", response_model=CancelRequestResponse)
def cancel_request(
    request_id: Annotated[str, ApiPath(min_length=1)],
    registry: RegistryDep,
) -> CancelRequestResponse:
    return CancelRequestResponse(cancelled=registry.cancel(request_id))


@router.get("/library/bootstrap", response_model=SaveLibraryBootstrapResponse)
def library_bootstrap(library: LibraryDep) -> SaveLibraryBootstrapResponse:
    active_save_id, saves = library.bootstrap_payload()
    return SaveLibraryBootstrapResponse(active_save_id=active_save_id, saves=saves)


@router.post("/library/saves", response_model=SaveLibraryBootstrapResponse)
def create_save(
    request: Request,
    library: LibraryDep,
    registry: RegistryDep,
    payload: Annotated[CreateSaveRequest, Body()] | None = None,
) -> SaveLibraryBootstrapResponse:
    if payload is None:
        payload = CreateSaveRequest()
    if payload.select:
        _guard_save_library_idle(registry)
    seed = _service_seed(request.app)
    create_state = seed.new_setup_state() if seed is not None else build_service().new_setup_state()
    save_id = library.create_save(create_state=create_state, select=payload.select)
    if payload.select:
        _bind_service_to_active_save(request.app, save_id)
    active_save_id, saves = library.bootstrap_payload()
    return SaveLibraryBootstrapResponse(active_save_id=active_save_id, saves=saves)


@router.post("/library/select", response_model=SaveLibraryBootstrapResponse)
def select_save(
    request: Request,
    library: LibraryDep,
    registry: RegistryDep,
    payload: Annotated[SelectSaveRequest, Body()],
) -> SaveLibraryBootstrapResponse:
    _guard_save_library_idle(registry)
    try:
        library.select_active(payload.save_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    _bind_service_to_active_save(request.app, payload.save_id)
    active_save_id, saves = library.bootstrap_payload()
    return SaveLibraryBootstrapResponse(active_save_id=active_save_id, saves=saves)


@router.get("/state", response_model=GameState)
def read_state(svc: ServiceDep) -> GameState:
    try:
        return svc.load_state()
    except Exception as exc:
        logger.exception("Failed to load state.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load state: {exc}",
        ) from exc


@router.post("/state/reset", response_model=GameState)
def reset(svc: ServiceDep) -> GameState:
    return svc.reset()


@router.post("/state/chaos", response_model=GameState)
def set_chaos(svc: ServiceDep, payload: Annotated[ChaosFactorRequest, Body()]) -> GameState:
    return svc.set_chaos_factor(payload.value)


@router.post("/state/notes", response_model=GameState)
def update_notes(svc: ServiceDep, payload: Annotated[NotesRequest, Body()]) -> GameState:
    try:
        return svc.update_notes(
            setting_notes=payload.setting_notes,
            player_notes=payload.player_notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/state/directives", response_model=GameState)
def update_directives(svc: ServiceDep, payload: Annotated[DirectivesRequest, Body()]) -> GameState:
    try:
        return svc.update_directives(
            world_guidance=payload.world_guidance,
            play_guidance=payload.play_guidance,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/oracle/yes-no", response_model=GameState)
def ask_oracle(svc: ServiceDep, payload: Annotated[YesNoRequest, Body()]) -> GameState:
    try:
        return svc.ask_oracle(payload.question, payload.likelihood)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/oracle/random-event", response_model=GameState)
def random_event(svc: ServiceDep) -> GameState:
    try:
        return svc.generate_random_event()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/oracle/scene-check", response_model=GameState)
def scene_check(svc: ServiceDep, payload: Annotated[SceneCheckRequest, Body()]) -> GameState:
    try:
        return svc.check_scene(payload.expected_scene)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/action", response_model=GameState)
def submit_action(
    svc: ServiceDep,
    payload: Annotated[PlayerActionRequest, Body()],
) -> GameState:
    try:
        return svc.submit_player_action(payload.action)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/action/stream")
def submit_action_stream(
    svc: ServiceDep,
    registry: RegistryDep,
    payload: Annotated[PlayerActionRequest, Body()],
) -> StreamingResponse:
    request_id = _new_request_id()
    token = registry.register(request_id)
    return _stream_game_state(
        svc.stream_submit_player_action(payload.action, cancel_token=token),
        route="player_action",
        request_id=request_id,
        cancellation_registry=registry,
    )


@router.post("/turn", response_model=GameState)
def submit_turn(
    svc: ServiceDep,
    payload: Annotated[PlayerTurnRequest, Body()],
) -> GameState:
    try:
        return svc.submit_player_turn(payload.text)
    except TurnPlanningError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/turn/stream")
def submit_turn_stream(
    svc: ServiceDep,
    registry: RegistryDep,
    payload: Annotated[PlayerTurnRequest, Body()],
) -> StreamingResponse:
    # We label the route as `player_action` here because the backend's
    # turn router decides the *real* route inside the service. The
    # frontend uses the `meta` route only to label the provisional
    # bubble, and `player_action` is the conservative default that
    # matches every prose-producing branch.
    request_id = _new_request_id()
    token = registry.register(request_id)
    return _stream_game_state(
        svc.stream_submit_player_turn(payload.text, cancel_token=token),
        route="player_action",
        request_id=request_id,
        cancellation_registry=registry,
    )


@router.post("/explain", response_model=ExplanationResponse)
def explain(
    svc: ServiceDep,
    payload: Annotated[ExplainRequest, Body()],
) -> ExplanationResponse:
    try:
        result = svc.explain(payload.question)
        return ExplanationResponse(answer=result.answer, thinking=result.thinking)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/explain/stream")
def explain_stream(
    svc: ServiceDep,
    registry: RegistryDep,
    payload: Annotated[ExplainRequest, Body()],
) -> StreamingResponse:
    request_id = _new_request_id()
    token = registry.register(request_id)
    return _stream_setup_payload(
        svc.stream_explain(payload.question, cancel_token=token),
        route="explanation",
        payload_kind="explanation",
        serialize=lambda result: {"answer": result.answer},
        request_id=request_id,
        cancellation_registry=registry,
    )


@router.post("/cairn/save", response_model=GameState)
def cairn_save(
    svc: ServiceDep,
    payload: Annotated[CairnSaveRequest, Body()],
) -> GameState:
    try:
        return svc.resolve_cairn_save(payload.ability, payload.reason)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/cairn/attack", response_model=GameState)
def cairn_attack(
    svc: ServiceDep,
    payload: Annotated[CairnAttackRequest, Body()],
) -> GameState:
    try:
        return svc.attack_target(
            target_name=payload.target_name,
            target_armor=payload.target_armor,
            weapon_item_id=payload.weapon_item_id,
            stance=payload.stance,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/cairn/harm", response_model=GameState)
def cairn_harm(
    svc: ServiceDep,
    payload: Annotated[CairnHarmRequest, Body()],
) -> GameState:
    try:
        return svc.suffer_harm(
            amount=payload.amount,
            source=payload.source,
            in_combat=payload.in_combat,
            armor_applies=payload.armor_applies,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/cairn/recover", response_model=GameState)
def cairn_recover(
    svc: ServiceDep,
    payload: Annotated[CairnRecoveryRequest, Body()],
) -> GameState:
    try:
        return svc.recover_character(payload.kind)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/cairn/retreat", response_model=GameState)
def cairn_retreat(
    svc: ServiceDep,
    payload: Annotated[CairnRetreatRequest, Body()],
) -> GameState:
    try:
        return svc.retreat_from_encounter(payload.reason)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/cairn/acquire", response_model=GameState)
def cairn_acquire(
    svc: ServiceDep,
    payload: Annotated[CairnAcquireRequest, Body()],
) -> GameState:
    try:
        return svc.acquire_inventory(payload.text)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/cairn/equip", response_model=GameState)
def cairn_equip(
    svc: ServiceDep,
    payload: Annotated[CairnEquipRequest, Body()],
) -> GameState:
    try:
        return svc.set_item_equipped(item_id=payload.item_id, equipped=payload.equipped)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/character/templates", response_model=CharacterTemplatesResponse)
def character_templates(svc: ServiceDep) -> CharacterTemplatesResponse:
    result = svc.list_character_templates_result()
    return CharacterTemplatesResponse(templates=result.templates, thinking=result.thinking)


@router.get("/character/templates/stream")
def character_templates_stream(
    svc: ServiceDep,
    registry: RegistryDep,
) -> StreamingResponse:
    request_id = _new_request_id()
    token = registry.register(request_id)
    return _stream_setup_payload(
        svc.stream_character_templates(cancel_token=token),
        route="character_templates",
        payload_kind="character_draft",
        serialize=lambda result: {
            "templates": [t.model_dump(mode="json") for t in result.templates],
        },
        request_id=request_id,
        cancellation_registry=registry,
    )


@router.post("/character/draft", response_model=CharacterDraftResponse)
def character_draft(
    svc: ServiceDep,
    payload: Annotated[CharacterDraftRequest, Body()],
) -> CharacterDraftResponse:
    result = svc.generate_character_draft_result(
        mode=payload.mode,
        prompt=payload.prompt,
        template=payload.template,
    )
    return CharacterDraftResponse(draft=result.draft, thinking=result.thinking)


@router.post("/character/draft/stream")
def character_draft_stream(
    svc: ServiceDep,
    registry: RegistryDep,
    payload: Annotated[CharacterDraftRequest, Body()],
) -> StreamingResponse:
    request_id = _new_request_id()
    token = registry.register(request_id)
    return _stream_setup_payload(
        svc.stream_character_draft(
            mode=payload.mode,
            prompt=payload.prompt,
            template=payload.template,
            cancel_token=token,
        ),
        route="character_draft",
        payload_kind="character_draft",
        serialize=lambda result: {"draft": result.draft.model_dump(mode="json")},
        request_id=request_id,
        cancellation_registry=registry,
    )


@router.post("/character/quiz", response_model=CharacterQuizResponse)
def character_quiz(
    svc: ServiceDep,
    payload: Annotated[CharacterQuizRequest, Body()],
) -> CharacterQuizResponse:
    result = svc.generate_character_quiz_result(payload.concept)
    return CharacterQuizResponse(quiz=result.quiz, thinking=result.thinking)


@router.post("/character/quiz/stream")
def character_quiz_stream(
    svc: ServiceDep,
    registry: RegistryDep,
    payload: Annotated[CharacterQuizRequest, Body()],
) -> StreamingResponse:
    request_id = _new_request_id()
    token = registry.register(request_id)
    return _stream_setup_payload(
        svc.stream_character_quiz(payload.concept, cancel_token=token),
        route="character_quiz",
        payload_kind="character_quiz",
        serialize=lambda result: {"quiz": result.quiz.model_dump(mode="json")},
        request_id=request_id,
        cancellation_registry=registry,
    )


@router.post("/character/draft/quizzed", response_model=CharacterDraftResponse)
def character_quizzed_draft(
    svc: ServiceDep,
    payload: Annotated[CharacterQuizzedDraftRequest, Body()],
) -> CharacterDraftResponse:
    result = svc.generate_quizzed_character_draft_result(
        concept=payload.concept,
        answers=payload.answers,
        final_note=payload.final_note,
    )
    return CharacterDraftResponse(draft=result.draft, thinking=result.thinking)


@router.post("/character/draft/quizzed/stream")
def character_quizzed_draft_stream(
    svc: ServiceDep,
    registry: RegistryDep,
    payload: Annotated[CharacterQuizzedDraftRequest, Body()],
) -> StreamingResponse:
    request_id = _new_request_id()
    token = registry.register(request_id)
    return _stream_setup_payload(
        svc.stream_quizzed_character_draft(
            concept=payload.concept,
            answers=payload.answers,
            final_note=payload.final_note,
            cancel_token=token,
        ),
        route="character_draft",
        payload_kind="character_draft",
        serialize=lambda result: {"draft": result.draft.model_dump(mode="json")},
        request_id=request_id,
        cancellation_registry=registry,
    )


@router.post("/character/finalize", response_model=GameState)
def finalize_character(
    svc: ServiceDep,
    payload: Annotated[CharacterFinalizeRequest, Body()],
) -> GameState:
    return svc.finalize_character(payload.character)


@router.post("/campaign/start", response_model=GameState)
def start_campaign(svc: ServiceDep) -> GameState:
    try:
        return svc.start_campaign()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/campaign/end", response_model=GameState)
def end_campaign(
    svc: ServiceDep,
    payload: Annotated[CampaignEndRequest, Body()],
) -> GameState:
    try:
        return svc.end_campaign(reason=payload.reason, summary=payload.summary)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/campaign/start/stream")
def start_campaign_stream(
    svc: ServiceDep,
    registry: RegistryDep,
) -> StreamingResponse:
    # Adapt `Generator[..., CampaignWorldResult]` to the
    # `Generator[..., GameState]` shape that `_stream_game_state` expects
    # by unwrapping `.state` on completion. The wrapper below mirrors
    # the unary `start_campaign` path: a `ValueError` from the underlying
    # generator (e.g. campaign already active) is allowed to bubble so
    # the streaming envelope can convert it into an `error` event.
    request_id = _new_request_id()
    token = registry.register(request_id)
    inner = svc.stream_start_campaign(cancel_token=token)

    def adapter() -> Generator[CompletionDelta, None, GameState]:
        result = yield from inner
        return result.state

    return _stream_game_state(
        adapter(),
        route="campaign_start",
        request_id=request_id,
        cancellation_registry=registry,
    )


@router.post("/messages/{event_id}/regenerate", response_model=GameState)
def regenerate_message(
    svc: ServiceDep,
    event_id: Annotated[str, ApiPath(min_length=1)],
) -> GameState:
    try:
        return svc.regenerate_response(event_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/messages/{event_id}/regenerate/stream")
def regenerate_message_stream(
    svc: ServiceDep,
    registry: RegistryDep,
    event_id: Annotated[str, ApiPath(min_length=1)],
) -> StreamingResponse:
    request_id = _new_request_id()
    token = registry.register(request_id)
    return _stream_game_state(
        svc.stream_regenerate_response(event_id, cancel_token=token),
        route="regenerate",
        request_id=request_id,
        cancellation_registry=registry,
    )


def create_app(
    service: GameService | None = None,
    save_library: SaveLibrary | None = None,
) -> FastAPI:
    """Create the FastAPI application.

    Pass an explicit `service` from tests to preserve the old single-save
    behavior. In production, the app now boots through a save library that
    resolves one active save slot (or none, if the user has not created one
    yet) and binds the gameplay service to that slot.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        library = save_library
        if library is None and service is None:
            library = build_save_library()

        app.state.save_library = library
        app.state.service_template = service

        if library is not None:
            library.ensure_initialized()
            active_state_path = library.active_state_path()
            if active_state_path is not None:
                if service is not None:
                    service.bind_store(StateStore(active_state_path))
                    app.state.service = service
                else:
                    app.state.service = build_service(active_state_path)
            else:
                app.state.service = None
        else:
            app.state.service = service or build_service()
        app.state.cancellation_registry = CancellationRegistry()
        try:
            yield
        finally:
            # GameService writes are synchronous + atomic per-call, so there
            # is no flush phase. We keep the hook so future async resources
            # (db pools, websockets) have a single place to wind down.
            app.state.service = None
            app.state.service_template = None
            app.state.save_library = None
            app.state.cancellation_registry = None

    app = FastAPI(
        title="Dungeon Master",
        version="0.1.0",
        description=(
            "Personal solo TTRPG harness. Python owns deterministic mechanics; "
            "the LLM only generates narration."
        ),
        lifespan=lifespan,
    )

    # The frontend is served from Vite at :5173 in dev. In single-user prod
    # we typically reverse-proxy or run them on the same host, but the
    # permissive policy is fine because this is a personal-machine app.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)
    return app


# Module-level app instance for `uvicorn dungeon_master.api:app`.
app = create_app()
