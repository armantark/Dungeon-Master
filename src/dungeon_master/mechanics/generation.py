from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from pydantic import Field, ValidationError, model_validator

from dungeon_master.campaign import render_creative_direction
from dungeon_master.cancel import CancellationToken
from dungeon_master.llm.completion import (
    LITELLM_RETRYABLE_ERRORS,
    CompletionFunction,
    CompletionRequest,
    complete_text,
    extract_json_object,
)
from dungeon_master.mechanics.combat import EncounterScalingPolicy
from dungeon_master.mechanics.inventory import ResolvedActor
from dungeon_master.models import (
    CairnAbility,
    CairnCharacterState,
    CairnItemPower,
    CairnItemState,
    CairnItemTag,
    CairnMechanicsSource,
    CairnResourceCost,
    CairnResourcePool,
    CairnResourceRechargePolicy,
    CharacterSheet,
    EncounterInitiator,
    EncounterState,
    EncounterThreatLevel,
    EnemyCombatant,
    GameState,
    InventoryItem,
    StrictModel,
)
from dungeon_master.narrative import NarrativeConfig
from dungeon_master.prompt_fragments import (
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


class GenerationSupport:
    _config: NarrativeConfig
    _completion: CompletionFunction
    _backfill_function: BackfillFunction | None

    if TYPE_CHECKING:

        def _recompute_derived(self, character: CharacterSheet) -> None: ...

        def _require_ready(self, state: GameState) -> None: ...

        def _resolve_actor(self, state: GameState, actor_id: str | None) -> ResolvedActor: ...

        def _has_active_enemies(self, encounter: EncounterState) -> bool: ...

    def ensure_character_state(
        self,
        state: GameState,
        *,
        allow_backfill: bool,
        cancel_token: CancellationToken | None = None,
    ) -> bool:
        character = state.character
        if character.cairn.source == CairnMechanicsSource.UNSET:
            if not allow_backfill:
                return False
            self._backfill_character(state, cancel_token=cancel_token)
            return True

        if (
            character.cairn.source == CairnMechanicsSource.NARRATIVE_BACKFILL
            and character.cairn.backfill_version < CURRENT_BACKFILL_VERSION
            and allow_backfill
        ):
            self._backfill_character(state, cancel_token=cancel_token)
            return True

        self._recompute_derived(character)
        return False

    def acquire_items(
        self,
        state: GameState,
        *,
        text: str,
        actor_id: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> str:
        self._require_ready(state)
        actor = self._resolve_actor(state, actor_id)
        cleaned = text.strip()
        if not cleaned:
            message = "Acquisition text cannot be empty."
            raise ValueError(message)

        generated: GeneratedInventoryAcquisition | None = None
        if self._config.is_usable():
            prompt = self._build_acquisition_prompt(state, cleaned, actor=actor)
            acquisition_profile = self._config.profiles.cairn_acquisition
            request = CompletionRequest(
                model=self._config.model,
                messages=[
                    {"role": "system", "content": CAIRN_ACQUISITION_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=acquisition_profile.temperature,
                max_tokens=acquisition_profile.max_tokens,
                timeout=self._config.timeout_seconds,
                stream=True,
                api_key=self._config.api_key,
                base_url=self._config.base_url,
                reasoning_effort=acquisition_profile.reasoning_effort,
                reasoning=acquisition_profile.reasoning(
                    default_exclude=self._config.exclude_reasoning,
                ),
                extra_headers=self._openrouter_headers(),
                response_format=None,
                cancel_token=cancel_token,
                trace_route="cairn.acquisition",
                trace_profile="cairn_acquisition",
            )
            try:
                payload = self._complete_json(request)
                generated = GeneratedInventoryAcquisition.model_validate_json(
                    extract_json_object(payload),
                )
            except ValueError:
                generated = None

        if generated is None:
            generated = self._fallback_inventory_acquisition(cleaned)

        acquired = self._inventory_items_from_profiles(
            generated.items,
            source=CairnMechanicsSource.EXPLICIT,
        )
        actor.sheet.inventory.extend(acquired)
        self._normalize_newly_equipped_weapons(actor.sheet, acquired)
        self._recompute_derived(actor.sheet)
        return self._inventory_acquisition_summary(acquired, actor=actor)

    def backfill_companion_sheet(
        self,
        state: GameState,
        authored: CharacterSheet,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> CharacterSheet:
        if self._backfill_function is not None:
            draft_state = state.model_copy(deep=True)
            draft_state.character = authored
            sheet = self._backfill_function(draft_state)
            self._recompute_derived(sheet)
            return sheet

        if not self._config.is_usable():
            self._recompute_derived(authored)
            return authored

        draft_state = state.model_copy(deep=True)
        draft_state.character = authored
        prompt = self._build_backfill_prompt(draft_state)
        backfill_profile = self._config.profiles.cairn_backfill
        request = CompletionRequest(
            model=self._config.model,
            messages=[
                {"role": "system", "content": CAIRN_BACKFILL_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=backfill_profile.temperature,
            max_tokens=backfill_profile.max_tokens,
            timeout=self._config.timeout_seconds,
            stream=False,
            api_key=self._config.api_key,
            base_url=self._config.base_url,
            reasoning_effort=backfill_profile.reasoning_effort,
            reasoning=backfill_profile.reasoning(default_exclude=self._config.exclude_reasoning),
            extra_headers=self._openrouter_headers(),
            response_format=None,
            cancel_token=cancel_token,
            trace_route="cairn.companion_backfill",
            trace_profile="cairn_backfill",
        )
        payload = self._complete_json(request)
        generated = GeneratedCairnBackfill.model_validate_json(extract_json_object(payload))
        sheet = self._apply_generated_backfill(authored, generated)
        self._recompute_derived(sheet)
        return sheet

    def _backfill_character(
        self,
        state: GameState,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> None:
        if self._backfill_function is not None:
            state.character = self._backfill_function(state)
            self._recompute_derived(state.character)
            return

        if not self._config.is_usable():
            message = "Cairn backfill requires a configured model."
            raise ValueError(message)

        prompt = self._build_backfill_prompt(state)
        backfill_profile = self._config.profiles.cairn_backfill
        request = CompletionRequest(
            model=self._config.model,
            messages=[
                {"role": "system", "content": CAIRN_BACKFILL_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=backfill_profile.temperature,
            max_tokens=backfill_profile.max_tokens,
            timeout=self._config.timeout_seconds,
            stream=False,
            api_key=self._config.api_key,
            base_url=self._config.base_url,
            reasoning_effort=backfill_profile.reasoning_effort,
            reasoning=backfill_profile.reasoning(default_exclude=self._config.exclude_reasoning),
            extra_headers=self._openrouter_headers(),
            response_format=None,
            cancel_token=cancel_token,
            trace_route="cairn.backfill",
            trace_profile="cairn_backfill",
        )
        payload = self._complete_json(request)
        generated = GeneratedCairnBackfill.model_validate_json(extract_json_object(payload))
        state.character = self._apply_generated_backfill(state.character, generated)
        self._recompute_derived(state.character)

    def _apply_generated_backfill(
        self,
        authored: CharacterSheet,
        generated: GeneratedCairnBackfill,
    ) -> CharacterSheet:
        inventory = self._inventory_items_from_profiles(
            generated.inventory,
            source=CairnMechanicsSource.NARRATIVE_BACKFILL,
            backfill_version=CURRENT_BACKFILL_VERSION,
        )
        return authored.model_copy(
            update={
                "inventory": inventory,
                "cairn": CairnCharacterState(
                    source=CairnMechanicsSource.NARRATIVE_BACKFILL,
                    backfill_version=CURRENT_BACKFILL_VERSION,
                    skills=generated.skills,
                    abilities=generated.abilities,
                    str_score=generated.str_score,
                    dex_score=generated.dex_score,
                    wil_score=generated.wil_score,
                    max_str_score=generated.str_score,
                    max_dex_score=generated.dex_score,
                    max_wil_score=generated.wil_score,
                    hp=generated.max_hp,
                    max_hp=generated.max_hp,
                    armor=0,
                    fatigue=generated.fatigue,
                    deprived=generated.deprived,
                    critically_wounded=generated.critically_wounded,
                    doomed=generated.doomed,
                    paralyzed=generated.paralyzed,
                    delirious=generated.delirious,
                    dead=generated.dead,
                    slots_total=FULL_INVENTORY_SLOTS,
                    backpack_slots=BACKPACK_SLOTS,
                    comfortable_slots=COMFORTABLE_SLOTS,
                    notes=generated.notes,
                ),
            },
            deep=True,
        )

    def _inventory_items_from_profiles(
        self,
        profiles: list[GeneratedCairnItemProfile],
        *,
        source: CairnMechanicsSource,
        backfill_version: int = 0,
    ) -> list[InventoryItem]:
        return [
            InventoryItem(
                name=profile.name,
                details=profile.details,
                cairn=CairnItemState(
                    source=source,
                    backfill_version=backfill_version,
                    tags=profile.tags,
                    slots=profile.slots,
                    weapon_damage_die=profile.weapon_damage_die,
                    armor_bonus=profile.armor_bonus,
                    uses=profile.uses,
                    resources=profile.resources,
                    attack_costs=profile.attack_costs,
                    use_costs=profile.use_costs,
                    equipped=profile.equipped,
                    power=profile.power,
                ),
            )
            for profile in profiles
        ]

    def _normalize_newly_equipped_weapons(
        self,
        character: CharacterSheet,
        acquired: list[InventoryItem],
    ) -> None:
        equipped_weapon = next(
            (
                item
                for item in acquired
                if CairnItemTag.WEAPON in item.cairn.tags and item.cairn.equipped
            ),
            None,
        )
        if equipped_weapon is None:
            return
        for item in character.inventory:
            if CairnItemTag.WEAPON in item.cairn.tags:
                item.cairn.equipped = item.id == equipped_weapon.id

    def _build_acquisition_prompt(
        self,
        state: GameState,
        text: str,
        *,
        actor: ResolvedActor,
    ) -> str:
        return (
            CAIRN_ACQUISITION_USER_PROMPT_TEMPLATE.replace("<<ACQUISITION>>", text)
            .replace("<<CURRENT_SCENE>>", state.current_scene)
            .replace("<<SETTING_NOTES>>", self._prompt_setting_context(state))
            .replace(
                "<<INVENTORY_JSON>>",
                json.dumps(
                    [item.model_dump(mode="json") for item in actor.sheet.inventory],
                    indent=2,
                ),
            )
            .replace(
                "<<CHARACTER_NOTES>>",
                f"Actor: {actor.name}\n{actor.sheet.cairn.notes or '(none)'}",
            )
        )

    def _fallback_inventory_acquisition(self, text: str) -> GeneratedInventoryAcquisition:
        return GeneratedInventoryAcquisition(
            items=[
                GeneratedCairnItemProfile(
                    name="Acquired gear",
                    details=f"Taken during play: {text}",
                    tags=[CairnItemTag.UTILITY],
                    slots=1,
                    weapon_damage_die=None,
                    armor_bonus=0,
                    uses=None,
                    equipped=False,
                ),
            ],
        )

    def _inventory_acquisition_summary(
        self,
        acquired: list[InventoryItem],
        *,
        actor: ResolvedActor,
    ) -> str:
        names = ", ".join(item.name for item in acquired)
        equipped = [
            item.name
            for item in acquired
            if item.cairn.equipped
            and (
                CairnItemTag.WEAPON in item.cairn.tags
                or CairnItemTag.ARMOR in item.cairn.tags
                or CairnItemTag.SHIELD in item.cairn.tags
            )
        ]
        actor_prefix = "" if actor.is_player else f"{actor.name} acquired "
        if equipped:
            equipped_names = ", ".join(equipped)
            if actor.is_player:
                return f"Acquired {names}. Readied: {equipped_names}."
            return f"{actor_prefix}{names}. Readied: {equipped_names}."
        if actor.is_player:
            return f"Acquired {names}."
        return f"{actor_prefix}{names}."

    def _build_backfill_prompt(self, state: GameState) -> str:
        return (
            CAIRN_BACKFILL_USER_PROMPT_TEMPLATE.replace(
                "<<CHARACTER_JSON>>",
                state.character.model_dump_json(indent=2),
            )
            .replace("<<CAMPAIGN_SEED>>", render_creative_direction(state.campaign_seed))
            .replace("<<CURRENT_SCENE>>", state.current_scene)
            .replace("<<SETTING_NOTES>>", self._prompt_setting_context(state))
            .replace(
                "<<THREAD_TITLES>>", ", ".join(thread.title for thread in state.threads) or "(none)"
            )
            .replace(
                "<<NPC_NAMES>>",
                ", ".join(npc.display_label() for npc in state.npcs) or "(none)",
            )
        )

    def _complete_json(self, request: CompletionRequest) -> str:
        last_error: Exception | None = None
        for attempt in range(self._config.max_retries + 1):
            try:
                completed = complete_text(request, self._completion)
                content_json = completed.content
                if not content_json:
                    _raise_empty_backfill_content_error()
            except (
                *LITELLM_RETRYABLE_ERRORS,
                ValidationError,
                json.JSONDecodeError,
                EmptyBackfillContentError,
                ValueError,
            ) as exc:
                last_error = exc
                if attempt < self._config.max_retries:
                    time.sleep(0.4 * (attempt + 1))
            else:
                return content_json
        message = str(last_error) if last_error else "Cairn backfill failed."
        raise ValueError(message)

    def _openrouter_headers(self) -> dict[str, str] | None:
        if not self._config.model.startswith("openrouter/"):
            return None
        headers: dict[str, str] = {}
        if self._config.site_url is not None:
            headers["HTTP-Referer"] = self._config.site_url
        if self._config.app_name is not None:
            headers["X-Title"] = self._config.app_name
        return headers or None

    def _ensure_encounter(  # noqa: PLR0913
        self,
        state: GameState,
        *,
        player_input: str,
        target_name: str,
        fallback_target_armor: int,
        initiator: EncounterInitiator,
        cancel_token: CancellationToken | None = None,
    ) -> EncounterState:
        encounter = state.encounter
        if encounter.active and self._has_active_enemies(encounter):
            return encounter

        state.encounter = self._seed_encounter(
            state,
            player_input=player_input,
            target_name=target_name,
            fallback_target_armor=fallback_target_armor,
            initiator=initiator,
            cancel_token=cancel_token,
        )
        return state.encounter

    def _seed_encounter(  # noqa: PLR0913
        self,
        state: GameState,
        *,
        player_input: str,
        target_name: str,
        fallback_target_armor: int,
        initiator: EncounterInitiator,
        cancel_token: CancellationToken | None = None,
    ) -> EncounterState:
        generated: GeneratedEncounterSeed | None = None
        if self._config.is_usable():
            prompt = self._build_encounter_prompt(
                state,
                player_input=player_input,
                target_name=target_name,
                initiator=initiator,
            )
            encounter_profile = self._config.profiles.cairn_encounter_seed
            request = CompletionRequest(
                model=self._config.model,
                messages=[
                    {"role": "system", "content": CAIRN_ENCOUNTER_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=encounter_profile.temperature,
                max_tokens=encounter_profile.max_tokens,
                timeout=self._config.timeout_seconds,
                stream=True,
                api_key=self._config.api_key,
                base_url=self._config.base_url,
                reasoning_effort=encounter_profile.reasoning_effort,
                # Cap reasoning to keep encounter seeding under ~30s wallclock.
                # The fallback seed (`_fallback_encounter_seed`) is a perfectly
                # serviceable single-foe encounter, so we'd rather time out
                # the LLM than make the player wait minutes for richer stats.
                # We keep this as a bounded budget profile for the same reason.
                reasoning=encounter_profile.reasoning(
                    default_exclude=self._config.exclude_reasoning
                ),
                extra_headers=self._openrouter_headers(),
                response_format=None,
                cancel_token=cancel_token,
                trace_route="cairn.encounter_seed",
                trace_profile="cairn_encounter_seed",
            )
            try:
                payload = self._complete_json(request)
                generated = GeneratedEncounterSeed.model_validate_json(extract_json_object(payload))
            except ValueError:
                generated = None

        policy = EncounterScalingPolicy.for_danger(state.campaign_seed.danger_profile)
        if generated is None:
            generated = self._fallback_encounter_seed(
                target_name=target_name,
                target_armor=fallback_target_armor,
            )
        generated = self._scaled_encounter_seed(generated, policy)

        return EncounterState(
            active=True,
            round_number=1,
            first_round_dex_gate_pending=True,
            initiator=initiator,
            combatants=[
                EnemyCombatant(
                    name=combatant.name,
                    description=combatant.description,
                    hp=combatant.hp,
                    max_hp=combatant.hp,
                    str_score=combatant.str_score,
                    dex_score=combatant.dex_score,
                    wil_score=combatant.wil_score,
                    armor=combatant.armor,
                    weapon_name=combatant.weapon_name,
                    weapon_damage_die=combatant.weapon_damage_die,
                    threat_level=combatant.threat_level,
                    weakness=combatant.weakness,
                    tactics=combatant.tactics,
                    leader=combatant.leader,
                    notes=combatant.notes,
                )
                for combatant in generated.combatants
            ],
            notes=generated.notes,
        )

    def _build_encounter_prompt(
        self,
        state: GameState,
        *,
        player_input: str,
        target_name: str,
        initiator: EncounterInitiator,
    ) -> str:
        return (
            CAIRN_ENCOUNTER_USER_PROMPT_TEMPLATE.replace("<<CURRENT_SCENE>>", state.current_scene)
            .replace("<<SETTING_NOTES>>", self._prompt_setting_context(state))
            .replace(
                "<<NPC_NAMES>>",
                ", ".join(npc.display_label() for npc in state.npcs) or "(none)",
            )
            .replace("<<CHARACTER_JSON>>", state.character.model_dump_json(indent=2))
            .replace("<<PLAYER_INPUT>>", player_input)
            .replace("<<ENCOUNTER_INITIATOR>>", initiator.value)
            .replace("<<TARGET_NAME>>", target_name)
        )

    def _prompt_setting_context(self, state: GameState) -> str:
        if not state.directives.has_content():
            return state.setting_notes
        directive_lines: list[str] = []
        if state.directives.world_guidance.strip():
            directive_lines.append(f"World guidance: {state.directives.world_guidance.strip()}")
        if state.directives.play_guidance.strip():
            directive_lines.append(f"Play guidance: {state.directives.play_guidance.strip()}")
        return state.setting_notes + "\n\nCampaign directives:\n" + "\n".join(directive_lines)

    def _fallback_encounter_seed(
        self,
        *,
        target_name: str,
        target_armor: int,
    ) -> GeneratedEncounterSeed:
        return GeneratedEncounterSeed(
            notes=(
                "Fallback encounter seed created because no combat seed model response was "
                "available."
            ),
            combatants=[
                GeneratedEncounterCombatant(
                    name=target_name.strip() or "Hostile foe",
                    description="A hostile figure drawn into the fight by the current scene.",
                    hp=3,
                    str_score=10,
                    dex_score=10,
                    wil_score=8,
                    armor=target_armor,
                    weapon_name="Weathered weapon",
                    weapon_damage_die=6,
                    threat_level=EncounterThreatLevel.ORDINARY,
                    leader=True,
                    notes="Fallback combatant.",
                ),
            ],
        )

    def _scaled_encounter_seed(
        self,
        seed: GeneratedEncounterSeed,
        policy: EncounterScalingPolicy,
    ) -> GeneratedEncounterSeed:
        combatants = [
            self._scaled_combatant(combatant, policy)
            for combatant in seed.combatants[: policy.max_combatants]
        ]
        if not any(combatant.leader for combatant in combatants):
            first = combatants[0]
            combatants[0] = first.model_copy(update={"leader": True})
        return GeneratedEncounterSeed(notes=seed.notes, combatants=combatants)

    def _scaled_combatant(
        self,
        combatant: GeneratedEncounterCombatant,
        policy: EncounterScalingPolicy,
    ) -> GeneratedEncounterCombatant:
        threat_level = combatant.threat_level
        hp = max(1, min(combatant.hp, policy.hp_cap_for(threat_level)))
        armor = max(0, min(combatant.armor, policy.armor_cap_for(threat_level)))
        die = combatant.weapon_damage_die
        if die not in ALLOWED_WEAPON_DICE:
            die = min(ALLOWED_WEAPON_DICE, key=lambda side: abs(side - die))
        return combatant.model_copy(
            update={
                "hp": hp,
                "armor": armor,
                "weapon_damage_die": die,
            },
        )
