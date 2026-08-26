from pathlib import Path
from typing import cast

from dungeon_master.models import (
    NPC,
    CharacterQuizAnswer,
    EventType,
    GameState,
    GameThread,
    InventoryItem,
    Likelihood,
    OracleKind,
    OracleOutcome,
)
from dungeon_master.oracle import OracleEngine
from dungeon_master.service import GameService
from dungeon_master.state_store import StateStore
from dungeon_master.turn_router import (
    PlannedTurnOp,
    PlannedTurnOpKind,
    TurnPlan,
    TurnRoute,
    TurnRouter,
)
from tests.service.cairn_fakes import (
    FakeCairnEngine,
)
from tests.service.planning import scripted_classifier
from tests.test_service import (
    CapturingNarrative,
    CountingNarrative,
    FakeCampaignGenerator,
    FakeCharacterEffectUpdater,
    FakeCharacterGenerator,
    FakeInventoryUpdater,
    FakeNarrative,
    FakeNpcUpdater,
    FakeThreadUpdater,
    SequencedNarrative,
    SetupCharacterGenerator,
)


def test_generate_character_quiz_uses_concept(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=SetupCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    quiz = service.generate_character_quiz("An Armenian Apostolic paladin.")

    assert quiz.concept == "An Armenian Apostolic paladin."
    assert len(quiz.questions) >= 3


def test_generate_quizzed_draft_threads_answers_through(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=SetupCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    quiz = service.generate_character_quiz("A scarred deserter.")
    answers = [
        CharacterQuizAnswer(
            question_id=quiz.questions[0].id,
            prompt=quiz.questions[0].prompt,
            value="Wounded but standing.",
        ),
        CharacterQuizAnswer(
            question_id=quiz.questions[1].id,
            prompt=quiz.questions[1].prompt,
            value="A name I cannot say.",
        ),
        CharacterQuizAnswer(
            question_id=quiz.questions[2].id,
            prompt=quiz.questions[2].prompt,
            value="My old company.",
            is_other=True,
        ),
    ]

    draft = service.generate_quizzed_character_draft(
        concept="A scarred deserter.",
        answers=answers,
        final_note="One scar shaped like a sigil.",
    )

    assert draft.epithet == "A scarred deserter."
    assert "Wounded but standing." in draft.backstory
    assert "A name I cannot say." in draft.backstory
    assert "My old company." in draft.backstory
    assert draft.condition == "One scar shaped like a sigil."


def test_regenerate_response_preserves_oracle_outcome(tmp_path: Path) -> None:
    narrative = CountingNarrative()
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=narrative,
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    first = service.ask_oracle("Is the abbey gate watched?", Likelihood.LIKELY)
    first_event_id = first.action_log[-1].id
    first_outcome = first.oracle_history[-1]

    repaired = service.regenerate_response(first_event_id)
    latest_outcome = repaired.oracle_history[-1]

    assert latest_outcome.id == first_outcome.id
    assert latest_outcome.answer == first_outcome.answer
    assert repaired.action_log[-2].title == "Narrative regenerated"
    assert repaired.action_log[-1].title == "Narrative response"
    assert repaired.action_log[-1].content.startswith("GEN 2:")


def test_regenerate_response_reapplies_all_narration_derived_state(tmp_path: Path) -> None:
    narrative = CountingNarrative()

    def mutate_character(state: GameState, narrative_text: str) -> tuple[str, ...]:
        state.character.cairn.abilities.append(narrative_text)
        return ("Narrated ability applied.",)

    def mutate_inventory(state: GameState, outcome: OracleOutcome) -> tuple[str, ...]:
        del outcome
        state.character.inventory.append(
            InventoryItem(name="Narrated token", details="Derived from the replacement prose."),
        )
        return ("Narrated inventory applied.",)

    character_updater = FakeCharacterEffectUpdater(mutate=mutate_character)
    inventory_updater = FakeInventoryUpdater(mutate=mutate_inventory)
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=narrative,
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        character_effect_updater=character_updater,
        inventory_updater=inventory_updater,
    )

    first = service.ask_oracle("Is the abbey gate watched?", Likelihood.LIKELY)
    repaired = service.regenerate_response(first.action_log[-1].id)

    assert len(character_updater.calls) == 2
    assert len(inventory_updater.calls) == 2
    assert repaired.character.cairn.abilities[-1].startswith("GEN 2:")
    assert [item.name for item in repaired.character.inventory].count("Narrated token") == 1


def test_streamed_regenerate_does_not_duplicate_prior_narrative(tmp_path: Path) -> None:
    narrative = CountingNarrative()
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=narrative,
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        turn_router=TurnRouter(classifier=scripted_classifier),
    )

    stream = service.stream_submit_player_turn("Is the abbey gate watched? [likely]")
    for _ in stream:
        pass
    state = service.load_state()
    first_event_id = state.action_log[-1].id

    repaired = service.regenerate_response(first_event_id)
    narrative_events = [
        event for event in repaired.action_log if event.event_type == EventType.NARRATIVE
    ]

    assert len(narrative_events) == 1
    assert repaired.action_log[-2].title == "Narrative regenerated"
    assert repaired.action_log[-1].title == "Narrative response"


