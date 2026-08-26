from pathlib import Path
from typing import cast

from dungeon_master.application.capability_guard import CapabilityOracleGuardResult
from dungeon_master.application.game_service import GameService
from dungeon_master.domain.models import (
    AttackStance,
    CairnAbility,
    CairnCharacterState,
    CairnItemState,
    CairnItemTag,
    CairnMechanicsSource,
    CairnResourceCost,
    CairnResourceDrawPolicy,
    CairnResourceKind,
    CairnResourcePool,
    CairnRestKind,
    CairnSurvivalAction,
    CairnTimeAdvance,
    CharacterSheet,
    EncounterInitiator,
    EncounterState,
    EnemyCombatant,
    EventType,
    GameState,
    InventoryItem,
    Likelihood,
    OracleKind,
    OracleOutcome,
    PartyMember,
    RetreatOutcome,
)
from dungeon_master.llm.narration import NarrativeConfig
from dungeon_master.llm.planning import (
    PlannedTurnOp,
    PlannedTurnOpKind,
    TurnPlan,
    TurnRoute,
    TurnRouter,
)
from dungeon_master.mechanics.engine import CairnEngine
from dungeon_master.mechanics.oracle import OracleEngine
from dungeon_master.memory import LocationMemory
from dungeon_master.persistence.state_store import StateStore
from tests.factories import sample_state
from tests.service.cairn_fakes import (
    FakeCairnEngine,
    ResourceTrackingFakeCairnEngine,
)
from tests.service.planning import scripted_classifier
from tests.test_service import (
    CapturingNarrative,
    CapturingStreamingNarrative,
    FakeCampaignGenerator,
    FakeCapabilityOracleGuard,
    FakeCharacterEffectUpdater,
    FakeCharacterGenerator,
    FakeNarrative,
    SequencedNarrative,
)


