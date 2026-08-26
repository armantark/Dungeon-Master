from pathlib import Path

import pytest

from dungeon_master.application.game_service import GameService
from dungeon_master.domain.models import (
    NPC,
    AttackStance,
    CairnAbility,
    CairnCharacterState,
    CairnItemEffectKind,
    CairnItemPower,
    CairnItemPowerKind,
    CairnItemState,
    CairnItemTag,
    CairnMechanicsSource,
    CairnRestKind,
    CampaignDangerProfile,
    CampaignEndReason,
    CampaignSeed,
    CampaignStatus,
    CampaignTimePeriod,
    CharacterSheet,
    EncounterAdvantagePayoff,
    EncounterState,
    EnemyCombatant,
    EventType,
    GameEvent,
    GameState,
    InventoryItem,
    Likelihood,
    NPCPlayerLabelKind,
    NPCStatus,
    OracleKind,
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
from dungeon_master.persistence.state_store import StateStore
from tests.factories import sample_state
from tests.service.cairn_fakes import (
    FakeCairnEngine,
    FatalFakeCairnEngine,
)
from tests.service.planning import scripted_classifier
from tests.test_service import (
    FakeCampaignGenerator,
    FakeCharacterGenerator,
    FakeNarrative,
    SetupCharacterGenerator,
    single_test_runtime,
)


def test_service_player_turn_executes_inventory_acquisition_plan(tmp_path: Path) -> None:
    def acquire_classifier(text: str, likelihood: Likelihood | None) -> TurnPlan:
        del likelihood
        return TurnPlan(
            route=TurnRoute.PLAYER_ACTION,
            text=text,
            ops=(
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.ACQUIRE_ITEM,
                    text="I loot the abbey ghoul for a lantern and a purse of coins.",
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
        turn_router=TurnRouter(classifier=acquire_classifier),
    )

    state = service.submit_player_turn("I loot the abbey ghoul for a lantern and a purse of coins.")

    assert state.oracle_history[0].kind == OracleKind.PLAYER_ACTION
    assert [item.name for item in state.character.inventory] == [
        "Test knife",
        "Test map",
        "Pilgrim lantern",
        "Purse of old silver",
    ]
    assert "Acquired Pilgrim lantern, Purse of old silver." in state.action_log[1].content


def test_service_player_turn_transfers_inventory_to_companion(tmp_path: Path) -> None:
    def transfer_classifier(text: str, likelihood: Likelihood | None) -> TurnPlan:
        del likelihood
        return TurnPlan(
            route=TurnRoute.PLAYER_ACTION,
            text=text,
            ops=(
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.TRANSFER_ITEM,
                    text=text,
                    item_name="Test map",
                    source_actor_name="player",
                    target_actor_name="Brother Sava",
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
        turn_router=TurnRouter(classifier=transfer_classifier),
    )
    state = service.load_state()
    state.character.cairn.source = CairnMechanicsSource.EXPLICIT
    state.character.inventory[1].cairn = CairnItemState(
        source=CairnMechanicsSource.EXPLICIT,
        slots=1,
    )
    state.character.cairn.slots_used = 2
    state.party_members.append(
        PartyMember(
            sheet=CharacterSheet(
                name="Brother Sava",
                cairn=CairnCharacterState(
                    source=CairnMechanicsSource.EXPLICIT,
                    hp=3,
                    max_hp=3,
                ),
            ),
        ),
    )
    service._save_state_commit(state, create_checkpoint=True)  # noqa: SLF001

    next_state = service.submit_player_turn("I hand the test map to Brother Sava.")

    assert [item.name for item in next_state.character.inventory] == ["Test knife"]
    assert [item.name for item in next_state.party_members[0].sheet.inventory] == ["Test map"]
    assert next_state.character.cairn.slots_used == 1
    assert next_state.party_members[0].sheet.cairn.slots_used == 1
    assert (
        "Transferred Test map from Test Wanderer to Brother Sava."
        in next_state.action_log[1].content
    )


def test_service_player_turn_recruits_visible_npc_to_party(tmp_path: Path) -> None:
    def recruit_classifier(text: str, likelihood: Likelihood | None) -> TurnPlan:
        del likelihood
        return TurnPlan(
            route=TurnRoute.PLAYER_ACTION,
            text=text,
            ops=(
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.RECRUIT_NPC,
                    text=text,
                    npc_name="Brother Sava",
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
        turn_router=TurnRouter(classifier=recruit_classifier),
    )
    state = service.load_state()
    recruitable = NPC(
        name="Brother Sava",
        role="Lantern bearer",
        disposition="wary but willing",
    )
    state.npcs.append(recruitable)
    service._save_state_commit(state, create_checkpoint=True)  # noqa: SLF001

    next_state = service.submit_player_turn("I ask Brother Sava to join us.")

    assert len(next_state.party_members) == 1
    member = next_state.party_members[0]
    assert member.npc_id == recruitable.id
    assert member.display_label() == "Brother Sava"
    assert member.sheet.cairn.source == CairnMechanicsSource.EXPLICIT
    assert member.sheet.inventory[0].name == "Brother Sava's walking stick"
    assert next_state.npcs[-1].status == NPCStatus.RETIRED
    assert "Recruited Brother Sava into the party." in next_state.action_log[1].content


def test_recruitment_resolves_misnamed_visible_descriptor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def recruit_classifier(text: str, likelihood: Likelihood | None) -> TurnPlan:
        del likelihood
        return TurnPlan(
            route=TurnRoute.PLAYER_ACTION,
            text=text,
            ops=(
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.RECRUIT_NPC,
                    text=text,
                    npc_name="Covenant Initiate",
                ),
            ),
        )

    captured_prompt: str | None = None

    def fake_complete_text(request: object, completion: object) -> object:
        del completion
        nonlocal captured_prompt
        captured_prompt = request.messages[1]["content"]  # type: ignore[attr-defined]
        return type("Completion", (), {"content": '{"npc_id":"npc_hierarch"}'})()

    monkeypatch.setattr(
        "dungeon_master.application.turn_plan_execution.complete_text",
        fake_complete_text,
    )
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        turn_router=TurnRouter(classifier=recruit_classifier),
        llm_runtime=single_test_runtime(),
    )
    state = service.load_state()
    state.current_scene = "The blood-hierarch waits beside his militant flock."
    recruitable = NPC(
        id="npc_hierarch",
        name="Covenant Blood-hierarch",
        role="High-ranking priest coordinating the hunt",
        disposition="fanatical awe",
        player_label="Blood-hierarch",
        player_label_kind=NPCPlayerLabelKind.DESCRIPTOR,
    )
    state.npcs.append(recruitable)
    state.action_log.append(
        GameEvent(
            event_type=EventType.NARRATIVE,
            title="Narrative response",
            content=("The blood-hierarch offers a militant flock and waits for your command."),
        ),
    )
    service._save_state_commit(state, create_checkpoint=True)  # noqa: SLF001

    next_state = service.submit_player_turn("I ask the Hierarch if he will lend his abilities.")

    assert len(next_state.party_members) == 1
    member = next_state.party_members[0]
    assert member.npc_id == "npc_hierarch"
    assert member.display_label() == "Blood-hierarch"
    assert next_state.npcs[-1].status == NPCStatus.RETIRED
    assert captured_prompt is not None
    assert "Covenant Initiate" in captured_prompt
    assert "Blood-hierarch" in captured_prompt


def test_recruitment_backfill_receives_recent_visible_gear_context(tmp_path: Path) -> None:
    captured_backstory: str | None = None

    def recruit_classifier(text: str, likelihood: Likelihood | None) -> TurnPlan:
        del likelihood
        return TurnPlan(
            route=TurnRoute.PLAYER_ACTION,
            text=text,
            ops=(
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.RECRUIT_NPC,
                    text=text,
                    npc_name="Brother Sava",
                ),
            ),
        )

    def companion_backfill(state: GameState) -> CharacterSheet:
        nonlocal captured_backstory
        captured_backstory = state.character.backstory
        sheet = state.character.model_copy(deep=True)
        sheet.cairn = CairnCharacterState(
            source=CairnMechanicsSource.EXPLICIT,
            hp=3,
            max_hp=3,
        )
        sheet.inventory = [
            InventoryItem(
                name="Rusted wood-axe",
                details="The weapon already surfaced in play.",
                cairn=CairnItemState(
                    source=CairnMechanicsSource.EXPLICIT,
                    tags=[CairnItemTag.WEAPON],
                    weapon_damage_die=6,
                    equipped=True,
                ),
            ),
        ]
        return sheet

    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=CairnEngine(
            config=NarrativeConfig(model="", api_key=None, base_url=None),
            backfill_function=companion_backfill,
        ),
        turn_router=TurnRouter(classifier=recruit_classifier),
    )
    state = service.load_state()
    state.action_log.append(
        GameEvent(
            event_type=EventType.NARRATIVE,
            title="Narrative response",
            content="Brother Sava waits by the fire, keeping a rusted wood-axe ready.",
        ),
    )
    recruitable = NPC(
        name="Brother Sava",
        role="Lantern bearer",
        disposition="wary but willing",
    )
    state.npcs.append(recruitable)
    service._save_state_commit(state, create_checkpoint=True)  # noqa: SLF001

    next_state = service.submit_player_turn("I ask Brother Sava to join us.")

    assert captured_backstory is not None
    backstory = captured_backstory
    assert "Recent player-visible context for this recruit" in backstory
    assert "rusted wood-axe ready" in backstory
    assert next_state.party_members[0].sheet.inventory[0].name == "Rusted wood-axe"


