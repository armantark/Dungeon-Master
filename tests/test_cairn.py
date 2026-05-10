import pytest
from litellm.types.utils import ModelResponse

from dungeon_master.cairn import (
    AttackActor,
    CairnEngine,
    EncounterScalingPolicy,
    GeneratedCairnBackfill,
    GeneratedCairnItemProfile,
    GeneratedEncounterCombatant,
    GeneratedEncounterSeed,
)
from dungeon_master.models import (
    AttackStance,
    CairnCharacterState,
    CairnConditionKey,
    CairnDayPhase,
    CairnItemEffectKind,
    CairnItemPower,
    CairnItemPowerKind,
    CairnItemState,
    CairnItemTag,
    CairnMechanicsSource,
    CairnSurvivalAction,
    CairnTimeAdvance,
    CampaignDangerProfile,
    EncounterAdvantagePayoff,
    EncounterEndReason,
    EncounterInitiator,
    EncounterState,
    EncounterThreatLevel,
    EnemyCombatant,
    GameState,
    InventoryItem,
    PartyMember,
    RetreatOutcome,
)
from dungeon_master.narrative import CompletionRequest, NarrativeConfig
from tests.factories import sample_state


def _ready_state() -> GameState:
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
    )
    weapon = state.character.inventory[0]
    weapon.cairn = CairnItemState(
        source=CairnMechanicsSource.EXPLICIT,
        tags=[CairnItemTag.WEAPON],
        weapon_damage_die=6,
        equipped=True,
    )
    return state


def _active_encounter_state(*, player_dex: int, enemy_dex: int) -> GameState:
    state = _ready_state()
    state.character.cairn.dex_score = player_dex
    state.character.cairn.max_dex_score = player_dex
    state.encounter = EncounterState(
        active=True,
        round_number=2,
        combatants=[
            EnemyCombatant(
                name="Abbey ghoul",
                hp=4,
                max_hp=4,
                dex_score=enemy_dex,
            ),
        ],
    )
    return state


def _companion_state() -> GameState:
    state = _ready_state()
    companion = PartyMember(
        sheet=state.character.model_copy(deep=True),
        loyalty="Paid through the next dawn.",
    )
    companion.sheet.name = "Brother Sava"
    companion.sheet.inventory = [
        InventoryItem(
            name="Sava's spear",
            details="A hireling's ashwood spear.",
            cairn=CairnItemState(
                source=CairnMechanicsSource.EXPLICIT,
                tags=[CairnItemTag.WEAPON],
                weapon_damage_die=8,
                equipped=True,
            ),
        ),
        InventoryItem(
            name="Shared rope",
            details="Twenty-five feet of knotted rope.",
            cairn=CairnItemState(source=CairnMechanicsSource.EXPLICIT, slots=1),
        ),
    ]
    companion.sheet.cairn = CairnCharacterState(
        source=CairnMechanicsSource.EXPLICIT,
        str_score=10,
        dex_score=18,
        wil_score=9,
        max_str_score=10,
        max_dex_score=18,
        max_wil_score=9,
        hp=3,
        max_hp=3,
    )
    state.party_members.append(companion)
    return state


class RecordingAcquisitionCompletion:
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


class RecordingBackfillCompletion(RecordingAcquisitionCompletion):
    def __call__(self, request: CompletionRequest) -> ModelResponse:
        self.messages = request.messages
        del request
        return ModelResponse(choices=[{"message": {"content": self.payload}}])


def _usable_test_config() -> NarrativeConfig:
    return NarrativeConfig(model="test-model", api_key=None, base_url=None)


def test_generated_backfill_normalizes_zero_weapon_damage_for_non_weapons() -> None:
    generated = GeneratedCairnBackfill.model_validate(
        {
            "skills": ["Road-hardened"],
            "abilities": [],
            "str_score": 10,
            "dex_score": 10,
            "wil_score": 10,
            "max_hp": 3,
            "fatigue": 0,
            "deprived": False,
            "critically_wounded": False,
            "doomed": False,
            "paralyzed": False,
            "delirious": False,
            "dead": False,
            "notes": "Generated from a model payload that used 0 as a placeholder.",
            "inventory": [
                {
                    "name": "Tallow candle",
                    "details": "A tiny light for the ash road.",
                    "tags": ["light", "petty"],
                    "slots": 0,
                    "weapon_damage_die": 0,
                    "armor_bonus": 0,
                    "uses": None,
                    "equipped": False,
                },
                {
                    "name": "Trail rations",
                    "details": "Dried bread and salt fish.",
                    "tags": ["supplies"],
                    "slots": 1,
                    "weapon_damage_die": "0",
                    "armor_bonus": 0,
                    "uses": None,
                    "equipped": False,
                },
            ],
        },
    )

    assert [item.weapon_damage_die for item in generated.inventory] == [None, None]


