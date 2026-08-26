"""Canonical state, oracle, player-turn, explanation, and regeneration routes."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Body, HTTPException, Request, status
from fastapi import Path as ApiPath
from fastapi.responses import StreamingResponse  # noqa: TC002

from dungeon_master.models import GameState, OracleOutcome
from dungeon_master.transport.http.runtime import ServiceDep, StreamRuntimeDep
from dungeon_master.transport.http.schemas import (
    CampaignSeedRequest,
    ChaosFactorRequest,
    DirectivesRequest,
    ExplainRequest,
    ExplanationResponse,
    NotesRequest,
    PlayerActionRequest,
    PlayerTurnRequest,
    SceneCheckRequest,
    YesNoRequest,
)
from dungeon_master.transport.http.streaming import start_game_state_stream, start_setup_stream
from dungeon_master.turn_router import TurnPlanningError

logger = logging.getLogger(__name__)
router = APIRouter()


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


@router.post("/state/campaign-seed", response_model=GameState)
def update_campaign_seed(
    svc: ServiceDep,
    payload: Annotated[CampaignSeedRequest, Body()],
) -> GameState:
    try:
        return svc.update_campaign_seed(payload.campaign_seed)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/oracle/yes-no", response_model=GameState)
def ask_oracle(svc: ServiceDep, payload: Annotated[YesNoRequest, Body()]) -> GameState:
    try:
        return svc.ask_oracle(payload.question, payload.likelihood)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/oracle/yes-no/preview", response_model=OracleOutcome)
def preview_oracle(svc: ServiceDep, payload: Annotated[YesNoRequest, Body()]) -> OracleOutcome:
    try:
        return svc.preview_oracle(payload.question, payload.likelihood)
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
def submit_action(svc: ServiceDep, payload: Annotated[PlayerActionRequest, Body()]) -> GameState:
    try:
        return svc.submit_player_action(payload.action)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/action/stream")
def submit_action_stream(
    request: Request,
    svc: ServiceDep,
    stream_runtime: StreamRuntimeDep,
    payload: Annotated[PlayerActionRequest, Body()],
) -> StreamingResponse:
    return start_game_state_stream(
        request,
        generator_factory=lambda token: svc.stream_submit_player_action(
            payload.action,
            cancel_token=token,
        ),
        route="player_action",
        stream_runtime=stream_runtime,
    )


@router.post("/turn", response_model=GameState)
def submit_turn(svc: ServiceDep, payload: Annotated[PlayerTurnRequest, Body()]) -> GameState:
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
    request: Request,
    svc: ServiceDep,
    stream_runtime: StreamRuntimeDep,
    payload: Annotated[PlayerTurnRequest, Body()],
) -> StreamingResponse:
    return start_game_state_stream(
        request,
        generator_factory=lambda token: svc.stream_submit_player_turn(
            payload.text,
            cancel_token=token,
        ),
        route="player_action",
        stream_runtime=stream_runtime,
    )


@router.post("/explain", response_model=ExplanationResponse)
def explain(svc: ServiceDep, payload: Annotated[ExplainRequest, Body()]) -> ExplanationResponse:
    try:
        result = svc.explain(payload.question)
        return ExplanationResponse(answer=result.answer, thinking=result.thinking)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/explain/stream")
def explain_stream(
    request: Request,
    svc: ServiceDep,
    stream_runtime: StreamRuntimeDep,
    payload: Annotated[ExplainRequest, Body()],
) -> StreamingResponse:
    return start_setup_stream(
        request,
        generator_factory=lambda token: svc.stream_explain(
            payload.question,
            cancel_token=token,
        ),
        route="explanation",
        payload_kind="explanation",
        serialize=lambda result: {"answer": result.answer},
        stream_runtime=stream_runtime,
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
    request: Request,
    svc: ServiceDep,
    stream_runtime: StreamRuntimeDep,
    event_id: Annotated[str, ApiPath(min_length=1)],
) -> StreamingResponse:
    return start_game_state_stream(
        request,
        generator_factory=lambda token: svc.stream_regenerate_response(
            event_id,
            cancel_token=token,
        ),
        route="regenerate",
        stream_runtime=stream_runtime,
    )
