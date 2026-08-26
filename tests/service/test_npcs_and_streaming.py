from collections.abc import Generator
from pathlib import Path
from threading import Event
from typing import cast

import pytest

from dungeon_master.cancel import CancellationToken, RequestCancelledError
from dungeon_master.memory import MemoryState
from dungeon_master.models import (
    NPC,
    CharacterSheet,
    GameState,
    GameThread,
    Likelihood,
    NPCPlayerLabelKind,
    NPCStatus,
    OracleOutcome,
    PartyMember,
    StageStatus,
    ThreadStatus,
)
from dungeon_master.narrative import CompletionDelta
from dungeon_master.npc_updater import (
    LegacyNPCRosterRepairResult,
)
from dungeon_master.oracle import OracleEngine
from dungeon_master.service import TURN_STREAM_STAGE_ORDER, GameService
from dungeon_master.state_store import StateStore
from dungeon_master.turn_router import (
    PlannedTurnOp,
    PlannedTurnOpKind,
    TurnPlan,
    TurnRoute,
    TurnRouter,
)
from tests.factories import sample_state
from tests.service.cairn_fakes import (
    FakeCairnEngine,
)
from tests.service.planning import scripted_classifier
from tests.test_service import (
    CapturingStreamingNarrative,
    FakeCampaignGenerator,
    FakeCharacterEffectUpdater,
    FakeCharacterGenerator,
    FakeNarrative,
    FakeNpcUpdater,
    FakeThreadUpdater,
    ParallelNpcUpdater,
    ParallelThreadUpdater,
    SlowStreamingNarrative,
)


def test_service_npc_updater_creates_npc_and_persists_memory(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")

    def mutate(state: GameState, outcome: OracleOutcome) -> tuple[str, ...]:
        del outcome
        created = NPC(
            name="Brother Vahagn",
            role="Bell-ringer hiding a blood debt",
            disposition="guarded",
        )
        state.npcs.append(created)
        return (created.id,)

    updater = FakeNpcUpdater(mutate=mutate)
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        npc_updater=updater,
    )

    state = service.submit_player_action("I ask the bell-ringer why he watches me.")
    memory = store.load_memory()

    created = next(npc for npc in state.npcs if npc.name == "Brother Vahagn")
    assert updater.calls == []
    assert updater.post_calls == [
        (
            "I ask the bell-ringer why he watches me.",
            state.oracle_history[-1].summary,
            state.action_log[-1].content,
        ),
    ]
    assert state.oracle_history[-1].referenced_npc_id == created.id
    assert state.oracle_history[-1].referenced_npc_ids == [created.id]
    assert any(card.npc_id == created.id for card in memory.npc_memory)


def test_service_load_state_repairs_legacy_npc_roster_once(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")
    legacy = sample_state()
    legacy.npc_roster_version = 1
    store.save(legacy, create_checkpoint=False)
    existing_id = legacy.npcs[0].id
    repair = LegacyNPCRosterRepairResult(
        introduced_npcs=(
            NPC(
                id=existing_id,
                name="Generated NPC One",
                role="Witness finally met in person",
                disposition="fearful",
            ),
        ),
        hidden_npcs=(
            NPC(
                name="The Hierophant",
                role="Face-thief patriarch",
                disposition="patient malice",
            ),
        ),
    )
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        npc_updater=FakeNpcUpdater(repair=repair),
    )

    state = service.load_state()
    reloaded = store.load()

    assert state.npc_roster_version == 2
    assert [npc.name for npc in state.npcs] == ["Generated NPC One"]
    assert [npc.name for npc in state.hidden_npcs] == ["The Hierophant"]
    assert state.npcs[0].id == existing_id
    assert reloaded.npc_roster_version == 2


