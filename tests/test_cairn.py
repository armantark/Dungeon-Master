from litellm.types.utils import ModelResponse

from dungeon_master.cairn import CairnEngine
from dungeon_master.models import (
    AttackStance,
    CairnCharacterState,
    CairnItemState,
    CairnItemTag,
    CairnMechanicsSource,
    EncounterEndReason,
    EncounterInitiator,
    EncounterState,
    EnemyCombatant,
    GameState,
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
