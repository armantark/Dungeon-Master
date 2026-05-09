from pathlib import Path

import pytest

from dungeon_master.config import (
    DEFAULT_GEMINI_FLASH_MODEL,
    DEFAULT_GEMINI_PRO_MODEL,
    AppConfig,
    LLMConfig,
    LLMCredentials,
    LLMCredentialsStore,
    LLMPreset,
    LLMRuntimeSettings,
    RuntimeSettingsStore,
    build_llm_runtime,
)
from dungeon_master.models import OracleKind


def test_app_config_uses_new_narration_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("LITELLM_NARRATION_TEMPERATURE", raising=False)
    monkeypatch.delenv("LITELLM_TEMPERATURE", raising=False)
    monkeypatch.delenv("LITELLM_NARRATION_MAX_TOKENS", raising=False)
    monkeypatch.delenv("LITELLM_MAX_TOKENS", raising=False)
    monkeypatch.delenv("LITELLM_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("DUNGEON_MASTER_STATE_PATH", raising=False)

    config = AppConfig.from_env()
    narration_profile = config.llm.profiles.narration_for(
        kind=OracleKind.PLAYER_ACTION,
        reasoning_policy=config.llm.reasoning_policy,
    )

    assert config.state_path.as_posix() == "data/game_state.json"
    assert config.credentials_path.as_posix() == "data/llm_credentials.json"
    assert config.llm.temperature == 1.25
    assert config.llm.max_tokens == 4500
    assert config.llm.timeout_seconds == 600.0
    assert narration_profile.temperature == 1.25
    assert narration_profile.max_tokens == 4500
    assert narration_profile.reasoning_effort == "minimal"
    assert narration_profile.reasoning(default_exclude=False) == {
        "max_tokens": 300,
        "exclude": False,
    }


def test_llm_config_accepts_deprecated_narration_knobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("LITELLM_TEMPERATURE", "1.4")
    monkeypatch.setenv("LITELLM_MAX_TOKENS", "5200")
    monkeypatch.delenv("LITELLM_NARRATION_TEMPERATURE", raising=False)
    monkeypatch.delenv("LITELLM_NARRATION_MAX_TOKENS", raising=False)

    config = LLMConfig.from_env()
    narration_profile = config.profiles.narration_for(
        kind=OracleKind.YES_NO,
        reasoning_policy=config.reasoning_policy,
    )

    assert config.temperature == 1.4
    assert config.max_tokens == 5200
    assert narration_profile.temperature == 1.4
    assert narration_profile.max_tokens == 5200
    assert narration_profile.reasoning_effort == "minimal"


def test_llm_profiles_keep_structured_calls_low_temperature() -> None:
    config = LLMConfig(
        model="test-model",
        api_key="test-key",
        base_url="https://example.com",
        temperature=1.35,
        max_tokens=5100,
    )
    narration_profile = config.profiles.narration_for(
        kind=OracleKind.RANDOM_EVENT,
        reasoning_policy=config.reasoning_policy,
    )

    assert narration_profile.temperature == 1.35
    assert narration_profile.reasoning_effort == "low"
    assert narration_profile.reasoning_max_tokens == 600
    assert config.profiles.turn_router.temperature == 0.05
    assert config.profiles.turn_router.reasoning_effort == "minimal"
    assert config.profiles.turn_router.reasoning_max_tokens == 64
    assert config.profiles.turn_router.reasoning(default_exclude=False) == {
        "max_tokens": 64,
        "exclude": True,
    }
    assert config.profiles.thread_updater.temperature == 0.05
    assert config.profiles.thread_updater.reasoning(default_exclude=False) == {
        "max_tokens": 96,
        "exclude": True,
    }
    assert config.profiles.npc_updater.temperature == 0.05
    assert config.profiles.npc_updater.reasoning(default_exclude=False) == {
        "max_tokens": 96,
        "exclude": True,
    }
    assert config.profiles.campaign_world.max_tokens == 12000


def test_build_llm_runtime_uses_gemini_split_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-key")

    runtime = build_llm_runtime(LLMRuntimeSettings(llm_preset=LLMPreset.GEMINI_SPLIT))

    assert runtime.structured.model == DEFAULT_GEMINI_FLASH_MODEL
    assert runtime.narration.model == DEFAULT_GEMINI_PRO_MODEL
    assert runtime.reasoning.model == DEFAULT_GEMINI_PRO_MODEL
    assert runtime.structured.api_key == "gemini-key"
    assert runtime.narration.api_key == "gemini-key"
    assert runtime.structured.base_url is None
    assert runtime.narration.base_url is None


def test_build_llm_runtime_prefers_stored_credentials_over_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "env-openrouter")
    monkeypatch.setenv("GEMINI_API_KEY", "env-gemini")

    runtime = build_llm_runtime(
        LLMRuntimeSettings(llm_preset=LLMPreset.GEMINI_SPLIT),
        LLMCredentials(
            openrouter_api_key="stored-openrouter",
            gemini_api_key="stored-gemini",
        ),
    )

    assert runtime.structured.api_key == "stored-gemini"
    assert runtime.narration.api_key == "stored-gemini"


def test_runtime_settings_store_round_trips(tmp_path: Path) -> None:
    store = RuntimeSettingsStore(tmp_path / "runtime_settings.json")

    initial = store.load()
    store.save(LLMRuntimeSettings(llm_preset=LLMPreset.GEMINI_SPLIT))
    reloaded = store.load()

    assert initial.llm_preset == LLMPreset.KIMI
    assert reloaded.llm_preset == LLMPreset.GEMINI_SPLIT


def test_credentials_store_round_trips(tmp_path: Path) -> None:
    store = LLMCredentialsStore(tmp_path / "llm_credentials.json")

    initial = store.load()
    store.save(
        LLMCredentials(
            openrouter_api_key="openrouter-secret",
            gemini_api_key="gemini-secret",
        ),
    )
    reloaded = store.load()

    assert initial.openrouter_api_key is None
    assert initial.gemini_api_key is None
    assert reloaded.openrouter_api_key == "openrouter-secret"
    assert reloaded.gemini_api_key == "gemini-secret"
