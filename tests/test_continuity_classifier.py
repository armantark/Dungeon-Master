import pytest
from litellm.types.utils import ModelResponse

from dungeon_master.continuity_classifier import ContinuityClassifier, ContinuityUpdateScope
from dungeon_master.models import NPC, NPCPlayerLabelKind, OracleKind, OracleOutcome
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
    assert "Clarification and lore-check questions" in completion.request.messages[0]["content"]
    system_prompt = " ".join(completion.request.messages[0]["content"].split())
    assert "is he of legend?" in system_prompt
    assert "known name, no known name, a title/descriptor only" in system_prompt
    assert "must not pre-answer that question" in system_prompt
    assert "pre-narration lookup" in completion.request.messages[0]["content"]
    assert "Generated narration" in user_prompt
    assert "(not generated yet)" in user_prompt


def test_continuity_classifier_can_skip_clarification_lore_questions() -> None:
    completion = RecordingContinuityCompletion("none")
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
        summary="Narrative continuation requested without an oracle roll.",
        chaos_factor=5,
    )

    scope = classifier.classify_update_scope(
        state,
        player_input="Do we know his name? Or is it of legend?",
        outcome=outcome,
    )

    assert scope == ContinuityUpdateScope.NONE


def test_continuity_classifier_prompt_distinguishes_resolved_disclosures() -> None:
    completion = RecordingContinuityCompletion("npcs")
    classifier = ContinuityClassifier(
        config=NarrativeConfig(model="test-model", api_key=None, base_url=None),
        completion_function=completion,
    )
    state = sample_state()
    outcome = OracleOutcome(
        kind=OracleKind.PLAYER_ACTION,
        summary="The icon's patriarch is named as Saint Vyr, a dead patron of the abbey.",
        chaos_factor=5,
    )

    scope = classifier.classify_update_scope(
        state,
        player_input="Do we know his name?",
        outcome=outcome,
    )

    assert scope == ContinuityUpdateScope.NPCS
    assert completion.request is not None
    system_prompt = " ".join(completion.request.messages[0]["content"].split())
    assert "If the resolved turn already says a durable change happened" in system_prompt
    assert "a name is disclosed" in system_prompt


def test_continuity_classifier_prompt_uses_generated_narration_for_post_check() -> None:
    completion = RecordingContinuityCompletion("both")
    classifier = ContinuityClassifier(
        config=NarrativeConfig(model="test-model", api_key=None, base_url=None),
        completion_function=completion,
    )
    state = sample_state()
    outcome = OracleOutcome(
        kind=OracleKind.PLAYER_ACTION,
        summary="Narrative continuation requested without an oracle roll.",
        chaos_factor=5,
    )

    scope = classifier.classify_update_scope(
        state,
        player_input="Do we know his name?",
        outcome=outcome,
        narrative_text="The lead icon names him Saint Vyr, first patriarch of the pass.",
    )

    assert scope == ContinuityUpdateScope.BOTH
    assert completion.request is not None
    user_prompt = completion.request.messages[1]["content"]
    system_prompt = " ".join(completion.request.messages[0]["content"].split())
    assert "Generated narration, if this is a post-narration check:" in user_prompt
    assert "Saint Vyr" in user_prompt
    assert "judge the actual prose" in system_prompt
    assert "newly establishes durable lore" in system_prompt


def test_continuity_classifier_prompt_mentions_descriptor_name_reveals() -> None:
    completion = RecordingContinuityCompletion("npcs")
    classifier = ContinuityClassifier(
        config=NarrativeConfig(model="test-model", api_key=None, base_url=None),
        completion_function=completion,
    )
    state = sample_state()
    state.npcs = [
        NPC(
            name="Covenant Blood-hierarch",
            player_label="Blood-hierarch",
            player_label_kind=NPCPlayerLabelKind.DESCRIPTOR,
            role="High-ranking Covenant priest",
        ),
    ]
    outcome = OracleOutcome(
        kind=OracleKind.PLAYER_ACTION,
        summary="Narrative continuation requested without an oracle roll.",
        chaos_factor=5,
    )

    scope = classifier.classify_update_scope(
        state,
        player_input="I ask the hierarch his name.",
        outcome=outcome,
        narrative_text="The priest murmurs, 'You may call me Ennius.'",
    )

    assert scope == ContinuityUpdateScope.NPCS
    assert completion.request is not None
    system_prompt = " ".join(completion.request.messages[0]["content"].split())
    assert "newly revealed proper name for a descriptor-visible NPC" in system_prompt


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
