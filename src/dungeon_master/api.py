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
from fastapi.responses import StreamingResponse

from dungeon_master import __version__
from dungeon_master.cancel import CancellationToken
from dungeon_master.config import (
    LLMCredentials,
    LLMCredentialsStore,
    LLMProviderCredentialStatus,
    LLMRuntimeBundle,
    LLMRuntimeSettings,
    RuntimeSettingsStore,
    build_llm_runtime,
    describe_llm_presets,
    resolve_provider_credentials,
)
from dungeon_master.models import GameState, OracleOutcome
from dungeon_master.narrative import CompletionDelta
from dungeon_master.save_library import SaveLibrary
from dungeon_master.service import GameService
from dungeon_master.settings import (
    credentials_path_from_env,
    runtime_settings_path_from_env,
    state_path_from_env,
)
from dungeon_master.state_store import StateStore
from dungeon_master.transport.http.schemas import (
    CairnAcquireRequest,
    CairnAttackRequest,
    CairnEquipRequest,
    CairnHarmRequest,
    CairnRecoveryRequest,
    CairnRetreatRequest,
    CairnSaveRequest,
    CampaignEndRequest,
    CampaignSeedRequest,
    CancelRequestResponse,
    ChaosFactorRequest,
    CharacterDraftRequest,
    CharacterDraftResponse,
    CharacterFinalizeRequest,
    CharacterQuizRequest,
    CharacterQuizResponse,
    CharacterQuizzedDraftRequest,
    CharacterTemplatesResponse,
    CreateSaveRequest,
    DirectivesRequest,
    ExplainRequest,
    ExplanationResponse,
    LLMCredentialsUpdateRequest,
    LLMPresetOptionResponse,
    LLMProviderCredentialResponse,
    LLMSettingsResponse,
    LLMSettingsUpdateRequest,
    NotesRequest,
    PlayerActionRequest,
    PlayerTurnRequest,
    SaveLibraryBootstrapResponse,
    SceneCheckRequest,
    SelectSaveRequest,
    YesNoRequest,
)
from dungeon_master.transport.stream_runtime import (
    PayloadKind,
    SessionRegistry,
    StreamRuntime,
    StreamSession,
    StreamSessionNotFoundError,
    StreamSessionSaveMismatchError,
)
from dungeon_master.turn_router import TurnPlanningError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Generator

logger = logging.getLogger(__name__)
API_KEY_MASK_VISIBLE = 4
API_KEY_MASK_SHORT_THRESHOLD = API_KEY_MASK_VISIBLE * 2


class ServiceUnavailableError(RuntimeError):
    """Raised when a request lands before the lifespan has wired up the service."""


def build_service(
    state_path: Path | None = None,
    *,
    llm_runtime: LLMRuntimeBundle | None = None,
) -> GameService:
    """Construct a `GameService` bound to a single state file.

    Kept as a free function so tests can inject a tmp_path without
    monkey-patching environment variables.
    """
    path = state_path or state_path_from_env()
    return GameService(store=StateStore(path), llm_runtime=llm_runtime)


def build_save_library(legacy_state_path: Path | None = None) -> SaveLibrary:
    path = legacy_state_path or state_path_from_env()
    return SaveLibrary(path)


def build_runtime_settings_store(settings_path: Path | None = None) -> RuntimeSettingsStore:
    path = settings_path or runtime_settings_path_from_env()
    return RuntimeSettingsStore(path)


def build_credentials_store(settings_path: Path | None = None) -> LLMCredentialsStore:
    path = settings_path or credentials_path_from_env()
    return LLMCredentialsStore(path)


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


def get_runtime_settings_store(request: Request) -> RuntimeSettingsStore:
    store = getattr(request.app.state, "runtime_settings_store", None)
    if not isinstance(store, RuntimeSettingsStore):
        raise ServiceUnavailableError
    return store


def get_credentials_store(request: Request) -> LLMCredentialsStore:
    store = getattr(request.app.state, "credentials_store", None)
    if not isinstance(store, LLMCredentialsStore):
        raise ServiceUnavailableError
    return store


