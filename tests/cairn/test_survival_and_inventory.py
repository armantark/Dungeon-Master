import pytest

from dungeon_master.domain.models import (
    CairnDayPhase,
    CairnItemEffectKind,
    CairnItemPower,
    CairnItemPowerKind,
    CairnItemState,
    CairnItemTag,
    CairnMechanicsSource,
    CairnResourceDeltaReason,
    CairnResourceKind,
    CairnResourcePool,
    CairnResourceRechargePolicy,
    CairnSurvivalAction,
    CairnTimeAdvance,
    EncounterEndReason,
    InventoryItem,
    RetreatOutcome,
)
from dungeon_master.llm.narration import NarrativeConfig
from dungeon_master.mechanics.engine import (
    CairnEngine,
)
from tests.cairn.support import (
    RecordingAcquisitionCompletion,
    _active_encounter_state,
    _companion_state,
    _ready_state,
)


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


def test_survival_time_recharges_policy_resources() -> None:
    state = _ready_state()
    lantern = InventoryItem(
        name="Self-feeding lantern",
        details="Its worm-oil condenses slowly through the day.",
        cairn=CairnItemState(
            source=CairnMechanicsSource.EXPLICIT,
            tags=[CairnItemTag.LIGHT],
            resources=[
                CairnResourcePool(
                    label="Oil",
                    kind=CairnResourceKind.FUEL,
                    current=0,
                    max=2,
                    recharge_policy=CairnResourceRechargePolicy.PER_WATCH,
                ),
            ],
        ),
    )
    state.character.inventory.append(lantern)
    engine = CairnEngine(seed=1, config=NarrativeConfig(model="", api_key=None, base_url=None))

    update = engine.advance_survival_clock(
        state,
        time_advance=CairnTimeAdvance.WATCH,
        actions=(),
    )

    assert lantern.cairn.resources[0].current == 1
    assert update.resolution.resource_deltas[0].resource_label == "Oil"
    assert update.resolution.resource_deltas[0].before == 0
    assert update.resolution.resource_deltas[0].after == 1
    assert update.resolution.resource_deltas[0].reason == CairnResourceDeltaReason.RECHARGE


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
        "]}",
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


def test_acquire_items_normalizes_petty_slot_mistake_and_recomputes_burden() -> None:
    state = _ready_state()
    completion = RecordingAcquisitionCompletion(
        '{"items":['
        '{"name":"Folded phone number","details":"A tiny scrap of paper.",'
        '"tags":["petty","utility"],"slots":1,"weapon_damage_die":null,'
        '"armor_bonus":0,"uses":null,"equipped":false}'
        "]}",
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

    engine.acquire_items(state, text="I pick up the folded phone number.")

    assert state.character.inventory[-1].cairn.slots == 0
    assert state.character.cairn.slots_used == 2


def test_acquire_items_can_ready_new_weapon_and_unequip_old_one() -> None:
    state = _ready_state()
    original_weapon = state.character.inventory[0]
    completion = RecordingAcquisitionCompletion(
        '{"items":['
        '{"name":"Ghoul spear","details":"Still wet from the fight.",'
        '"tags":["weapon"],"slots":1,"weapon_damage_die":8,'
        '"armor_bonus":0,"uses":null,"equipped":true}'
        "]}",
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


def test_transfer_item_resolves_actors_by_stable_id() -> None:
    state = _companion_state()
    companion = state.party_members[0]
    companion.sheet.name = state.character.name
    item = state.character.inventory[1]
    engine = CairnEngine(seed=1, config=NarrativeConfig(model="", api_key=None, base_url=None))

    summary = engine.transfer_item(
        state,
        item_id=item.id,
        source_actor_id="player",
        target_actor_id=companion.id,
    )

    assert summary == (
        f"Transferred {item.name} from {state.character.name} to {companion.sheet.name}."
    )
    assert item not in state.character.inventory
    assert companion.sheet.inventory[-1] is item


def test_transfer_item_repairs_complete_derived_state_for_both_actors() -> None:
    state = _companion_state()
    companion = state.party_members[0]
    engine = CairnEngine(seed=1, config=NarrativeConfig(model="", api_key=None, base_url=None))
    weapon = state.character.inventory[0]
    weapon.cairn.tags.append(CairnItemTag.ARMOR)
    weapon.cairn.armor_bonus = 2
    state.character.cairn = state.character.cairn.model_copy(
        update={"primary_weapon_item_id": weapon.id},
    )
    state.character.cairn.dex_score = 0
    state.character.cairn.survival.watches_since_meal = 3
    state.character.cairn.slots_used = 99
    state.character.cairn.armor = 3
    companion.sheet.cairn.primary_weapon_item_id = "missing-item"
    companion.sheet.cairn.str_score = 0
    companion.sheet.cairn.slots_total = 3
    companion.sheet.cairn.hp = 3
    companion.sheet.cairn.survival.watches_since_sleep = 6
    companion.sheet.cairn.slots_used = 99
    companion.sheet.cairn.armor = 3

    engine.transfer_item(
        state,
        item_id=weapon.id,
        source_actor_id=None,
        target_actor_id=companion.id,
    )

    repaired_primary_weapon_id = state.character.cairn.primary_weapon_item_id
    assert weapon.cairn.equipped is False
    assert repaired_primary_weapon_id is None
    assert state.character.cairn.armor == 0
    assert state.character.cairn.slots_used == 1
    assert state.character.cairn.overloaded is False
    assert state.character.cairn.deprived is True
    assert state.character.cairn.paralyzed is True
    assert companion.sheet.cairn.primary_weapon_item_id == companion.sheet.inventory[0].id
    assert companion.sheet.inventory[0].cairn.equipped is True
    assert companion.sheet.cairn.armor == 0
    assert companion.sheet.cairn.slots_used == 3
    assert companion.sheet.cairn.overloaded is True
    assert companion.sheet.cairn.hp == 0
    assert companion.sheet.cairn.deprived is True
    assert companion.sheet.cairn.dead is True


def test_transfer_item_rejects_same_actor_without_mutating_inventory() -> None:
    state = _ready_state()
    item = state.character.inventory[0]
    engine = CairnEngine(seed=1, config=NarrativeConfig(model="", api_key=None, base_url=None))

    with pytest.raises(ValueError, match="Cannot transfer an item to the same actor"):
        engine.transfer_item(
            state,
            item_id=item.id,
            source_actor_id=None,
            target_actor_id="player",
        )

    assert state.character.inventory[0] is item


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