def test_recruitment_backfill_receives_recent_scene_context_without_label(
    tmp_path: Path,
) -> None:
    captured_backstory: str | None = None

    def recruit_classifier(text: str, likelihood: Likelihood | None) -> TurnPlan:
        del likelihood
        return TurnPlan(
            route=TurnRoute.PLAYER_ACTION,
            text=text,
            ops=(
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.RECRUIT_NPC,
                    text=text,
                    npc_name="the scarred deserter",
                ),
            ),
        )

    def companion_backfill(state: GameState) -> CharacterSheet:
        nonlocal captured_backstory
        captured_backstory = state.character.backstory
        sheet = state.character.model_copy(deep=True)
        sheet.cairn = CairnCharacterState(
            source=CairnMechanicsSource.EXPLICIT,
            hp=3,
            max_hp=3,
        )
        sheet.inventory = [
            InventoryItem(
                name="Notched falchion",
                details="The weapon was established by the recruitment scene.",
                cairn=CairnItemState(
                    source=CairnMechanicsSource.EXPLICIT,
                    tags=[CairnItemTag.WEAPON],
                    weapon_damage_die=6,
                    equipped=True,
                ),
            ),
        ]
        return sheet

    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=CairnEngine(
            config=NarrativeConfig(model="", api_key=None, base_url=None),
            backfill_function=companion_backfill,
        ),
        turn_router=TurnRouter(classifier=recruit_classifier),
    )
    state = service.load_state()
    state.action_log.append(
        GameEvent(
            event_type=EventType.NARRATIVE,
            title="Narrative response",
            content=(
                "The old soldier lowers his notched falchion and offers to guard your retreat."
            ),
        ),
    )
    recruitable = NPC(
        name="Scarred deserter",
        role="Scarred deserter",
        disposition="grimly loyal",
        player_label="the scarred deserter",
        player_label_kind=NPCPlayerLabelKind.DESCRIPTOR,
    )
    state.npcs.append(recruitable)
    service._save_state_commit(state, create_checkpoint=True)  # noqa: SLF001

    next_state = service.submit_player_turn("I ask the scarred deserter to join us.")

    assert captured_backstory is not None
    backstory = captured_backstory
    assert "Recent visible transcript window" in backstory
    assert "notched falchion" in backstory
    assert next_state.party_members[0].sheet.inventory[0].name == "Notched falchion"