def test_service_reveals_hidden_npc_named_in_narration(tmp_path: Path) -> None:
    class RevealingNarrative(FakeNarrative):
        def generate(  # noqa: PLR0913
            self,
            state: GameState,
            outcome: OracleOutcome,
            player_input: str,
            *,
            execution_context: str | None = None,
            memory_context: str | None = None,
            scene_messages: list[dict[str, str]] | None = None,
            cancel_token: CancellationToken | None = None,
        ) -> str:
            del (
                state,
                outcome,
                player_input,
                execution_context,
                memory_context,
                scene_messages,
                cancel_token,
            )
            return "The Hierophant steps from the ash-dark arch and finally speaks."

    store = StateStore(tmp_path / "game_state.json")
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=RevealingNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )
    state = service.load_state()
    state.hidden_npcs.append(
        NPC(
            name="The Hierophant",
            role="Face-thief patriarch",
            disposition="patient malice",
        ),
    )
    state.npcs = []
    store.save(state, create_checkpoint=False)

    updated = service.submit_player_action("I wait in terrified silence.")

    assert [npc.name for npc in updated.npcs] == ["The Hierophant"]
    assert updated.hidden_npcs == []
    assert updated.oracle_history[-1].referenced_npc_id == updated.npcs[0].id
    assert updated.oracle_history[-1].referenced_npc_ids == [updated.npcs[0].id]


def test_service_promotes_visible_descriptor_npc_when_true_name_is_narrated(
    tmp_path: Path,
) -> None:
    class NameGrantingNarrative(FakeNarrative):
        def generate(  # noqa: PLR0913
            self,
            state: GameState,
            outcome: OracleOutcome,
            player_input: str,
            *,
            execution_context: str | None = None,
            memory_context: str | None = None,
            scene_messages: list[dict[str, str]] | None = None,
            cancel_token: CancellationToken | None = None,
        ) -> str:
            del (
                state,
                outcome,
                player_input,
                execution_context,
                memory_context,
                scene_messages,
                cancel_token,
            )
            return "The Hierophant lifts the ash veil and finally offers his true name."

    store = StateStore(tmp_path / "game_state.json")
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=NameGrantingNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )
    state = service.load_state()
    state.npcs = [
        NPC(
            name="The Hierophant",
            role="Face-thief patriarch",
            disposition="patient malice",
            player_label="The ash-veiled bellringer",
            player_label_kind=NPCPlayerLabelKind.DESCRIPTOR,
        ),
    ]
    state.hidden_npcs = []
    store.save(state, create_checkpoint=False)

    updated = service.submit_player_action("I demand the bellringer name himself.")

    assert updated.npcs[0].player_label == "The Hierophant"
    assert updated.npcs[0].player_label_kind == NPCPlayerLabelKind.PROPER_NAME
    assert updated.oracle_history[-1].referenced_npc_ids == [updated.npcs[0].id]


def test_service_syncs_recruited_party_member_when_true_name_is_narrated(
    tmp_path: Path,
) -> None:
    class NameGrantingNarrative(FakeNarrative):
        def generate(  # noqa: PLR0913
            self,
            state: GameState,
            outcome: OracleOutcome,
            player_input: str,
            *,
            execution_context: str | None = None,
            memory_context: str | None = None,
            scene_messages: list[dict[str, str]] | None = None,
            cancel_token: CancellationToken | None = None,
        ) -> str:
            del (
                state,
                outcome,
                player_input,
                execution_context,
                memory_context,
                scene_messages,
                cancel_token,
            )
            return "The shivering youth lowers his hood. His name is Kaelen."

    store = StateStore(tmp_path / "game_state.json")
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=NameGrantingNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )
    state = service.load_state()
    npc = NPC(
        name="Kaelen",
        role="Fugitive guide from Oakhaven",
        disposition="steady after revealing himself",
        player_label="Shivering Youth",
        player_label_kind=NPCPlayerLabelKind.DESCRIPTOR,
    )
    state.npcs = [npc]
    state.party_members.append(
        PartyMember(
            sheet=CharacterSheet(
                name="Shivering Youth",
                archetype="Fugitive guide",
                epithet="grimly cooperative",
            ),
            npc_id=npc.id,
            loyalty="grimly cooperative",
        ),
    )
    store.save(state, create_checkpoint=False)

    updated = service.submit_player_action("I ask the youth for his name.")

    assert updated.npcs[0].player_label == "Kaelen"
    assert updated.npcs[0].player_label_kind == NPCPlayerLabelKind.PROPER_NAME
    assert updated.party_members[0].sheet.name == "Kaelen"
    assert updated.party_members[0].sheet.archetype == "Fugitive guide from Oakhaven"
    assert updated.party_members[0].sheet.epithet == "steady after revealing himself"
    assert updated.party_members[0].loyalty == "steady after revealing himself"


