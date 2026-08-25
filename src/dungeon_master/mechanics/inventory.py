from __future__ import annotations

from dungeon_master.models import (
    CairnCharacterState,
    CairnItemTag,
    CharacterSheet,
    InventoryItem,
)

MAX_ARMOR = 3
FOOD_DEPRIVED_WATCHES = 3
SLEEP_DEPRIVED_WATCHES = 6


def transfer_item(
    source: CharacterSheet,
    target: CharacterSheet,
    *,
    item_id: str,
) -> InventoryItem:
    item = next((candidate for candidate in source.inventory if candidate.id == item_id), None)
    if item is None:
        message = f"Unknown inventory item: {item_id}"
        raise ValueError(message)

    source.inventory = [candidate for candidate in source.inventory if candidate.id != item_id]
    item.cairn.equipped = False
    target.inventory = [*target.inventory, item]
    repair_derived_state(source)
    repair_derived_state(target)
    return item


def repair_derived_state(character: CharacterSheet) -> None:
    cairn = character.cairn
    weapons = [
        item for item in character.inventory if CairnItemTag.WEAPON in item.cairn.tags
    ]
    equipped_weapons = [item for item in weapons if item.cairn.equipped]
    primary_weapon = next(
        (
            item
            for item in equipped_weapons
            if item.id == cairn.primary_weapon_item_id
        ),
        equipped_weapons[0] if equipped_weapons else (weapons[0] if weapons else None),
    )

    for weapon in weapons:
        weapon.cairn.equipped = primary_weapon is not None and weapon.id == primary_weapon.id
    cairn.primary_weapon_item_id = primary_weapon.id if primary_weapon is not None else None

    cairn.armor = min(
        MAX_ARMOR,
        sum(
            item.cairn.armor_bonus
            for item in character.inventory
            if item.cairn.equipped
            and (
                CairnItemTag.ARMOR in item.cairn.tags
                or CairnItemTag.SHIELD in item.cairn.tags
            )
        ),
    )
    cairn.slots_used = cairn.fatigue + sum(
        item.cairn.slots for item in character.inventory
    )
    cairn.overloaded = cairn.slots_used >= cairn.slots_total
    sync_survival_flags(cairn)
    if cairn.overloaded:
        cairn.hp = 0
    cairn.paralyzed = cairn.dex_score == 0
    cairn.delirious = cairn.wil_score == 0
    cairn.dead = cairn.dead or cairn.str_score == 0


def sync_survival_flags(cairn: CairnCharacterState) -> None:
    cairn.survival.food_deprived = (
        cairn.survival.watches_since_meal >= FOOD_DEPRIVED_WATCHES
    )
    cairn.survival.sleep_deprived = (
        cairn.survival.watches_since_sleep >= SLEEP_DEPRIVED_WATCHES
    )
    cairn.deprived = (
        cairn.survival.food_deprived
        or cairn.survival.sleep_deprived
        or cairn.survival.other_deprived
    )