def test_regenerate_response_reapplies_post_narration_npc_disclosure(tmp_path: Path) -> None:
    narrative = SequencedNarrative(
        [
            "A nameless patriarch watches from the icon's cold lead face.",
            "The Hierophant watches from the icon's cold lead face.",
        ],
    )
    store = StateStore(tmp_path / "game_state.json")
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=narrative,
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )
    seeded = service.load_state()
    seeded.hidden_npcs.append(
        NPC(
            name="The Hierophant",
            role="Face-thief patriarch",
            disposition="patient malice",
        ),
    )
    store.save(seeded, create_checkpoint=True)

    first = service.ask_oracle("Is the abbey gate watched?", Likelihood.LIKELY)
    assert all(npc.name != "The Hierophant" for npc in first.npcs)
    first_event_id = first.action_log[-1].id

    repaired = service.regenerate_response(first_event_id)

    revealed = next(npc for npc in repaired.npcs if npc.name == "The Hierophant")
    assert revealed.player_knows_proper_name() is True
    assert repaired.oracle_history[-1].referenced_npc_ids == [revealed.id]
    assert all(npc.name != "The Hierophant" for npc in repaired.hidden_npcs)


def test_regenerate_response_rebuilds_scene_history_from_checkpoint(tmp_path: Path) -> None:
    narrative = CapturingNarrative()
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=narrative,
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    first = service.ask_oracle("Is the abbey gate watched?", Likelihood.LIKELY)
    first_event_id = first.action_log[-1].id

    repaired = service.regenerate_response(first_event_id)
    scene_messages = cast("list[dict[str, str]]", narrative.calls[-1]["scene_messages"])

    assert repaired.action_log[-1].content == (
        "CAPTURED: Oracle question: Is the abbey gate watched?"
    )
    assert scene_messages == []


def test_regenerate_response_preserves_later_directive_edits(tmp_path: Path) -> None:
    narrative = CountingNarrative()
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=narrative,
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    first = service.ask_oracle("Is the abbey gate watched?", Likelihood.LIKELY)
    first_event_id = first.action_log[-1].id
    service.update_directives(
        world_guidance="Keep miracles subtle and costly.",
        play_guidance="The hierophant cannot speak first.",
    )

    repaired = service.regenerate_response(first_event_id)

    assert repaired.directives.world_guidance == "Keep miracles subtle and costly."
    assert repaired.directives.play_guidance == "The hierophant cannot speak first."


def test_memory_sidecar_preserves_explicit_input_and_execution_context(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        turn_router=TurnRouter(classifier=scripted_classifier),
    )

    service.ask_oracle("Is the abbey gate watched?", Likelihood.LIKELY)
    service.submit_player_turn("I draw the test knife.")
    memory = store.load_memory()

    assert (
        memory.recent_turn_summaries[0].player_input
        == "Oracle question: Is the abbey gate watched?"
    )
    assert memory.recent_turn_summaries[-1].execution_context
    assert "Equipment updated" in memory.recent_turn_summaries[-1].execution_context


def test_service_thread_updater_creates_thread_and_persists_memory(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")

    def mutate(state: GameState, outcome: OracleOutcome) -> tuple[str, ...]:
        del outcome
        created = GameThread(
            title="The hierophant's unfinished demand",
            stakes="If ignored, the abbey's claim hardens into open pursuit.",
        )
        state.threads.append(created)
        return (created.id,)

    updater = FakeThreadUpdater(mutate=mutate)
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        thread_updater=updater,
    )

    state = service.submit_player_action("I accept the charge, but not the leash.")
    memory = store.load_memory()

    created = next(
        thread for thread in state.threads if thread.title == "The hierophant's unfinished demand"
    )
    assert updater.calls == []
    assert updater.post_calls == [
        (
            "I accept the charge, but not the leash.",
            state.oracle_history[-1].summary,
            state.action_log[-1].content,
        ),
    ]
    assert state.oracle_history[-1].referenced_thread_id == created.id
    assert state.oracle_history[-1].referenced_thread_ids == [created.id]
    assert any(
        loop.text.startswith("The hierophant's unfinished demand") for loop in memory.open_loops
    )