def test_service_syncs_recruited_party_member_after_post_narration_npc_update(
    tmp_path: Path,
) -> None:
    def mutate(state: GameState, outcome: OracleOutcome) -> tuple[str, ...]:
        del outcome
        npc = state.npcs[0]
        npc.name = "Vilerius"
        npc.player_label = "Vilerius"
        npc.player_label_kind = NPCPlayerLabelKind.PROPER_NAME
        npc.role = "Scarred martyr veteran"
        npc.disposition = "loyal after revealing his name"
        return (npc.id,)

    store = StateStore(tmp_path / "game_state.json")
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        npc_updater=FakeNpcUpdater(mutate=mutate),
    )
    state = service.load_state()
    npc = NPC(
        name="Scarred Martyr Veteran",
        role="Scarred zealot",
        disposition="zealous",
        player_label="Imposing warrior",
        player_label_kind=NPCPlayerLabelKind.DESCRIPTOR,
    )
    state.npcs = [npc]
    state.party_members.append(
        PartyMember(
            sheet=CharacterSheet(
                name="Imposing warrior",
                archetype="Scarred zealot",
                epithet="zealous",
            ),
            npc_id=npc.id,
            loyalty="zealous",
        ),
    )
    store.save(state, create_checkpoint=False)

    updated = service.submit_player_action("I ask the warrior his name.")

    assert updated.npcs[0].name == "Vilerius"
    assert updated.npcs[0].player_label_kind == NPCPlayerLabelKind.PROPER_NAME
    assert updated.party_members[0].sheet.name == "Vilerius"
    assert updated.party_members[0].sheet.archetype == "Scarred martyr veteran"
    assert updated.party_members[0].sheet.epithet == "loyal after revealing his name"
    assert updated.party_members[0].loyalty == "loyal after revealing his name"


def test_service_only_persists_visible_npc_ids_on_outcomes(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")

    def mutate(state: GameState, outcome: OracleOutcome) -> tuple[str, ...]:
        del outcome
        hidden = NPC(
            name="The Hierophant",
            role="Face-thief patriarch",
            disposition="patient malice",
            player_label="The ash-veiled bellringer",
            player_label_kind=NPCPlayerLabelKind.DESCRIPTOR,
        )
        state.hidden_npcs.append(hidden)
        return (hidden.id,)

    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        npc_updater=FakeNpcUpdater(mutate=mutate),
    )

    updated = service.submit_player_action("I wait for the watcher to reveal himself.")

    assert [npc.name for npc in updated.hidden_npcs] == ["The Hierophant"]
    assert updated.oracle_history[-1].referenced_npc_id is None
    assert updated.oracle_history[-1].referenced_npc_ids == []


