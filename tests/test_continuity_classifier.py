import pytest
from litellm.types.utils import ModelResponse

from dungeon_master.continuity_classifier import ContinuityClassifier, ContinuityUpdateScope
from dungeon_master.models import NPC, OracleKind, OracleOutcome
from dungeon_master.narrative import CompletionRequest, NarrativeConfig
from tests.factories import sample_state


class RecordingContinuityCompletion:
    def __init__(self, content: str) -> None:
        self._content = content
        self.request: CompletionRequest | None = None

    def __call__(self, request: CompletionRequest) -> ModelResponse:
        self.request = request

        def _stream() -> list[dict[str, object]]:
            return [
                {
                    "choices": [
                        {
                            "delta": {
                                "content": self._content,
                            },
                        },
                    ],
                },
            ]

        return _stream()  # type: ignore[return-value]


def test_continuity_classifier_parses_keyword_scope() -> None:
    completion = RecordingContinuityCompletion("threads")
    classifier = ContinuityClassifier(
        config=NarrativeConfig(model="test-model", api_key=None, base_url=None),
        completion_function=completion,
    )
    state = sample_state()
    outcome = OracleOutcome(
        kind=OracleKind.PLAYER_ACTION,
        summary="A vow takes hold.",
        chaos_factor=5,
    )

    scope = classifier.classify_update_scope(
        state,
        player_input="I swear to hunt the ferryman down.",
        outcome=outcome,
    )

    assert scope == ContinuityUpdateScope.THREADS


def test_continuity_classifier_falls_back_to_both_on_invalid_output() -> None:
    completion = RecordingContinuityCompletion("maybe")
    classifier = ContinuityClassifier(
        config=NarrativeConfig(model="test-model", api_key=None, base_url=None),
        completion_function=completion,
    )
    state = sample_state()
    outcome = OracleOutcome(
        kind=OracleKind.PLAYER_ACTION,
        summary="Nothing durable changes.",
        chaos_factor=5,
    )

    scope = classifier.classify_update_scope(
        state,
        player_input="I say something local and self-contained.",
        outcome=outcome,
    )

    assert scope == ContinuityUpdateScope.BOTH


def test_continuity_classifier_prompt_is_small_and_grounded() -> None:
    completion = RecordingContinuityCompletion("both")
    classifier = ContinuityClassifier(
        config=NarrativeConfig(model="test-model", api_key=None, base_url=None),
        completion_function=completion,
    )
    state = sample_state()
    state.hidden_npcs.append(
        NPC(
            name="The Hierophant",
            role="Face-thief patriarch",
            disposition="patient malice",
        ),
    )
    outcome = OracleOutcome(
        kind=OracleKind.PLAYER_ACTION,
        summary="The watcher refuses to answer.",
        chaos_factor=5,
    )

    scope = classifier.classify_update_scope(
        state,
        player_input="I ask the watcher what he wants from me.",
        outcome=outcome,
        execution_context="Executed backend steps:\n- Checked carried gear.",
    )

    assert scope == ContinuityUpdateScope.BOTH
    assert completion.request is not None
    assert completion.request.max_tokens == 16
    assert completion.request.reasoning == {"max_tokens": 32, "exclude": True}
    assert completion.request.messages[1]["content"]
    user_prompt = completion.request.messages[1]["content"]
    assert "Current threads:" in user_prompt
    assert "Visible recurring NPCs:" in user_prompt
    assert "Hidden recurring NPCs:" in user_prompt
    assert "The Hierophant" in user_prompt


def test_continuity_classifier_logs_scope_and_traces_request(
    caplog: pytest.LogCaptureFixture,
) -> None:
    completion = RecordingContinuityCompletion("threads")
    classifier = ContinuityClassifier(
        config=NarrativeConfig(model="test-model", api_key=None, base_url="https://example.com"),
        completion_function=completion,
    )
    state = sample_state()
    outcome = OracleOutcome(
        kind=OracleKind.PLAYER_ACTION,
        summary="A vow takes hold.",
        chaos_factor=5,
    )

    caplog.set_level("INFO", logger="dungeon_master.trace")
    scope = classifier.classify_update_scope(
        state,
        player_input="I swear to hunt the ferryman down.",
        outcome=outcome,
    )

    assert scope == ContinuityUpdateScope.THREADS
    assert completion.request is not None
    assert completion.request.trace_route == "continuity_classifier.scope"
    assert completion.request.trace_profile == "continuity_classifier"
    assert any(
        'continuity.classifier scope="threads" source="model"' in message
        for message in caplog.messages
    )
