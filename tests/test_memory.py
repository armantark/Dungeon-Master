from dungeon_master.memory import CommittedTurnMemory, MemoryManager
from dungeon_master.models import (
    NPC,
    EventType,
    GameEvent,
    NPCPlayerLabelKind,
    NPCStatus,
    OracleKind,
    OracleOutcome,
    SceneStatus,
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
    state.oracle_history = [*state.oracle_history, outcome]
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


def test_memory_manager_uses_descriptor_labels_for_visible_npcs() -> None:
    state = sample_state()
    state.npcs[0].name = "The Hierophant"
    state.npcs[0].player_label = "The ash-veiled bellringer"
    state.npcs[0].player_label_kind = NPCPlayerLabelKind.DESCRIPTOR
    outcome = OracleOutcome(
        kind=OracleKind.PLAYER_ACTION,
        summary="The ash-veiled bellringer leaves a reliquary token in your path.",
        chaos_factor=state.chaos_factor,
        referenced_npc_id=state.npcs[0].id,
        referenced_npc_ids=[state.npcs[0].id],
    )
    manager = MemoryManager()
    memory = manager.update_from_turn(
        state,
        CommittedTurnMemory(
            player_input="I track the ash-veiled bellringer through the cloister fog.",
            outcome=outcome,
            narrative_text="The bellringer never lets you see more than the ash-white veil.",
        ),
    )

    planner = manager.retrieve_for_planner(state, memory, "I call after the bellringer.")
    npc_context = manager.retrieve_for_npc_updater(
        state,
        memory,
        "I call after the bellringer.",
        outcome,
    )

    assert any("The ash-veiled bellringer (descriptor)" in line for line in planner.relevant_memory)
    assert any("The ash-veiled bellringer (descriptor)" in line for line in npc_context.active_npcs)
    assert all("The Hierophant" not in line for line in planner.relevant_memory)


def test_memory_manager_does_not_surface_hidden_npcs_in_player_facing_contexts() -> None:
    state = sample_state()
    state.hidden_npcs = [
        *state.hidden_npcs,
        NPC(
            name="The Hierophant",
            role="Face-thief patriarch",
            disposition="patient malice",
        ),
    ]
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


def test_memory_manager_keeps_full_current_scene_transcript() -> None:
    state = sample_state()
    manager = MemoryManager()
    first = OracleOutcome(
        kind=OracleKind.PLAYER_ACTION,
        summary="You challenge the bellringer at the threshold.",
        chaos_factor=state.chaos_factor,
        scene_number_snapshot=1,
        scene_label_snapshot=state.current_scene,
        scene_status_snapshot=SceneStatus.EXPECTED,
    )
    second = OracleOutcome(
        kind=OracleKind.YES_NO,
        summary="No: The bellringer will not answer plainly.",
        chaos_factor=state.chaos_factor,
        scene_number_snapshot=1,
        scene_label_snapshot=state.current_scene,
        scene_status_snapshot=SceneStatus.EXPECTED,
    )

    memory = manager.update_from_turn(
        state,
        CommittedTurnMemory(
            player_input="I call to the ash-veiled bellringer.",
            outcome=first,
            narrative_text="He turns only enough for the bell to catch the light.",
        ),
    )
    memory = manager.update_from_turn(
        state,
        CommittedTurnMemory(
            player_input="Why do you hunt me?",
            outcome=second,
            narrative_text="The silence answers before the figure does.",
        ),
        memory=memory,
    )

    planner = manager.retrieve_for_planner(state, memory, "I press him again.")

    assert [message.role for message in planner.scene_messages] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert planner.scene_messages[0].content == "I call to the ash-veiled bellringer."
    assert planner.scene_messages[-1].content == "The silence answers before the figure does."
    assert all("Resolved outcome:" not in message.content for message in planner.scene_messages)


def test_memory_manager_compacts_prior_scenes_into_campaign_chronicle() -> None:
    initial_state = sample_state()
    manager = MemoryManager()
    first = OracleOutcome(
        kind=OracleKind.PLAYER_ACTION,
        summary="You force your way through the broken transept.",
        chaos_factor=initial_state.chaos_factor,
        scene_number_snapshot=1,
        scene_label_snapshot=initial_state.current_scene,
        scene_status_snapshot=SceneStatus.EXPECTED,
    )
    memory = manager.update_from_turn(
        initial_state,
        CommittedTurnMemory(
            player_input="I shoulder through the collapse toward the road.",
            outcome=first,
            narrative_text="Dust and old mortar choke the threshold as you emerge.",
        ),
    )

    next_state = initial_state.model_copy(deep=True)
    next_state.scene_number = 2
    next_state.current_scene = "The ash road below the chapel."
    next_state.scene_status = SceneStatus.EXPECTED
    second = OracleOutcome(
        kind=OracleKind.PLAYER_ACTION,
        summary="Narrative continuation requested without an oracle roll.",
        chaos_factor=next_state.chaos_factor,
        scene_number_snapshot=2,
        scene_label_snapshot=next_state.current_scene,
        scene_status_snapshot=SceneStatus.EXPECTED,
    )
    memory = manager.update_from_turn(
        next_state,
        CommittedTurnMemory(
            player_input="I scan the road for living company.",
            outcome=second,
            narrative_text="The road lies open beneath the ash-heavy sky.",
        ),
        memory=memory,
    )

    narrator = manager.retrieve_for_narrator(
        next_state,
        memory,
        "I scan the road for living company.",
        second,
    )

    assert len(narrator.scene_messages) == 2
    assert narrator.scene_messages[0].content == "I scan the road for living company."
    assert any(line.startswith("Scene 1:") for line in narrator.campaign_chronicle)


def test_narrator_memory_uses_native_scene_transcript_without_duplicate_summaries() -> None:
    state = sample_state()
    manager = MemoryManager()
    first = OracleOutcome(
        kind=OracleKind.PLAYER_ACTION,
        summary="You study the icon for the patriarch's face.",
        chaos_factor=state.chaos_factor,
        scene_number_snapshot=1,
        scene_label_snapshot=state.current_scene,
        scene_status_snapshot=SceneStatus.EXPECTED,
    )
    second = OracleOutcome(
        kind=OracleKind.PLAYER_ACTION,
        summary="The patriarch's icon keeps that face turned toward you.",
        chaos_factor=state.chaos_factor,
        scene_number_snapshot=1,
        scene_label_snapshot=state.current_scene,
        scene_status_snapshot=SceneStatus.EXPECTED,
    )

    memory = manager.update_from_turn(
        state,
        CommittedTurnMemory(
            player_input="I study the icon and the patriarch's face.",
            outcome=first,
            narrative_text="The icon's old patriarch stares down through smoke-black varnish.",
        ),
    )
    memory = manager.update_from_turn(
        state,
        CommittedTurnMemory(
            player_input="Is the patriarch on the icon the same face again?",
            outcome=second,
            narrative_text="The same gaunt face haunts the icon and the chapel wall alike.",
        ),
        memory=memory,
    )

    narrator = manager.retrieve_for_narrator(
        state,
        memory,
        "Do we know his name? Or is it of legend?",
        second,
    )

    assert narrator.recent_turns == []
    assert [message.role for message in narrator.scene_messages] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert narrator.scene_messages[-2].content == (
        "Is the patriarch on the icon the same face again?"
    )
    assert narrator.scene_messages[-1].content == (
        "The same gaunt face haunts the icon and the chapel wall alike."
    )
    assert all("Resolved outcome:" not in message.content for message in narrator.scene_messages)


def test_narrator_memory_uses_query_matching_for_visible_npcs() -> None:
    state = sample_state()
    state.npcs[0].name = "The Hierophant"
    state.npcs[0].player_label = "The ash-veiled bellringer"
    state.npcs[0].player_label_kind = NPCPlayerLabelKind.DESCRIPTOR
    outcome = OracleOutcome(
        kind=OracleKind.PLAYER_ACTION,
        summary="The ash-veiled bellringer waits beneath the icon.",
        chaos_factor=state.chaos_factor,
    )
    manager = MemoryManager()
    memory = manager.update_from_turn(
        state,
        CommittedTurnMemory(
            player_input="I ask whether the ash-veiled bellringer has a name.",
            outcome=outcome,
            narrative_text="The bellringer's veil never parts enough to answer you.",
        ),
    )

    narrator = manager.retrieve_for_narrator(
        state,
        memory,
        "Do we know the ash-veiled bellringer's name?",
        outcome,
    )

    assert any(
        "The ash-veiled bellringer (descriptor)" in line
        for line in narrator.relevant_memory
    )
    assert all("The Hierophant" not in line for line in narrator.relevant_memory)