def get_stream_runtime(request: Request) -> StreamRuntime:
    runtime = getattr(request.app.state, "stream_runtime", None)
    if not isinstance(runtime, StreamRuntime):
        raise ServiceUnavailableError
    return runtime


def get_session_registry(request: Request) -> SessionRegistry:
    return get_stream_runtime(request).sessions


ServiceDep = Annotated[GameService, Depends(get_service)]
LibraryDep = Annotated[SaveLibrary, Depends(get_save_library)]
RuntimeSettingsStoreDep = Annotated[RuntimeSettingsStore, Depends(get_runtime_settings_store)]
CredentialsStoreDep = Annotated[LLMCredentialsStore, Depends(get_credentials_store)]
SessionRegistryDep = Annotated[SessionRegistry, Depends(get_session_registry)]
StreamRuntimeDep = Annotated[StreamRuntime, Depends(get_stream_runtime)]


def _service_seed(app: FastAPI) -> GameService | None:
    seeded = getattr(app.state, "service_template", None)
    if isinstance(seeded, GameService):
        return seeded
    live = getattr(app.state, "service", None)
    if isinstance(live, GameService):
        return live
    return None


def _runtime_bundle(app: FastAPI) -> LLMRuntimeBundle:
    bundle = getattr(app.state, "llm_runtime", None)
    if not isinstance(bundle, LLMRuntimeBundle):
        raise ServiceUnavailableError
    return bundle


def _stored_llm_credentials(app: FastAPI) -> LLMCredentials:
    credentials = getattr(app.state, "llm_credentials", None)
    if not isinstance(credentials, LLMCredentials):
        raise ServiceUnavailableError
    return credentials


def _mask_api_key(api_key: str | None) -> str | None:
    if api_key is None:
        return None
    if len(api_key) <= API_KEY_MASK_SHORT_THRESHOLD:
        return "*" * len(api_key)
    return f"{api_key[:API_KEY_MASK_VISIBLE]}...{api_key[-API_KEY_MASK_VISIBLE:]}"


def _credential_response(
    status: LLMProviderCredentialStatus,
) -> LLMProviderCredentialResponse:
    return LLMProviderCredentialResponse(
        id=status.provider,
        label=status.label,
        configured=status.configured,
        source=status.source,
        masked_key=_mask_api_key(status.api_key),
    )


def _llm_settings_response(
    bundle: LLMRuntimeBundle,
    credentials: LLMCredentials,
) -> LLMSettingsResponse:
    provider_statuses = resolve_provider_credentials(credentials)
    return LLMSettingsResponse(
        preset=bundle.settings.llm_preset,
        structured_model=bundle.structured.model,
        narration_model=bundle.narration.model,
        reasoning_model=bundle.reasoning.model,
        presets=[
            LLMPresetOptionResponse(
                id=descriptor.id,
                label=descriptor.label,
                description=descriptor.description,
                structured_model=descriptor.structured_model,
                narration_model=descriptor.narration_model,
                reasoning_model=descriptor.reasoning_model,
                available=descriptor.is_available(provider_statuses),
                missing_env_vars=descriptor.missing_env_vars(provider_statuses),
            )
            for descriptor in describe_llm_presets()
        ],
        needs_key=not any(status.configured for status in provider_statuses),
        provider_credentials=[_credential_response(status) for status in provider_statuses],
    )


def _apply_runtime_settings(app: FastAPI, settings: LLMRuntimeSettings) -> LLMRuntimeBundle:
    bundle = build_llm_runtime(settings, _stored_llm_credentials(app))
    seen_services: set[int] = set()
    for attr in ("service", "service_template"):
        service = getattr(app.state, attr, None)
        if not isinstance(service, GameService):
            continue
        identity = id(service)
        if identity in seen_services:
            continue
        service.apply_llm_runtime(bundle)
        seen_services.add(identity)
    app.state.llm_runtime = bundle
    return bundle


