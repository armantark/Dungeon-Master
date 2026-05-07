from litellm.types.utils import ModelResponse

from dungeon_master.models import NPCPlayerLabelKind, NPCStatus, OracleKind, OracleOutcome
from dungeon_master.narrative import CompletionRequest, NarrativeConfig
from dungeon_master.npc_updater import NPCUpdater
from tests.factories import sample_state


class RecordingNPCCompletion:
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


def _updater(payload: str) -> NPCUpdater:
    return NPCUpdater(
        config=NarrativeConfig(model="test-model", api_key=None, base_url=None, max_retries=0),
        completion_function=RecordingNPCCompletion(payload),
    )


def test_npc_updater_creates_new_npc_from_validated_json() -> None:
    state = sample_state()
    updater = _updater(
        """
        {
          "ops": [
            {
              "kind": "create",
              "npc_id": null,
              "name": "Brother Vahagn",
              "role": "Bell-ringer hiding a blood debt",
              "disposition": "guarded"
            }
          ]
        }
        """,
    )
    outcome = OracleOutcome(
        kind=OracleKind.PLAYER_ACTION,
        summary="A bell-ringer steps from the cloister shadows and names your sin.",
        chaos_factor=state.chaos_factor,
    )

    result = updater.update_npcs(
        state,
        player_input="I ask the bell-ringer why he watches me.",
        outcome=outcome,
        execution_context="Executed backend steps:\n- Narrative continuation requested.",
        memory_context="Current NPCs:\n- Generated NPC One",
    )

    created = next(npc for npc in state.npcs if npc.name == "Brother Vahagn")
    assert result.touched_npc_ids == (created.id,)
    assert created.status == NPCStatus.ACTIVE
    assert created.role == "Bell-ringer hiding a blood debt"


def test_npc_updater_can_update_and_retire_existing_npcs() -> None:
    state = sample_state()
    updater = _updater(
        f"""
        {{
          "ops": [
            {{
              "kind": "update",
              "npc_id": "{state.npcs[0].id}",
              "name": "Generated NPC One",
              "role": "Abbey witness turned informant",
              "disposition": "fearful"
            }},
            {{
              "kind": "retire",
              "npc_id": "{state.npcs[1].id}",
              "name": "Generated NPC Two",
              "role": "Dismissed watchman",
              "disposition": "gone to ground"
            }}
          ]
        }}
        """,
    )
    outcome = OracleOutcome(
        kind=OracleKind.RANDOM_EVENT,
        summary="NPC pressure: the witness breaks and the watchman withdraws.",
        chaos_factor=state.chaos_factor,
        referenced_npc_id=state.npcs[0].id,
    )

    result = updater.update_npcs(
        state,
        player_input="I corner the witness until he sells out the watchman.",
        outcome=outcome,
    )

    assert result.touched_npc_ids == (state.npcs[0].id, state.npcs[1].id)
    assert state.npcs[0].role == "Abbey witness turned informant"
    assert state.npcs[0].disposition == "fearful"
    assert state.npcs[0].status == NPCStatus.ACTIVE
    assert state.npcs[1].status == NPCStatus.RETIRED


def test_npc_updater_skips_invalid_targets_and_reactivates_duplicate_creates() -> None:
    state = sample_state()
    state.npcs[0].status = NPCStatus.RETIRED
    updater = _updater(
        """
        {
          "ops": [
            {
              "kind": "create",
              "npc_id": null,
              "name": "Generated NPC One",
              "role": "Returned witness",
              "disposition": "ashamed"
            },
            {
              "kind": "retire",
              "npc_id": "npc_missing",
              "name": "Ghost watcher",
              "role": "Should be ignored",
              "disposition": "irrelevant"
            }
          ]
        }
        """,
    )
    outcome = OracleOutcome(
        kind=OracleKind.YES_NO,
        summary="Yes: the witness is still here if you know where to knock.",
        chaos_factor=state.chaos_factor,
    )

    result = updater.update_npcs(
        state,
        player_input="Is the witness still in the district?",
        outcome=outcome,
    )

    assert len(state.npcs) == 2
    assert result.touched_npc_ids == (state.npcs[0].id,)
    assert state.npcs[0].status == NPCStatus.ACTIVE
    assert state.npcs[0].role == "Returned witness"
    assert state.npcs[0].disposition == "ashamed"


def test_npc_updater_can_create_hidden_npc_without_visible_roster_leak() -> None:
    state = sample_state()
    updater = _updater(
        """
        {
          "ops": [
            {
              "kind": "create",
              "npc_id": null,
              "name": "The Hierophant",
              "role": "Face-thief patriarch",
              "disposition": "patient malice",
              "player_visible": false
            }
          ]
        }
        """,
    )
    outcome = OracleOutcome(
        kind=OracleKind.PLAYER_ACTION,
        summary="Something watches from the ruined chapel tower.",
        chaos_factor=state.chaos_factor,
    )

    result = updater.update_npcs(
        state,
        player_input="I feel watched, but I cannot place by whom.",
        outcome=outcome,
    )

    hidden = next(npc for npc in state.hidden_npcs if npc.name == "The Hierophant")
    assert result.touched_npc_ids == (hidden.id,)
    assert all(npc.name != "The Hierophant" for npc in state.npcs)
    assert hidden.role == "Face-thief patriarch"
    assert hidden.status == NPCStatus.ACTIVE


def test_npc_updater_can_create_visible_descriptor_without_leaking_true_name() -> None:
    state = sample_state()
    state.npcs = []
    updater = _updater(
        """
        {
          "ops": [
            {
              "kind": "create",
              "npc_id": null,
              "name": "The Hierophant",
              "player_label": "The ash-veiled bellringer",
              "player_label_kind": "descriptor",
              "role": "Face-thief patriarch",
              "disposition": "patient malice",
              "player_visible": true
            }
          ]
        }
        """,
    )
    outcome = OracleOutcome(
        kind=OracleKind.PLAYER_ACTION,
        summary="The bellringer leaves another reliquary token on the sill.",
        chaos_factor=state.chaos_factor,
    )

    result = updater.update_npcs(
        state,
        player_input="I follow the ash-veiled bellringer through the cloister fog.",
        outcome=outcome,
    )

    created = next(npc for npc in state.npcs if npc.name == "The Hierophant")
    assert result.touched_npc_ids == (created.id,)
    assert created.display_label() == "The ash-veiled bellringer"
    assert created.player_label_kind == NPCPlayerLabelKind.DESCRIPTOR
    assert created.player_knows_proper_name() is False


def test_npc_updater_can_reseed_legacy_roster() -> None:
    state = sample_state()
    updater = _updater(
        """
        {
          "introduced": [
            {
              "name": "Generated NPC One",
              "role": "Witness finally met in person",
              "disposition": "fearful"
            }
          ],
          "hidden": [
            {
              "name": "The Hierophant",
              "role": "Face-thief patriarch",
              "disposition": "patient malice"
            }
          ]
        }
        """,
    )

    repaired = updater.reseed_legacy_roster(state, use_model=True)

    assert [npc.name for npc in repaired.introduced_npcs] == ["Generated NPC One"]
    assert repaired.introduced_npcs[0].id == state.npcs[0].id
    assert [npc.name for npc in repaired.hidden_npcs] == ["The Hierophant"]
