from __future__ import annotations

from collections.abc import Callable

from pydantic import Field, model_validator

from dungeon_master.domain.models import (
    CairnAbility,
    CairnItemPower,
    CairnItemTag,
    CairnResourceCost,
    CairnResourcePool,
    CairnResourceRechargePolicy,
    CharacterSheet,
    EncounterThreatLevel,
    GameState,
    StrictModel,
)
from dungeon_master.llm.prompt_fragments import (
    CAIRN_ALLOWED_ENUMS,
    CAIRN_ITEM_SEMANTICS,
    JSON_ONLY,
    SEED_AUTHORITY,
)

D6_SIDES = 6
D4_SIDES = 4
D8_SIDES = 8
D10_SIDES = 10
D12_SIDES = 12
FULL_INVENTORY_SLOTS = 10
BACKPACK_SLOTS = 6
COMFORTABLE_SLOTS = 5
CURRENT_BACKFILL_VERSION = 4
ALLOWED_WEAPON_DICE: tuple[int, ...] = (D4_SIDES, D6_SIDES, D8_SIDES, D10_SIDES, D12_SIDES)

CAIRN_BACKFILL_SYSTEM_PROMPT = f"""You convert a fiction-first character into a
Cairn-inspired backend mechanics record.

{JSON_ONLY}

Setting authority:
- {SEED_AUTHORITY}
- The campaign seed supplied in the user prompt is authoritative.
- If the seed is mundane or modern, translate Cairn mechanics into lightweight
  ordinary capability/resource abstractions that fit the supplied setting.

Rules philosophy:
- This project uses Cairn-style structured play: STR, DEX, WIL, HP, armor,
  burden/slots, practical inventory, and deterministic item semantics.
- `skills` and `abilities` should be short textual specialties or permissions,
  not bonuses.
- Biography details should primarily affect stats, condition, skills, abilities,
  and notes.
- Inventory should be a practical starting bundle appropriate to the
  character profile and campaign seed. Do not force weapons, armor, relics,
  survival gear, or occult items into a mundane/non-combat seed.
- When the authored character is an ordinary person rather than an abstract
  adventuring kit, include the clothing, accessories, and immediate personal
  carry that define how they actually show up in play, as long as those items
  are concrete and useful enough to track.
- If the authored character context names concrete visible gear already
  established in play, especially carried or wielded weapons, preserve that
  gear in the structured inventory unless the context says it was lost,
  traded, or discarded.
- Keep the inventory lean and believable. Most items should be useful in play,
  not symbolic transcripts of the backstory.
- {CAIRN_ITEM_SEMANTICS}
  Examples:
  bow + quiver: quiver resource `{{label:"Arrows", kind:"ammo", current:12}}`
  and bow attack cost `{{label:"Arrows", kind:"ammo", amount:1,
  draw_policy:"actor_inventory"}}`; repeating crossbow with internal magazine:
  weapon resource `{{label:"Bolts", kind:"ammo", current:5, max:5}}` and self
  attack cost; sunlight laser: weapon resource `{{label:"Sun charge",
  kind:"charge", current:2, max:2, recharge_policy:"in_sunlight"}}`.
- Allowed resource recharge policies are: none, per_turn, per_watch, per_day,
  on_rest, in_sunlight, manual_condition. Do not emit per_rest.
- If an item is a spellbook, scroll, relic, or holy relic, include a bounded
  `power` object. Keep powers item-bound, limited, and costly when appropriate;
  do not invent generic blessing/buff states.

Mechanical constraints:
- `str_score`, `dex_score`, `wil_score` are each 3-18.
- `max_hp` is 1-6.
- `armor` is derived later in code; set armor bonuses on items instead.
- `slots_total` is always 10, `backpack_slots` is 6, `comfortable_slots` is 5.
- `fatigue` normally starts at 0 unless the condition clearly implies it.
- `deprived`, `critically_wounded`, `doomed`, `paralyzed`, `delirious`, and
  `dead` should default false unless the condition clearly requires otherwise.
- Favor at least one equipped primary weapon if the character plausibly has one.
- `weapon_damage_die` must be null for non-weapon items. For weapon items, use
  one of 4, 6, 8, 10, or 12; do not use 0 as a placeholder.
"""

