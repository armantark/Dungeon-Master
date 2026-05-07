from dungeon_master.memory import CommittedTurnMemory, MemoryManager
from dungeon_master.models import (
    NPC,
    EventType,
    GameEvent,
    NPCStatus,
    OracleKind,
    OracleOutcome,
)
from tests.factories import sample_state


def test_memory_manager_tracks_turn_and_related_entities() -> None:
    state = sample_state()
    outcome = OracleOutcome(
        kind=OracleKind.RANDOM_EVENT,
        summary="Thread pressure: betray bitter old blood",
        chaos_factor=state.chaos_factor,
        referenced_thread_id=state.threads[0].id,
        referenced_thread_ids=[state.threads[0].id, state.threads[1].id],
        referenced_npc_id=state.npcs[0].id,
        referenced_npc_ids=[state.npcs[0].id, state.npcs[1].id],
    )
    manager = MemoryManager()

    memory = manager.update_from_turn(
        state,
        CommittedTurnMemory(
            player_input="I press the watchful witness for the truth.",
            outcome=outcome,
            narrative_text="You corner the witness and force the matter into the light.",
            execution_context="Executed backend steps:\n- Oracle resolved: Thread pressure.",
        ),
    )

    assert memory.turn_count == 1
    assert memory.recent_turn_summaries[-1].related_thread_ids == [
        state.threads[0].id,
        state.threads[1].id,
    ]
    assert memory.recent_turn_summaries[-1].related_npc_ids == [
        state.npcs[0].id,
        state.npcs[1].id,
    ]
    assert memory.thread_memory[0].last_touched_turn == 1
    assert any(state.npcs[0].name in line for line in manager.retrieve_for_narrator(
        state,
        memory,
        "I demand answers.",
        outcome,
    ).relevant_memory)


def test_memory_manager_bootstraps_existing_history() -> None:
    state = sample_state()
    outcome = OracleOutcome(
        kind=OracleKind.YES_NO,
        summary="Yes: The abbey gate is watched.",
        chaos_factor=state.chaos_factor,
    )
    state.oracle_history.append(outcome)
    state.action_log = [
        GameEvent(
            event_type=EventType.PLAYER,
            title="Player action",
            content="I watch the gate from the ditch.",
        ),
        GameEvent(
            event_type=EventType.NARRATIVE,
            title="Narrative response",
            content="You sink into the ditch and count the lantern passes.",
            oracle_outcome_id=outcome.id,
        ),
    ]
    manager = MemoryManager()

    memory = manager.bootstrap_from_state(state)

    assert memory.turn_count == 1
    assert memory.recent_turn_summaries[-1].oracle_summary == outcome.summary
    assert memory.current_scene_summary
    assert any(loop.text.startswith("Generated thread one") for loop in memory.open_loops)


def test_planner_memory_uses_query_and_inventory_context() -> None:
    state = sample_state()
    outcome = OracleOutcome(
        kind=OracleKind.RANDOM_EVENT,
        summary="Generated NPC One appears beneath the abbey wall.",
        chaos_factor=state.chaos_factor,
        referenced_npc_id=state.npcs[0].id,
    )
    manager = MemoryManager()
    memory = manager.update_from_turn(
        state,
        CommittedTurnMemory(
            player_input="I question Generated NPC One about the knife.",
            outcome=outcome,
            narrative_text="The watcher stares at your knife before answering.",
        ),
    )

    planner = manager.retrieve_for_planner(
        state,
        memory,
        "I draw the Test knife and question Generated NPC One.",
    )

    assert "Test knife" in planner.inventory_summary
    assert any("Generated NPC One" in line for line in planner.relevant_memory)


def test_thread_updater_memory_context_prefers_direct_and_matching_threads() -> None:
    state = sample_state()
    outcome = OracleOutcome(
        kind=OracleKind.PLAYER_ACTION,
        summary="You swear to settle Generated thread two before dawn.",
        chaos_factor=state.chaos_factor,
        referenced_thread_id=state.threads[0].id,
        referenced_thread_ids=[state.threads[0].id, state.threads[1].id],
    )
    manager = MemoryManager()
    memory = manager.update_from_turn(
        state,
        CommittedTurnMemory(
            player_input="I swear to settle Generated thread two before dawn.",
            outcome=outcome,
            narrative_text="You bind yourself to both debts before the abbey wall.",
        ),
    )

    context = manager.retrieve_for_thread_updater(
        state,
        memory,
        "I pursue Generated thread two.",
        outcome,
    )

    assert any("Generated thread one" in line for line in context.active_threads)
    assert any("Generated thread two" in line for line in context.active_threads)


def test_npc_updater_memory_context_prefers_direct_and_matching_npcs() -> None:
    state = sample_state()
    state.npcs[1].status = NPCStatus.RETIRED
    outcome = OracleOutcome(
        kind=OracleKind.PLAYER_ACTION,
        summary="Generated NPC One drops his false name and the wary watcher leaves the cast.",
        chaos_factor=state.chaos_factor,
        referenced_npc_id=state.npcs[0].id,
        referenced_npc_ids=[state.npcs[0].id, state.npcs[1].id],
    )
    manager = MemoryManager()
    memory = manager.update_from_turn(
        state,
        CommittedTurnMemory(
            player_input=(
                "I press Generated NPC One until he names his patron "
                "and dismiss the wary watcher."
            ),
            outcome=outcome,
            narrative_text="One witness breaks; the other withdraws from the night's business.",
        ),
    )

    context = manager.retrieve_for_npc_updater(
        state,
        memory,
        "I question Generated NPC One again.",
        outcome,
    )

    assert any("Generated NPC One" in line for line in context.active_npcs)
    assert any("Generated NPC Two (retired)" in line for line in context.active_npcs)


def test_memory_manager_does_not_surface_hidden_npcs_in_player_facing_contexts() -> None:
    state = sample_state()
    state.hidden_npcs.append(
        NPC(
            name="The Hierophant",
            role="Face-thief patriarch",
            disposition="patient malice",
        ),
    )
    manager = MemoryManager()
    memory = manager.bootstrap_from_state(state)
    outcome = OracleOutcome(
        kind=OracleKind.PLAYER_ACTION,
        summary="Narrative continuation requested without an oracle roll.",
        chaos_factor=state.chaos_factor,
    )

    planner = manager.retrieve_for_planner(state, memory, "I wait.")
    narrator = manager.retrieve_for_narrator(state, memory, "I wait.", outcome)

    assert all("The Hierophant" not in line for line in planner.relevant_memory)
    assert all("The Hierophant" not in line for line in narrator.relevant_memory)
