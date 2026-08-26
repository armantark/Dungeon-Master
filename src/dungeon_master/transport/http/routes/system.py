"""Runtime lifecycle, settings, and save-library routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, HTTPException, Request, status
from fastapi import Path as ApiPath
from fastapi.responses import StreamingResponse  # noqa: TC002

from dungeon_master.config import LLMRuntimeSettings, build_llm_runtime
from dungeon_master.transport.http.runtime import (
    CredentialsStoreDep,
    LibraryDep,
    RuntimeSettingsStoreDep,
    SessionRegistryDep,
    StreamRuntimeDep,
    apply_runtime_settings,
    bind_service_to_active_save,
    build_service,
    guard_request_idle,
    llm_settings_response,
    runtime_bundle,
    service_seed,
    stored_llm_credentials,
)
from dungeon_master.transport.http.schemas import (
    CancelRequestResponse,
    CreateSaveRequest,
    LLMCredentialsUpdateRequest,
    LLMSettingsResponse,
    LLMSettingsUpdateRequest,
    SaveLibraryBootstrapResponse,
    SelectSaveRequest,
)
from dungeon_master.transport.http.streaming import active_save_id, streaming_response
from dungeon_master.transport.stream_runtime import (
    StreamSessionNotFoundError,
    StreamSessionSaveMismatchError,
)

router = APIRouter()


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
            active_save_id=active_save_id(request.app),
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
    return streaming_response(session)


@router.get("/library/bootstrap", response_model=SaveLibraryBootstrapResponse)
def library_bootstrap(library: LibraryDep) -> SaveLibraryBootstrapResponse:
    selected_save_id, saves = library.bootstrap_payload()
    return SaveLibraryBootstrapResponse(active_save_id=selected_save_id, saves=saves)


@router.get("/settings/llm", response_model=LLMSettingsResponse)
def read_llm_settings(request: Request) -> LLMSettingsResponse:
    return llm_settings_response(runtime_bundle(request.app), stored_llm_credentials(request.app))


@router.post("/settings/llm", response_model=LLMSettingsResponse)
def update_llm_settings(
    request: Request,
    settings_store: RuntimeSettingsStoreDep,
    registry: SessionRegistryDep,
    payload: Annotated[LLMSettingsUpdateRequest, Body()],
) -> LLMSettingsResponse:
    guard_request_idle(
        registry,
        detail="Cannot change LLM settings while a request is still in flight.",
    )
    settings = LLMRuntimeSettings(llm_preset=payload.preset)
    credentials = stored_llm_credentials(request.app)
    candidate = build_llm_runtime(settings, credentials)
    candidate_response = llm_settings_response(candidate, credentials)
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
    bundle = apply_runtime_settings(request.app, settings)
    return llm_settings_response(bundle, credentials)


@router.post("/settings/credentials", response_model=LLMSettingsResponse)
def update_llm_credentials(
    request: Request,
    settings_store: RuntimeSettingsStoreDep,
    credentials_store: CredentialsStoreDep,
    registry: SessionRegistryDep,
    payload: Annotated[LLMCredentialsUpdateRequest, Body()],
) -> LLMSettingsResponse:
    guard_request_idle(
        registry,
        detail="Cannot change LLM credentials while a request is still in flight.",
    )
    credentials = stored_llm_credentials(request.app)
    updated_credentials = credentials.with_provider(payload.provider, payload.api_key)
    if updated_credentials is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="provider credentials cannot be empty",
        )
    credentials_store.save(updated_credentials)
    request.app.state.llm_credentials = updated_credentials
    bundle = apply_runtime_settings(request.app, settings_store.load())
    return llm_settings_response(bundle, updated_credentials)


@router.post("/library/saves", response_model=SaveLibraryBootstrapResponse)
def create_save(
    request: Request,
    library: LibraryDep,
    registry: SessionRegistryDep,
    payload: Annotated[CreateSaveRequest, Body()] | None = None,
) -> SaveLibraryBootstrapResponse:
    payload = payload or CreateSaveRequest()
    if payload.select:
        guard_request_idle(
            registry,
            detail="Cannot switch saves while a request is still in flight.",
        )
    seed = service_seed(request.app)
    create_state = (
        seed.new_setup_state()
        if seed is not None
        else build_service(llm_runtime=runtime_bundle(request.app)).new_setup_state()
    )
    save_id = library.create_save(create_state=create_state, select=payload.select)
    if payload.select:
        bind_service_to_active_save(request.app, save_id)
    selected_save_id, saves = library.bootstrap_payload()
    return SaveLibraryBootstrapResponse(active_save_id=selected_save_id, saves=saves)


@router.post("/library/select", response_model=SaveLibraryBootstrapResponse)
def select_save(
    request: Request,
    library: LibraryDep,
    registry: SessionRegistryDep,
    payload: Annotated[SelectSaveRequest, Body()],
) -> SaveLibraryBootstrapResponse:
    guard_request_idle(
        registry,
        detail="Cannot switch saves while a request is still in flight.",
    )
    try:
        library.select_active(payload.save_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    bind_service_to_active_save(request.app, payload.save_id)
    selected_save_id, saves = library.bootstrap_payload()
    return SaveLibraryBootstrapResponse(active_save_id=selected_save_id, saves=saves)