CAIRN_BACKFILL_USER_PROMPT_TEMPLATE = """Return JSON with this shape:
{
  "skills": ["short skill phrase"],
  "abilities": ["short ability phrase"],
  "str_score": 10,
  "dex_score": 10,
  "wil_score": 10,
  "max_hp": 3,
  "fatigue": 0,
  "deprived": false,
  "critically_wounded": false,
  "doomed": false,
  "paralyzed": false,
  "delirious": false,
  "dead": false,
  "notes": "1-2 sentences explaining the build and loadout choices",
  "inventory": [
    {
      "name": "practical item name",
      "details": "how it helps in play and why this character carries it",
      "tags": ["petty", "weapon", "holy"],
      "slots": 1,
      "weapon_damage_die": 6,
      "armor_bonus": 0,
      "uses": null,
      "resources": [],
      "attack_costs": [],
      "use_costs": [],
      "equipped": true,
      "power": {
        "kind": "none",
        "name": "",
        "summary": "",
        "effect": "none",
        "effect_amount": 1,
        "effect_ability": null,
        "clears_condition": null,
        "recharge_condition": "",
        "requires_wil_save_in_danger": false,
        "adds_fatigue": false,
        "consumed_on_use": false
      }
    }
  ]
}}

{CAIRN_ALLOWED_ENUMS}
Inventory rule: `weapon_damage_die` is null for every non-weapon item. If `tags`
includes `weapon`, `weapon_damage_die` must be 4, 6, 8, 10, or 12. Never emit 0.

The authored character is:
<<CHARACTER_JSON>>

The generated opening state around that character is:
Campaign seed:
<<CAMPAIGN_SEED>>

Current scene: <<CURRENT_SCENE>>
Setting notes: <<SETTING_NOTES>>
Threads: <<THREAD_TITLES>>
NPCs: <<NPC_NAMES>>

Important instruction:
- You may replace the existing authored inventory with a better Cairn-style
  practical starting bundle if the authored items are too symbolic or too
  on-the-nose.
- Preserve concrete carried gear named in the authored character context,
  especially weapons or tools already surfaced to the player.
- Preserve at most one or two iconic biography-derived items.
- Put most biography influence into stats, skills, abilities, condition,
  and notes rather than inventory objects.
"""

CAIRN_ENCOUNTER_SYSTEM_PROMPT = f"""You convert a scene into a concrete
Cairn-inspired encounter only when the supplied scene and trigger actually
support one.

{JSON_ONLY}

Rules:
- Only create hostile combatants already present in, or directly implied by,
  the supplied scene + player action.
- Prefer 1-4 foes.
- Use Cairn-scale stats: HP, STR, DEX, WIL, armor, and a weapon damage die.
- Use threat levels explicitly: `ordinary` foes are typical humans/minor
  creatures around 3 HP; `hardier` foes are elites or tougher creatures around
  6 HP; `serious` foes are clearly telegraphed monsters or major threats at
  10+ HP.
- Armor must be 0-3.
- Weapon damage dice must be 4, 6, 8, 10, or 12.
- Add `weakness` or `tactics` only when the immediate fiction makes them clear.
- If multiple combatants appear, mark at most one as `leader`.
- Keep the encounter grounded and playable; do not invent a boss fight out
  of a minor scuffle.
- Obey the supplied campaign seed and setting context.
"""

CAIRN_ENCOUNTER_USER_PROMPT_TEMPLATE = """Return JSON with this shape:
{
  "notes": "1-2 sentences explaining why these foes are present",
  "combatants": [
    {
      "name": "foe name",
      "description": "brief physical/immediate-fiction read",
      "hp": 5,
      "str_score": 12,
      "dex_score": 10,
      "wil_score": 8,
      "armor": 1,
      "weapon_name": "hatchet",
      "weapon_damage_die": 6,
      "threat_level": "ordinary",
      "weakness": "optional fiction-grounded vulnerability",
      "tactics": "optional immediate combat tactic",
      "leader": false,
      "notes": "optional short note"
    }
  ]
}

Current scene:
<<CURRENT_SCENE>>

Setting notes:
<<SETTING_NOTES>>

Known NPCs:
<<NPC_NAMES>>

Character JSON:
<<CHARACTER_JSON>>

Combat trigger text:
<<PLAYER_INPUT>>

Encounter initiator:
<<ENCOUNTER_INITIATOR>>

Named target, if any:
<<TARGET_NAME>>
"""