def test_service_player_turn_uses_holy_relic_as_structured_outcome(tmp_path: Path) -> None:
    def relic_classifier(text: str, likelihood: Likelihood | None) -> TurnPlan:
        del likelihood
        return TurnPlan(
            route=TurnRoute.PLAYER_ACTION,
            text=text,
            ops=(
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.USE_ITEM,
                    text=text,
                    item_name="leaden icon",
                ),
            ),
        )

    store = StateStore(tmp_path / "game_state.json")
    seeded = sample_state()
    seeded.character.cairn = CairnCharacterState(
        source=CairnMechanicsSource.EXPLICIT,
        wil_score=7,
        max_wil_score=10,
        hp=4,
        max_hp=4,
    )
    seeded.character.inventory.append(
        InventoryItem(
            name="Leaden icon",
            details="A cold icon of a nameless patriarch.",
            cairn=CairnItemState(
                source=CairnMechanicsSource.EXPLICIT,
                tags=[CairnItemTag.HOLY, CairnItemTag.RELIC, CairnItemTag.PETTY],
                slots=0,
                uses=1,
                power=CairnItemPower(
                    kind=CairnItemPowerKind.HOLY_RELIC,
                    name="Intercession of the Nameless Patriarch",
                    effect=CairnItemEffectKind.RESTORE_ATTRIBUTE,
                    effect_amount=1,
                    recharge_condition="Confess a true failing at a consecrated threshold.",
                ),
            ),
        ),
    )
    store.save(seeded, create_checkpoint=False)
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
        turn_router=TurnRouter(classifier=relic_classifier),
    )

    state = service.submit_player_turn("I kiss the leaden icon and ask for intercession.")

    outcome = state.oracle_history[-1]
    assert outcome.kind == OracleKind.PLAYER_ACTION
    assert outcome.cairn is not None
    assert outcome.cairn.item_name == "Leaden icon"
    assert outcome.cairn.item_power_kind == CairnItemPowerKind.HOLY_RELIC
    assert outcome.cairn.wil_before == 7
    assert outcome.cairn.wil_after == 8
    assert state.character.cairn.wil_score == 8
    assert state.action_log[1].title == "Item use"
    assert "WIL restored 7->8" in state.action_log[-1].content


