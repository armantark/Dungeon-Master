"""Integration tests for the FastAPI surface.

These tests don't go to the network: a `FakeNarrative` and
`FakeCampaignGenerator` replace LiteLLM, so we exercise the routing,
serialization, and state-mutation contracts without spending tokens.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from fastapi.testclient import TestClient

from dungeon_master import __version__
from dungeon_master.api import (
    PlayerTurnRequest,
    create_app,
    reattach_request_stream,
    submit_turn_stream,
)
from dungeon_master.config import (
    DEFAULT_GEMINI_FLASH_MODEL,
    DEFAULT_GEMINI_PRO_MODEL,
    DEFAULT_MODEL,
    LLMCredentialsStore,
    LLMPreset,
    LLMProvider,
    RuntimeSettingsStore,
)
from dungeon_master.models import (
    GameState,
    OracleKind,
    OracleOutcome,
    SceneStatus,
)
from dungeon_master.oracle import OracleEngine
from dungeon_master.save_library import SaveLibrary
from dungeon_master.service import GameService
from dungeon_master.state_store import StateStore
from dungeon_master.turn_router import (
    TurnRouter,
)
from tests.factories import sample_state

if TYPE_CHECKING:
    import pytest


from tests.api.mechanics_fakes import (
    FakePlayableCairnEngine,
    SetupCharacterGenerator,
)
from tests.api.narrative_fakes import (
    BlockingThoughtfulNarrative,
    FakeCampaignGenerator,
    FakeCharacterGenerator,
    FakeExplainer,
    FakeNarrative,
)
from tests.api.support import (
    _client,
    _collect_stream_events,
    _library_service,
    _request_for_app,
    scripted_classifier,
)


def test_health(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_uses_package_version(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["version"] == __version__


def test_cancel_unknown_request_returns_false(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post("/api/requests/req_missing/cancel")
    assert response.status_code == 200
    assert response.json() == {"cancelled": False}


def test_cancel_live_request_returns_true(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        session = cast("Any", client.app).state.stream_runtime.sessions.register(
            "req_live",
            route="test",
            save_id=None,
        )
        response = client.post("/api/requests/req_live/cancel")
    assert response.status_code == 200
    assert response.json() == {"cancelled": True}
    assert session.cancel_token.cancelled


def test_library_bootstrap_returns_empty_when_no_saves_exist(tmp_path: Path) -> None:
    service = _library_service(tmp_path)
    library = SaveLibrary(tmp_path / "game_state.json")

    with TestClient(create_app(service=service, save_library=library)) as client:
        response = client.get("/api/library/bootstrap")
        state_response = client.get("/api/state")

    assert response.status_code == 200
    assert response.json() == {"active_save_id": None, "saves": []}
    assert state_response.status_code == 409
    assert state_response.json()["detail"] == "No active save selected."


def test_llm_settings_endpoint_defaults_to_kimi(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-key")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    library = SaveLibrary(tmp_path / "game_state.json")
    settings_store = RuntimeSettingsStore(tmp_path / "runtime_settings.json")

    with TestClient(
        create_app(save_library=library, runtime_settings_store=settings_store),
    ) as client:
        response = client.get("/api/settings/llm")

    assert response.status_code == 200
    payload = response.json()
    assert payload["preset"] == LLMPreset.KIMI.value
    assert payload["structured_model"] == DEFAULT_MODEL
    assert payload["narration_model"] == DEFAULT_MODEL
    assert payload["needs_key"] is False
    assert any(credential["source"] == "env" for credential in payload["provider_credentials"])
    assert any(option["id"] == LLMPreset.GEMINI_SPLIT.value for option in payload["presets"])


def test_llm_settings_endpoint_reports_first_run_when_no_credentials_exist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    monkeypatch.setenv("LITELLM_API_KEY", "")
    library = SaveLibrary(tmp_path / "game_state.json")
    settings_store = RuntimeSettingsStore(tmp_path / "runtime_settings.json")
    credentials_store = LLMCredentialsStore(tmp_path / "llm_credentials.json")

    with TestClient(
        create_app(
            save_library=library,
            runtime_settings_store=settings_store,
            credentials_store=credentials_store,
        ),
    ) as client:
        response = client.get("/api/settings/llm")

    assert response.status_code == 200
    payload = response.json()
    assert payload["needs_key"] is True
    assert all(not credential["configured"] for credential in payload["provider_credentials"])
    assert any(not option["available"] for option in payload["presets"])


def test_llm_settings_endpoint_updates_to_gemini_split(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-key")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    library = SaveLibrary(tmp_path / "game_state.json")
    settings_store = RuntimeSettingsStore(tmp_path / "runtime_settings.json")

    with TestClient(
        create_app(save_library=library, runtime_settings_store=settings_store),
    ) as client:
        response = client.post(
            "/api/settings/llm",
            json={"preset": LLMPreset.GEMINI_SPLIT.value},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["preset"] == LLMPreset.GEMINI_SPLIT.value
        assert payload["structured_model"] == DEFAULT_GEMINI_FLASH_MODEL
        assert payload["narration_model"] == DEFAULT_GEMINI_PRO_MODEL
        assert settings_store.load().llm_preset == LLMPreset.GEMINI_SPLIT
        app = cast("Any", client.app)
        assert app.state.llm_runtime.structured.model == DEFAULT_GEMINI_FLASH_MODEL
        assert app.state.llm_runtime.narration.model == DEFAULT_GEMINI_PRO_MODEL


def test_llm_credentials_endpoint_persists_masked_gemini_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    monkeypatch.setenv("LITELLM_API_KEY", "")
    library = SaveLibrary(tmp_path / "game_state.json")
    settings_store = RuntimeSettingsStore(tmp_path / "runtime_settings.json")
    credentials_store = LLMCredentialsStore(tmp_path / "llm_credentials.json")

    with TestClient(
        create_app(
            save_library=library,
            runtime_settings_store=settings_store,
            credentials_store=credentials_store,
        ),
    ) as client:
        response = client.post(
            "/api/settings/credentials",
            json={"provider": LLMProvider.GEMINI.value, "api_key": "gemini-secret-1234"},
        )

    assert response.status_code == 200
    payload = response.json()
    gemini = next(
        credential
        for credential in payload["provider_credentials"]
        if credential["id"] == LLMProvider.GEMINI.value
    )
    assert gemini["configured"] is True
    assert gemini["source"] == "stored"
    assert gemini["masked_key"] == "gemi...1234"
    assert credentials_store.load().gemini_api_key == "gemini-secret-1234"
    assert all(
        "gemini-secret-1234" not in json.dumps(credential)
        for credential in payload["provider_credentials"]
    )


def test_llm_settings_endpoint_uses_stored_credentials_for_preset_switch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    monkeypatch.setenv("LITELLM_API_KEY", "")
    library = SaveLibrary(tmp_path / "game_state.json")
    settings_store = RuntimeSettingsStore(tmp_path / "runtime_settings.json")
    credentials_store = LLMCredentialsStore(tmp_path / "llm_credentials.json")

    with TestClient(
        create_app(
            save_library=library,
            runtime_settings_store=settings_store,
            credentials_store=credentials_store,
        ),
    ) as client:
        save_response = client.post(
            "/api/settings/credentials",
            json={"provider": LLMProvider.GEMINI.value, "api_key": "gemini-stored-key"},
        )
        response = client.post(
            "/api/settings/llm",
            json={"preset": LLMPreset.GEMINI_SPLIT.value},
        )
        assert save_response.status_code == 200
        assert response.status_code == 200
        payload = response.json()
        assert payload["preset"] == LLMPreset.GEMINI_SPLIT.value
        assert payload["structured_model"] == DEFAULT_GEMINI_FLASH_MODEL
        app = cast("Any", client.app)
        assert app.state.llm_runtime.structured.api_key == "gemini-stored-key"
        assert app.state.llm_runtime.narration.api_key == "gemini-stored-key"


def test_llm_settings_endpoint_rejects_switch_while_request_is_in_flight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-key")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    library = SaveLibrary(tmp_path / "game_state.json")
    settings_store = RuntimeSettingsStore(tmp_path / "runtime_settings.json")

    with TestClient(
        create_app(save_library=library, runtime_settings_store=settings_store),
    ) as client:
        cast("Any", client.app).state.stream_runtime.sessions.register(
            "req_live",
            route="test",
            save_id=None,
        )
        response = client.post(
            "/api/settings/llm",
            json={"preset": LLMPreset.GEMINI_SPLIT.value},
        )

    assert response.status_code == 409
    assert (
        response.json()["detail"]
        == "Cannot change LLM settings while a request is still in flight."
    )


def test_create_save_endpoint_selects_new_save_and_exposes_state(tmp_path: Path) -> None:
    service = _library_service(tmp_path)
    library = SaveLibrary(tmp_path / "game_state.json")

    with TestClient(create_app(service=service, save_library=library)) as client:
        response = client.post("/api/library/saves", json={"select": True})
        state_response = client.get("/api/state")

    assert response.status_code == 200
    payload = response.json()
    assert payload["active_save_id"] is not None
    assert len(payload["saves"]) == 1
    assert payload["saves"][0]["campaign_status"] == "character_creation"
    assert state_response.status_code == 200
    assert state_response.json()["campaign_status"] == "character_creation"


def test_select_save_endpoint_switches_the_active_state_store(tmp_path: Path) -> None:
    service = _library_service(tmp_path)
    library = SaveLibrary(tmp_path / "game_state.json")

    first_id = library.create_save(create_state=sample_state(), select=True)
    second_id = library.create_save(create_state=sample_state(), select=False)

    first_store = StateStore(library.state_path_for(first_id))
    first_state = first_store.load()
    first_state.character.name = "Vrtanes"
    first_state.character.epithet = "Myrrh-stained anathematist"
    first_store.save(first_state, create_checkpoint=False)

    second_store = StateStore(library.state_path_for(second_id))
    second_state = second_store.load()
    second_state.character.name = "Sahak"
    second_state.character.epithet = "Apostolic penitent"
    second_store.save(second_state, create_checkpoint=False)

    with TestClient(create_app(service=service, save_library=library)) as client:
        initial = client.get("/api/state")
        switched = client.post("/api/library/select", json={"save_id": second_id})
        after_switch = client.get("/api/state")

    assert initial.status_code == 200
    assert initial.json()["character"]["name"] == "Vrtanes"
    assert switched.status_code == 200
    assert switched.json()["active_save_id"] == second_id
    assert after_switch.status_code == 200
    assert after_switch.json()["character"]["name"] == "Sahak"


def test_select_save_endpoint_rejects_switch_while_request_is_in_flight(
    tmp_path: Path,
) -> None:
    service = _library_service(tmp_path)
    library = SaveLibrary(tmp_path / "game_state.json")

    library.create_save(create_state=service.new_setup_state(), select=True)
    second_id = library.create_save(create_state=service.new_setup_state(), select=False)

    with TestClient(create_app(service=service, save_library=library)) as client:
        cast("Any", client.app).state.stream_runtime.sessions.register(
            "req_live",
            route="test",
            save_id=library.active_save_id(),
        )
        response = client.post("/api/library/select", json={"save_id": second_id})

    assert response.status_code == 409
    assert response.json()["detail"] == "Cannot switch saves while a request is still in flight."


def test_reattach_request_stream_rejects_different_active_save(tmp_path: Path) -> None:
    narrative = BlockingThoughtfulNarrative()
    service = GameService(
        store=StateStore(tmp_path / "seed_game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=narrative,
        explainer=FakeExplainer(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=SetupCharacterGenerator(),
        cairn_engine=FakePlayableCairnEngine(),
        turn_router=TurnRouter(classifier=scripted_classifier),
    )
    library = SaveLibrary(tmp_path / "game_state.json")
    first_id = library.create_save(create_state=sample_state(), select=True)
    second_id = library.create_save(create_state=sample_state(), select=False)

    with TestClient(create_app(service=service, save_library=library)) as client:
        app = cast("Any", client.app)
        response = submit_turn_stream(
            request=_request_for_app(app, "/api/turn/stream"),
            svc=app.state.service,
            stream_runtime=app.state.stream_runtime,
            payload=PlayerTurnRequest(text="I swing my cudgel at the abbey ghoul."),
        )
        initial_events = asyncio.run(_collect_stream_events(response.body_iterator, limit=1))
        request_id = cast("str", initial_events[0]["request_id"])
        assert narrative.started.wait(timeout=1.0)
        narrative.release.set()
        resumed = reattach_request_stream(
            request=_request_for_app(app, f"/api/requests/{request_id}/stream"),
            request_id=request_id,
            stream_runtime=app.state.stream_runtime,
        )
        resumed_events = asyncio.run(_collect_stream_events(resumed.body_iterator))
        assert resumed_events[-1]["type"] == "final_state"
        assert client.post("/api/library/select", json={"save_id": second_id}).status_code == 200
        wrong_save = client.get(f"/api/requests/{request_id}/stream")

    assert first_id != second_id
    assert wrong_save.status_code == 409
    assert wrong_save.json()["detail"] == "Request belongs to a different active save."


def test_state_round_trip(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        first = client.get("/api/state").json()
        second = client.get("/api/state").json()
    # The campaign is generated once on the first read and persisted, so a
    # second read must return the same canonical state - this is what
    # protects us from "the oracle keeps regenerating my campaign" bugs.
    assert first["id"] == second["id"]
    assert len(first["threads"]) == 3


def test_chaos_factor_clamped(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post("/api/state/chaos", json={"value": 12})
    # Pydantic must reject out-of-range values up front; we never want a
    # chaos factor outside [1, 9] to slip into the persisted state file.
    assert response.status_code == 422


def test_chaos_factor_persists(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        client.post("/api/state/chaos", json={"value": 7})
        state = client.get("/api/state").json()
    assert state["chaos_factor"] == 7


def test_oracle_yes_no(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/api/oracle/yes-no",
            json={"question": "Does anything stir?", "likelihood": "Even odds"},
        )
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["oracle_history"]) == 1
    assert payload["oracle_history"][0]["kind"] == "yes_no"


def test_oracle_yes_no_preview_returns_non_canonical_outcome(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/api/oracle/yes-no/preview",
            json={"question": "Does anything stir?", "likelihood": "Even odds"},
        )
        state = client.get("/api/state").json()

    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "yes_no"
    assert payload["question"] == "Does anything stir?"
    assert state["oracle_history"] == []
    assert all(event["title"] != "Oracle answer" for event in state["action_log"])


def test_random_event_uses_generated_tables(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post("/api/oracle/random-event")
    assert response.status_code == 200
    outcome = response.json()["oracle_history"][0]
    # Random events must pull from the campaign-generated word banks; a
    # missing focus/action would mean we accidentally re-introduced the
    # hardcoded oracle tables.
    assert outcome["event_focus"]
    assert outcome["event_action"]


def test_scene_check_advances_scene(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/api/oracle/scene-check",
            json={"expected_scene": "I cross the bone bridge."},
        )
    state = response.json()
    assert state["scene_number"] >= 2


def test_scene_check_same_scene_does_not_increment_scene_number(tmp_path: Path) -> None:
    class SameSceneOracle(OracleEngine):
        def check_scene(self, state: GameState, expected_scene: str) -> OracleOutcome:
            return OracleOutcome(
                kind=OracleKind.SCENE_CHECK,
                summary=f"expected: {expected_scene}",
                question=expected_scene,
                chaos_factor=state.chaos_factor,
                scene_status=SceneStatus.EXPECTED,
            )

    store = StateStore(tmp_path / "game_state.json")
    state = sample_state()
    state.current_scene = "The ossuary chapel."
    state.scene_status = SceneStatus.EXPECTED
    store.save(state, create_checkpoint=False)
    service = GameService(
        store=store,
        oracle=SameSceneOracle(),
        narrative=FakeNarrative(),
        explainer=FakeExplainer(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakePlayableCairnEngine(),
        turn_router=TurnRouter(classifier=scripted_classifier),
    )
    with TestClient(create_app(service=service)) as client:
        response = client.post(
            "/api/oracle/scene-check",
            json={"expected_scene": "The ossuary chapel."},
        )

    assert response.status_code == 200
    assert response.json()["scene_number"] == 1
