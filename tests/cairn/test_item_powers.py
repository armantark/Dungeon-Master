from dungeon_master.cairn import (
    CairnEngine,
)
from dungeon_master.models import (
    CairnConditionKey,
    CairnItemEffectKind,
    CairnItemPower,
    CairnItemPowerKind,
    CairnItemState,
    CairnItemTag,
    CairnMechanicsSource,
    CairnResourceCost,
    CairnResourceDeltaReason,
    CairnResourceKind,
    CairnResourcePool,
    CairnResourceRechargePolicy,
    InventoryItem,
)
from dungeon_master.narrative import NarrativeConfig
from tests.cairn.support import (
    _ready_state,
)


def test_item_use_consumes_structured_charge_resource() -> None:
    state = _ready_state()
    relic = InventoryItem(
        name="Glass sun battery",
        details="A small light-catching cell.",
        cairn=CairnItemState(
            source=CairnMechanicsSource.EXPLICIT,
            tags=[CairnItemTag.RELIC],
            resources=[
                CairnResourcePool(
                    label="Sun charge",
                    kind=CairnResourceKind.CHARGE,
                    current=2,
                    max=2,
                    recharge_policy=CairnResourceRechargePolicy.IN_SUNLIGHT,
                ),
            ],
            use_costs=[
                CairnResourceCost(label="Sun charge", kind=CairnResourceKind.CHARGE),
            ],
            power=CairnItemPower(
                kind=CairnItemPowerKind.RELIC,
                name="Cauterizing gleam",
                effect=CairnItemEffectKind.RESTORE_HP,
                effect_amount=1,
            ),
        ),
    )
    state.character.inventory.append(relic)
    engine = CairnEngine(seed=1, config=NarrativeConfig(model="", api_key=None, base_url=None))

    outcome = engine.use_item(state, item_id=relic.id, intent="I spend the battery's light.")

    assert relic.cairn.resources[0].current == 1
    assert outcome.cairn is not None
    assert outcome.cairn.resource_deltas[0].resource_label == "Sun charge"
    assert outcome.cairn.resource_deltas[0].reason == CairnResourceDeltaReason.ITEM_USE


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