def test_service_explicit_inventory_acquire_records_system_and_narrative(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        turn_router=TurnRouter(classifier=scripted_classifier),
    )

    state = service.acquire_inventory("I buy a lantern and a purse of old silver.")

    assert state.action_log[0].title == "Inventory acquired"
    assert state.action_log[1].title == "Narrative response"
    assert state.oracle_history[0].summary == "Acquired Pilgrim lantern, Purse of old silver."
    assert [item.name for item in state.character.inventory][-2:] == [
        "Pilgrim lantern",
        "Purse of old silver",
    ]


def test_finalize_character_sets_ready_to_start(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=SetupCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    character = sample_state().character
    state = service.finalize_character(character)

    assert state.campaign_status == CampaignStatus.READY_TO_START
    assert state.character.name == character.name


def test_update_campaign_seed_before_campaign_start(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=SetupCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )
    seed = CampaignSeed(
        preset="Ashen Bronze",
        time_period=CampaignTimePeriod.BRONZE_AGE,
        danger_profile=CampaignDangerProfile.HARSH,
    )

    state = service.update_campaign_seed(seed)

    assert state.campaign_seed.preset == "Ashen Bronze"
    assert state.campaign_seed.time_period == CampaignTimePeriod.BRONZE_AGE
    assert state.campaign_seed.danger_profile == CampaignDangerProfile.HARSH


def test_character_quiz_uses_active_campaign_seed(tmp_path: Path) -> None:
    character_generator = SetupCharacterGenerator()
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=character_generator,
        cairn_engine=FakeCairnEngine(),
    )
    seed = CampaignSeed(
        preset="Modern romance",
        time_period=CampaignTimePeriod.MODERN,
    )
    service.update_campaign_seed(seed)

    service.generate_character_quiz_result("lonely software engineer")

    assert character_generator.quiz_seeds
    assert character_generator.quiz_seeds[-1] is not None
    assert character_generator.quiz_seeds[-1].preset == "Modern romance"
    assert character_generator.quiz_seeds[-1].time_period == CampaignTimePeriod.MODERN