def test_service_update_directives_persists_without_action_log_event(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    state = service.update_directives(
        world_guidance="Keep miracles subtle and costly.",
        play_guidance="The hierophant cannot speak first.",
    )
    reloaded = store.load()

    assert state.directives.world_guidance == "Keep miracles subtle and costly."
    assert reloaded.directives.play_guidance == "The hierophant cannot speak first."
    assert all(event.title != "Campaign directives updated" for event in state.action_log)


def test_streamed_turn_thread_updater_can_resolve_thread(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")

    def mutate(state: GameState, outcome: OracleOutcome) -> tuple[str, ...]:
        del outcome
        state.threads[0].status = ThreadStatus.RESOLVED
        return (state.threads[0].id,)

    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        thread_updater=FakeThreadUpdater(mutate=mutate),
    )

    stream = service.stream_submit_player_action("I burn the old ledger and walk away.")
    for _ in stream:
        pass
    state = store.load()
    memory = store.load_memory()

    assert state.threads[0].status == ThreadStatus.RESOLVED
    assert state.oracle_history[-1].referenced_thread_id == state.threads[0].id
    assert state.oracle_history[-1].referenced_thread_ids == [state.threads[0].id]
    assert all(not loop.text.startswith(state.threads[0].title) for loop in memory.open_loops)
    resolved_card = next(
        card for card in memory.thread_memory if card.thread_id == state.threads[0].id
    )
    assert resolved_card.status == ThreadStatus.RESOLVED


def test_streamed_turn_npc_updater_can_retire_npc(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")

    def mutate(state: GameState, outcome: OracleOutcome) -> tuple[str, ...]:
        del outcome
        state.npcs[0].status = NPCStatus.RETIRED
        state.npcs[0].disposition = "gone to ground"
        return (state.npcs[0].id,)

    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        npc_updater=FakeNpcUpdater(mutate=mutate),
    )

    stream = service.stream_submit_player_action("I pay the witness to disappear before dawn.")
    for _ in stream:
        pass
    state = store.load()
    memory = store.load_memory()

    assert state.npcs[0].status == NPCStatus.RETIRED
    assert state.oracle_history[-1].referenced_npc_id == state.npcs[0].id
    assert state.oracle_history[-1].referenced_npc_ids == [state.npcs[0].id]
    retired_card = next(card for card in memory.npc_memory if card.npc_id == state.npcs[0].id)
    assert retired_card.status == NPCStatus.RETIRED
    assert retired_card.disposition == "gone to ground"


def test_stream_cancel_discards_inflight_turn_state(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=SlowStreamingNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )
    before = service.load_state()
    token = CancellationToken("req_test")

    stream = service.stream_submit_player_action(
        "I wait in silence.",
        cancel_token=token,
    )
    first = next(stream)
    assert first.stage is not None

    thinking_delta = next(delta for delta in stream if delta.thinking)
    assert thinking_delta.thinking == "Working..."

    token.cancel()
    with pytest.raises(RequestCancelledError):
        next(stream)

    after = store.load()
    assert after.updated_at == before.updated_at
    assert after.action_log == before.action_log
    assert after.oracle_history == before.oracle_history
    assert not store.events_path.exists()
    assert not store.turn_checkpoints_dir.exists()


def test_continuity_parallelizes_thread_and_npc_generation_when_scope_is_both(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "game_state.json")
    thread_started = Event()
    npc_started = Event()

    def mutate_thread(state: GameState, outcome: OracleOutcome) -> tuple[str, ...]:
        del outcome
        created = GameThread(
            title="The bellringer marks a debt",
            stakes="If ignored, the abbey's watchers close in.",
        )
        state.threads.append(created)
        return (created.id,)

    def mutate_npc(state: GameState, outcome: OracleOutcome) -> tuple[str, ...]:
        del outcome
        created = NPC(
            name="Brother Sava",
            role="Bellringer",
            disposition="watchful",
        )
        state.npcs.append(created)
        return (created.id,)

    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        thread_updater=ParallelThreadUpdater(
            started=thread_started,
            other_started=npc_started,
            mutate=mutate_thread,
        ),
        npc_updater=ParallelNpcUpdater(
            started=npc_started,
            other_started=thread_started,
            mutate=mutate_npc,
        ),
    )

    state = service.submit_player_action("I ask the bellringer to name his price.")

    assert any(thread.title == "The bellringer marks a debt" for thread in state.threads)
    assert any(npc.name == "Brother Sava" for npc in state.npcs)


def test_streamed_player_action_reuses_memory_sidecar_load_before_narration(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "game_state.json")
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )
    load_calls = 0
    original_load_memory_or_none = store.load_memory_or_none

    def counting_load_memory_or_none() -> MemoryState | None:
        nonlocal load_calls
        load_calls += 1
        return original_load_memory_or_none()

    store.load_memory_or_none = counting_load_memory_or_none  # type: ignore[method-assign]

    stream = service.stream_submit_player_action("I wait in silence.")
    for _ in stream:
        pass

    assert load_calls == 1


# --- StageTiming persistence ----------------------------------------------
#
# These anchor the contract introduced when the pre-narration checklist
# was promoted from a frontend-only ephemeral surface to canonical state.
# Three things matter:
#   1. The narrative GameEvent persists a `stage_timings` snapshot for
#      every stage the tracker observed during the streamed turn.
#   2. Stages skipped by route (e.g. player-action skips planning /
#      mechanics) land as `skipped` rather than `done`, so the UI can
#      render the same channel for the same turn shape across routes.
#   3. The stage timestamps are monotonic in canonical pipeline order:
#      `started_at` of stage N+1 is never earlier than `completed_at`
#      of stage N for stages that actually ran. This guards against a
#      future refactor that accidentally records timestamps off the
#      bootstrap frame instead of the real ACTIVE transition.


