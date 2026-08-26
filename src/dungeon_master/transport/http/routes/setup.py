"""Character creation and campaign lifecycle routes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Body, HTTPException, Request, status
from fastapi.responses import StreamingResponse  # noqa: TC002

from dungeon_master.domain.models import GameState
from dungeon_master.transport.http.runtime import ServiceDep, StreamRuntimeDep
from dungeon_master.transport.http.schemas import (
    CampaignEndRequest,
    CharacterDraftRequest,
    CharacterDraftResponse,
    CharacterFinalizeRequest,
    CharacterQuizRequest,
    CharacterQuizResponse,
    CharacterQuizzedDraftRequest,
    CharacterTemplatesResponse,
)
from dungeon_master.transport.http.streaming import start_game_state_stream, start_setup_stream

if TYPE_CHECKING:
    from collections.abc import Generator

    from dungeon_master.application.cancellation import CancellationToken
    from dungeon_master.llm.narration import CompletionDelta

router = APIRouter()


@router.get("/character/templates", response_model=CharacterTemplatesResponse)
def character_templates(svc: ServiceDep) -> CharacterTemplatesResponse:
    result = svc.list_character_templates_result()
    return CharacterTemplatesResponse(templates=result.templates, thinking=result.thinking)


@router.get("/character/templates/stream")
def character_templates_stream(
    request: Request,
    svc: ServiceDep,
    stream_runtime: StreamRuntimeDep,
) -> StreamingResponse:
    return start_setup_stream(
        request,
        generator_factory=lambda token: svc.stream_character_templates(cancel_token=token),
        route="character_templates",
        payload_kind="character_draft",
        serialize=lambda result: {
            "templates": [template.model_dump(mode="json") for template in result.templates],
        },
        stream_runtime=stream_runtime,
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
    request: Request,
    svc: ServiceDep,
    stream_runtime: StreamRuntimeDep,
    payload: Annotated[CharacterDraftRequest, Body()],
) -> StreamingResponse:
    return start_setup_stream(
        request,
        generator_factory=lambda token: svc.stream_character_draft(
            mode=payload.mode,
            prompt=payload.prompt,
            template=payload.template,
            cancel_token=token,
        ),
        route="character_draft",
        payload_kind="character_draft",
        serialize=lambda result: {"draft": result.draft.model_dump(mode="json")},
        stream_runtime=stream_runtime,
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
    request: Request,
    svc: ServiceDep,
    stream_runtime: StreamRuntimeDep,
    payload: Annotated[CharacterQuizRequest, Body()],
) -> StreamingResponse:
    return start_setup_stream(
        request,
        generator_factory=lambda token: svc.stream_character_quiz(
            payload.concept,
            cancel_token=token,
        ),
        route="character_quiz",
        payload_kind="character_quiz",
        serialize=lambda result: {"quiz": result.quiz.model_dump(mode="json")},
        stream_runtime=stream_runtime,
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
    request: Request,
    svc: ServiceDep,
    stream_runtime: StreamRuntimeDep,
    payload: Annotated[CharacterQuizzedDraftRequest, Body()],
) -> StreamingResponse:
    return start_setup_stream(
        request,
        generator_factory=lambda token: svc.stream_quizzed_character_draft(
            concept=payload.concept,
            answers=payload.answers,
            final_note=payload.final_note,
            cancel_token=token,
        ),
        route="character_draft",
        payload_kind="character_draft",
        serialize=lambda result: {"draft": result.draft.model_dump(mode="json")},
        stream_runtime=stream_runtime,
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
    request: Request,
    svc: ServiceDep,
    stream_runtime: StreamRuntimeDep,
) -> StreamingResponse:
    def adapter(token: CancellationToken) -> Generator[CompletionDelta, None, GameState]:
        result = yield from svc.stream_start_campaign(cancel_token=token)
        return result.state

    return start_game_state_stream(
        request,
        generator_factory=adapter,
        route="campaign_start",
        stream_runtime=stream_runtime,
    )