def test_service_commits_oracle_turn_with_narration(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    state = service.ask_oracle("Is the abbey gate watched?", Likelihood.LIKELY)

    assert len(state.oracle_history) == 1
    assert len(state.action_log) == 2
    assert state.action_log[-1].content.startswith("FAKE:")


def test_service_persists_memory_sidecar_after_committed_turn(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    service.ask_oracle("Is the abbey gate watched?", Likelihood.LIKELY)
    memory = store.load_memory()

    assert memory.turn_count == 1
    assert memory.recent_turn_summaries[-1].oracle_kind == OracleKind.YES_NO
    assert memory.current_scene_summary


def test_capability_oracle_guard_blocks_unsupported_ability_roll(tmp_path: Path) -> None:
    guard = FakeCapabilityOracleGuard(
        CapabilityOracleGuardResult(
            outcome=OracleOutcome(
                kind=OracleKind.YES_NO,
                summary=(
                    "No: Does Ennius possess resurrection magic? (unsupported by canonical sheet)"
                ),
                question="Does Ennius possess resurrection magic?",
                likelihood=Likelihood.IMPOSSIBLE,
                answer="No",
                probability=1,
                chaos_factor=5,
            ),
            execution_summary=(
                "Capability rejected as unsupported by canonical sheet: "
                "No: Does Ennius possess resurrection magic?"
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
        capability_oracle_guard=guard,
    )

    state = service.ask_oracle("Does Ennius possess resurrection magic?", Likelihood.EVEN)

    outcome = state.oracle_history[0]
    assert guard.calls == [("Does Ennius possess resurrection magic?", Likelihood.EVEN)]
    assert outcome.answer == "No"
    assert outcome.rolls == []
    assert outcome.likelihood == Likelihood.IMPOSSIBLE
    assert "unsupported by canonical sheet" in state.action_log[1].content


def test_capability_oracle_guard_answers_established_ability_without_roll(
    tmp_path: Path,
) -> None:
    guard = FakeCapabilityOracleGuard(
        CapabilityOracleGuardResult(
            outcome=OracleOutcome(
                kind=OracleKind.YES_NO,
                summary="Yes: Does Kalael have Telepathy? (Telepathy is on the sheet)",
                question="Does Kalael have Telepathy?",
                likelihood=Likelihood.NEARLY_CERTAIN,
                answer="Yes",
                probability=99,
                chaos_factor=5,
            ),
            execution_summary="Capability answered from canonical sheet.",
        ),
    )
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        capability_oracle_guard=guard,
    )

    state = service.ask_oracle("Does Kalael have Telepathy?", Likelihood.EVEN)

    outcome = state.oracle_history[0]
    assert outcome.answer == "Yes"
    assert outcome.rolls == []
    assert outcome.likelihood == Likelihood.NEARLY_CERTAIN


def test_capability_oracle_guard_constrains_latent_ability_roll(tmp_path: Path) -> None:
    guard = FakeCapabilityOracleGuard(
        CapabilityOracleGuardResult(
            likelihood=Likelihood.UNLIKELY,
            execution_summary=(
                "Capability question constrained by canonical sheet context "
                "to Unlikely: healing vial supports limited restorative rites."
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
        capability_oracle_guard=guard,
    )

    state = service.ask_oracle("Does Ennius possess healing magic?", Likelihood.EVEN)

    outcome = state.oracle_history[0]
    assert outcome.likelihood == Likelihood.UNLIKELY
    assert outcome.probability == 30
    assert outcome.rolls[0].result == 18
    assert "constrained by canonical sheet context" in state.action_log[1].content


def test_narrator_context_rebuilds_from_checkpoints_not_stale_sidecar(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "game_state.json")
    narrative = CapturingNarrative()
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=narrative,
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    first = service.submit_player_action("I leave the chapel behind.")
    stale = store.load_memory()
    stale.location_memory = [
        LocationMemory(
            location_key=stale.current_scene_key,
            label=first.current_scene,
            summary="Player asked: We need to find a quest in the chapel.",
            last_touched_turn=1,
            recent_developments=["We need to find a quest in the chapel."],
        ),
    ]
    store.save_memory(stale)

    service.submit_player_action("I ask Kaelen whether he can hold the rear wall.")
    latest_call = narrative.calls[-1]
    memory_context = cast("str", latest_call["memory_context"])
    scene_messages = cast("list[dict[str, str]]", latest_call["scene_messages"])

    assert "We need to find a quest" not in memory_context
    assert "I leave the chapel behind." in memory_context
    assert scene_messages == [
        {
            "role": "user",
            "content": "I leave the chapel behind.",
        },
        {
            "role": "assistant",
            "content": "CAPTURED: I leave the chapel behind.",
        },
    ]


def test_streamed_narrator_context_uses_deferred_checkpoint_override(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "game_state.json")
    narrative = CapturingStreamingNarrative()
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=narrative,
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    service.submit_player_action("I leave the chapel behind.")
    stale = store.load_memory()
    stale.location_memory = [
        LocationMemory(
            location_key=stale.current_scene_key,
            label=stale.active_location_key,
            summary="Player asked: We need to find a quest in the chapel.",
            last_touched_turn=1,
            recent_developments=["We need to find a quest in the chapel."],
        ),
    ]
    store.save_memory(stale)

    stream = service.stream_submit_player_action(
        "I ask Kaelen whether he can hold the rear wall.",
    )
    for _ in stream:
        pass
    latest_call = narrative.calls[-1]
    memory_context = cast("str", latest_call["memory_context"])
    scene_messages = cast("list[dict[str, str]]", latest_call["scene_messages"])

    assert "We need to find a quest" not in memory_context
    assert "I ask Kaelen whether he can hold the rear wall." in memory_context
    assert scene_messages == [
        {
            "role": "user",
            "content": "I leave the chapel behind.",
        },
        {
            "role": "assistant",
            "content": "CAPTURED: I leave the chapel behind.",
        },
    ]


def test_service_scene_check_updates_current_scene(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    state = service.check_scene("I arrive before midnight.")

    assert state.scene_number == 2
    assert state.current_scene == "Interrupted before: I arrive before midnight."
    assert len(state.oracle_history) == 1


def test_service_player_action_does_not_require_oracle_roll(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    state = service.submit_player_action("I listen at the abbey door.")

    assert state.oracle_history[0].rolls == []
    assert state.action_log[0].title == "Player action"
    assert state.action_log[1].title == "Narrative response"


def test_service_player_turn_routes_question_through_oracle(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        turn_router=TurnRouter(classifier=scripted_classifier),
    )

    state = service.submit_player_turn("Is the abbey gate watched? [likely]")

    assert state.action_log[0].title == "Player action"
    assert state.action_log[1].title == "Oracle answer"
    assert state.action_log[2].title == "Narrative response"
    assert state.oracle_history[0].kind == "yes_no"
    assert state.oracle_history[0].likelihood == Likelihood.LIKELY


def test_service_player_turn_applies_narrated_character_effects(tmp_path: Path) -> None:
    def mutate(state: GameState, narrative_text: str) -> tuple[str, ...]:
        assert "blood-bond connects you" in narrative_text
        state.character.cairn.max_hp -= 1
        state.character.cairn.hp = min(state.character.cairn.hp, state.character.cairn.max_hp)
        state.character.cairn.abilities.append("Telepathy")
        return ("Max HP -1.", "Ability gained: Telepathy.")

    updater = FakeCharacterEffectUpdater(mutate=mutate)
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=SequencedNarrative(
            [
                ("The ritual takes hold, and the blood-bond connects you mind-to-mind forever."),
            ],
        ),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        turn_router=TurnRouter(classifier=scripted_classifier),
        character_effect_updater=updater,
    )

    state = service.submit_player_turn("Is the abbey gate watched? [likely]")

    assert state.character.cairn.hp == 3
    assert state.character.cairn.max_hp == 3
    assert state.character.cairn.abilities[-1] == "Telepathy"
    assert updater.calls == [
        (
            "Is the abbey gate watched? [likely]",
            state.oracle_history[0].summary,
            "The ritual takes hold, and the blood-bond connects you mind-to-mind forever.",
        ),
    ]


def test_service_player_turn_applies_narrated_party_member_effects(tmp_path: Path) -> None:
    def mutate(state: GameState, narrative_text: str) -> tuple[str, ...]:
        assert "blood-bond connects you" in narrative_text
        companion = state.party_members[0].sheet
        companion.cairn.max_hp -= 1
        companion.cairn.hp = min(companion.cairn.hp, companion.cairn.max_hp)
        companion.cairn.abilities.append("Telepathy")
        return ("Vilerius Max HP -1.", "Vilerius gained ability: Telepathy.")

    updater = FakeCharacterEffectUpdater(mutate=mutate)
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=SequencedNarrative(
            [
                ("The ritual takes hold, and the blood-bond connects you mind-to-mind forever."),
            ],
        ),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        turn_router=TurnRouter(classifier=scripted_classifier),
        character_effect_updater=updater,
    )
    seeded = service.load_state()
    seeded.party_members.append(
        PartyMember(
            sheet=CharacterSheet(
                name="Vilerius",
                archetype="Companion",
                cairn=CairnCharacterState(
                    source=CairnMechanicsSource.EXPLICIT,
                    hp=6,
                    max_hp=6,
                ),
            ),
        ),
    )
    service._save_state_commit(seeded, create_checkpoint=True)  # noqa: SLF001

    state = service.submit_player_turn("Is the abbey gate watched? [likely]")
    companion = state.party_members[0].sheet

    assert companion.cairn.hp == 5
    assert companion.cairn.max_hp == 5
    assert companion.cairn.abilities == ["Telepathy"]
    assert "Telepathy" not in state.character.cairn.abilities


def test_service_player_turn_routes_scene_transition(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        turn_router=TurnRouter(classifier=scripted_classifier),
    )

    state = service.submit_player_turn("I cross the bone bridge before dawn.")

    assert state.action_log[0].title == "Player action"
    assert state.action_log[1].title == "Scene check"
    assert state.scene_number == 2
    assert state.oracle_history[0].kind == "scene_check"


def test_service_player_turn_routes_obvious_save(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        turn_router=TurnRouter(classifier=scripted_classifier),
    )

    state = service.submit_player_turn("I balance across the abbey beam.")

    assert state.action_log[0].title == "Player action"
    assert state.action_log[1].title == "Cairn save"
    assert state.oracle_history[0].kind == "save"
    assert state.oracle_history[0].cairn is not None
    assert state.oracle_history[0].cairn.ability == CairnAbility.DEX


def test_service_player_turn_routes_attack(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        turn_router=TurnRouter(classifier=scripted_classifier),
    )

    state = service.submit_player_turn("I swing my cudgel at the abbey ghoul.")

    assert state.action_log[0].title == "Player action"
    assert state.action_log[1].title == "Attack resolution"
    assert state.oracle_history[0].kind == "attack"
    assert state.oracle_history[0].cairn is not None
    assert state.oracle_history[0].cairn.target_name == "Abbey ghoul"


def test_service_companion_attack_can_publish_resource_delta(tmp_path: Path) -> None:
    def companion_attack_classifier(text: str, likelihood: Likelihood | None) -> TurnPlan:
        del likelihood
        return TurnPlan(
            route=TurnRoute.ATTACK,
            text=text,
            ops=(
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.ATTACK,
                    text=text,
                    target_name="Fleeing zealot",
                    actor_name="Drusus",
                    item_name="Drusus' bow",
                    stance=AttackStance.NORMAL,
                ),
            ),
        )

    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=ResourceTrackingFakeCairnEngine(),
        turn_router=TurnRouter(classifier=companion_attack_classifier),
    )
    state = service.load_state()
    drusus = PartyMember(sheet=CharacterSheet(name="Drusus"))
    bow = InventoryItem(
        name="Drusus' bow",
        details="A weathered hunting bow.",
        cairn=CairnItemState(
            source=CairnMechanicsSource.EXPLICIT,
            tags=[CairnItemTag.WEAPON, CairnItemTag.RANGED],
            weapon_damage_die=6,
            equipped=True,
            attack_costs=[
                CairnResourceCost(
                    label="Arrows",
                    kind=CairnResourceKind.AMMO,
                    draw_policy=CairnResourceDrawPolicy.ACTOR_INVENTORY,
                ),
            ],
        ),
    )
    quiver = InventoryItem(
        name="Drusus' quiver",
        details="Iron-headed arrows.",
        cairn=CairnItemState(
            source=CairnMechanicsSource.EXPLICIT,
            tags=[CairnItemTag.SUPPLIES, CairnItemTag.RANGED],
            resources=[
                CairnResourcePool(
                    label="Arrows",
                    kind=CairnResourceKind.AMMO,
                    current=4,
                    max=12,
                ),
            ],
        ),
    )
    drusus.sheet.inventory = [bow, quiver]
    drusus.sheet.cairn.primary_weapon_item_id = bow.id
    state.party_members.append(drusus)
    service._save_state_commit(state, create_checkpoint=True)  # noqa: SLF001

    updated = service.submit_player_turn("Drusus can use his bow to snipe them.")
    outcome = updated.oracle_history[0]

    assert updated.party_members[0].sheet.inventory[1].cairn.resources[0].current == 3
    assert outcome.cairn is not None
    assert outcome.cairn.actor_name == "Drusus"
    assert outcome.cairn.resource_deltas[0].resource_label == "Arrows"
    assert outcome.cairn.resource_deltas[0].before == 4
    assert outcome.cairn.resource_deltas[0].after == 3
    assert "Arrows 4->3" in updated.action_log[1].content


def test_service_player_turn_can_begin_encounter_without_attack(tmp_path: Path) -> None:
    def begin_encounter_classifier(text: str, likelihood: Likelihood | None) -> TurnPlan:
        del likelihood
        return TurnPlan(
            route=TurnRoute.PLAYER_ACTION,
            text=text,
            ops=(
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.BEGIN_ENCOUNTER,
                    text=text,
                    target_name="Infected horde",
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
        turn_router=TurnRouter(classifier=begin_encounter_classifier),
    )

    state = service.submit_player_turn("Let's start an encounter with the horde.")

    assert state.action_log[1].title == "Encounter started"
    assert state.encounter.active is True
    assert state.encounter.round_number == 1
    assert state.encounter.first_round_dex_gate_pending is True
    assert state.oracle_history[0].kind == "player_action"
    assert state.oracle_history[0].cairn is not None
    assert state.oracle_history[0].cairn.combat_started is True
    assert state.oracle_history[0].cairn.player_acted is False
    assert state.oracle_history[0].cairn.target_name == "Infected horde"


def test_service_player_turn_commits_clarification_without_mechanics(tmp_path: Path) -> None:
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

    state = service.submit_player_turn("We retreat from the doorway.")

    assert [event.title for event in state.action_log] == [
        "Player action",
        "Clarification needed",
    ]
    assert state.action_log[-1].content == (
        "Who is retreating: you alone, or you and Kaelen together?"
    )
    assert state.action_log[-1].event_type == EventType.NARRATIVE
    assert state.oracle_history == []


def test_service_player_turn_routes_enemy_opener_into_tracked_combat(tmp_path: Path) -> None:
    def ambush_classifier(text: str, likelihood: Likelihood | None) -> TurnPlan:
        del likelihood
        return TurnPlan(
            route=TurnRoute.HARM,
            text=text,
            ops=(
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.ENEMY_OPENER,
                    text=text,
                    harm_source="Abbey ghoul",
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
        turn_router=TurnRouter(classifier=ambush_classifier),
    )

    state = service.submit_player_turn(
        "The abbey ghoul drops from the choir loft and claws me before I can raise my cudgel.",
    )

    assert state.action_log[0].title == "Player action"
    assert state.action_log[1].title == "Ambush resolution"
    assert state.oracle_history[0].kind == "harm"
    assert state.oracle_history[0].cairn is not None
    assert state.oracle_history[0].cairn.combat_initiator == EncounterInitiator.ENEMY
    assert state.oracle_history[0].cairn.combat_started is True
    assert state.encounter.active is True
    assert state.encounter.initiator == EncounterInitiator.ENEMY


def test_service_player_turn_routes_recovery(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        turn_router=TurnRouter(classifier=scripted_classifier),
    )

    state = service.submit_player_turn("I catch my breath and drink water.")

    assert state.action_log[0].title == "Player action"
    assert state.action_log[1].title == "Recovery"
    assert state.oracle_history[0].kind == "recovery"
    assert state.oracle_history[0].cairn is not None
    assert state.oracle_history[0].cairn.rest_kind == CairnRestKind.BREATHER


def test_service_player_turn_commits_survival_clock_advance(tmp_path: Path) -> None:
    def waiting_classifier(text: str, _likelihood: Likelihood | None) -> TurnPlan:
        return TurnPlan(
            route=TurnRoute.PLAYER_ACTION,
            text=text,
            time_advance=CairnTimeAdvance.WATCH,
            ops=(PlannedTurnOp(kind=PlannedTurnOpKind.NARRATE, text=text),),
        )

    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=CairnEngine(
            seed=1,
            config=NarrativeConfig(model="", api_key=None, base_url=None),
        ),
        turn_router=TurnRouter(classifier=waiting_classifier),
    )
    seeded = sample_state()
    seeded.character.cairn = CairnCharacterState(
        source=CairnMechanicsSource.EXPLICIT,
        str_score=12,
        dex_score=12,
        wil_score=10,
        max_str_score=12,
        max_dex_score=12,
        max_wil_score=10,
        hp=4,
        max_hp=4,
        primary_weapon_item_id=seeded.character.inventory[0].id,
    )
    seeded.character.inventory[0].cairn = CairnItemState(
        source=CairnMechanicsSource.EXPLICIT,
        tags=[CairnItemTag.WEAPON],
        weapon_damage_die=6,
        equipped=True,
    )
    service._store.save(seeded, create_checkpoint=False)  # noqa: SLF001

    state = service.submit_player_turn("I keep watch by the thorn hedge until dusk.")

    assert state.character.cairn.survival.watch_index == 1
    assert state.oracle_history[-1].cairn is not None
    assert state.oracle_history[-1].cairn.time_advance == CairnTimeAdvance.WATCH


def test_service_full_rest_eats_and_sleeps_before_recovery(tmp_path: Path) -> None:
    def full_rest_classifier(text: str, _likelihood: Likelihood | None) -> TurnPlan:
        return TurnPlan(
            route=TurnRoute.RECOVERY,
            text=text,
            time_advance=CairnTimeAdvance.OVERNIGHT,
            survival_actions=(CairnSurvivalAction.EAT, CairnSurvivalAction.SLEEP),
            ops=(
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.RECOVERY,
                    text=text,
                    rest_kind=CairnRestKind.FULL_REST,
                ),
            ),
        )

    store = StateStore(tmp_path / "game_state.json")
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=CairnEngine(
            seed=1,
            config=NarrativeConfig(model="", api_key=None, base_url=None),
        ),
        turn_router=TurnRouter(classifier=full_rest_classifier),
    )
    state = sample_state()
    state.character.cairn = CairnCharacterState(
        source=CairnMechanicsSource.EXPLICIT,
        str_score=12,
        dex_score=12,
        wil_score=10,
        max_str_score=12,
        max_dex_score=12,
        max_wil_score=10,
        hp=4,
        max_hp=4,
        primary_weapon_item_id=state.character.inventory[0].id,
    )
    state.character.inventory[0].cairn = CairnItemState(
        source=CairnMechanicsSource.EXPLICIT,
        tags=[CairnItemTag.WEAPON],
        weapon_damage_die=6,
        equipped=True,
    )
    state.character.cairn.hp = 1
    state.character.cairn.survival.watches_since_meal = 3
    state.character.cairn.survival.food_deprived = True
    state.character.cairn.deprived = True
    state.character.inventory.append(
        InventoryItem(
            name="Trail rations",
            details="Hard bread and salt fish.",
            cairn=CairnItemState(
                source=CairnMechanicsSource.EXPLICIT,
                tags=[CairnItemTag.SUPPLIES],
                slots=1,
                uses=None,
            ),
        ),
    )
    store.save(state, create_checkpoint=False)

    rested = service.submit_player_turn("I eat my trail rations and sleep by the fire.")

    assert rested.character.cairn.hp == rested.character.cairn.max_hp
    assert rested.character.cairn.deprived is False
    assert rested.character.cairn.survival.watches_since_meal == 0
    assert rested.character.cairn.survival.watches_since_sleep == 0
    assert rested.oracle_history[-1].cairn is not None
    assert rested.oracle_history[-1].cairn.ration_uses_before == 3
    assert rested.oracle_history[-1].cairn.ration_uses_after == 2


def test_service_player_turn_routes_retreat(tmp_path: Path) -> None:
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
    state = service.load_state()
    state.encounter = EncounterState(
        active=True,
        round_number=2,
        combatants=[EnemyCombatant(name="Abbey ghoul", hp=4, max_hp=4)],
    )
    store.save(state, create_checkpoint=False)

    retreated = service.submit_player_turn("I fall back through the chapel arch.")

    assert retreated.action_log[0].title == "Player action"
    assert retreated.action_log[1].title == "Retreat resolution"
    assert retreated.oracle_history[0].kind == "retreat"
    assert retreated.oracle_history[0].cairn is not None
    assert retreated.oracle_history[0].cairn.retreat_outcome == RetreatOutcome.ESCAPED


def test_service_player_turn_routes_equip(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        turn_router=TurnRouter(classifier=scripted_classifier),
    )

    state = service.submit_player_turn("I draw the test knife.")

    assert state.action_log[0].title == "Player action"
    assert state.action_log[1].title == "Narrative response"
    assert state.oracle_history[0].summary == "Equipment updated: Test knife equipped."


def test_service_player_turn_executes_compound_inventory_plan(tmp_path: Path) -> None:
    def compound_classifier(text: str, likelihood: Likelihood | None) -> TurnPlan:
        del likelihood
        return TurnPlan(
            route=TurnRoute.PLAYER_ACTION,
            text=text,
            ops=(
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.INSPECT_INVENTORY,
                    text="I check my supplies.",
                ),
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.DROP_ITEM,
                    text="I drop the test map.",
                    item_name="Test map",
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
        turn_router=TurnRouter(classifier=compound_classifier),
    )

    state = service.submit_player_turn("I check my supplies and drop the map.")

    assert state.action_log[0].title == "Player action"
    assert state.action_log[1].title == "Narrative response"
    assert state.oracle_history[0].kind == OracleKind.PLAYER_ACTION
    assert [item.name for item in state.character.inventory] == ["Test knife"]
    assert "Dropped Test map." in state.action_log[1].content