def _consume_stream(generator: Generator[CompletionDelta, None, GameState]) -> GameState:
    """Drain a streamed turn and return the final GameState.

    Test helper because the generator protocol returns the final state
    via StopIteration.value, which `for _ in stream` would silently
    discard. Several assertions below want to verify state and timings
    in the same test, so we centralize the pattern here.
    """
    while True:
        try:
            next(generator)
        except StopIteration as stop:
            return cast("GameState", stop.value)


def test_streamed_player_turn_persists_stage_timings(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        turn_router=TurnRouter(classifier=scripted_classifier),
    )

    final = _consume_stream(
        service.stream_submit_player_turn("Is the abbey gate watched? [likely]"),
    )
    narrative_event = final.action_log[-1]
    timings = narrative_event.stage_timings
    by_id = {timing.stage_id: timing for timing in timings}

    # Every canonical stage should appear in order. Natural-language turns
    # now reconcile continuity after narration by default, so the late
    # post-narration stage should complete even when the pre-narration
    # classifier/updater stages were skipped.
    assert [t.stage_id for t in timings] == list(TURN_STREAM_STAGE_ORDER)
    for stage_id in (
        "planning_turn",
        "resolving_mechanics",
        "preparing_narration",
        "streaming_narration",
        "reconciling_continuity",
    ):
        timing = by_id[stage_id]
        assert timing.status == StageStatus.DONE
        assert timing.started_at is not None
        assert timing.completed_at is not None
        assert timing.completed_at >= timing.started_at


def test_streamed_player_turn_applies_narrated_character_effects(tmp_path: Path) -> None:
    def mutate(state: GameState, narrative_text: str) -> tuple[str, ...]:
        assert narrative_text.startswith("STREAMED:")
        state.character.cairn.max_hp -= 1
        state.character.cairn.hp = min(state.character.cairn.hp, state.character.cairn.max_hp)
        state.character.cairn.abilities.append("Telepathy")
        return ("Max HP -1.", "Ability gained: Telepathy.")

    updater = FakeCharacterEffectUpdater(mutate=mutate)
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=CapturingStreamingNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        turn_router=TurnRouter(classifier=scripted_classifier),
        character_effect_updater=updater,
    )

    final = _consume_stream(
        service.stream_submit_player_turn("Is the abbey gate watched? [likely]"),
    )

    assert final.character.cairn.hp == 3
    assert final.character.cairn.max_hp == 3
    assert final.character.cairn.abilities[-1] == "Telepathy"
    assert updater.calls == [
        (
            "Is the abbey gate watched? [likely]",
            final.oracle_history[0].summary,
            "STREAMED: Is the abbey gate watched? [likely]",
        ),
    ]


def test_streamed_player_turn_commits_clarification_without_mechanics(tmp_path: Path) -> None:
    def clarify_classifier(text: str, likelihood: Likelihood | None) -> TurnPlan:
        del likelihood
        return TurnPlan(
            route=TurnRoute.PLAYER_ACTION,
            text=text,
            ops=(
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.CLARIFY,
                    text="Who is retreating: you alone, or you and Kaelen together?",
                ),
            ),
        )

    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        turn_router=TurnRouter(classifier=clarify_classifier),
    )

    final = _consume_stream(service.stream_submit_player_turn("We retreat from the doorway."))
    by_id = {timing.stage_id: timing for timing in final.action_log[-1].stage_timings}

    assert [event.title for event in final.action_log] == [
        "Player action",
        "Clarification needed",
    ]
    assert final.oracle_history == []
    assert by_id["planning_turn"].status == StageStatus.DONE
    assert by_id["resolving_mechanics"].status == StageStatus.SKIPPED
    assert by_id["preparing_narration"].status == StageStatus.PENDING
    assert by_id["streaming_narration"].status == StageStatus.PENDING