def test_service_post_narration_reconciliation_runs_for_every_turn(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "game_state.json")
    thread_updater = FakeThreadUpdater()
    npc_updater = FakeNpcUpdater()
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        thread_updater=thread_updater,
        npc_updater=npc_updater,
    )

    updated = service.submit_player_action("I keep moving and say nothing.")

    assert thread_updater.calls == []
    assert npc_updater.calls == []
    assert thread_updater.post_calls == [
        (
            "I keep moving and say nothing.",
            updated.oracle_history[-1].summary,
            updated.action_log[-1].content,
        ),
    ]
    assert npc_updater.post_calls == [
        (
            "I keep moving and say nothing.",
            updated.oracle_history[-1].summary,
            updated.action_log[-1].content,
        ),
    ]
    assert updated.oracle_history[-1].referenced_thread_ids == []
    assert updated.oracle_history[-1].referenced_npc_ids == []


def test_service_reconciles_pure_narrate_turn_after_narration(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "game_state.json")
    thread_updater = FakeThreadUpdater()
    npc_updater = FakeNpcUpdater()
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        thread_updater=thread_updater,
        npc_updater=npc_updater,
        turn_router=TurnRouter(classifier=scripted_classifier),
    )

    updated = service.submit_player_turn("I study the icon and pray for intercession.")

    assert thread_updater.calls == []
    assert npc_updater.calls == []
    assert thread_updater.post_calls == [
        (
            "I study the icon and pray for intercession.",
            updated.oracle_history[-1].summary,
            updated.action_log[-1].content,
        ),
    ]
    assert npc_updater.post_calls == [
        (
            "I study the icon and pray for intercession.",
            updated.oracle_history[-1].summary,
            updated.action_log[-1].content,
        ),
    ]
    assert updated.oracle_history[-1].kind == OracleKind.PLAYER_ACTION
    assert updated.oracle_history[-1].referenced_thread_ids == []
    assert updated.oracle_history[-1].referenced_npc_ids == []


def test_service_save_turn_reconciles_inventory_and_continuity_after_narration(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "game_state.json")
    thread_updater = FakeThreadUpdater()
    npc_updater = FakeNpcUpdater()

    def mutate_inventory(state: GameState, outcome: OracleOutcome) -> tuple[str, ...]:
        del outcome
        state.character.inventory.append(
            InventoryItem(name="Fedora", details="Added from committed narration."),
        )
        return ("Fedora canonized.",)

    inventory_updater = FakeInventoryUpdater(mutate=mutate_inventory)
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        thread_updater=thread_updater,
        npc_updater=npc_updater,
        inventory_updater=inventory_updater,
        turn_router=TurnRouter(classifier=scripted_classifier),
    )

    updated = service.submit_player_turn("I balance across the abbey beam.")

    assert thread_updater.calls == []
    assert npc_updater.calls == []
    assert thread_updater.post_calls == [
        (
            "I balance across the abbey beam.",
            updated.oracle_history[-1].summary,
            updated.action_log[-1].content,
        ),
    ]
    assert npc_updater.post_calls == [
        (
            "I balance across the abbey beam.",
            updated.oracle_history[-1].summary,
            updated.action_log[-1].content,
        ),
    ]
    assert inventory_updater.calls == [
        (
            "I balance across the abbey beam.",
            updated.oracle_history[-1].summary,
            updated.action_log[-1].content,
        ),
    ]
    assert any(item.name == "Fedora" for item in updated.character.inventory)


def test_service_recon_turn_does_not_advance_scene_and_reconciles_after_narration(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "game_state.json")
    thread_updater = FakeThreadUpdater()
    npc_updater = FakeNpcUpdater()

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
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        thread_updater=thread_updater,
        npc_updater=npc_updater,
        turn_router=TurnRouter(classifier=recon_classifier),
    )
    initial = service.load_state()

    updated = service.submit_player_turn("Are there enemies along the goat-path?")

    assert updated.scene_number == initial.scene_number
    assert updated.current_scene == initial.current_scene
    assert [event.title for event in updated.action_log] == [
        "Player action",
        "Narrative response",
    ]
    assert updated.oracle_history[-1].kind == OracleKind.PLAYER_ACTION
    assert "current vantage without advancing" in updated.action_log[-1].content
    assert thread_updater.calls == []
    assert npc_updater.calls == []
    assert thread_updater.post_calls == [
        (
            "Are there enemies along the goat-path?",
            updated.oracle_history[-1].summary,
            updated.action_log[-1].content,
        ),
    ]
    assert npc_updater.post_calls == [
        (
            "Are there enemies along the goat-path?",
            updated.oracle_history[-1].summary,
            updated.action_log[-1].content,
        ),
    ]


