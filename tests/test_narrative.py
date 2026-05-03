import pytest
from litellm.types.utils import ModelResponse

from dungeon_master.models import OracleKind, OracleOutcome
from dungeon_master.narrative import (
    DEFAULT_MODEL,
    DEFAULT_REASONING_POLICY,
    CompletionRequest,
    NarrativeConfig,
    NarrativeEngine,
)
from tests.factories import sample_state


class RecordingCompletion:
    def __init__(self) -> None:
        self.model: str | None = None
        self.messages: list[dict[str, str]] | None = None
        self.reasoning_effort: str | None = None
        self.reasoning: dict[str, object] | None = None
        self.api_key: str | None = None

    def __call__(self, request: CompletionRequest) -> ModelResponse:
        self.model = request.model
        self.messages = request.messages
        self.reasoning_effort = request.reasoning_effort
        self.reasoning = request.reasoning
        self.api_key = request.api_key
        return ModelResponse(
            choices=[{"message": {"role": "assistant", "content": "The abbey waits."}}],
        )


def test_default_narrative_config_uses_openrouter_kimi(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("LITELLM_MODEL", raising=False)

    config = NarrativeConfig.from_env()

    assert config.model == DEFAULT_MODEL
    assert config.api_key == "test-key"
    assert config.reasoning_policy == DEFAULT_REASONING_POLICY
    assert config.exclude_reasoning is True
    assert config.is_usable()


def test_openrouter_model_without_key_uses_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    # `NarrativeConfig.from_env` calls `load_dotenv()`, which (by default,
    # `override=False`) refuses to overwrite already-set env vars but
    # *does* fill in unset ones. Simply deleting the variable would let
    # `.env` re-supply a real key on the developer's machine, defeating
    # the test. Setting an explicit empty string blocks the .env fallback
    # and keeps the test deterministic across environments.
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setenv("LITELLM_API_KEY", "")
    state = sample_state()
    outcome = OracleOutcome(
        kind=OracleKind.PLAYER_ACTION,
        summary="No oracle roll.",
        chaos_factor=state.chaos_factor,
    )
    engine = NarrativeEngine(config=NarrativeConfig.from_env())

    result = engine.generate(state, outcome, "I wait.")

    assert "No model is configured" in result


def test_narrative_engine_passes_task_based_reasoning_to_litellm() -> None:
    completion = RecordingCompletion()
    state = sample_state()
    outcome = OracleOutcome(
        kind=OracleKind.RANDOM_EVENT,
        summary="A random event demands synthesis.",
        chaos_factor=state.chaos_factor,
    )
    config = NarrativeConfig(
        model=DEFAULT_MODEL,
        api_key="test-key",
        base_url="https://openrouter.ai/api/v1",
        reasoning_policy="auto",
        exclude_reasoning=True,
    )
    engine = NarrativeEngine(config=config, completion_function=completion)

    result = engine.generate(state, outcome, "I knock on the abbey gate.")

    assert result == "The abbey waits."
    assert completion.model == DEFAULT_MODEL
    assert completion.api_key == "test-key"
    assert completion.reasoning_effort == "high"
    assert completion.reasoning == {"effort": "high", "exclude": True}


def test_narrative_engine_allows_fixed_medium_reasoning() -> None:
    completion = RecordingCompletion()
    state = sample_state()
    outcome = OracleOutcome(
        kind=OracleKind.SCENE_CHECK,
        summary="A scene check would normally use high reasoning.",
        chaos_factor=state.chaos_factor,
    )
    config = NarrativeConfig(
        model=DEFAULT_MODEL,
        api_key="test-key",
        base_url="https://openrouter.ai/api/v1",
        reasoning_policy="medium",
        exclude_reasoning=True,
    )
    engine = NarrativeEngine(config=config, completion_function=completion)

    engine.generate(state, outcome, "I enter the hospice.")

    assert completion.reasoning_effort == "medium"
    assert completion.reasoning == {"effort": "medium", "exclude": True}