def test_start_campaign_uses_finalized_character(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=SetupCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    character = sample_state().character.model_copy(deep=True)
    character.name = "Sable"
    service.finalize_character(character)
    state = service.start_campaign()

    assert state.campaign_status == CampaignStatus.ACTIVE
    assert state.character.name == "Sable"
    assert state.character.cairn.source == CairnMechanicsSource.NARRATIVE_BACKFILL
    assert state.character.cairn.slots_used >= 1
    assert state.character.cairn.primary_weapon_item_id is not None


def test_start_campaign_preserves_campaign_seed(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=SetupCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )
    seed = CampaignSeed(
        preset="Lethal pilgrimage",
        danger_profile=CampaignDangerProfile.LETHAL,
    )

    service.update_campaign_seed(seed)
    service.finalize_character(sample_state().character)
    state = service.start_campaign()

    assert state.campaign_seed.preset == "Lethal pilgrimage"
    assert state.campaign_seed.danger_profile == CampaignDangerProfile.LETHAL


def test_setup_advantage_turn_records_cairn_payoff(tmp_path: Path) -> None:
    def advantage_classifier(text: str, likelihood: Likelihood | None) -> TurnPlan:
        del likelihood
        return TurnPlan(
            route=TurnRoute.PLAYER_ACTION,
            text=text,
            ops=(
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.SETUP_ADVANTAGE,
                    text=text,
                    target_name="abbey ghoul",
                    advantage_payoff=EncounterAdvantagePayoff.ENHANCED_ATTACK,
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
        turn_router=TurnRouter(classifier=advantage_classifier),
    )

    state = service.submit_player_turn("I blind the abbey ghoul with ash.")

    assert state.oracle_history[0].kind == OracleKind.PLAYER_ACTION
    assert state.oracle_history[0].cairn is not None
    assert (
        state.oracle_history[0].cairn.advantage_payoff == EncounterAdvantagePayoff.ENHANCED_ATTACK
    )


def test_load_state_backfills_active_character_once(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    state = service.load_state()

    assert state.character.cairn.source == CairnMechanicsSource.NARRATIVE_BACKFILL
    assert state.character.cairn.max_hp >= 1
    assert any(
        item.cairn.source == CairnMechanicsSource.NARRATIVE_BACKFILL
        for item in state.character.inventory
    )


def test_load_state_syncs_dead_active_campaign_into_terminal_death_state(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")
    seeded = sample_state()
    seeded.character.cairn = CairnCharacterState(
        source=CairnMechanicsSource.EXPLICIT,
        str_score=0,
        dex_score=10,
        wil_score=10,
        max_str_score=10,
        max_dex_score=10,
        max_wil_score=10,
        hp=0,
        max_hp=4,
        dead=True,
    )
    store.save(seeded, create_checkpoint=False)

    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    loaded = service.load_state()
    persisted = store.load()

    assert loaded.campaign_status == CampaignStatus.ENDED
    assert loaded.campaign_end_reason == CampaignEndReason.DEATH
    assert loaded.campaign_end_summary == "Test Wanderer's campaign ended in death."
    assert persisted.campaign_status == CampaignStatus.ENDED
    assert persisted.campaign_end_reason == CampaignEndReason.DEATH


def test_end_campaign_marks_retirement_and_blocks_further_play(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    ended = service.end_campaign(
        reason=CampaignEndReason.RETIREMENT,
        summary="Vrtanes lays down the cudgel and leaves the chapel road behind.",
    )

    assert ended.campaign_status == CampaignStatus.ENDED
    assert ended.campaign_end_reason == CampaignEndReason.RETIREMENT
    assert (
        ended.campaign_end_summary
        == "Vrtanes lays down the cudgel and leaves the chapel road behind."
    )
    assert ended.action_log[-1].title == "Campaign ended"

    with pytest.raises(ValueError, match="retirement"):
        service.submit_player_turn("I keep walking down the ash-dark road.")


def test_end_campaign_marks_victory_with_default_summary(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    ended = service.end_campaign(reason=CampaignEndReason.VICTORY)

    assert ended.campaign_status == CampaignStatus.ENDED
    assert ended.campaign_end_reason == CampaignEndReason.VICTORY
    assert ended.campaign_end_summary == "Test Wanderer achieved a final victory."


def test_service_resolve_save_records_deterministic_outcome(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    state = service.resolve_cairn_save(CairnAbility.WIL, "Resist the bell's whisper.")

    assert state.oracle_history[-1].kind == "save"
    assert state.oracle_history[-1].cairn is not None
    assert state.oracle_history[-1].cairn.ability == CairnAbility.WIL


def test_service_attack_uses_primary_weapon(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    state = service.load_state()
    primary_weapon_id = state.character.cairn.primary_weapon_item_id
    assert primary_weapon_id is not None

    attacked = service.attack_target(
        target_name="Abbey ghoul",
        target_armor=1,
        weapon_item_id=primary_weapon_id,
        stance=AttackStance.NORMAL,
    )

    assert attacked.oracle_history[-1].kind == "attack"
    assert attacked.oracle_history[-1].cairn is not None
    assert attacked.oracle_history[-1].cairn.weapon_item_id == primary_weapon_id


def test_service_harm_can_trigger_str_loss(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    state = service.load_state()
    state.character.cairn.hp = 1
    store.save(state, create_checkpoint=False)

    harmed = service.suffer_harm(
        amount=5,
        source="Falling masonry",
        in_combat=True,
        armor_applies=False,
    )

    assert harmed.oracle_history[-1].kind == "harm"
    assert harmed.character.cairn.hp == 0
    assert harmed.character.cairn.str_score <= harmed.character.cairn.max_str_score


def test_service_fatal_harm_ends_campaign_in_death(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FatalFakeCairnEngine(),
    )

    state = service.load_state()
    state.character.cairn.hp = 1
    state.character.cairn.str_score = 1
    store.save(state, create_checkpoint=False)

    harmed = service.suffer_harm(
        amount=5,
        source="Falling masonry",
        in_combat=True,
        armor_applies=False,
    )

    assert harmed.campaign_status == CampaignStatus.ENDED
    assert harmed.campaign_end_reason == CampaignEndReason.DEATH
    assert harmed.campaign_end_summary is not None
    assert "Final turn: Fatal harm from Falling masonry." in harmed.campaign_end_summary
    assert harmed.action_log[-1].title == "Campaign ended"


def test_service_recovery_restores_hp(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    state = service.load_state()
    state.character.cairn.hp = 0
    store.save(state, create_checkpoint=False)

    recovered = service.recover_character(CairnRestKind.BREATHER)

    assert recovered.oracle_history[-1].kind == "recovery"
    assert recovered.character.cairn.hp == recovered.character.cairn.max_hp


def test_service_explicit_retreat_records_deterministic_outcome(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )
    state = service.load_state()
    state.encounter = EncounterState(
        active=True,
        round_number=2,
        combatants=[EnemyCombatant(name="Abbey ghoul", hp=4, max_hp=4)],
    )
    store.save(state, create_checkpoint=False)

    retreated = service.retreat_from_encounter("Break contact and reach the chapel arch.")

    assert retreated.oracle_history[-1].kind == "retreat"
    assert retreated.oracle_history[-1].cairn is not None
    assert retreated.oracle_history[-1].cairn.retreat_outcome == RetreatOutcome.ESCAPED