def test_generated_backfill_defaults_missing_weapon_damage_for_weapons() -> None:
    generated = GeneratedCairnBackfill.model_validate(
        {
            "skills": ["Road-hardened"],
            "abilities": [],
            "str_score": 10,
            "dex_score": 10,
            "wil_score": 10,
            "max_hp": 3,
            "fatigue": 0,
            "deprived": False,
            "critically_wounded": False,
            "doomed": False,
            "paralyzed": False,
            "delirious": False,
            "dead": False,
            "notes": "Generated from a model payload that omitted a weapon die.",
            "inventory": [
                {
                    "name": "Notched cudgel",
                    "details": "A heavy pilgrim's club.",
                    "tags": ["weapon"],
                    "slots": 1,
                    "weapon_damage_die": 0,
                    "armor_bonus": 0,
                    "uses": None,
                    "equipped": True,
                },
                {
                    "name": "Trail rations",
                    "details": "Dried bread and salt fish.",
                    "tags": ["supplies"],
                    "slots": 1,
                    "weapon_damage_die": None,
                    "armor_bonus": 0,
                    "uses": None,
                    "equipped": False,
                },
            ],
        },
    )

    assert generated.inventory[0].weapon_damage_die == 6
    assert generated.inventory[1].weapon_damage_die is None


def test_backfill_prompt_preserves_visible_authored_gear() -> None:
    state = sample_state()
    authored = state.character.model_copy(
        update={
            "name": "Test Companion",
            "backstory": (
                "Recent player-visible context for this recruit:\n"
                "- Narrative response: The companion keeps a rusted wood-axe ready."
            ),
        },
        deep=True,
    )
    payload = GeneratedCairnBackfill(
        skills=["Keep watch"],
        abilities=["Hold a doorway"],
        str_score=10,
        dex_score=11,
        wil_score=9,
        max_hp=3,
        inventory=[
            GeneratedCairnItemProfile(
                name="Rusted wood-axe",
                details="The weapon already surfaced in play.",
                tags=[CairnItemTag.WEAPON],
                slots=1,
                weapon_damage_die=6,
                armor_bonus=0,
                uses=None,
                equipped=True,
            ),
            GeneratedCairnItemProfile(
                name="Threadbare shawl",
                details="A poor cloak against ash-cold air.",
                tags=[CairnItemTag.PETTY],
                slots=0,
                weapon_damage_die=None,
                armor_bonus=0,
                uses=None,
                equipped=False,
            ),
        ],
    ).model_dump_json()
    completion = RecordingBackfillCompletion(payload)
    engine = CairnEngine(
        config=NarrativeConfig(model="test-model", api_key="test-key", base_url=None),
        completion_function=completion,
    )

    sheet = engine.backfill_companion_sheet(state, authored)

    assert completion.messages is not None
    system_prompt = " ".join(completion.messages[0]["content"].split())
    user_prompt = " ".join(completion.messages[1]["content"].split())
    assert "concrete visible gear already established in play" in system_prompt
    assert "Preserve concrete carried gear named in the authored character context" in user_prompt
    assert "rusted wood-axe" in user_prompt
    assert sheet.inventory[0].name == "Rusted wood-axe"
    assert sheet.cairn.primary_weapon_item_id == sheet.inventory[0].id


def test_resolve_attack_seeds_encounter_and_tracks_target() -> None:
    state = _ready_state()
    engine = CairnEngine(
        seed=1,
        config=NarrativeConfig(model="", api_key=None, base_url=None),
    )

    outcome = engine.resolve_attack(
        state,
        target_name="Abbey ghoul",
        target_armor=1,
        weapon_item_id=state.character.inventory[0].id,
        stance=AttackStance.NORMAL,
    )

    assert state.encounter.active is True
    assert state.encounter.initiator == EncounterInitiator.PLAYER
    assert len(state.encounter.combatants) == 1
    assert state.encounter.combatants[0].name == "Abbey ghoul"
    assert outcome.kind == "attack"
    assert outcome.cairn is not None
    assert outcome.cairn.combat_initiator == EncounterInitiator.PLAYER
    assert outcome.cairn.target_combatant_id == state.encounter.combatants[0].id
    assert outcome.cairn.combat_round == 1
    assert outcome.cairn.player_acted is True
    assert outcome.cairn.damage_after_armor == 4


def test_fallback_encounter_seed_uses_ordinary_cairn_scale() -> None:
    state = _ready_state()
    engine = CairnEngine(
        seed=1,
        config=NarrativeConfig(model="", api_key=None, base_url=None),
    )

    outcome = engine.resolve_attack(
        state,
        target_name="Abbey ghoul",
        target_armor=2,
        weapon_item_id=state.character.inventory[0].id,
        stance=AttackStance.NORMAL,
    )

    foe = state.encounter.combatants[0]
    assert foe.max_hp == 3
    assert foe.hp <= 3
    assert foe.armor == 1
    assert foe.threat_level == EncounterThreatLevel.ORDINARY
    assert outcome.cairn is not None
    assert outcome.cairn.target_armor == 1


