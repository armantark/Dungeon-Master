from dungeon_master.cairn import CairnEngine
from dungeon_master.models import (
    AttackStance,
    CairnCharacterState,
    CairnItemState,
    CairnItemTag,
    CairnMechanicsSource,
    EncounterEndReason,
    EncounterState,
    EnemyCombatant,
    GameState,
    RetreatOutcome,
)
from dungeon_master.narrative import NarrativeConfig
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
    assert len(state.encounter.combatants) == 1
    assert state.encounter.combatants[0].name == "Abbey ghoul"
    assert outcome.kind == "attack"
    assert outcome.cairn is not None
    assert outcome.cairn.target_combatant_id == state.encounter.combatants[0].id
    assert outcome.cairn.combat_round == 1
    assert outcome.cairn.player_acted is True
    assert outcome.cairn.damage_after_armor == 4


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
