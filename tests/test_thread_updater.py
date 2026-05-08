from litellm.types.utils import ModelResponse

from dungeon_master.models import OracleKind, OracleOutcome, ThreadStatus
from dungeon_master.narrative import CompletionRequest, NarrativeConfig
from dungeon_master.thread_updater import ThreadUpdater
from tests.factories import sample_state


class RecordingThreadCompletion:
    def __init__(self, payload: str) -> None:
        self.payload = payload
        self.messages: list[dict[str, str]] | None = None

    def __call__(self, request: CompletionRequest) -> ModelResponse:
        self.messages = request.messages
        del request

        def _stream() -> list[dict[str, object]]:
            return [
                {
                    "choices": [
                        {
                            "delta": {
                                "content": self.payload,
                            },
                        },
                    ],
                },
            ]

        return _stream()  # type: ignore[return-value]


def _updater(payload: str) -> ThreadUpdater:
    return ThreadUpdater(
        config=NarrativeConfig(model="test-model", api_key=None, base_url=None, max_retries=0),
        completion_function=RecordingThreadCompletion(payload),
    )


def test_thread_updater_creates_new_thread_from_validated_json() -> None:
    state = sample_state()
    updater = _updater(
        """
        {
          "ops": [
            {
              "kind": "create",
              "thread_id": null,
              "title": "The hierophant's unfinished demand",
              "stakes": "If ignored, the anathema he named will return with harsher terms."
            }
          ]
        }
        """,
    )
    outcome = OracleOutcome(
        kind=OracleKind.PLAYER_ACTION,
        summary="You accept the terms but leave the cost undefined.",
        chaos_factor=state.chaos_factor,
    )

    result = updater.update_threads(
        state,
        player_input="I tell him I will hear the charge.",
        outcome=outcome,
        execution_context="Executed backend steps:\n- Narrative continuation requested.",
        memory_context="Current threads:\n- Generated thread one",
    )

    created = next(
        thread for thread in state.threads if thread.title == "The hierophant's unfinished demand"
    )
    assert result.touched_thread_ids == (created.id,)
    assert created.status == ThreadStatus.ACTIVE


def test_thread_updater_can_update_and_resolve_existing_threads() -> None:
    state = sample_state()
    updater = _updater(
        f"""
        {{
          "ops": [
            {{
              "kind": "update",
              "thread_id": "{state.threads[0].id}",
              "title": "Generated thread one",
              "stakes": "The abbey witness now knows your face and can expose you."
            }},
            {{
              "kind": "resolve",
              "thread_id": "{state.threads[1].id}",
              "title": "Generated thread two",
              "stakes": "Its demand is discharged; only the aftermath remains."
            }}
          ]
        }}
        """,
    )
    outcome = OracleOutcome(
        kind=OracleKind.RANDOM_EVENT,
        summary="Thread pressure: a witness binds the old debt closed.",
        chaos_factor=state.chaos_factor,
        referenced_thread_id=state.threads[0].id,
    )

    result = updater.update_threads(
        state,
        player_input="I force the witness to name who sent him.",
        outcome=outcome,
    )

    assert result.touched_thread_ids == (state.threads[0].id, state.threads[1].id)
    assert state.threads[0].stakes == "The abbey witness now knows your face and can expose you."
    assert state.threads[1].status == ThreadStatus.RESOLVED


def test_thread_updater_skips_invalid_targets_and_duplicate_creates() -> None:
    state = sample_state()
    updater = _updater(
        """
        {
          "ops": [
            {
              "kind": "create",
              "thread_id": null,
              "title": "Generated thread one",
              "stakes": "A duplicate create should collapse onto the existing thread."
            },
            {
              "kind": "resolve",
              "thread_id": "thread_missing",
              "title": "Ghost thread",
              "stakes": "Should be ignored."
            }
          ]
        }
        """,
    )
    outcome = OracleOutcome(
        kind=OracleKind.YES_NO,
        summary="Yes: The old debt still follows you.",
        chaos_factor=state.chaos_factor,
    )

    result = updater.update_threads(
        state,
        player_input="Does the old debt still matter here?",
        outcome=outcome,
    )

    assert len(state.threads) == 3
    assert result.touched_thread_ids == (state.threads[0].id,)


def test_thread_updater_prompt_includes_final_narration_when_supplied() -> None:
    completion = RecordingThreadCompletion('{"ops":[]}')
    updater = ThreadUpdater(
        config=NarrativeConfig(model="test-model", api_key=None, base_url=None, max_retries=0),
        completion_function=completion,
    )
    state = sample_state()
    outcome = OracleOutcome(
        kind=OracleKind.PLAYER_ACTION,
        summary="Narrative continuation requested without an oracle roll.",
        chaos_factor=state.chaos_factor,
    )

    generated = updater.generate_thread_updates(
        state,
        player_input="I ask the patriarch for his forgotten name.",
        outcome=outcome,
        narrative_text="The old relief names him Saint Vyr, whose oath still binds the pass.",
    )

    assert generated is not None
    assert completion.messages is not None
    user_prompt = completion.messages[1]["content"]
    assert "Final narration response" in user_prompt
    assert "Saint Vyr" in user_prompt
