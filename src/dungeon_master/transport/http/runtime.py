"""FastAPI dependency wiring and runtime configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, status

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
from dungeon_master.save_library import SaveLibrary
from dungeon_master.service import GameService
from dungeon_master.settings import (
    credentials_path_from_env,
    runtime_settings_path_from_env,
    state_path_from_env,
)
from dungeon_master.state_store import StateStore
from dungeon_master.transport.http.schemas import (
    LLMPresetOptionResponse,
    LLMProviderCredentialResponse,
    LLMSettingsResponse,
)
from dungeon_master.transport.stream_runtime import SessionRegistry, StreamRuntime

API_KEY_MASK_VISIBLE = 4
API_KEY_MASK_SHORT_THRESHOLD = API_KEY_MASK_VISIBLE * 2


class ServiceUnavailableError(RuntimeError):
    """Raised when a request lands before the lifespan wires the service."""


def build_service(
    state_path: Path | None = None,
    *,
    llm_runtime: LLMRuntimeBundle | None = None,
) -> GameService:
    """Construct a service bound to one state file."""
    path = state_path or state_path_from_env()
    return GameService(store=StateStore(path), llm_runtime=llm_runtime)


def build_save_library(legacy_state_path: Path | None = None) -> SaveLibrary:
    return SaveLibrary(legacy_state_path or state_path_from_env())


def build_runtime_settings_store(settings_path: Path | None = None) -> RuntimeSettingsStore:
    return RuntimeSettingsStore(settings_path or runtime_settings_path_from_env())


def build_credentials_store(settings_path: Path | None = None) -> LLMCredentialsStore:
    return LLMCredentialsStore(settings_path or credentials_path_from_env())


def get_service(request: Request) -> GameService:
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


def service_seed(app: FastAPI) -> GameService | None:
    seeded = getattr(app.state, "service_template", None)
    if isinstance(seeded, GameService):
        return seeded
    live = getattr(app.state, "service", None)
    return live if isinstance(live, GameService) else None


def runtime_bundle(app: FastAPI) -> LLMRuntimeBundle:
    bundle = getattr(app.state, "llm_runtime", None)
    if not isinstance(bundle, LLMRuntimeBundle):
        raise ServiceUnavailableError
    return bundle


def stored_llm_credentials(app: FastAPI) -> LLMCredentials:
    credentials = getattr(app.state, "llm_credentials", None)
    if not isinstance(credentials, LLMCredentials):
        raise ServiceUnavailableError
    return credentials


def mask_api_key(api_key: str | None) -> str | None:
    if api_key is None:
        return None
    if len(api_key) <= API_KEY_MASK_SHORT_THRESHOLD:
        return "*" * len(api_key)
    return f"{api_key[:API_KEY_MASK_VISIBLE]}...{api_key[-API_KEY_MASK_VISIBLE:]}"


def llm_settings_response(
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
        provider_credentials=[credential_response(status) for status in provider_statuses],
    )


def credential_response(status: LLMProviderCredentialStatus) -> LLMProviderCredentialResponse:
    return LLMProviderCredentialResponse(
        id=status.provider,
        label=status.label,
        configured=status.configured,
        source=status.source,
        masked_key=mask_api_key(status.api_key),
    )


def apply_runtime_settings(app: FastAPI, settings: LLMRuntimeSettings) -> LLMRuntimeBundle:
    bundle = build_llm_runtime(settings, stored_llm_credentials(app))
    seen_services: set[int] = set()
    for attr in ("service", "service_template"):
        service = getattr(app.state, attr, None)
        if not isinstance(service, GameService) or id(service) in seen_services:
            continue
        service.apply_llm_runtime(bundle)
        seen_services.add(id(service))
    app.state.llm_runtime = bundle
    return bundle


def initialize_llm_runtime(
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


def bind_service_to_active_save(app: FastAPI, save_id: str) -> GameService:
    library = getattr(app.state, "save_library", None)
    if not isinstance(library, SaveLibrary):
        raise ServiceUnavailableError
    state_path = library.state_path_for(save_id)
    seed = service_seed(app)
    if seed is not None:
        seed.bind_store(StateStore(state_path))
        app.state.service = seed
        return seed
    service = build_service(state_path, llm_runtime=runtime_bundle(app))
    app.state.service = service
    return service


def guard_request_idle(registry: SessionRegistry, *, detail: str) -> None:
    if registry.has_active_requests():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)