def _initialize_llm_runtime(
    app: FastAPI,
    *,
    settings_store: RuntimeSettingsStore,
    credentials_store: LLMCredentialsStore,
) -> LLMRuntimeBundle:
    runtime_settings = settings_store.load()
    llm_credentials = credentials_store.load()
    llm_runtime = build_llm_runtime(runtime_settings, llm_credentials)
    app.state.runtime_settings_store = settings_store
    app.state.credentials_store = credentials_store
    app.state.llm_credentials = llm_credentials
    app.state.llm_runtime = llm_runtime
    return llm_runtime


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

    service = build_service(state_path, llm_runtime=_runtime_bundle(app))
    app.state.service = service
    return service


def _guard_request_idle(
    registry: SessionRegistry,
    *,
    detail: str,
) -> None:
    # F-12 keeps the backend single-active-save for v1. Switching the bound
    # store while a streamed request is still registered would let one request
    # start against save A and commit against save B. We therefore force the
    # conservative invariant: no save creation/selection that changes the
    # active slot while any streamed request is still alive in the registry.
    if registry.has_active_requests():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail,
        )


router = APIRouter(prefix="/api")


# FastAPI only adapts retained sessions to HTTP responses. Session creation,
# cancellation, NDJSON production, worker ownership, and replay live in the
# transport runtime.


def _active_save_id(app: FastAPI) -> str | None:
    library = getattr(app.state, "save_library", None)
    if not isinstance(library, SaveLibrary):
        return None
    return library.active_save_id()


def _streaming_response(session: StreamSession) -> StreamingResponse:
    return StreamingResponse(session.attach(), media_type="application/x-ndjson")


def _start_game_state_stream(
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
        save_id=_active_save_id(request.app),
        generator_factory=generator_factory,
    )
    return _streaming_response(session)


def _start_setup_stream[SetupResult](  # noqa: PLR0913
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
        save_id=_active_save_id(request.app),
        generator_factory=generator_factory,
        payload_kind=payload_kind,
        serializer=serialize,
    )
    return _streaming_response(session)


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/requests/{request_id}/cancel", response_model=CancelRequestResponse)
def cancel_request(
    request_id: Annotated[str, ApiPath(min_length=1)],
    registry: SessionRegistryDep,
) -> CancelRequestResponse:
    return CancelRequestResponse(cancelled=registry.cancel(request_id))


@router.get("/requests/{request_id}/stream")
def reattach_request_stream(
    request: Request,
    request_id: Annotated[str, ApiPath(min_length=1)],
    stream_runtime: StreamRuntimeDep,
) -> StreamingResponse:
    try:
        session = stream_runtime.session_for_reattach(
            request_id,
            active_save_id=_active_save_id(request.app),
        )
    except StreamSessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Request stream not found or already expired.",
        ) from exc
    except StreamSessionSaveMismatchError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Request belongs to a different active save.",
        ) from exc
    return _streaming_response(session)


@router.get("/library/bootstrap", response_model=SaveLibraryBootstrapResponse)
def library_bootstrap(library: LibraryDep) -> SaveLibraryBootstrapResponse:
    active_save_id, saves = library.bootstrap_payload()
    return SaveLibraryBootstrapResponse(active_save_id=active_save_id, saves=saves)


@router.get("/settings/llm", response_model=LLMSettingsResponse)
def read_llm_settings(request: Request) -> LLMSettingsResponse:
    return _llm_settings_response(
        _runtime_bundle(request.app),
        _stored_llm_credentials(request.app),
    )


