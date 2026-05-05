from dungeon_master.memory import CommittedTurnMemory, MemoryManager
from dungeon_master.models import EventType, GameEvent, OracleKind, OracleOutcome
from tests.factories import sample_state


def test_memory_manager_tracks_turn_and_related_entities() -> None:
    state = sample_state()
    outcome = OracleOutcome(
        kind=OracleKind.RANDOM_EVENT,
        summary="Thread pressure: betray bitter old blood",
        chaos_factor=state.chaos_factor,
        referenced_thread_id=state.threads[0].id,
        referenced_npc_id=state.npcs[0].id,
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
    assert memory.recent_turn_summaries[-1].related_thread_ids == [state.threads[0].id]
    assert memory.recent_turn_summaries[-1].related_npc_ids == [state.npcs[0].id]
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
