"""HTTP surface for the deterministic-oracle / LLM-narrative game.

The API is intentionally thin: every mutation funnels through `GameService`
and returns the entire `GameState`. Returning the whole state on every
request keeps the frontend trivially reconcilable (no diff protocol, no
optimistic state) and matches the personal-use single-writer assumption.
The Python side stays the single source of truth; the LLM never edits state.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Body, Depends, FastAPI, HTTPException, Request, status
from fastapi import Path as ApiPath
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from dungeon_master.campaign import CharacterDraftMode
from dungeon_master.models import (
    CharacterQuiz,
    CharacterQuizAnswer,
    CharacterSheet,
    GameState,
    Likelihood,
)
from dungeon_master.service import GameService
from dungeon_master.settings import state_path_from_env
from dungeon_master.state_store import StateStore

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)


class ChaosFactorRequest(BaseModel):
    value: int = Field(ge=1, le=9)


class NotesRequest(BaseModel):
    setting_notes: str = Field(min_length=1)
    player_notes: str = Field(min_length=1)


class YesNoRequest(BaseModel):
    question: str = Field(min_length=1)
    likelihood: Likelihood


class SceneCheckRequest(BaseModel):
    expected_scene: str = Field(min_length=1)


class PlayerActionRequest(BaseModel):
    action: str = Field(min_length=1)


class PlayerTurnRequest(BaseModel):
    text: str = Field(min_length=1)


class CharacterDraftRequest(BaseModel):
    mode: CharacterDraftMode
    prompt: str | None = None
    template: CharacterSheet | None = None


class CharacterFinalizeRequest(BaseModel):
    character: CharacterSheet


class CharacterTemplatesResponse(BaseModel):
    templates: list[CharacterSheet]


class CharacterDraftResponse(BaseModel):
    draft: CharacterSheet


class CharacterQuizRequest(BaseModel):
    concept: str = Field(min_length=1, max_length=2000)


class CharacterQuizResponse(BaseModel):
    quiz: CharacterQuiz


class CharacterQuizzedDraftRequest(BaseModel):
    concept: str = Field(min_length=1, max_length=2000)
    answers: list[CharacterQuizAnswer] = Field(default_factory=list)
    final_note: str | None = None


class ServiceUnavailableError(RuntimeError):
    """Raised when a request lands before the lifespan has wired up the service."""


def build_service(state_path: Path | None = None) -> GameService:
    """Construct a `GameService` bound to a single state file.

    Kept as a free function so tests can inject a tmp_path without
    monkey-patching environment variables.
    """
    path = state_path or state_path_from_env()
    return GameService(store=StateStore(path))


def get_service(request: Request) -> GameService:
    """FastAPI dependency that pulls the live `GameService` off app state.

    We resolve via `Request.app.state` rather than a closure so each route
    handler can live at module level (testable, mypy-friendly, and easy
    to grep for).
    """
    service = getattr(request.app.state, "service", None)
    if not isinstance(service, GameService):
        raise ServiceUnavailableError
    return service


ServiceDep = Annotated[GameService, Depends(get_service)]

router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


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


@router.post("/turn", response_model=GameState)
def submit_turn(
    svc: ServiceDep,
    payload: Annotated[PlayerTurnRequest, Body()],
) -> GameState:
    try:
        return svc.submit_player_turn(payload.text)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/character/templates", response_model=CharacterTemplatesResponse)
def character_templates(svc: ServiceDep) -> CharacterTemplatesResponse:
    return CharacterTemplatesResponse(templates=svc.list_character_templates())


@router.post("/character/draft", response_model=CharacterDraftResponse)
def character_draft(
    svc: ServiceDep,
    payload: Annotated[CharacterDraftRequest, Body()],
) -> CharacterDraftResponse:
    draft = svc.generate_character_draft(
        mode=payload.mode,
        prompt=payload.prompt,
        template=payload.template,
    )
    return CharacterDraftResponse(draft=draft)


@router.post("/character/quiz", response_model=CharacterQuizResponse)
def character_quiz(
    svc: ServiceDep,
    payload: Annotated[CharacterQuizRequest, Body()],
) -> CharacterQuizResponse:
    return CharacterQuizResponse(quiz=svc.generate_character_quiz(payload.concept))


@router.post("/character/draft/quizzed", response_model=CharacterDraftResponse)
def character_quizzed_draft(
    svc: ServiceDep,
    payload: Annotated[CharacterQuizzedDraftRequest, Body()],
) -> CharacterDraftResponse:
    draft = svc.generate_quizzed_character_draft(
        concept=payload.concept,
        answers=payload.answers,
        final_note=payload.final_note,
    )
    return CharacterDraftResponse(draft=draft)


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


@router.post("/messages/{event_id}/regenerate", response_model=GameState)
def regenerate_message(
    svc: ServiceDep,
    event_id: Annotated[str, ApiPath(min_length=1)],
) -> GameState:
    try:
        return svc.regenerate_response(event_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


def create_app(service: GameService | None = None) -> FastAPI:
    """Create the FastAPI application.

    Pass an explicit `service` from tests; otherwise the lifespan
    constructs one from environment configuration.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.service = service or build_service()
        try:
            yield
        finally:
            # GameService writes are synchronous + atomic per-call, so there
            # is no flush phase. We keep the hook so future async resources
            # (db pools, websockets) have a single place to wind down.
            app.state.service = None

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
