"""FastAPI application assembly and runtime lifespan."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dungeon_master import __version__
from dungeon_master.config import LLMCredentialsStore, RuntimeSettingsStore
from dungeon_master.save_library import SaveLibrary
from dungeon_master.service import GameService
from dungeon_master.state_store import StateStore
from dungeon_master.transport.http.routes import gameplay, mechanics, setup, system
from dungeon_master.transport.http.runtime import (
    build_credentials_store,
    build_runtime_settings_store,
    build_save_library,
    build_service,
    initialize_llm_runtime,
)
from dungeon_master.transport.stream_runtime import StreamRuntime

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

router = APIRouter(prefix="/api")
router.include_router(system.router)
router.include_router(gameplay.router)
router.include_router(mechanics.router)
router.include_router(setup.router)


def create_app(
    service: GameService | None = None,
    save_library: SaveLibrary | None = None,
    runtime_settings_store: RuntimeSettingsStore | None = None,
    credentials_store: LLMCredentialsStore | None = None,
) -> FastAPI:
    """Create an application around an optional prebuilt service or save library."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        library = save_library
        if library is None and service is None:
            library = build_save_library()
        settings_store = runtime_settings_store or build_runtime_settings_store()
        llm_credentials_store = credentials_store or build_credentials_store()
        llm_runtime = initialize_llm_runtime(
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
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^(http://(localhost|127\.0\.0\.1):\d+|tauri://localhost)$",
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)
    return app
