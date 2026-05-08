from collections.abc import Generator

import pytest
from litellm.types.utils import ModelResponse

from dungeon_master.cancel import CancellationRegistry, RequestCancelledError
from dungeon_master.models import OracleKind, OracleOutcome
from dungeon_master.narrative import (
    DEFAULT_MODEL,
    DEFAULT_REASONING_POLICY,
    CompletionRequest,
    NarrativeConfig,
    NarrativeEngine,
    _completion,
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


class SlowStreamingCompletion:
    def __call__(self, request: CompletionRequest) -> ModelResponse:
        cancel_token = request.cancel_token

        def _stream() -> Generator[dict[str, object], None, None]:
            yield {"choices": [{"delta": {"thinking": "first"}}]}
            if cancel_token is not None:
                cancel_token.cancel()
            while True:
                yield {"choices": [{"delta": {"content": "late"}}]}

        return _stream()  # type: ignore[return-value]


def test_default_narrative_config_uses_openrouter_kimi(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("LITELLM_MODEL", raising=False)

    config = NarrativeConfig.from_env()

    assert config.model == DEFAULT_MODEL
    assert config.api_key == "test-key"
    assert config.reasoning_policy == DEFAULT_REASONING_POLICY
    # We default to streaming reasoning back so the UI can show a live
    # "thinking..." chip while Kimi K2.6 spends 60-180s on internal
    # deliberation. Set LITELLM_EXCLUDE_REASONING=true to opt out.
    assert config.exclude_reasoning is False
    assert config.temperature == 1.25
    assert config.max_tokens == 4500
    assert config.timeout_seconds == 600.0
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
    assert completion.reasoning_effort == "medium"
    # OpenRouter forbids combining `effort` and `max_tokens` in the nested
    # reasoning dict, so we surface `effort` only via the top-level
    # `reasoning_effort` alias and keep `max_tokens` here for deterministic
    # budget control.
    assert completion.reasoning == {"max_tokens": 1200, "exclude": True}


def test_completion_logs_llm_trace(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fake_completion(**_: object) -> ModelResponse:
        return ModelResponse(
            choices=[{"message": {"role": "assistant", "content": "The abbey waits."}}],
            usage={"prompt_tokens": 123, "completion_tokens": 45, "total_tokens": 168},
        )

    monkeypatch.setattr("dungeon_master.narrative.litellm_completion", fake_completion)
    request = CompletionRequest(
        model="test-model",
        messages=[{"role": "user", "content": "hello"}],
        temperature=0.1,
        max_tokens=32,
        timeout=1.0,
        stream=False,
        api_key=None,
        base_url=None,
        reasoning_effort="low",
        reasoning={"exclude": True},
        extra_headers=None,
        trace_route="test.route",
        trace_profile="test.profile",
    )

    caplog.set_level("INFO", logger="dungeon_master.trace")
    _completion(request)

    assert any(
        'llm.call route="test.route" profile="test.profile" request_id=null '
        'model="test-model" stream=false prompt_tokens=123 completion_tokens=45'
        in message
        for message in caplog.messages
    )


def test_narrative_prompt_prefers_compact_grounded_prose() -> None:
    completion = RecordingCompletion()
    state = sample_state()
    outcome = OracleOutcome(
        kind=OracleKind.PLAYER_ACTION,
        summary="Narrative continuation requested without an oracle roll.",
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

    engine.generate(state, outcome, "I check my supplies before leaving.")

    assert completion.messages is not None
    system_prompt = completion.messages[0]["content"]
    user_prompt = completion.messages[1]["content"]
    assert "usually one paragraph, at most two" in system_prompt
    assert "Mirror the player's declared action before extending the scene." in system_prompt
    assert "Address the player-character in second person" in system_prompt
    assert "latent threats as flavor" in system_prompt
    assert "hardened present-tense facts" in system_prompt
    assert "Write 1-2 compact paragraphs of playable narration, usually 1." in user_prompt
    assert "Use second person (`you`) for the player-character." in user_prompt
    assert "Only harden facts that are supported by the supplied outcome/state." in user_prompt


def test_narrative_prompt_includes_bounded_memory_context() -> None:
    completion = RecordingCompletion()
    state = sample_state()
    outcome = OracleOutcome(
        kind=OracleKind.PLAYER_ACTION,
        summary="Narrative continuation requested without an oracle roll.",
        chaos_factor=state.chaos_factor,
    )
    engine = NarrativeEngine(
        config=NarrativeConfig(
            model=DEFAULT_MODEL,
            api_key="test-key",
            base_url="https://openrouter.ai/api/v1",
            reasoning_policy="auto",
            exclude_reasoning=True,
        ),
        completion_function=completion,
    )

    engine.generate(
        state,
        outcome,
        "I press into the abbey yard.",
        memory_context="Current scene summary: The abbey yard is wet with ash.",
    )

    assert completion.messages is not None
    user_prompt = completion.messages[1]["content"]
    assert "Bounded memory context:" in user_prompt
    assert "The abbey yard is wet with ash." in user_prompt


def test_narrative_prompt_includes_campaign_directives_when_present() -> None:
    completion = RecordingCompletion()
    state = sample_state()
    state.directives.world_guidance = "Keep miracles subtle and costly."
    state.directives.play_guidance = "The hierophant cannot speak first."
    outcome = OracleOutcome(
        kind=OracleKind.PLAYER_ACTION,
        summary="Narrative continuation requested without an oracle roll.",
        chaos_factor=state.chaos_factor,
    )
    engine = NarrativeEngine(
        config=NarrativeConfig(
            model=DEFAULT_MODEL,
            api_key="test-key",
            base_url="https://openrouter.ai/api/v1",
            reasoning_policy="auto",
            exclude_reasoning=True,
        ),
        completion_function=completion,
    )

    engine.generate(state, outcome, "I wait for the hierophant to answer.")

    assert completion.messages is not None
    user_prompt = completion.messages[1]["content"]
    assert "Campaign directives:" in user_prompt
    assert "Keep miracles subtle and costly." in user_prompt
    assert "The hierophant cannot speak first." in user_prompt


def test_narrative_prompt_compacts_character_payload() -> None:
    completion = RecordingCompletion()
    state = sample_state()
    outcome = OracleOutcome(
        kind=OracleKind.PLAYER_ACTION,
        summary="Narrative continuation requested without an oracle roll.",
        chaos_factor=state.chaos_factor,
    )
    engine = NarrativeEngine(
        config=NarrativeConfig(
            model=DEFAULT_MODEL,
            api_key="test-key",
            base_url="https://openrouter.ai/api/v1",
            reasoning_policy="auto",
            exclude_reasoning=True,
        ),
        completion_function=completion,
    )

    engine.generate(state, outcome, "I check my knife and rations.")

    assert completion.messages is not None
    user_prompt = completion.messages[1]["content"]
    assert state.character.model_dump_json() not in user_prompt
    assert '"inventory":' in user_prompt
    assert '"name":"Test Wanderer"' in user_prompt


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
    assert completion.reasoning == {"max_tokens": 1200, "exclude": True}


def test_narrative_stream_raises_on_cancellation_without_fallback() -> None:
    registry = CancellationRegistry()
    token = registry.register("req_test")
    state = sample_state()
    outcome = OracleOutcome(
        kind=OracleKind.PLAYER_ACTION,
        summary="Narration continues.",
        chaos_factor=state.chaos_factor,
    )
    config = NarrativeConfig(
        model=DEFAULT_MODEL,
        api_key="test-key",
        base_url="https://openrouter.ai/api/v1",
    )
    engine = NarrativeEngine(config=config, completion_function=SlowStreamingCompletion())

    stream = engine.iter_stream(state, outcome, "I listen.", cancel_token=token)
    first = next(stream)

    assert first.thinking == "first"
    with pytest.raises(RequestCancelledError):
        next(stream)