@router.post("/settings/llm", response_model=LLMSettingsResponse)
def update_llm_settings(
    request: Request,
    settings_store: RuntimeSettingsStoreDep,
    registry: SessionRegistryDep,
    payload: Annotated[LLMSettingsUpdateRequest, Body()],
) -> LLMSettingsResponse:
    _guard_request_idle(
        registry,
        detail="Cannot change LLM settings while a request is still in flight.",
    )
    settings = LLMRuntimeSettings(llm_preset=payload.preset)
    stored_credentials = _stored_llm_credentials(request.app)
    candidate = build_llm_runtime(settings, stored_credentials)
    candidate_response = _llm_settings_response(candidate, stored_credentials)
    selected_option = next(
        (option for option in candidate_response.presets if option.id == payload.preset),
        None,
    )
    if selected_option is not None and not selected_option.available:
        missing = ", ".join(selected_option.missing_env_vars) or "required provider credentials"
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Preset {payload.preset.value!r} is unavailable. Missing: {missing}.",
        )
    settings_store.save(settings)
    bundle = _apply_runtime_settings(request.app, settings)
    return _llm_settings_response(bundle, stored_credentials)


@router.post("/settings/credentials", response_model=LLMSettingsResponse)
def update_llm_credentials(
    request: Request,
    settings_store: RuntimeSettingsStoreDep,
    credentials_store: CredentialsStoreDep,
    registry: SessionRegistryDep,
    payload: Annotated[LLMCredentialsUpdateRequest, Body()],
) -> LLMSettingsResponse:
    _guard_request_idle(
        registry,
        detail="Cannot change LLM credentials while a request is still in flight.",
    )
    stored_credentials = _stored_llm_credentials(request.app)
    updated_credentials = stored_credentials.with_provider(payload.provider, payload.api_key)
    if updated_credentials is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="provider credentials cannot be empty",
        )
    credentials_store.save(updated_credentials)
    request.app.state.llm_credentials = updated_credentials
    bundle = _apply_runtime_settings(request.app, settings_store.load())
    return _llm_settings_response(bundle, updated_credentials)


@router.post("/library/saves", response_model=SaveLibraryBootstrapResponse)
def create_save(
    request: Request,
    library: LibraryDep,
    registry: SessionRegistryDep,
    payload: Annotated[CreateSaveRequest, Body()] | None = None,
) -> SaveLibraryBootstrapResponse:
    if payload is None:
        payload = CreateSaveRequest()
    if payload.select:
        _guard_request_idle(
            registry,
            detail="Cannot switch saves while a request is still in flight.",
        )
    seed = _service_seed(request.app)
    create_state = (
        seed.new_setup_state()
        if seed is not None
        else build_service(llm_runtime=_runtime_bundle(request.app)).new_setup_state()
    )
    save_id = library.create_save(create_state=create_state, select=payload.select)
    if payload.select:
        _bind_service_to_active_save(request.app, save_id)
    active_save_id, saves = library.bootstrap_payload()
    return SaveLibraryBootstrapResponse(active_save_id=active_save_id, saves=saves)


