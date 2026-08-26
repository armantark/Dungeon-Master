import pytest

from dungeon_master.cairn import (
    AttackActor,
    CairnEngine,
    EncounterScalingPolicy,
    GeneratedEncounterCombatant,
    GeneratedEncounterSeed,
)
from dungeon_master.models import (
    AttackStance,
    CairnItemState,
    CairnItemTag,
    CairnMechanicsSource,
    CairnResourceCost,
    CairnResourceDeltaReason,
    CairnResourceDrawPolicy,
    CairnResourceKind,
    CairnResourcePool,
    CampaignDangerProfile,
    EncounterAdvantagePayoff,
    EncounterEndReason,
    EncounterInitiator,
    EncounterState,
    EncounterThreatLevel,
    EnemyCombatant,
    InventoryItem,
)
from dungeon_master.narrative import NarrativeConfig
from tests.cairn.support import (
    RecordingAcquisitionCompletion,
    _active_encounter_state,
    _companion_state,
    _ready_state,
    _usable_test_config,
)


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
        participant.damage_after_armor for participant in outcome.cairn.coordinated_participants
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


def test_ranged_attack_consumes_actor_inventory_resource() -> None:
    state = _companion_state()
    companion = state.party_members[0]
    bow = companion.sheet.inventory[0]
    bow.name = "Drusus' bow"
    bow.cairn.tags = [CairnItemTag.WEAPON, CairnItemTag.RANGED]
    bow.cairn.weapon_damage_die = 6
    bow.cairn.attack_costs = [
        CairnResourceCost(
            label="Arrows",
            kind=CairnResourceKind.AMMO,
            amount=1,
            draw_policy=CairnResourceDrawPolicy.ACTOR_INVENTORY,
        ),
    ]
    quiver = InventoryItem(
        name="Quiver of iron-headed arrows",
        details="A companion's arrow bundle.",
        cairn=CairnItemState(
            source=CairnMechanicsSource.EXPLICIT,
            tags=[CairnItemTag.SUPPLIES, CairnItemTag.RANGED],
            resources=[
                CairnResourcePool(
                    label="Arrows",
                    kind=CairnResourceKind.AMMO,
                    current=3,
                    max=12,
                ),
            ],
        ),
    )
    companion.sheet.inventory.append(quiver)
    engine = CairnEngine(seed=1, config=NarrativeConfig(model="", api_key=None, base_url=None))

    outcome = engine.resolve_attack(
        state,
        target_name="Abbey ghoul",
        target_armor=0,
        weapon_item_id=bow.id,
        stance=AttackStance.NORMAL,
        actor_id=companion.id,
    )

    assert quiver.cairn.resources[0].current == 2
    assert outcome.cairn is not None
    assert outcome.cairn.resource_deltas == [
        outcome.cairn.resource_deltas[0],
    ]
    delta = outcome.cairn.resource_deltas[0]
    assert delta.actor_id == companion.id
    assert delta.item_id == quiver.id
    assert delta.resource_label == "Arrows"
    assert delta.before == 3
    assert delta.after == 2
    assert delta.reason == CairnResourceDeltaReason.ATTACK


def test_attack_rejects_insufficient_resource_without_partial_mutation() -> None:
    state = _ready_state()
    weapon = state.character.inventory[0]
    weapon.cairn.resources = [
        CairnResourcePool(
            label="Sun charge",
            kind=CairnResourceKind.CHARGE,
            current=0,
            max=2,
        ),
    ]
    weapon.cairn.attack_costs = [
        CairnResourceCost(
            label="Sun charge",
            kind=CairnResourceKind.CHARGE,
            amount=1,
            draw_policy=CairnResourceDrawPolicy.SELF,
        ),
    ]
    engine = CairnEngine(seed=1, config=NarrativeConfig(model="", api_key=None, base_url=None))

    with pytest.raises(ValueError, match="insufficient Sun charge"):
        engine.resolve_attack(
            state,
            target_name="Abbey ghoul",
            target_armor=0,
            weapon_item_id=weapon.id,
            stance=AttackStance.NORMAL,
        )

    assert weapon.cairn.resources[0].current == 0
    assert state.encounter.active is True
    assert state.encounter.combatants[0].hp == state.encounter.combatants[0].max_hp


def test_coordinated_attack_consumes_each_participant_resource() -> None:
    state = _companion_state()
    companion = state.party_members[0]
    player_weapon = state.character.inventory[0]
    player_weapon.cairn.resources = [
        CairnResourcePool(
            label="Charges",
            kind=CairnResourceKind.CHARGE,
            current=2,
            max=2,
        ),
    ]
    player_weapon.cairn.attack_costs = [
        CairnResourceCost(label="Charges", kind=CairnResourceKind.CHARGE),
    ]
    companion_weapon = companion.sheet.inventory[0]
    companion_weapon.cairn.resources = [
        CairnResourcePool(
            label="Charges",
            kind=CairnResourceKind.CHARGE,
            current=2,
            max=2,
        ),
    ]
    companion_weapon.cairn.attack_costs = [
        CairnResourceCost(label="Charges", kind=CairnResourceKind.CHARGE),
    ]
    engine = CairnEngine(seed=1, config=NarrativeConfig(model="", api_key=None, base_url=None))

    outcome = engine.resolve_coordinated_attack(
        state,
        target_name="Abbey ghoul",
        target_armor=0,
        participants=(
            AttackActor(id=None, name=state.character.name, sheet=state.character),
            AttackActor(id=companion.id, name=companion.sheet.name, sheet=companion.sheet),
        ),
    )

    assert player_weapon.cairn.resources[0].current == 1
    assert companion_weapon.cairn.resources[0].current == 1
    assert outcome.cairn is not None
    assert len(outcome.cairn.resource_deltas) == 2
    assert {delta.actor_id for delta in outcome.cairn.resource_deltas} == {None, companion.id}