def test_encounter_scaling_normalizes_out_of_band_llm_stats() -> None:
    engine = CairnEngine(config=NarrativeConfig(model="", api_key=None, base_url=None))
    generated = GeneratedEncounterSeed(
        notes="A model tried to overbuild an ordinary scuffle.",
        combatants=[
            GeneratedEncounterCombatant(
                name="Overbuilt footpad",
                hp=12,
                str_score=18,
                dex_score=18,
                wil_score=18,
                armor=3,
                weapon_name="crooked knife",
                weapon_damage_die=7,
                threat_level=EncounterThreatLevel.ORDINARY,
            ),
            GeneratedEncounterCombatant(
                name="Second footpad",
                hp=9,
                str_score=12,
                dex_score=10,
                wil_score=8,
                armor=3,
                weapon_name="club",
                weapon_damage_die=6,
                threat_level=EncounterThreatLevel.HARDIER,
            ),
        ],
    )

    scaled = engine._scaled_encounter_seed(  # noqa: SLF001
        generated,
        EncounterScalingPolicy.for_danger(CampaignDangerProfile.STANDARD),
    )

    assert scaled.combatants[0].hp == 3
    assert scaled.combatants[0].armor == 1
    assert scaled.combatants[0].weapon_damage_die in {4, 6, 8, 10, 12}
    assert scaled.combatants[0].leader is True
    assert scaled.combatants[1].hp == 6
    assert scaled.combatants[1].armor == 2


def test_lethal_encounter_scaling_allows_telegraphed_serious_threat() -> None:
    engine = CairnEngine(config=NarrativeConfig(model="", api_key=None, base_url=None))
    generated = GeneratedEncounterSeed(
        notes="A clear monster, not a street scuffle.",
        combatants=[
            GeneratedEncounterCombatant(
                name="Bell-tower ogre",
                hp=12,
                str_score=18,
                dex_score=6,
                wil_score=10,
                armor=3,
                weapon_name="iron bell-clapper",
                weapon_damage_die=12,
                threat_level=EncounterThreatLevel.SERIOUS,
                weakness="Its bare ankles are exposed below the bell skirt.",
            ),
        ],
    )

    scaled = engine._scaled_encounter_seed(  # noqa: SLF001
        generated,
        EncounterScalingPolicy.for_danger(CampaignDangerProfile.LETHAL),
    )

    assert scaled.combatants[0].hp == 12
    assert scaled.combatants[0].armor == 3
    assert scaled.combatants[0].weakness == "Its bare ankles are exposed below the bell skirt."


def test_setup_advantage_is_consumed_by_matching_attack() -> None:
    state = _ready_state()
    state.encounter = EncounterState(
        active=True,
        round_number=1,
        first_round_dex_gate_pending=True,
        initiator=EncounterInitiator.PLAYER,
        combatants=[
            EnemyCombatant(
                name="Abbey ghoul",
                hp=4,
                max_hp=4,
                armor=1,
                weakness="Ash blinds the white film over its eyes.",
            ),
        ],
    )
    engine = CairnEngine(
        seed=1,
        config=NarrativeConfig(model="", api_key=None, base_url=None),
    )

    setup = engine.setup_advantage(
        state,
        target_name="Abbey ghoul",
        setup="I fling ash into the ghoul's filmed eyes.",
        payoff=EncounterAdvantagePayoff.ENHANCED_ATTACK,
    )
    attack = engine.resolve_attack(
        state,
        target_name="Abbey ghoul",
        target_armor=0,
        weapon_item_id=state.character.inventory[0].id,
        stance=AttackStance.NORMAL,
    )

    assert setup.cairn is not None
    assert setup.cairn.advantage_consumed is False
    assert attack.cairn is not None
    assert attack.cairn.advantage_payoff == EncounterAdvantagePayoff.ENHANCED_ATTACK
    assert attack.cairn.advantage_consumed is True
    assert attack.cairn.attack_stance == AttackStance.ENHANCED
    assert state.encounter.pending_advantages == []


def test_attack_rejects_dangling_primary_weapon_instead_of_unarmed_fallback() -> None:
    state = _ready_state()
    missing_weapon_id = state.character.inventory[0].id
    state.character.inventory = state.character.inventory[1:]
    state.character.cairn.primary_weapon_item_id = missing_weapon_id
    engine = CairnEngine(
        seed=1,
        config=NarrativeConfig(model="", api_key=None, base_url=None),
    )

    with pytest.raises(ValueError, match="primary weapon is missing from inventory"):
        engine.resolve_attack(
            state,
            target_name="Abbey ghoul",
            target_armor=1,
            weapon_item_id=None,
            stance=AttackStance.NORMAL,
        )