def test_service_post_narration_continuity_can_touch_threads_and_npcs(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "game_state.json")

    def mutate_thread(state: GameState, outcome: OracleOutcome) -> tuple[str, ...]:
        del outcome
        created = GameThread(
            title="The patriarch's forgotten name",
            stakes="If pursued, the ruined chapel may reveal who still invokes it.",
        )
        state.threads.append(created)
        return (created.id,)

    def mutate_npc(state: GameState, outcome: OracleOutcome) -> tuple[str, ...]:
        del outcome
        created = NPC(
            name="Saint Vyr",
            role="Patriarch of the ruined chapel",
            disposition="silent in lead",
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
        thread_updater=FakeThreadUpdater(mutate=mutate_thread),
        npc_updater=FakeNpcUpdater(mutate=mutate_npc),
        turn_router=TurnRouter(classifier=scripted_classifier),
    )

    updated = service.submit_player_turn("I study the icon and pray for intercession.")

    assert updated.oracle_history[-1].referenced_thread_ids
    assert updated.oracle_history[-1].referenced_npc_ids


def test_service_post_narration_continuity_runs_noop_updaters_when_narration_adds_no_lore(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "game_state.json")
    thread_updater = FakeThreadUpdater()
    npc_updater = FakeNpcUpdater()
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        thread_updater=thread_updater,
        npc_updater=npc_updater,
        turn_router=TurnRouter(classifier=scripted_classifier),
    )

    updated = service.submit_player_turn("Do we know the patriarch's name?")

    assert thread_updater.post_calls == [
        (
            "Do we know the patriarch's name?",
            updated.oracle_history[-1].summary,
            updated.action_log[-1].content,
        ),
    ]
    assert npc_updater.post_calls == [
        (
            "Do we know the patriarch's name?",
            updated.oracle_history[-1].summary,
            updated.action_log[-1].content,
        ),
    ]
    assert updated.oracle_history[-1].referenced_thread_ids == []
    assert updated.oracle_history[-1].referenced_npc_ids == []


def test_service_post_narration_reconciles_npcs_and_threads(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "game_state.json")

    def mutate(state: GameState, outcome: OracleOutcome) -> tuple[str, ...]:
        del outcome
        created = GameThread(
            title="The ferryman's warning grows teeth",
            stakes="If ignored, the crossing toll becomes a trap.",
        )
        state.threads.append(created)
        return (created.id,)

    thread_updater = FakeThreadUpdater(mutate=mutate)
    npc_updater = FakeNpcUpdater()
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        thread_updater=thread_updater,
        npc_updater=npc_updater,
    )

    updated = service.submit_player_action("I accept the ferryman's warning.")

    created = next(
        thread for thread in updated.threads if thread.title == "The ferryman's warning grows teeth"
    )
    assert thread_updater.calls == []
    assert npc_updater.calls == []
    assert thread_updater.post_calls == [
        (
            "I accept the ferryman's warning.",
            updated.oracle_history[-1].summary,
            updated.action_log[-1].content,
        ),
    ]
    assert npc_updater.post_calls == [
        (
            "I accept the ferryman's warning.",
            updated.oracle_history[-1].summary,
            updated.action_log[-1].content,
        ),
    ]
    assert updated.oracle_history[-1].referenced_thread_ids == [created.id]
    assert updated.oracle_history[-1].referenced_npc_ids == []


def test_service_post_narration_reconciles_threads_and_npcs(
    tmp_path: Path,
) -> None:
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

    thread_updater = FakeThreadUpdater()
    npc_updater = FakeNpcUpdater(mutate=mutate)
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        thread_updater=thread_updater,
        npc_updater=npc_updater,
    )

    updated = service.submit_player_action("I press the bell-ringer for the truth.")

    created = next(npc for npc in updated.npcs if npc.name == "Brother Vahagn")
    assert thread_updater.calls == []
    assert npc_updater.calls == []
    assert thread_updater.post_calls == [
        (
            "I press the bell-ringer for the truth.",
            updated.oracle_history[-1].summary,
            updated.action_log[-1].content,
        ),
    ]
    assert npc_updater.post_calls == [
        (
            "I press the bell-ringer for the truth.",
            updated.oracle_history[-1].summary,
            updated.action_log[-1].content,
        ),
    ]
    assert updated.oracle_history[-1].referenced_thread_ids == []
    assert updated.oracle_history[-1].referenced_npc_ids == [created.id]