CAIRN_ACQUISITION_SYSTEM_PROMPT = f"""You convert an active-play acquisition into
canonical Cairn-style carried items.

{JSON_ONLY}

Rules:
- Only author items explicitly present in, or directly implied by, the
  acquisition text. Do not invent bonus loot, currency systems, or merchants.
- Keep the result practical and playable. Prefer 1-3 items; use 4 only for a
  small coherent bundle.
- If the text implies money, arrows, rations, herbs, or similar fungible
  goods, represent them as one bundle item rather than inventing a quantity
  field.
- {CAIRN_ITEM_SEMANTICS}
- If the acquired item is a spellbook, scroll, relic, or holy relic, include a
  bounded `power` object. Relics do not add Fatigue by default; spellbooks do;
  scrolls are consumed; holy relics should stay subtle and item-bound.
- `equipped` should usually be false unless the text clearly says the player
  immediately readies, dons, or straps on the item.
- Preserve the player's meaning; do not rewrite a humble find into treasure.
"""

CAIRN_ACQUISITION_USER_PROMPT_TEMPLATE = f"""Return JSON with this shape:
{{
  "items": [
    {{
      "name": "practical acquired item name",
      "details": "how this item exists in the fiction and helps in play",
      "tags": ["petty", "weapon", "utility"],
      "slots": 1,
      "weapon_damage_die": null,
      "armor_bonus": 0,
      "uses": null,
      "resources": [],
      "attack_costs": [],
      "use_costs": [],
      "equipped": false,
      "power": {{
        "kind": "none",
        "name": "",
        "summary": "",
        "effect": "none",
        "effect_amount": 1,
        "effect_ability": null,
        "clears_condition": null,
        "recharge_condition": "",
        "requires_wil_save_in_danger": false,
        "adds_fatigue": false,
        "consumed_on_use": false
      }}
    }}
  ]
}}

{CAIRN_ALLOWED_ENUMS}

Acquisition text:
<<ACQUISITION>>

Current scene:
<<CURRENT_SCENE>>

Setting notes:
<<SETTING_NOTES>>

Current inventory:
<<INVENTORY_JSON>>

Character build notes:
<<CHARACTER_NOTES>>
"""