def test_coordinated_attack_records_each_participant() -> None:
    state = _companion_state()
    companion = state.party_members[0]
    engine = CairnEngine(
        seed=1,
        config=NarrativeConfig(model="", api_key=None, base_url=None),
    )

    outcome = engine.resolve_coordinated_attack(
        state,
        target_name="Abbey ghoul",
        target_armor=0,
        participants=(
            AttackActor(id=None, name=state.character.name, sheet=state.character),
            AttackActor(id=companion.id, name=companion.sheet.name, sheet=companion.sheet),
        ),
    )

    assert outcome.kind == "attack"
    assert outcome.cairn is not None
    assert outcome.cairn.coordinated_attack is True
    assert outcome.cairn.player_acted is True
    assert len(outcome.cairn.coordinated_participants) == 2
    assert [participant.actor_name for participant in outcome.cairn.coordinated_participants] == [
        state.character.name,
        "Brother Sava",
    ]
    assert all(participant.acted for participant in outcome.cairn.coordinated_participants)
    assert outcome.cairn.damage_after_armor == sum(
        participant.damage_after_armor
        for participant in outcome.cairn.coordinated_participants
    )


def test_resolve_attack_against_broad_opening_target_uses_seeded_leader() -> None:
    state = _ready_state()
    state.encounter = EncounterState(
        active=False,
        round_number=2,
        end_reason=EncounterEndReason.PLAYER_ESCAPED,
        combatants=[
            EnemyCombatant(
                name="Spent prior foe",
                hp=1,
                max_hp=1,
            ),
        ],
    )

    engine = CairnEngine(
        seed=1,
        config=_usable_test_config(),
        completion_function=RecordingAcquisitionCompletion(
            """{
              "notes": "The vanguard pushes through the hovel doorway.",
              "combatants": [
                {
                  "name": "Leper-Crowd Bell-Ringer",
                  "description": "A rotting fanatic swinging a rusted bell.",
                  "hp": 4,
                  "str_score": 9,
                  "dex_score": 9,
                  "wil_score": 11,
                  "armor": 0,
                  "weapon_name": "Heavy iron bell",
                  "weapon_damage_die": 6,
                  "leader": true,
                  "notes": "Signals the rest of the crowd."
                },
                {
                  "name": "Leper-Pilgrim",
                  "description": "A diseased zealot in filthy robes.",
                  "hp": 3,
                  "str_score": 8,
                  "dex_score": 8,
                  "wil_score": 10,
                  "armor": 0,
                  "weapon_name": "Jagged censer",
                  "weapon_damage_die": 6,
                  "leader": false,
                  "notes": "Fights with reckless devotion."
                }
              ]
            }""",
        ),
    )

    outcome = engine.resolve_attack(
        state,
        target_name="Leper-crowd vanguard",
        target_armor=0,
        weapon_item_id=state.character.inventory[0].id,
        stance=AttackStance.NORMAL,
    )

    assert state.encounter.active is True
    assert [combatant.name for combatant in state.encounter.combatants] == [
        "Leper-Crowd Bell-Ringer",
        "Leper-Pilgrim",
    ]
    assert outcome.cairn is not None
    assert outcome.question == "Attack Leper-Crowd Bell-Ringer"
    assert outcome.cairn.target_name == "Leper-Crowd Bell-Ringer"
    assert outcome.cairn.target_combatant_id == state.encounter.combatants[0].id


def test_resolve_attack_keeps_strict_targeting_during_active_encounter() -> None:
    state = _active_encounter_state(player_dex=18, enemy_dex=8)
    engine = CairnEngine(
        seed=1,
        config=NarrativeConfig(model="", api_key=None, base_url=None),
    )

    with pytest.raises(
        ValueError,
        match="No active foe matches 'leper-crowd vanguard'\\.",
    ):
        engine.resolve_attack(
            state,
            target_name="leper-crowd vanguard",
            target_armor=0,
            weapon_item_id=state.character.inventory[0].id,
            stance=AttackStance.NORMAL,
        )


def test_resolve_enemy_opener_seeds_encounter_and_tracks_enemy_initiative() -> None:
    state = _ready_state()
    engine = CairnEngine(
        seed=1,
        config=NarrativeConfig(model="", api_key=None, base_url=None),
    )

    outcome = engine.resolve_enemy_opener(
        state,
        source="Abbey ghoul",
        text="The abbey ghoul drops from the choir loft and rakes me before I can react.",
    )

    assert outcome.kind == "harm"
    assert outcome.cairn is not None
    assert outcome.cairn.combat_started is True
    assert outcome.cairn.combat_round == 1
    assert outcome.cairn.combat_initiator == EncounterInitiator.ENEMY
    assert outcome.cairn.player_acted is False
    assert outcome.cairn.enemy_damage is not None
    assert state.encounter.active is True
    assert state.encounter.initiator == EncounterInitiator.ENEMY
    assert state.encounter.first_round_dex_gate_pending is False
    assert state.encounter.round_number == 2


def test_resolve_attack_failed_first_round_still_allows_enemy_retaliation() -> None:
    state = _ready_state()
    state.character.cairn.dex_score = 3
    state.character.cairn.max_dex_score = 3
    engine = CairnEngine(
        seed=1,
        config=NarrativeConfig(model="", api_key=None, base_url=None),
    )

    outcome = engine.resolve_attack(
        state,
        target_name="Abbey ghoul",
        target_armor=1,
        weapon_item_id=state.character.inventory[0].id,
        stance=AttackStance.NORMAL,
    )

    assert outcome.cairn is not None
    assert outcome.cairn.player_acted is False
    assert outcome.cairn.base_damage is None
    assert outcome.cairn.enemy_damage == 1
    assert state.character.cairn.hp == 3


def test_companion_can_resolve_attack_with_own_weapon_and_take_retaliation() -> None:
    state = _companion_state()
    companion = state.party_members[0]
    engine = CairnEngine(
        seed=1,
        config=NarrativeConfig(model="", api_key=None, base_url=None),
    )

    outcome = engine.resolve_attack(
        state,
        target_name="Abbey ghoul",
        target_armor=0,
        weapon_item_id=companion.sheet.inventory[0].id,
        stance=AttackStance.NORMAL,
        actor_id=companion.id,
    )

    assert outcome.cairn is not None
    assert outcome.cairn.actor_id == companion.id
    assert outcome.cairn.actor_name == "Brother Sava"
    assert outcome.cairn.weapon_name == "Sava's spear"
    assert outcome.cairn.base_damage is not None
    assert outcome.cairn.hp_after == companion.sheet.cairn.hp
    assert companion.sheet.cairn.hp < companion.sheet.cairn.max_hp
    assert state.character.cairn.hp == 4


def test_suffer_harm_does_not_seed_encounter() -> None:
    state = _ready_state()
    engine = CairnEngine(
        seed=1,
        config=NarrativeConfig(model="", api_key=None, base_url=None),
    )

    outcome = engine.suffer_harm(
        state,
        amount=2,
        source="Falling masonry",
        in_combat=True,
        armor_applies=False,
    )

    assert outcome.kind == "harm"
    assert outcome.cairn is not None
    assert outcome.cairn.combat_started is None
    assert outcome.cairn.combat_initiator is None
    assert state.encounter.active is False


def test_companion_can_suffer_harm_without_mutating_player() -> None:
    state = _companion_state()
    companion = state.party_members[0]
    engine = CairnEngine(
        seed=1,
        config=NarrativeConfig(model="", api_key=None, base_url=None),
    )

    outcome = engine.suffer_harm(
        state,
        amount=2,
        source="Falling masonry",
        in_combat=False,
        armor_applies=False,
        actor_id=companion.id,
    )

    assert outcome.cairn is not None
    assert outcome.cairn.actor_id == companion.id
    assert companion.sheet.cairn.str_score == 8
    assert state.character.cairn.str_score == 12


def test_resolve_retreat_can_escape_encounter() -> None:
    state = _active_encounter_state(player_dex=20, enemy_dex=1)
    engine = CairnEngine(
        seed=2,
        config=NarrativeConfig(model="", api_key=None, base_url=None),
    )

    outcome = engine.resolve_retreat(state, "I break away into the chapel arch.")

    assert outcome.kind == "retreat"
    assert outcome.cairn is not None
    assert outcome.cairn.retreat_outcome == RetreatOutcome.ESCAPED
    assert outcome.cairn.encounter_end_reason == EncounterEndReason.PLAYER_ESCAPED
    assert state.encounter.active is False
    assert state.encounter.pursuit_active is False


def test_resolve_retreat_can_leave_pursuit_active() -> None:
    state = _active_encounter_state(player_dex=20, enemy_dex=19)
    engine = CairnEngine(
        seed=2,
        config=NarrativeConfig(model="", api_key=None, base_url=None),
    )

    outcome = engine.resolve_retreat(state, "I fall back but keep moving.")

    assert outcome.cairn is not None
    assert outcome.cairn.retreat_outcome == RetreatOutcome.DISENGAGED
    assert state.encounter.active is True
    assert state.encounter.player_disengaged is True
    assert state.encounter.pursuit_active is True


def test_resolve_retreat_can_fail_and_take_enemy_harm() -> None:
    state = _active_encounter_state(player_dex=1, enemy_dex=10)
    engine = CairnEngine(
        seed=2,
        config=NarrativeConfig(model="", api_key=None, base_url=None),
    )

    outcome = engine.resolve_retreat(state, "I try to flee through the nave.")

    assert outcome.cairn is not None
    assert outcome.cairn.retreat_outcome == RetreatOutcome.CAUGHT
    assert outcome.cairn.enemy_damage is not None
    assert state.encounter.active is True
    assert state.encounter.player_disengaged is False


def test_watch_advance_updates_phase_and_triggers_food_deprivation() -> None:
    state = _ready_state()
    state.character.cairn.survival.watch_index = 2
    state.character.cairn.survival.day_phase = CairnDayPhase.DAY
    state.character.cairn.survival.watches_since_meal = 2
    engine = CairnEngine(seed=1, config=NarrativeConfig(model="", api_key=None, base_url=None))

    update = engine.advance_survival_clock(
        state,
        time_advance=CairnTimeAdvance.WATCH,
    )

    assert state.character.cairn.survival.watch_index == 3
    assert state.character.cairn.survival.day_phase == CairnDayPhase.DUSK
    assert state.character.cairn.survival.watches_since_meal == 3
    assert state.character.cairn.survival.food_deprived is True
    assert state.character.cairn.deprived is True
    assert update.resolution.day_phase_after == CairnDayPhase.DUSK


def test_eating_ration_bundle_initializes_uses_and_clears_food_deprivation() -> None:
    state = _ready_state()
    ration = InventoryItem(
        name="Trail rations",
        details="Waxed cloth around hard bread and salt fish.",
        cairn=CairnItemState(
            source=CairnMechanicsSource.EXPLICIT,
            tags=[CairnItemTag.SUPPLIES],
            slots=1,
            uses=None,
        ),
    )
    state.character.inventory.append(ration)
    state.character.cairn.survival.watches_since_meal = 3
    state.character.cairn.survival.food_deprived = True
    state.character.cairn.deprived = True
    engine = CairnEngine(seed=1, config=NarrativeConfig(model="", api_key=None, base_url=None))

    update = engine.advance_survival_clock(
        state,
        time_advance=CairnTimeAdvance.NONE,
        actions=(CairnSurvivalAction.EAT,),
    )

    assert ration.cairn.uses == 2
    assert state.character.cairn.survival.watches_since_meal == 0
    assert state.character.cairn.survival.food_deprived is False
    assert state.character.cairn.deprived is False
    assert update.resolution.ration_item_name == "Trail rations"
    assert update.resolution.ration_uses_before == 3
    assert update.resolution.ration_uses_after == 2


def test_overnight_sleep_rolls_to_next_dawn_and_clears_sleep_deprivation() -> None:
    state = _ready_state()
    state.character.cairn.survival.day_number = 2
    state.character.cairn.survival.watch_index = 4
    state.character.cairn.survival.day_phase = CairnDayPhase.NIGHT
    state.character.cairn.survival.watches_since_sleep = 6
    state.character.cairn.survival.sleep_deprived = True
    state.character.cairn.deprived = True
    engine = CairnEngine(seed=1, config=NarrativeConfig(model="", api_key=None, base_url=None))

    update = engine.advance_survival_clock(
        state,
        time_advance=CairnTimeAdvance.OVERNIGHT,
        actions=(CairnSurvivalAction.SLEEP,),
    )

    assert state.character.cairn.survival.day_number == 3
    assert state.character.cairn.survival.watch_index == 0
    assert state.character.cairn.survival.day_phase == CairnDayPhase.DAWN
    assert state.character.cairn.survival.watches_since_sleep == 0
    assert state.character.cairn.survival.sleep_deprived is False
    assert state.character.cairn.deprived is False
    assert update.resolution.day_number_before == 2
    assert update.resolution.day_number_after == 3


def test_acquire_items_adds_typed_loot_and_recomputes_burden() -> None:
    state = _ready_state()
    completion = RecordingAcquisitionCompletion(
        '{"items":['
        '{"name":"Pilgrim lantern","details":"A soot-black lantern taken from the ghoul.",'
        '"tags":["light","utility"],"slots":1,"weapon_damage_die":null,'
        '"armor_bonus":0,"uses":3,"equipped":false},'
        '{"name":"Purse of old silver","details":"Stamped coins still accepted in market towns.",'
        '"tags":["petty","utility"],"slots":0,"weapon_damage_die":null,'
        '"armor_bonus":0,"uses":null,"equipped":false}'
        ']}',
    )
    engine = CairnEngine(
        seed=1,
        config=NarrativeConfig(
            model="test-model",
            api_key="test-key",
            base_url="https://example.com",
            exclude_reasoning=True,
        ),
        completion_function=completion,
    )

    summary = engine.acquire_items(
        state,
        text="I loot the abbey ghoul for a lantern and a purse of old silver.",
    )

    assert summary == "Acquired Pilgrim lantern, Purse of old silver."
    assert [item.name for item in state.character.inventory][-2:] == [
        "Pilgrim lantern",
        "Purse of old silver",
    ]
    assert state.character.cairn.slots_used == 3
    assert completion.messages is not None
    assert "Current inventory" in completion.messages[1]["content"]


def test_acquire_items_can_ready_new_weapon_and_unequip_old_one() -> None:
    state = _ready_state()
    original_weapon = state.character.inventory[0]
    completion = RecordingAcquisitionCompletion(
        '{"items":['
        '{"name":"Ghoul spear","details":"Still wet from the fight.",'
        '"tags":["weapon"],"slots":1,"weapon_damage_die":8,'
        '"armor_bonus":0,"uses":null,"equipped":true}'
        ']}',
    )
    engine = CairnEngine(
        seed=1,
        config=NarrativeConfig(
            model="test-model",
            api_key="test-key",
            base_url="https://example.com",
            exclude_reasoning=True,
        ),
        completion_function=completion,
    )

    summary = engine.acquire_items(
        state,
        text="I wrench the ghoul spear free and ready it at once.",
    )

    assert summary == "Acquired Ghoul spear. Readied: Ghoul spear."
    assert original_weapon.cairn.equipped is False
    new_weapon = state.character.inventory[-1]
    assert new_weapon.name == "Ghoul spear"
    assert new_weapon.cairn.equipped is True
    assert state.character.cairn.primary_weapon_item_id == new_weapon.id


def test_acquire_items_falls_back_when_model_is_unavailable() -> None:
    state = _ready_state()
    engine = CairnEngine(
        seed=1,
        config=NarrativeConfig(model="", api_key=None, base_url=None),
    )

    summary = engine.acquire_items(
        state,
        text="I gather the spoils into my sack.",
    )

    assert summary == "Acquired Acquired gear."
    assert state.character.inventory[-1].name == "Acquired gear"
    assert (
        state.character.inventory[-1].details
        == "Taken during play: I gather the spoils into my sack."
    )


def test_companion_can_acquire_and_drop_inventory() -> None:
    state = _companion_state()
    companion = state.party_members[0]
    engine = CairnEngine(
        seed=1,
        config=NarrativeConfig(model="", api_key=None, base_url=None),
    )

    summary = engine.acquire_items(
        state,
        text="Sava gathers the extra torch.",
        actor_id=companion.id,
    )

    assert summary == "Brother Sava acquired Acquired gear."
    assert companion.sheet.inventory[-1].name == "Acquired gear"
    assert len(state.character.inventory) == 2
    drop_summary = engine.drop_item(
        state,
        item_id=companion.sheet.inventory[-1].id,
        actor_id=companion.id,
    )
    assert drop_summary == "Brother Sava dropped Acquired gear."
    assert [item.name for item in companion.sheet.inventory] == ["Sava's spear", "Shared rope"]


def test_companion_item_use_consumes_companion_item() -> None:
    state = _companion_state()
    companion = state.party_members[0]
    scroll = InventoryItem(
        name="Sava's scroll",
        details="A petty scroll that stills a hostile will once.",
        cairn=CairnItemState(
            source=CairnMechanicsSource.EXPLICIT,
            tags=[CairnItemTag.PETTY, CairnItemTag.MAGIC, CairnItemTag.CONSUMABLE],
            slots=0,
            uses=1,
            power=CairnItemPower(
                kind=CairnItemPowerKind.SCROLL,
                name="Still Water",
                effect=CairnItemEffectKind.WARD_OR_PACIFY,
                consumed_on_use=True,
            ),
        ),
    )
    companion.sheet.inventory.append(scroll)
    engine = CairnEngine(seed=1, config=NarrativeConfig(model="", api_key=None, base_url=None))

    outcome = engine.use_item(
        state,
        item_id=scroll.id,
        intent="Sava reads the scroll aloud.",
        actor_id=companion.id,
    )

    assert outcome.cairn is not None
    assert outcome.cairn.actor_id == companion.id
    assert scroll not in companion.sheet.inventory
    assert all(item.name != "Sava's scroll" for item in state.character.inventory)


def test_spellbook_adds_fatigue_and_requires_wil_save_in_danger() -> None:
    state = _ready_state()
    state.encounter.active = True
    spellbook = InventoryItem(
        name="Book of Ashen Doors",
        details="A spellbook containing one dangerous passage-working.",
        cairn=CairnItemState(
            source=CairnMechanicsSource.EXPLICIT,
            tags=[CairnItemTag.MAGIC],
            slots=1,
            power=CairnItemPower(
                kind=CairnItemPowerKind.SPELLBOOK,
                name="Ashen Door",
                summary="Open a narrow passage where the wall is weakest.",
                effect=CairnItemEffectKind.CREATE_SAFE_PASSAGE,
                requires_wil_save_in_danger=True,
                adds_fatigue=True,
            ),
        ),
    )
    state.character.inventory.append(spellbook)
    engine = CairnEngine(seed=2, config=NarrativeConfig(model="", api_key=None, base_url=None))

    outcome = engine.use_item(state, item_id=spellbook.id, intent="I read the ashen spell.")

    assert outcome.cairn is not None
    assert outcome.cairn.item_power_kind == CairnItemPowerKind.SPELLBOOK
    assert outcome.cairn.item_effect_kind == CairnItemEffectKind.CREATE_SAFE_PASSAGE
    assert outcome.cairn.fatigue_before == 0
    assert outcome.cairn.fatigue_after is not None
    assert outcome.cairn.fatigue_after >= 1
    assert outcome.cairn.ability == "WIL"
    assert outcome.rolls[0].label == "item_wil_save"


def test_scroll_is_consumed_without_fatigue() -> None:
    state = _ready_state()
    scroll = InventoryItem(
        name="Scroll of Still Water",
        details="A petty scroll that stills a hostile will once.",
        cairn=CairnItemState(
            source=CairnMechanicsSource.EXPLICIT,
            tags=[CairnItemTag.PETTY, CairnItemTag.MAGIC, CairnItemTag.CONSUMABLE],
            slots=0,
            uses=1,
            power=CairnItemPower(
                kind=CairnItemPowerKind.SCROLL,
                name="Still Water",
                effect=CairnItemEffectKind.WARD_OR_PACIFY,
                consumed_on_use=True,
            ),
        ),
    )
    state.character.inventory.append(scroll)
    engine = CairnEngine(seed=1, config=NarrativeConfig(model="", api_key=None, base_url=None))

    outcome = engine.use_item(state, item_id=scroll.id, intent="I read the scroll aloud.")

    assert scroll not in state.character.inventory
    assert outcome.cairn is not None
    assert outcome.cairn.item_power_kind == CairnItemPowerKind.SCROLL
    assert outcome.cairn.uses_before == 1
    assert outcome.cairn.uses_after is None
    assert outcome.cairn.fatigue_before == 0
    assert outcome.cairn.fatigue_after == 0


def test_relic_spends_charge_and_reports_recharge_condition() -> None:
    state = _ready_state()
    relic = InventoryItem(
        name="Road-bell shard",
        details="It hums when a safe road bends near.",
        cairn=CairnItemState(
            source=CairnMechanicsSource.EXPLICIT,
            tags=[CairnItemTag.RELIC, CairnItemTag.UTILITY],
            slots=0,
            uses=2,
            power=CairnItemPower(
                kind=CairnItemPowerKind.RELIC,
                name="Road-bell shard",
                effect=CairnItemEffectKind.REVEAL_SIGN,
                recharge_condition="Hang it overnight above a crossroads.",
            ),
        ),
    )
    state.character.inventory.append(relic)
    engine = CairnEngine(seed=1, config=NarrativeConfig(model="", api_key=None, base_url=None))

    outcome = engine.use_item(state, item_id=relic.id, intent="I listen for the road.")

    assert relic.cairn.uses == 1
    assert outcome.cairn is not None
    assert outcome.cairn.item_power_kind == CairnItemPowerKind.RELIC
    assert outcome.cairn.uses_before == 2
    assert outcome.cairn.uses_after == 1
    assert outcome.cairn.recharge_condition == "Hang it overnight above a crossroads."


def test_holy_relic_can_restore_will_without_creating_buff_state() -> None:
    state = _ready_state()
    state.character.cairn.wil_score = 7
    icon = InventoryItem(
        name="Leaden patriarch icon",
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
                effect_ability=None,
                effect_amount=1,
                recharge_condition="Confess a true failing at a consecrated threshold.",
            ),
        ),
    )
    state.character.inventory.append(icon)
    engine = CairnEngine(seed=1, config=NarrativeConfig(model="", api_key=None, base_url=None))

    outcome = engine.use_item(
        state,
        item_id=icon.id,
        intent="I kiss the icon and ask for intercession.",
    )

    assert state.character.cairn.wil_score == 8
    assert outcome.cairn is not None
    assert outcome.cairn.item_power_kind == CairnItemPowerKind.HOLY_RELIC
    assert outcome.cairn.item_effect_kind == CairnItemEffectKind.RESTORE_ATTRIBUTE
    assert outcome.cairn.wil_before == 7
    assert outcome.cairn.wil_after == 8
    assert "bless" not in state.character.cairn.model_dump()


def test_holy_relic_can_clear_condition_through_typed_effect() -> None:
    state = _ready_state()
    state.character.cairn.delirious = True
    state.character.cairn.wil_score = 0
    icon = InventoryItem(
        name="Icon lamp",
        details="A soot-dark lamp lit before a saint.",
        cairn=CairnItemState(
            source=CairnMechanicsSource.EXPLICIT,
            tags=[CairnItemTag.HOLY, CairnItemTag.RELIC],
            power=CairnItemPower(
                kind=CairnItemPowerKind.HOLY_RELIC,
                effect=CairnItemEffectKind.CLEAR_CONDITION,
                clears_condition=CairnConditionKey.DELIRIOUS,
            ),
        ),
    )
    state.character.inventory.append(icon)
    engine = CairnEngine(seed=1, config=NarrativeConfig(model="", api_key=None, base_url=None))

    outcome = engine.use_item(state, item_id=icon.id, intent="I pray under the icon lamp.")

    assert state.character.cairn.delirious is False
    assert state.character.cairn.wil_score == 1
    assert outcome.cairn is not None
    assert outcome.cairn.item_effect_kind == CairnItemEffectKind.CLEAR_CONDITION