@router.post("/library/select", response_model=SaveLibraryBootstrapResponse)
def select_save(
    request: Request,
    library: LibraryDep,
    registry: SessionRegistryDep,
    payload: Annotated[SelectSaveRequest, Body()],
) -> SaveLibraryBootstrapResponse:
    _guard_request_idle(
        registry,
        detail="Cannot switch saves while a request is still in flight.",
    )
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
def preview_oracle(
    svc: ServiceDep,
    payload: Annotated[YesNoRequest, Body()],
) -> OracleOutcome:
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
    request: Request,
    svc: ServiceDep,
    stream_runtime: StreamRuntimeDep,
    payload: Annotated[PlayerActionRequest, Body()],
) -> StreamingResponse:
    return _start_game_state_stream(
        request,
        generator_factory=lambda token: svc.stream_submit_player_action(
            payload.action,
            cancel_token=token,
        ),
        route="player_action",
        stream_runtime=stream_runtime,
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
    request: Request,
    svc: ServiceDep,
    stream_runtime: StreamRuntimeDep,
    payload: Annotated[PlayerTurnRequest, Body()],
) -> StreamingResponse:
    # We label the route as `player_action` here because the backend's
    # turn router decides the *real* route inside the service. The
    # frontend uses the `meta` route only to label the provisional
    # bubble, and `player_action` is the conservative default that
    # matches every prose-producing branch.
    return _start_game_state_stream(
        request,
        generator_factory=lambda token: svc.stream_submit_player_turn(
            payload.text,
            cancel_token=token,
        ),
        route="player_action",
        stream_runtime=stream_runtime,
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
    request: Request,
    svc: ServiceDep,
    stream_runtime: StreamRuntimeDep,
    payload: Annotated[ExplainRequest, Body()],
) -> StreamingResponse:
    return _start_setup_stream(
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
    request: Request,
    svc: ServiceDep,
    stream_runtime: StreamRuntimeDep,
) -> StreamingResponse:
    return _start_setup_stream(
        request,
        generator_factory=lambda token: svc.stream_character_templates(cancel_token=token),
        route="character_templates",
        payload_kind="character_draft",
        serialize=lambda result: {
            "templates": [t.model_dump(mode="json") for t in result.templates],
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
    return _start_setup_stream(
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
    return _start_setup_stream(
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
    return _start_setup_stream(
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
    # Adapt `Generator[..., CampaignWorldResult]` to the
    # `Generator[..., GameState]` shape that `_stream_game_state` expects
    # by unwrapping `.state` on completion. The wrapper below mirrors
    # the unary `start_campaign` path: a `ValueError` from the underlying
    # generator (e.g. campaign already active) is allowed to bubble so
    # the streaming envelope can convert it into an `error` event.
    def adapter(token: CancellationToken) -> Generator[CompletionDelta, None, GameState]:
        inner = svc.stream_start_campaign(cancel_token=token)
        result = yield from inner
        return result.state

    return _start_game_state_stream(
        request,
        generator_factory=adapter,
        route="campaign_start",
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
    return _start_game_state_stream(
        request,
        generator_factory=lambda token: svc.stream_regenerate_response(
            event_id,
            cancel_token=token,
        ),
        route="regenerate",
        stream_runtime=stream_runtime,
    )


def create_app(
    service: GameService | None = None,
    save_library: SaveLibrary | None = None,
    runtime_settings_store: RuntimeSettingsStore | None = None,
    credentials_store: LLMCredentialsStore | None = None,
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
        settings_store = runtime_settings_store or build_runtime_settings_store()
        llm_credentials_store = credentials_store or build_credentials_store()
        llm_runtime = _initialize_llm_runtime(
            app,
            settings_store=settings_store,
            credentials_store=llm_credentials_store,
        )

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
                    app.state.service = build_service(active_state_path, llm_runtime=llm_runtime)
            else:
                app.state.service = None
        elif service is not None:
            app.state.service = service
        else:
            app.state.service = build_service(llm_runtime=llm_runtime)
        app.state.stream_runtime = StreamRuntime()
        try:
            yield
        finally:
            # GameService writes are synchronous + atomic per-call, so there
            # is no flush phase. We keep the hook so future async resources
            # (db pools, websockets) have a single place to wind down.
            app.state.service = None
            app.state.service_template = None
            app.state.save_library = None
            app.state.runtime_settings_store = None
            app.state.credentials_store = None
            app.state.llm_credentials = None
            app.state.llm_runtime = None
            stream_runtime = getattr(app.state, "stream_runtime", None)
            if isinstance(stream_runtime, StreamRuntime):
                stream_runtime.shutdown()
            app.state.stream_runtime = None

    app = FastAPI(
        title="Dungeon Master",
        version=__version__,
        description=(
            "Personal solo TTRPG harness. Python owns deterministic mechanics; "
            "the LLM only generates narration."
        ),
        lifespan=lifespan,
    )

    # The browser client is either Vite dev or Tauri's custom app origin.
    # This backend binds to localhost for a single-player desktop app, so a
    # local-only wildcard keeps packaged builds from failing CORS preflight.
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^(http://(localhost|127\.0\.0\.1):\d+|tauri://localhost)$",
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)
    return app


# Module-level app instance for `uvicorn dungeon_master.api:app`.
app = create_app()