class GeneratedCairnItemProfile(StrictModel):
    name: str = Field(min_length=1)
    details: str = Field(min_length=1)
    tags: list[CairnItemTag] = Field(default_factory=list)
    slots: int = Field(ge=0, le=10)
    weapon_damage_die: int | None = Field(default=None, ge=4, le=12)
    armor_bonus: int = Field(default=0, ge=0, le=3)
    uses: int | None = Field(default=None, ge=1)
    resources: list[CairnResourcePool] = Field(default_factory=list)
    attack_costs: list[CairnResourceCost] = Field(default_factory=list)
    use_costs: list[CairnResourceCost] = Field(default_factory=list)
    equipped: bool = False
    power: CairnItemPower = Field(default_factory=CairnItemPower)

    @model_validator(mode="before")
    @classmethod
    def normalize_generated_item_payload(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        migrated = dict(data)
        migrated["tags"] = _normalize_generated_item_tags(migrated.get("tags", []))
        if "power" in migrated:
            migrated["power"] = _normalize_generated_item_power(migrated.get("power"))
        for field_name in ("resources", "attack_costs", "use_costs"):
            migrated[field_name] = _normalize_generated_resource_entries(
                migrated.get(field_name, []),
            )
        raw_tags = migrated.get("tags", [])
        tags = {
            tag.value if isinstance(tag, CairnItemTag) else str(tag)
            for tag in raw_tags
            if isinstance(tag, CairnItemTag | str)
        }
        if CairnItemTag.BULKY.value in tags:
            migrated["slots"] = 2
        elif CairnItemTag.PETTY.value in tags:
            migrated["slots"] = 0
        has_weapon_tag = CairnItemTag.WEAPON.value in tags
        raw_die = migrated.get("weapon_damage_die")
        if raw_die in (0, "0", ""):
            migrated["weapon_damage_die"] = D6_SIDES if has_weapon_tag else None
        elif has_weapon_tag and raw_die is None:
            migrated["weapon_damage_die"] = D6_SIDES
        elif not has_weapon_tag:
            migrated["weapon_damage_die"] = None
        return migrated


class GeneratedCairnBackfill(StrictModel):
    skills: list[str] = Field(default_factory=list)
    abilities: list[str] = Field(default_factory=list)
    str_score: int = Field(ge=3, le=18)
    dex_score: int = Field(ge=3, le=18)
    wil_score: int = Field(ge=3, le=18)
    max_hp: int = Field(ge=1, le=6)
    fatigue: int = Field(default=0, ge=0)
    deprived: bool = False
    critically_wounded: bool = False
    doomed: bool = False
    paralyzed: bool = False
    delirious: bool = False
    dead: bool = False
    notes: str = Field(default="")
    inventory: list[GeneratedCairnItemProfile] = Field(min_length=2, max_length=8)


class GeneratedEncounterCombatant(StrictModel):
    name: str = Field(min_length=1)
    description: str = ""
    hp: int = Field(ge=1, le=12)
    str_score: int = Field(ge=3, le=18)
    dex_score: int = Field(ge=3, le=18)
    wil_score: int = Field(ge=3, le=18)
    armor: int = Field(default=0, ge=0, le=3)
    weapon_name: str = Field(min_length=1)
    weapon_damage_die: int = Field(ge=4, le=12)
    threat_level: EncounterThreatLevel = EncounterThreatLevel.ORDINARY
    weakness: str = ""
    tactics: str = ""
    leader: bool = False
    notes: str = ""

    @model_validator(mode="after")
    def normalize_weapon_die(self) -> GeneratedEncounterCombatant:
        if self.weapon_damage_die in ALLOWED_WEAPON_DICE:
            return self
        nearest = min(ALLOWED_WEAPON_DICE, key=lambda side: abs(side - self.weapon_damage_die))
        object.__setattr__(self, "weapon_damage_die", nearest)
        return self


class GeneratedEncounterSeed(StrictModel):
    notes: str = ""
    combatants: list[GeneratedEncounterCombatant] = Field(min_length=1, max_length=4)


class GeneratedInventoryAcquisition(StrictModel):
    items: list[GeneratedCairnItemProfile] = Field(min_length=1, max_length=4)


BackfillFunction = Callable[[GameState], CharacterSheet]


class EmptyBackfillContentError(ValueError):
    pass


def _raise_empty_backfill_content_error() -> None:
    message = "Cairn backfill returned empty content."
    raise EmptyBackfillContentError(message)


def _normalize_generated_item_tags(raw_tags: object) -> list[object]:
    if not isinstance(raw_tags, list):
        return []
    normalized: list[object] = []
    for raw_tag in raw_tags:
        if isinstance(raw_tag, CairnItemTag):
            candidate = raw_tag.value
        elif isinstance(raw_tag, str):
            candidate = raw_tag.strip().lower().replace("-", "_").replace(" ", "_")
        else:
            continue
        if candidate == "holy_relic":
            normalized.extend([CairnItemTag.HOLY.value, CairnItemTag.RELIC.value])
            continue
        if candidate in {tag.value for tag in CairnItemTag}:
            normalized.append(candidate)
    return _dedupe_preserve_order(normalized)


def _normalize_generated_item_power(raw_power: object) -> object:
    if raw_power is None:
        return raw_power
    if not isinstance(raw_power, dict):
        return raw_power
    migrated = dict(raw_power)
    raw_ability = migrated.get("effect_ability")
    if isinstance(raw_ability, str):
        cleaned_ability = raw_ability.strip().upper()
        if cleaned_ability in {ability.value for ability in CairnAbility}:
            migrated["effect_ability"] = cleaned_ability
    for field_name in ("kind", "effect", "clears_condition"):
        raw_value = migrated.get(field_name)
        if isinstance(raw_value, str):
            migrated[field_name] = raw_value.strip().lower().replace("-", "_").replace(" ", "_")
    return migrated


def _normalize_generated_resource_entries(raw_entries: object) -> list[object]:
    if not isinstance(raw_entries, list):
        return []
    normalized: list[object] = []
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, dict):
            normalized.append(raw_entry)
            continue
        migrated = dict(raw_entry)
        for field_name in ("kind", "draw_policy", "recharge_policy"):
            raw_value = migrated.get(field_name)
            if isinstance(raw_value, str):
                migrated[field_name] = _normalize_generated_resource_enum(raw_value)
        normalized.append(migrated)
    return normalized


def _normalize_generated_resource_enum(raw_value: str) -> str:
    cleaned = raw_value.strip().lower().replace("-", "_").replace(" ", "_")
    if cleaned in {"per_rest", "per_full_rest", "full_rest", "rest"}:
        return CairnResourceRechargePolicy.ON_REST.value
    return cleaned


def _dedupe_preserve_order(values: list[object]) -> list[object]:
    seen: set[object] = set()
    deduped: list[object] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped
