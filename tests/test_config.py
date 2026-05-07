import pytest

from dungeon_master.config import AppConfig, LLMConfig
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
    assert config.llm.temperature == 1.25
    assert config.llm.max_tokens == 4500
    assert config.llm.timeout_seconds == 600.0
    assert narration_profile.temperature == 1.25
    assert narration_profile.max_tokens == 4500


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
    assert config.profiles.turn_router.temperature == 0.05
    assert config.profiles.thread_updater.temperature == 0.05
    assert config.profiles.npc_updater.temperature == 0.05
    assert config.profiles.campaign_world.max_tokens == 12000