def test_streamed_pure_narrate_turn_has_one_continuity_stage(
    tmp_path: Path,
) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        turn_router=TurnRouter(classifier=scripted_classifier),
    )

    final = _consume_stream(
        service.stream_submit_player_turn("I study the icon and pray for intercession."),
    )
    by_id = {timing.stage_id: timing for timing in final.action_log[-1].stage_timings}

    assert "classifying_continuity" not in by_id
    assert "updating_threads" not in by_id
    assert "updating_npcs" not in by_id
    assert by_id["streaming_narration"].status == StageStatus.DONE
    assert by_id["reconciling_continuity"].status == StageStatus.DONE
    assert by_id["reconciling_continuity"].started_at is not None
    assert by_id["reconciling_continuity"].completed_at is not None


def test_streamed_recon_turn_has_one_continuity_stage(
    tmp_path: Path,
) -> None:
    def recon_classifier(text: str, likelihood: Likelihood | None) -> TurnPlan:
        if text == "Are there enemies along the goat-path?":
            return TurnPlan(
                route=TurnRoute.PLAYER_ACTION,
                text=text,
                ops=(
                    PlannedTurnOp(
                        kind=PlannedTurnOpKind.SEARCH_SCENE,
                        text=text,
                    ),
                ),
            )
        return scripted_classifier(text, likelihood)

    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        turn_router=TurnRouter(classifier=recon_classifier),
    )

    final = _consume_stream(
        service.stream_submit_player_turn("Are there enemies along the goat-path?"),
    )
    by_id = {timing.stage_id: timing for timing in final.action_log[-1].stage_timings}

    assert "classifying_continuity" not in by_id
    assert "updating_threads" not in by_id
    assert "updating_npcs" not in by_id
    assert by_id["streaming_narration"].status == StageStatus.DONE
    assert by_id["reconciling_continuity"].status == StageStatus.DONE
    assert by_id["reconciling_continuity"].started_at is not None
    assert by_id["reconciling_continuity"].completed_at is not None


def test_streamed_player_action_marks_skipped_stages(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    final = _consume_stream(
        service.stream_submit_player_action("I wait in silence."),
    )
    timings = final.action_log[-1].stage_timings
    by_id = {timing.stage_id: timing for timing in timings}

    # The action route bypasses planning + mechanics by design; their
    # entries must still appear in the persisted record (so the UI
    # never has to decide whether a stage "would have been there"),
    # but they're flagged skipped and have no timestamps.
    for skipped_id in (
        "planning_turn",
        "resolving_mechanics",
    ):
        assert by_id[skipped_id].status == StageStatus.SKIPPED
        assert by_id[skipped_id].started_at is None
        assert by_id[skipped_id].completed_at is None

    # And the narration + post-narration continuity stages recorded real
    # wall-clock entries.
    for done_id in ("streaming_narration", "reconciling_continuity"):
        assert by_id[done_id].status == StageStatus.DONE
        assert by_id[done_id].started_at is not None
        assert by_id[done_id].completed_at is not None


def test_streamed_regenerate_persists_stage_timings(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        turn_router=TurnRouter(classifier=scripted_classifier),
    )

    initial = _consume_stream(
        service.stream_submit_player_turn("Is the abbey gate watched? [likely]"),
    )
    target_event_id = initial.action_log[-1].id

    repaired = _consume_stream(service.stream_regenerate_response(target_event_id))
    timings = repaired.action_log[-1].stage_timings
    by_id = {timing.stage_id: timing for timing in timings}

    # Regenerate reuses the original outcome, then reconciles the new prose.
    for skipped_id in (
        "planning_turn",
        "resolving_mechanics",
    ):
        assert by_id[skipped_id].status == StageStatus.SKIPPED
    for done_id in ("preparing_narration", "streaming_narration", "reconciling_continuity"):
        timing = by_id[done_id]
        assert timing.status == StageStatus.DONE
        assert timing.started_at is not None
        assert timing.completed_at is not None


def test_stage_timings_round_trip_through_persistence(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    _consume_stream(service.stream_submit_player_action("I wait in silence."))
    # Reload from disk specifically (rather than the in-memory final
    # state) to assert the StageTiming list survives serialization.
    reloaded = store.load()
    timings = reloaded.action_log[-1].stage_timings

    assert len(timings) == len(TURN_STREAM_STAGE_ORDER)
    assert any(t.status == StageStatus.SKIPPED for t in timings)
    assert any(t.status == StageStatus.DONE and t.started_at is not None for t in timings)
