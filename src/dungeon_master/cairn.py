from __future__ import annotations

import json
import random
import time
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import Field, ValidationError, model_validator

from dungeon_master.cancel import CancellationToken
from dungeon_master.models import (
    AttackStance,
    CairnAbility,
    CairnCharacterState,
    CairnConditionKey,
    CairnDayPhase,
    CairnItemEffectKind,
    CairnItemPower,
    CairnItemPowerKind,
    CairnItemState,
    CairnItemTag,
    CairnMechanicsSource,
    CairnResolution,
    CairnRestKind,
    CairnSurvivalAction,
    CairnTimeAdvance,
    CampaignDangerProfile,
    CharacterSheet,
    CoordinatedAttackParticipant,
    EncounterAdvantagePayoff,
    EncounterEndReason,
    EncounterInitiator,
    EncounterState,
    EncounterThreatLevel,
    EnemyCombatant,
    GameState,
    InventoryItem,
    OracleKind,
    OracleOutcome,
    PendingEncounterAdvantage,
    RetreatOutcome,
    Roll,
    StrictModel,
)
from dungeon_master.narrative import (
    LITELLM_RETRYABLE_ERRORS,
    CompletionFunction,
    CompletionRequest,
    NarrativeConfig,
    _completion,
    complete_text,
    extract_json_object,
)

D20_SIDES = 20
D6_SIDES = 6
D4_SIDES = 4
D8_SIDES = 8
D10_SIDES = 10
D12_SIDES = 12
MAX_ARMOR = 3
FULL_INVENTORY_SLOTS = 10
BACKPACK_SLOTS = 6
COMFORTABLE_SLOTS = 5
CURRENT_BACKFILL_VERSION = 4
STR_BRANCH_MAX = 2
DEX_BRANCH_MAX = 4
WATCHES_PER_DAY = 6
FOOD_WARNING_WATCHES = 2
FOOD_DEPRIVED_WATCHES = 3
SLEEP_WARNING_WATCHES = 4
SLEEP_DEPRIVED_WATCHES = 6
ALLOWED_WEAPON_DICE: tuple[int, ...] = (D4_SIDES, D6_SIDES, D8_SIDES, D10_SIDES, D12_SIDES)

LASTING_SCAR_LOCATIONS: tuple[str, ...] = (
    "Neck",
    "Hands",
    "Eye",
    "Chest",
    "Legs",
    "Ear",
)


@dataclass(frozen=True)
class AttackActor:
    id: str | None
    name: str
    sheet: CharacterSheet
    weapon_item_id: str | None = None
    stance: AttackStance = AttackStance.NORMAL


@dataclass(frozen=True)
class EncounterScalingPolicy:
    danger_profile: CampaignDangerProfile
    max_combatants: int
    ordinary_hp_max: int
    hardier_hp_max: int
    serious_hp_max: int
    ordinary_armor_max: int
    hardier_armor_max: int
    serious_armor_max: int

    def hp_cap_for(self, threat_level: EncounterThreatLevel) -> int:
        if threat_level == EncounterThreatLevel.SERIOUS:
            return self.serious_hp_max
        if threat_level == EncounterThreatLevel.HARDIER:
            return self.hardier_hp_max
        return self.ordinary_hp_max

    def armor_cap_for(self, threat_level: EncounterThreatLevel) -> int:
        if threat_level == EncounterThreatLevel.SERIOUS:
            return self.serious_armor_max
        if threat_level == EncounterThreatLevel.HARDIER:
            return self.hardier_armor_max
        return self.ordinary_armor_max

    @classmethod
    def for_danger(cls, danger_profile: CampaignDangerProfile) -> EncounterScalingPolicy:
        if danger_profile == CampaignDangerProfile.STORY:
            return cls(
                danger_profile=danger_profile,
                max_combatants=2,
                ordinary_hp_max=3,
                hardier_hp_max=5,
                serious_hp_max=8,
                ordinary_armor_max=1,
                hardier_armor_max=2,
                serious_armor_max=3,
            )
        if danger_profile == CampaignDangerProfile.HARSH:
            return cls(
                danger_profile=danger_profile,
                max_combatants=4,
                ordinary_hp_max=4,
                hardier_hp_max=7,
                serious_hp_max=12,
                ordinary_armor_max=2,
                hardier_armor_max=3,
                serious_armor_max=3,
            )
        if danger_profile == CampaignDangerProfile.LETHAL:
            return cls(
                danger_profile=danger_profile,
                max_combatants=4,
                ordinary_hp_max=5,
                hardier_hp_max=8,
                serious_hp_max=12,
                ordinary_armor_max=2,
                hardier_armor_max=3,
                serious_armor_max=3,
            )
        return cls(
            danger_profile=danger_profile,
            max_combatants=4,
            ordinary_hp_max=3,
            hardier_hp_max=6,
            serious_hp_max=12,
            ordinary_armor_max=1,
            hardier_armor_max=2,
            serious_armor_max=3,
        )
BROKEN_LIMB_PARTS: tuple[str, ...] = (
    "Leg",
    "Leg",
    "Arm",
    "Arm",
    "Rib",
    "Skull",
)

CAIRN_BACKFILL_SYSTEM_PROMPT = """You convert a fiction-first dark-fantasy character into a
Cairn 2e-inspired backend mechanics record.

Return only valid JSON.

Rules philosophy:
- This project uses Cairn-style structured play: STR, DEX, WIL, HP, armor,
  burden/slots, practical inventory, and deterministic item semantics.
- `skills` and `abilities` should be short textual specialties or permissions,
  not bonuses.
- Biography and body-horror details should primarily affect stats, condition,
  skills, abilities, and notes.
- Inventory should be a practical starting bundle appropriate to the
  character's profile. Prefer a weapon, practical clothing/armor, light,
  supplies, tools, and at most one or two signature biography-derived items.
- If the authored character context names concrete visible gear already
  established in play, especially carried or wielded weapons, preserve that
  gear in the structured inventory unless the context says it was lost,
  traded, or discarded.
- Keep the inventory lean and believable. Most items should be useful in play,
  not symbolic transcripts of the backstory.
- Use Cairn-style item semantics: petty vs bulky, armor bonus, weapon die,
  uses, equipped state.
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
}

Allowed tags: petty, bulky, weapon, ranged, armor, shield, tool, light, relic, holy, healing, consumable, supplies, magic, utility
Allowed power kinds: none, spellbook, scroll, relic, holy_relic
Allowed effects: none, restore_hp, restore_attribute, clear_condition, enhance_attack, impair_target, force_save, reveal_sign, create_safe_passage, ward_or_pacify, extraordinary_aid, resurrect
Allowed clear conditions: deprived, critically_wounded, doomed, paralyzed, delirious
Inventory rule: `weapon_damage_die` is null for every non-weapon item. If `tags`
includes `weapon`, `weapon_damage_die` must be 4, 6, 8, 10, or 12. Never emit 0.

The authored character is:
<<CHARACTER_JSON>>

The generated opening state around that character is:
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

CAIRN_ENCOUNTER_SYSTEM_PROMPT = """You convert a dark-fantasy scene into a concrete
Cairn 2e combat encounter.

Return only valid JSON.

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

CAIRN_ACQUISITION_SYSTEM_PROMPT = """You convert an active-play acquisition into
canonical Cairn-style carried items.

Return only valid JSON.

Rules:
- Only author items explicitly present in, or directly implied by, the
  acquisition text. Do not invent bonus loot, currency systems, or merchants.
- Keep the result practical and playable. Prefer 1-3 items; use 4 only for a
  small coherent bundle.
- If the text implies money, arrows, rations, herbs, or similar fungible
  goods, represent them as one bundle item rather than inventing a quantity
  field.
- Use Cairn-style item semantics: petty vs bulky, armor bonus, weapon die,
  uses, equipped state.
- If the acquired item is a spellbook, scroll, relic, or holy relic, include a
  bounded `power` object. Relics do not add Fatigue by default; spellbooks do;
  scrolls are consumed; holy relics should stay subtle and item-bound.
- `equipped` should usually be false unless the text clearly says the player
  immediately readies, dons, or straps on the item.
- Preserve the player's meaning; do not rewrite a humble find into treasure.
"""

CAIRN_ACQUISITION_USER_PROMPT_TEMPLATE = """Return JSON with this shape:
{
  "items": [
    {
      "name": "practical acquired item name",
      "details": "how this item exists in the fiction and helps in play",
      "tags": ["petty", "weapon", "utility"],
      "slots": 1,
      "weapon_damage_die": null,
      "armor_bonus": 0,
      "uses": null,
      "equipped": false,
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
}

Allowed tags: petty, bulky, weapon, ranged, armor, shield, tool, light, relic, holy, healing, consumable, supplies, magic, utility
Allowed power kinds: none, spellbook, scroll, relic, holy_relic
Allowed effects: none, restore_hp, restore_attribute, clear_condition, enhance_attack, impair_target, force_save, reveal_sign, create_safe_passage, ward_or_pacify, extraordinary_aid, resurrect
Allowed clear conditions: deprived, critically_wounded, doomed, paralyzed, delirious

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
        raw_tags = migrated.get("tags", [])
        tags = {
            tag.value if isinstance(tag, CairnItemTag) else str(tag)
            for tag in raw_tags
            if isinstance(tag, CairnItemTag | str)
        }
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


def _dedupe_preserve_order(values: list[object]) -> list[object]:
    seen: set[object] = set()
    deduped: list[object] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


@dataclass(frozen=True)
class HarmApplication:
    source: str
    summary: str
    rolls: list[Roll]
    armor_value: int
    damage_after_armor: int
    hp_before: int
    hp_after: int
    str_before: int
    str_after: int
    scar_result: str | None


@dataclass(frozen=True)
class ItemUseResolution:
    summary: str
    effect_summary: str
    rolls: list[Roll]
    uses_before: int | None
    uses_after: int | None
    item_removed: bool
    hp_before: int
    hp_after: int
    str_before: int
    str_after: int
    dex_before: int
    dex_after: int
    wil_before: int
    wil_after: int
    fatigue_before: int
    fatigue_after: int
    attack_stance: AttackStance | None = None
    target_name: str | None = None
    wil_save_target: int | None = None
    wil_save_success: bool | None = None


@dataclass(frozen=True)
class SurvivalUpdate:
    summary: str
    resolution: CairnResolution


@dataclass(frozen=True)
class ResolvedActor:
    id: str
    name: str
    sheet: CharacterSheet
    is_player: bool


class CairnEngine:
    def __init__(
        self,
        seed: int | None = None,
        config: NarrativeConfig | None = None,
        completion_function: CompletionFunction = _completion,
        backfill_function: BackfillFunction | None = None,
    ) -> None:
        self._rng = random.Random(seed)
        self._config = config or NarrativeConfig.from_env()
        self._completion = completion_function
        self._backfill_function = backfill_function

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

    def resolve_save(
        self,
        state: GameState,
        ability: CairnAbility,
        reason: str,
        *,
        actor_id: str | None = None,
    ) -> OracleOutcome:
        self._require_ready(state)
        actor = self._resolve_actor(state, actor_id)
        score = self._ability_score(actor.sheet.cairn, ability)
        roll = self._roll(D20_SIDES, "save")
        success = roll.result == 1 or (roll.result != D20_SIDES and roll.result <= score)
        verdict = "passed" if success else "failed"
        actor_prefix = "" if actor.is_player else f"{actor.name}: "
        return OracleOutcome(
            kind=OracleKind.SAVE,
            summary=f"{actor_prefix}{ability.value} save {verdict}: {reason}",
            rolls=[roll],
            question=reason,
            chaos_factor=state.chaos_factor,
            cairn=CairnResolution(
                ability=ability,
                target=score,
                success=success,
                actor_id=None if actor.is_player else actor.id,
                actor_name=None if actor.is_player else actor.name,
            ),
        )

    def resolve_attack(  # noqa: PLR0913
        self,
        state: GameState,
        *,
        target_name: str,
        target_armor: int,
        weapon_item_id: str | None,
        stance: AttackStance,
        actor_id: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> OracleOutcome:
        self._require_ready(state)
        actor = self._resolve_actor(state, actor_id)
        existing_encounter_active = (
            state.encounter.active and self._has_active_enemies(state.encounter)
        )
        encounter = self._ensure_encounter(
            state,
            player_input=f"Attack {target_name}",
            target_name=target_name,
            fallback_target_armor=target_armor,
            initiator=EncounterInitiator.PLAYER,
            cancel_token=cancel_token,
        )
        target = (
            self._require_target(encounter, target_name)
            if existing_encounter_active
            else self._resolve_opening_attack_target(encounter, target_name)
        )
        pending_advantage = self._consume_pending_advantage(encounter, actor, target)
        weapon = self._resolve_weapon(actor.sheet, weapon_item_id)
        if weapon is None and actor.sheet.cairn.primary_weapon_item_id is not None:
            message = (
                f"{actor.name}'s primary weapon is missing from inventory; "
                "repair or re-equip before resolving an attack."
            )
            raise ValueError(message)
        effective_stance = (
            AttackStance.ENHANCED
            if pending_advantage is not None
            and pending_advantage.payoff == EncounterAdvantagePayoff.ENHANCED_ATTACK
            else stance
        )
        base_die = self._attack_die(weapon, effective_stance)
        round_before = encounter.round_number
        weapon_name = weapon.name if weapon is not None else "Unarmed strike"
        rolls: list[Roll] = []
        combat_started = encounter.round_number == 1 and encounter.first_round_dex_gate_pending
        player_acted = True
        initiative_target: int | None = None

        if encounter.first_round_dex_gate_pending:
            initiative_target = actor.sheet.cairn.dex_score
            initiative_roll = self._roll(D20_SIDES, "initiative")
            rolls.append(initiative_roll)
            player_acted = self._save_succeeds(initiative_roll.result, initiative_target)
            encounter.first_round_dex_gate_pending = False
        encounter.player_disengaged = False
        encounter.pursuit_active = False
        encounter.end_reason = None

        damage_roll = self._roll(base_die, "damage")
        target_hp_before = target.hp
        target_str_before = target.str_score
        target_defeated_before = target.defeated
        _morale_roll: Roll | None = None
        morale_target: int | None = None
        morale_success: bool | None = None
        defeated_ids: list[str] = []
        fled_ids: list[str] = []
        attack_rolls: list[Roll] = []

        if player_acted:
            rolls.append(damage_roll)
            damage_after_armor = max(0, damage_roll.result - target.armor)
            if (
                pending_advantage is not None
                and pending_advantage.payoff == EncounterAdvantagePayoff.DIRECT_STR_DAMAGE
            ):
                target_str_before = target.str_score
                target.str_score = max(0, target.str_score - damage_after_armor)
                save_roll = self._roll(D20_SIDES, "enemy_critical_damage")
                rolls.append(save_roll)
                target_defeated = not self._save_succeeds(save_roll.result, target.str_score)
                if target_defeated or target.str_score == 0:
                    target.defeated = True
                lone_zero_triggered = False
                damage_summary = (
                    f"{target.name} takes {damage_after_armor} direct STR damage"
                    f"{' and collapses' if target.defeated else ''}."
                )
                attack_rolls = []
            else:
                (
                    damage_summary,
                    attack_rolls,
                    target_defeated,
                    lone_zero_triggered,
                ) = self._apply_harm_to_combatant(target, damage_after_armor)
            if attack_rolls:
                rolls.extend(attack_rolls)
            if target_defeated and not target_defeated_before:
                defeated_ids.append(target.id)
            (
                _morale_roll,
                morale_target,
                morale_success,
                morale_fled_ids,
            ) = self._maybe_resolve_enemy_morale(
                encounter,
                lone_zero_triggered=lone_zero_triggered,
            )
            fled_ids.extend(morale_fled_ids)
            if target.id in morale_fled_ids:
                target.defeated = False
            if (
                pending_advantage is not None
                and pending_advantage.payoff == EncounterAdvantagePayoff.FORCE_MORALE
            ):
                (
                    _morale_roll,
                    morale_target,
                    morale_success,
                    morale_fled_ids,
                ) = self._resolve_enemy_morale(encounter)
                fled_ids.extend(morale_fled_ids)
            actor_prefix = "" if actor.is_player else f"{actor.name} "
            attack_summary = (
                f"{actor_prefix}attacks {target.name}: {weapon_name}. {damage_summary}"
            )
        else:
            damage_after_armor = 0
            actor_prefix = "You" if actor.is_player else actor.name
            attack_summary = (
                f"{actor_prefix} lost the first round and failed to act before {target.name} could close."
            )

        if (
            pending_advantage is not None
            and pending_advantage.payoff == EncounterAdvantagePayoff.DENY_ENEMY_ACTION
        ):
            enemy_harm = self._empty_harm_application(
                state,
                source="Enemy action denied by advantage",
                defender=actor.sheet,
            )
        else:
            enemy_harm = self._resolve_enemy_turn(state, encounter, defender=actor.sheet)
        rolls.extend(enemy_harm.rolls)
        encounter.active = self._has_active_enemies(encounter)
        if encounter.active:
            encounter.round_number += 1
            encounter.end_reason = None
        elif fled_ids:
            encounter.end_reason = EncounterEndReason.ENEMY_ROUT
            encounter.notes = "The remaining enemies broke and fled."
        else:
            encounter.end_reason = EncounterEndReason.VICTORY
            encounter.notes = "No active foes remain."

        return OracleOutcome(
            kind=OracleKind.ATTACK,
            summary=self._attack_summary(
                attack_summary=attack_summary,
                enemy_summary=enemy_harm.summary,
                encounter=encounter,
            ),
            rolls=rolls,
            question=f"Attack {target.name}",
            chaos_factor=state.chaos_factor,
            cairn=CairnResolution(
                combat_round=round_before,
                combat_started=combat_started,
                combat_active=encounter.active,
                combat_initiator=encounter.initiator,
                player_acted=player_acted,
                initiative_target=initiative_target,
                advantage_id=None if pending_advantage is None else pending_advantage.id,
                advantage_setup=None if pending_advantage is None else pending_advantage.setup,
                advantage_payoff=None if pending_advantage is None else pending_advantage.payoff,
                advantage_target_name=None if pending_advantage is None else pending_advantage.target_name,
                advantage_applied=pending_advantage is not None,
                advantage_consumed=pending_advantage is not None,
                weakness=(
                    None
                    if pending_advantage is None or pending_advantage.weakness == ""
                    else pending_advantage.weakness
                ),
                actor_id=None if actor.is_player else actor.id,
                actor_name=None if actor.is_player else actor.name,
                weapon_item_id=weapon.id if weapon is not None else None,
                weapon_name=weapon_name,
                target_combatant_id=target.id,
                target_name=target.name,
                target_armor=target.armor,
                attack_stance=effective_stance,
                base_damage=damage_roll.result if player_acted else None,
                damage_after_armor=damage_after_armor,
                target_hp_before=target_hp_before,
                target_hp_after=target.hp,
                target_str_before=target_str_before,
                target_str_after=target.str_score,
                target_defeated=target.defeated,
                target_fled=target.fled,
                hp_before=enemy_harm.hp_before,
                hp_after=enemy_harm.hp_after,
                str_before=enemy_harm.str_before,
                str_after=enemy_harm.str_after,
                enemy_damage=enemy_harm.damage_after_armor,
                enemy_damage_source=enemy_harm.source if enemy_harm.damage_after_armor else None,
                morale_target=morale_target,
                morale_success=morale_success,
                defeated_combatant_ids=defeated_ids,
                fled_combatant_ids=fled_ids,
                scar_result=enemy_harm.scar_result,
                overloaded=actor.sheet.cairn.overloaded,
            ),
        )

    def resolve_coordinated_attack(
        self,
        state: GameState,
        *,
        target_name: str,
        target_armor: int,
        participants: tuple[AttackActor, ...],
        cancel_token: CancellationToken | None = None,
    ) -> OracleOutcome:
        self._require_ready(state)
        if len(participants) < 2:
            message = "Coordinated attacks require at least two participants."
            raise ValueError(message)
        existing_encounter_active = (
            state.encounter.active and self._has_active_enemies(state.encounter)
        )
        encounter = self._ensure_encounter(
            state,
            player_input=f"Coordinated attack {target_name}",
            target_name=target_name,
            fallback_target_armor=target_armor,
            initiator=EncounterInitiator.PLAYER,
            cancel_token=cancel_token,
        )
        target = (
            self._require_target(encounter, target_name)
            if existing_encounter_active
            else self._resolve_opening_attack_target(encounter, target_name)
        )
        round_before = encounter.round_number
        combat_started = encounter.round_number == 1 and encounter.first_round_dex_gate_pending
        player_acted = True
        initiative_target: int | None = None
        rolls: list[Roll] = []

        if encounter.first_round_dex_gate_pending:
            initiative_target = min(actor.sheet.cairn.dex_score for actor in participants)
            initiative_roll = self._roll(D20_SIDES, "initiative")
            rolls.append(initiative_roll)
            player_acted = self._save_succeeds(initiative_roll.result, initiative_target)
            encounter.first_round_dex_gate_pending = False
        encounter.player_disengaged = False
        encounter.pursuit_active = False
        encounter.end_reason = None

        participants_out: list[CoordinatedAttackParticipant] = []
        defeated_ids: list[str] = []
        fled_ids: list[str] = []
        morale_target: int | None = None
        morale_success: bool | None = None
        total_damage_after_armor = 0
        base_damage: int | None = None
        target_hp_before_all = target.hp
        target_str_before_all = target.str_score
        target_defeated_before = target.defeated
        target_defeated = target.defeated
        lone_zero_triggered = False
        attack_summaries: list[str] = []

        for participant in participants:
            weapon = self._resolve_weapon(participant.sheet, participant.weapon_item_id)
            if weapon is None and participant.sheet.cairn.primary_weapon_item_id is not None:
                message = (
                    f"{participant.name}'s primary weapon is missing from inventory; "
                    "repair or re-equip before resolving an attack."
                )
                raise ValueError(message)
            weapon_name = weapon.name if weapon is not None else "Unarmed strike"
            before_hp = target.hp
            before_str = target.str_score
            participant_base_damage: int | None = None
            participant_damage = 0

            if player_acted and not target.defeated and not target.fled:
                damage_roll = self._roll(
                    self._attack_die(weapon, participant.stance),
                    f"damage_{participant.id or 'player'}",
                )
                rolls.append(damage_roll)
                participant_base_damage = damage_roll.result
                if base_damage is None:
                    base_damage = damage_roll.result
                participant_damage = max(0, damage_roll.result - target.armor)
                total_damage_after_armor += participant_damage
                (
                    damage_summary,
                    attack_rolls,
                    target_defeated,
                    participant_lone_zero,
                ) = self._apply_harm_to_combatant(target, participant_damage)
                if attack_rolls:
                    rolls.extend(attack_rolls)
                lone_zero_triggered = lone_zero_triggered or participant_lone_zero
                attack_summaries.append(
                    f"{participant.name} attacks {target.name}: {weapon_name}. {damage_summary}",
                )
            else:
                attack_summaries.append(
                    f"{participant.name} could not land their coordinated strike before {target.name} closed.",
                )

            participants_out.append(
                CoordinatedAttackParticipant(
                    actor_id=participant.id,
                    actor_name=participant.name,
                    weapon_item_id=weapon.id if weapon is not None else None,
                    weapon_name=weapon_name,
                    base_damage=participant_base_damage,
                    damage_after_armor=participant_damage,
                    target_hp_before=before_hp,
                    target_hp_after=target.hp,
                    target_str_before=before_str,
                    target_str_after=target.str_score,
                    target_defeated=target.defeated,
                    target_fled=target.fled,
                    acted=player_acted,
                ),
            )
            if target.defeated or target.fled:
                break

        if player_acted:
            if target_defeated and not target_defeated_before:
                defeated_ids.append(target.id)
            (
                _morale_roll,
                morale_target,
                morale_success,
                morale_fled_ids,
            ) = self._maybe_resolve_enemy_morale(
                encounter,
                lone_zero_triggered=lone_zero_triggered,
            )
            fled_ids.extend(morale_fled_ids)
            if target.id in morale_fled_ids:
                target.defeated = False
            attack_summary = " ".join(attack_summaries)
        else:
            attack_summary = (
                f"The coordinated attack failed the opening DEX gate; "
                f"{target.name} closed before Vrtanes or his companions could act."
            )

        enemy_harm = self._resolve_enemy_turn(state, encounter, defender=state.character)
        rolls.extend(enemy_harm.rolls)
        encounter.active = self._has_active_enemies(encounter)
        if encounter.active:
            encounter.round_number += 1
            encounter.end_reason = None
        elif fled_ids:
            encounter.end_reason = EncounterEndReason.ENEMY_ROUT
            encounter.notes = "The remaining enemies broke and fled."
        else:
            encounter.end_reason = EncounterEndReason.VICTORY
            encounter.notes = "No active foes remain."

        lead = participants_out[0]
        return OracleOutcome(
            kind=OracleKind.ATTACK,
            summary=self._attack_summary(
                attack_summary=attack_summary,
                enemy_summary=enemy_harm.summary,
                encounter=encounter,
            ),
            rolls=rolls,
            question=f"Coordinated attack {target.name}",
            chaos_factor=state.chaos_factor,
            cairn=CairnResolution(
                combat_round=round_before,
                combat_started=combat_started,
                combat_active=encounter.active,
                combat_initiator=encounter.initiator,
                player_acted=player_acted,
                initiative_target=initiative_target,
                actor_id=lead.actor_id,
                actor_name=None if lead.actor_id is None else lead.actor_name,
                weapon_item_id=lead.weapon_item_id,
                weapon_name=lead.weapon_name,
                target_combatant_id=target.id,
                target_name=target.name,
                target_armor=target.armor,
                attack_stance=participants[0].stance,
                base_damage=base_damage,
                damage_after_armor=total_damage_after_armor,
                target_hp_before=target_hp_before_all,
                target_hp_after=target.hp,
                target_str_before=target_str_before_all,
                target_str_after=target.str_score,
                target_defeated=target.defeated,
                target_fled=target.fled,
                hp_before=enemy_harm.hp_before,
                hp_after=enemy_harm.hp_after,
                str_before=enemy_harm.str_before,
                str_after=enemy_harm.str_after,
                enemy_damage=enemy_harm.damage_after_armor,
                enemy_damage_source=enemy_harm.source if enemy_harm.damage_after_armor else None,
                morale_target=morale_target,
                morale_success=morale_success,
                coordinated_attack=True,
                coordinated_participants=participants_out,
                defeated_combatant_ids=defeated_ids,
                fled_combatant_ids=fled_ids,
                scar_result=enemy_harm.scar_result,
                overloaded=state.character.cairn.overloaded,
            ),
        )

    def setup_advantage(  # noqa: PLR0913
        self,
        state: GameState,
        *,
        target_name: str,
        setup: str,
        payoff: EncounterAdvantagePayoff,
        actor_id: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> OracleOutcome:
        self._require_ready(state)
        actor = self._resolve_actor(state, actor_id)
        encounter = self._ensure_encounter(
            state,
            player_input=setup,
            target_name=target_name,
            fallback_target_armor=0,
            initiator=EncounterInitiator.PLAYER,
            cancel_token=cancel_token,
        )
        target = self._resolve_opening_attack_target(encounter, target_name)
        advantage = PendingEncounterAdvantage(
            actor_id=None if actor.is_player else actor.id,
            actor_name=None if actor.is_player else actor.name,
            target_combatant_id=target.id,
            target_name=target.name,
            setup=setup,
            payoff=payoff,
            weakness=target.weakness,
        )
        encounter.pending_advantages.append(advantage)
        if payoff == EncounterAdvantagePayoff.SKIP_DEX_GATE:
            encounter.first_round_dex_gate_pending = False
        summary = (
            f"Advantage set against {target.name}: {setup}. "
            f"Payoff: {payoff.value.replace('_', ' ')}."
        )
        return OracleOutcome(
            kind=OracleKind.PLAYER_ACTION,
            summary=summary,
            rolls=[],
            question=setup,
            chaos_factor=state.chaos_factor,
            cairn=CairnResolution(
                actor_id=None if actor.is_player else actor.id,
                actor_name=None if actor.is_player else actor.name,
                target_combatant_id=target.id,
                target_name=target.name,
                advantage_id=advantage.id,
                advantage_setup=setup,
                advantage_payoff=payoff,
                advantage_target_name=target.name,
                advantage_applied=True,
                advantage_consumed=False,
                weakness=advantage.weakness or None,
                combat_active=encounter.active,
                combat_initiator=encounter.initiator,
                combat_round=encounter.round_number,
                overloaded=actor.sheet.cairn.overloaded,
            ),
        )

    def begin_encounter(
        self,
        state: GameState,
        *,
        target_name: str,
        text: str,
        cancel_token: CancellationToken | None = None,
    ) -> OracleOutcome:
        self._require_ready(state)
        encounter = self._ensure_encounter(
            state,
            player_input=text,
            target_name=target_name,
            fallback_target_armor=0,
            initiator=EncounterInitiator.PLAYER,
            cancel_token=cancel_token,
        )
        encounter.active = self._has_active_enemies(encounter)
        encounter.player_disengaged = False
        encounter.pursuit_active = False
        encounter.end_reason = None if encounter.active else EncounterEndReason.VICTORY
        combatant_names = ", ".join(
            combatant.name
            for combatant in encounter.combatants
            if not combatant.defeated and not combatant.fled
        )
        summary = (
            f"Combat encounter started against {combatant_names or target_name}. "
            f"Round {encounter.round_number} is ready; no attack has been resolved yet."
        )
        return OracleOutcome(
            kind=OracleKind.PLAYER_ACTION,
            summary=summary,
            rolls=[],
            question=text,
            chaos_factor=state.chaos_factor,
            cairn=CairnResolution(
                combat_round=encounter.round_number,
                combat_started=True,
                combat_active=encounter.active,
                combat_initiator=encounter.initiator,
                player_acted=False,
                target_name=combatant_names or target_name,
                overloaded=state.character.cairn.overloaded,
            ),
        )

    def resolve_enemy_opener(
        self,
        state: GameState,
        *,
        source: str,
        text: str,
        cancel_token: CancellationToken | None = None,
    ) -> OracleOutcome:
        self._require_ready(state)
        encounter = self._ensure_encounter(
            state,
            player_input=text,
            target_name=source,
            fallback_target_armor=0,
            initiator=EncounterInitiator.ENEMY,
            cancel_token=cancel_token,
        )
        round_before = encounter.round_number
        combat_started = encounter.initiator == EncounterInitiator.ENEMY and round_before == 1
        encounter.first_round_dex_gate_pending = False
        encounter.player_disengaged = False
        encounter.pursuit_active = False
        encounter.end_reason = None

        enemy_harm = self._resolve_enemy_turn(
            state,
            encounter,
            preferred_attacker_name=source,
        )
        encounter.active = self._has_active_enemies(encounter)
        if encounter.active:
            encounter.round_number += 1
            encounter.end_reason = None
            summary = (
                f"{enemy_harm.source} seizes the initiative. {enemy_harm.summary} "
                f"Combat is active in round {encounter.round_number}."
            )
        else:
            encounter.end_reason = EncounterEndReason.VICTORY
            encounter.notes = "No active foes remain."
            summary = (
                f"{enemy_harm.source} struck first. {enemy_harm.summary} "
                "The immediate fight is no longer active."
            )

        return OracleOutcome(
            kind=OracleKind.HARM,
            summary=summary,
            rolls=enemy_harm.rolls,
            question=text,
            chaos_factor=state.chaos_factor,
            cairn=CairnResolution(
                combat_round=round_before,
                combat_started=combat_started,
                combat_active=encounter.active,
                combat_initiator=encounter.initiator,
                player_acted=False,
                target_name=enemy_harm.source,
                target_armor=enemy_harm.armor_value,
                damage_after_armor=enemy_harm.damage_after_armor,
                hp_before=enemy_harm.hp_before,
                hp_after=enemy_harm.hp_after,
                str_before=enemy_harm.str_before,
                str_after=enemy_harm.str_after,
                enemy_damage=enemy_harm.damage_after_armor,
                enemy_damage_source=enemy_harm.source if enemy_harm.damage_after_armor else None,
                scar_result=enemy_harm.scar_result,
                overloaded=state.character.cairn.overloaded,
            ),
        )

    def resolve_retreat(self, state: GameState, reason: str) -> OracleOutcome:
        self._require_ready(state)
        encounter = state.encounter
        if not encounter.active or not self._has_active_enemies(encounter):
            message = "No active encounter to retreat from."
            raise ValueError(message)

        round_before = encounter.round_number
        retreat_target = state.character.cairn.dex_score
        retreat_roll = self._roll(D20_SIDES, "retreat")
        rolls: list[Roll] = [retreat_roll]
        enemy_harm = self._empty_harm_application(state, source="No enemy harm")
        retreat_success = self._save_succeeds(retreat_roll.result, retreat_target)
        pursuit_target = self._highest_enemy_pursuit_target(encounter)
        retreat_outcome: RetreatOutcome
        encounter_end_reason: EncounterEndReason | None = None

        if not retreat_success:
            encounter.player_disengaged = False
            encounter.pursuit_active = False
            encounter.end_reason = None
            enemy_harm = self._resolve_enemy_turn(state, encounter)
            rolls.extend(enemy_harm.rolls)
            encounter.active = self._has_active_enemies(encounter)
            if encounter.active:
                encounter.round_number += 1
            encounter.notes = "Retreat failed; the enemy kept you pinned in the fight."
            retreat_outcome = RetreatOutcome.CAUGHT
            summary = (
                f"Retreat failed: {reason}. {enemy_harm.summary}"
            )
        else:
            pursuit_roll = self._roll(D20_SIDES, "pursuit")
            rolls.append(pursuit_roll)
            pursuers_close = self._save_succeeds(pursuit_roll.result, pursuit_target)
            if pursuers_close:
                encounter.player_disengaged = True
                encounter.pursuit_active = True
                encounter.active = True
                encounter.end_reason = None
                encounter.first_round_dex_gate_pending = False
                encounter.round_number += 1
                encounter.notes = "You broke contact, but the enemy remains in pursuit."
                retreat_outcome = RetreatOutcome.DISENGAGED
                summary = (
                    f"Retreat resolved: {reason}. You broke contact, but the enemy is still in pursuit."
                )
            else:
                encounter.player_disengaged = False
                encounter.pursuit_active = False
                encounter.active = False
                encounter.first_round_dex_gate_pending = False
                encounter.end_reason = EncounterEndReason.PLAYER_ESCAPED
                encounter.notes = "You escaped the encounter."
                retreat_outcome = RetreatOutcome.ESCAPED
                encounter_end_reason = EncounterEndReason.PLAYER_ESCAPED
                summary = f"Retreat resolved: {reason}. You escaped the encounter."

        return OracleOutcome(
            kind=OracleKind.RETREAT,
            summary=summary,
            rolls=rolls,
            question=reason,
            chaos_factor=state.chaos_factor,
            cairn=CairnResolution(
                ability=CairnAbility.DEX,
                target=retreat_target,
                success=retreat_success,
                combat_round=round_before,
                combat_active=encounter.active,
                combat_initiator=encounter.initiator,
                hp_before=enemy_harm.hp_before,
                hp_after=enemy_harm.hp_after,
                str_before=enemy_harm.str_before,
                str_after=enemy_harm.str_after,
                enemy_damage=enemy_harm.damage_after_armor,
                enemy_damage_source=enemy_harm.source if enemy_harm.damage_after_armor else None,
                retreat_outcome=retreat_outcome,
                player_disengaged=encounter.player_disengaged,
                pursuit_active=encounter.pursuit_active,
                encounter_end_reason=encounter_end_reason,
                overloaded=state.character.cairn.overloaded,
            ),
        )

    def suffer_harm(  # noqa: PLR0913
        self,
        state: GameState,
        *,
        amount: int,
        source: str,
        in_combat: bool,
        armor_applies: bool,
        actor_id: str | None = None,
    ) -> OracleOutcome:
        self._require_ready(state)
        actor = self._resolve_actor(state, actor_id)
        applied = self._apply_harm_to_character(
            actor.sheet.cairn,
            amount=amount,
            source=source,
            in_combat=in_combat,
            armor_applies=armor_applies,
        )
        self._recompute_derived(actor.sheet)
        actor_prefix = "" if actor.is_player else f"{actor.name}: "
        return OracleOutcome(
            kind=OracleKind.HARM,
            summary=f"{actor_prefix}{applied.summary}",
            rolls=applied.rolls,
            question=source,
            chaos_factor=state.chaos_factor,
            cairn=CairnResolution(
                actor_id=None if actor.is_player else actor.id,
                actor_name=None if actor.is_player else actor.name,
                combat_initiator=(
                    state.encounter.initiator
                    if in_combat and state.encounter.active
                    else None
                ),
                target_name=source,
                target_armor=applied.armor_value,
                base_damage=amount,
                damage_after_armor=applied.damage_after_armor,
                hp_before=applied.hp_before,
                hp_after=actor.sheet.cairn.hp,
                str_before=applied.str_before,
                str_after=actor.sheet.cairn.str_score,
                scar_result=applied.scar_result,
                overloaded=actor.sheet.cairn.overloaded,
            ),
        )

    def recover(
        self,
        state: GameState,
        kind: CairnRestKind,
        *,
        actor_id: str | None = None,
    ) -> OracleOutcome:
        self._require_ready(state)
        actor = self._resolve_actor(state, actor_id)
        cairn = actor.sheet.cairn
        hp_before = cairn.hp
        fatigue_before = cairn.fatigue
        str_before = cairn.str_score

        if cairn.dead:
            message = "Dead characters cannot recover through ordinary rest."
            raise ValueError(message)

        if kind == CairnRestKind.BREATHER:
            if not cairn.deprived:
                cairn.hp = cairn.max_hp
        elif kind == CairnRestKind.FULL_REST:
            if not cairn.deprived:
                cairn.hp = cairn.max_hp
                cairn.fatigue = 0
                cairn.critically_wounded = False
        elif not cairn.deprived:
            cairn.hp = cairn.max_hp
            cairn.fatigue = 0
            cairn.str_score = cairn.max_str_score
            cairn.dex_score = cairn.max_dex_score
            cairn.wil_score = cairn.max_wil_score
            cairn.critically_wounded = False
            cairn.paralyzed = False
            cairn.delirious = False

        self._recompute_derived(actor.sheet)
        actor_prefix = "" if actor.is_player else f"{actor.name}: "
        return OracleOutcome(
            kind=OracleKind.RECOVERY,
            summary=f"{actor_prefix}Recovery resolved: {kind.value}.",
            rolls=[],
            question=kind.value,
            chaos_factor=state.chaos_factor,
            cairn=CairnResolution(
                rest_kind=kind,
                actor_id=None if actor.is_player else actor.id,
                actor_name=None if actor.is_player else actor.name,
                hp_before=hp_before,
                hp_after=cairn.hp,
                str_before=str_before,
                str_after=cairn.str_score,
                fatigue_before=fatigue_before,
                fatigue_after=cairn.fatigue,
                overloaded=cairn.overloaded,
            ),
        )

    def advance_survival_clock(
        self,
        state: GameState,
        *,
        time_advance: CairnTimeAdvance,
        actions: tuple[CairnSurvivalAction, ...] = (),
        actor_id: str | None = None,
        extra_days: int = 0,
    ) -> SurvivalUpdate:
        self._require_ready(state)
        actor = self._resolve_actor(state, actor_id)
        cairn = actor.sheet.cairn
        self._sync_survival_flags(cairn)
        before = cairn.survival.model_copy(deep=True)
        deprived_before = cairn.deprived
        ration_item_id: str | None = None
        ration_item_name: str | None = None
        ration_uses_before: int | None = None
        ration_uses_after: int | None = None
        notes: list[str] = []

        watches = self._watch_count_for_time_advance(before.watch_index, time_advance)
        if watches > 0:
            self._advance_survival_watches(cairn, watches)
        if extra_days > 0:
            cairn.survival.day_number += extra_days
        if CairnSurvivalAction.EAT in actions:
            ration = self._find_ration_item(actor.sheet)
            if ration is None:
                notes.append("No rations available to eat")
            else:
                ration_item_id = ration.id
                ration_item_name = ration.name
                ration_uses_before, ration_uses_after = self._consume_ration(actor.sheet, ration)
                cairn.survival.watches_since_meal = 0
                cairn.survival.food_deprived = False
                notes.append(
                    f"Ate {ration.name} ({ration_uses_before}->{ration_uses_after})"
                )
        if CairnSurvivalAction.SLEEP in actions:
            cairn.survival.watches_since_sleep = 0
            cairn.survival.sleep_deprived = False
            notes.append("Slept and reset exhaustion pressure")
        self._sync_survival_flags(cairn)
        self._recompute_derived(actor.sheet)
        after = cairn.survival.model_copy(deep=True)
        actor_prefix = "" if actor.is_player else f"{actor.name}: "
        if time_advance != CairnTimeAdvance.NONE:
            notes.insert(
                0,
                f"time {time_advance.value} ({before.day_number}:{before.day_phase.value} -> "
                f"{after.day_number}:{after.day_phase.value})",
            )
        if not notes:
            notes.append("No survival-clock change")
        return SurvivalUpdate(
            summary=f"{actor_prefix}Survival clock updated: {'; '.join(notes)}.",
            resolution=CairnResolution(
                time_advance=time_advance,
                actor_id=None if actor.is_player else actor.id,
                actor_name=None if actor.is_player else actor.name,
                day_number_before=before.day_number,
                day_number_after=after.day_number,
                watch_index_before=before.watch_index,
                watch_index_after=after.watch_index,
                day_phase_before=before.day_phase,
                day_phase_after=after.day_phase,
                watches_since_meal_before=before.watches_since_meal,
                watches_since_meal_after=after.watches_since_meal,
                watches_since_sleep_before=before.watches_since_sleep,
                watches_since_sleep_after=after.watches_since_sleep,
                food_deprived_before=before.food_deprived,
                food_deprived_after=after.food_deprived,
                sleep_deprived_before=before.sleep_deprived,
                sleep_deprived_after=after.sleep_deprived,
                deprived_before=deprived_before,
                deprived_after=cairn.deprived,
                ration_item_id=ration_item_id,
                ration_item_name=ration_item_name,
                ration_uses_before=ration_uses_before,
                ration_uses_after=ration_uses_after,
                overloaded=cairn.overloaded,
            ),
        )

    def set_item_equipped(
        self,
        state: GameState,
        *,
        item_id: str,
        equipped: bool,
        actor_id: str | None = None,
    ) -> None:
        self._require_ready(state)
        actor = self._resolve_actor(state, actor_id)
        target = self._find_item(actor.sheet, item_id)
        if target is None:
            message = f"Unknown inventory item: {item_id}"
            raise ValueError(message)

        if CairnItemTag.WEAPON in target.cairn.tags and equipped:
            for item in actor.sheet.inventory:
                if item.id != item_id and CairnItemTag.WEAPON in item.cairn.tags:
                    item.cairn.equipped = False
        target.cairn.equipped = equipped
        self._recompute_derived(actor.sheet)

    def use_item(
        self,
        state: GameState,
        *,
        item_id: str,
        intent: str,
        actor_id: str | None = None,
    ) -> OracleOutcome:
        self._require_ready(state)
        actor = self._resolve_actor(state, actor_id)
        target = self._find_item(actor.sheet, item_id)
        if target is None:
            message = f"Unknown inventory item: {item_id}"
            raise ValueError(message)

        resolution = self._resolve_item_use(state, actor.sheet, target, intent=intent)
        self._recompute_derived(actor.sheet)
        actor_prefix = "" if actor.is_player else f"{actor.name}: "
        return OracleOutcome(
            kind=OracleKind.PLAYER_ACTION,
            summary=f"{actor_prefix}{resolution.summary}",
            rolls=resolution.rolls,
            question=intent,
            chaos_factor=state.chaos_factor,
            cairn=CairnResolution(
                actor_id=None if actor.is_player else actor.id,
                actor_name=None if actor.is_player else actor.name,
                item_id=item_id,
                item_name=target.name,
                item_power_kind=target.cairn.power.kind,
                item_effect_kind=target.cairn.power.effect,
                effect_summary=resolution.effect_summary,
                uses_before=resolution.uses_before,
                uses_after=resolution.uses_after,
                recharge_condition=target.cairn.power.recharge_condition or None,
                ability=CairnAbility.WIL if resolution.wil_save_target is not None else None,
                target=resolution.wil_save_target,
                success=resolution.wil_save_success,
                attack_stance=resolution.attack_stance,
                target_name=resolution.target_name,
                hp_before=resolution.hp_before,
                hp_after=resolution.hp_after,
                str_before=resolution.str_before,
                str_after=resolution.str_after,
                dex_before=resolution.dex_before,
                dex_after=resolution.dex_after,
                wil_before=resolution.wil_before,
                wil_after=resolution.wil_after,
                fatigue_before=resolution.fatigue_before,
                fatigue_after=resolution.fatigue_after,
                overloaded=actor.sheet.cairn.overloaded,
            ),
        )

    def _resolve_item_use(
        self,
        state: GameState,
        character: CharacterSheet,
        item: InventoryItem,
        *,
        intent: str,
    ) -> ItemUseResolution:
        cairn = character.cairn
        power = self._effective_item_power(item)
        hp_before = cairn.hp
        str_before = cairn.str_score
        dex_before = cairn.dex_score
        wil_before = cairn.wil_score
        fatigue_before = cairn.fatigue
        uses_before = item.cairn.uses
        rolls: list[Roll] = []
        effect_notes: list[str] = []
        attack_stance: AttackStance | None = None
        target_name: str | None = None
        wil_save_target: int | None = None
        wil_save_success: bool | None = None

        if CairnItemTag.LIGHT in item.cairn.tags:
            item.cairn.equipped = True
            effect_notes.append("light readied")

        if item.cairn.uses == 0:
            recharge = f" Recharge: {power.recharge_condition}." if power.recharge_condition else ""
            return ItemUseResolution(
                summary=f"Used {item.name}: no charges remain.{recharge}",
                effect_summary="No effect; the item is depleted.",
                rolls=[],
                uses_before=uses_before,
                uses_after=item.cairn.uses,
                item_removed=False,
                hp_before=hp_before,
                hp_after=cairn.hp,
                str_before=str_before,
                str_after=cairn.str_score,
                dex_before=dex_before,
                dex_after=cairn.dex_score,
                wil_before=wil_before,
                wil_after=cairn.wil_score,
                fatigue_before=fatigue_before,
                fatigue_after=cairn.fatigue,
            )

        if power.adds_fatigue or power.kind == CairnItemPowerKind.SPELLBOOK:
            cairn.fatigue += 1
            effect_notes.append("Fatigue +1")

        if self._item_use_requires_wil_save(state, character, power):
            wil_save_target = wil_before
            roll = self._roll(D20_SIDES, "item_wil_save")
            rolls.append(roll)
            wil_save_success = self._save_succeeds(roll.result, wil_save_target)
            if not wil_save_success:
                cairn.fatigue += 1
                effect_notes.append("WIL save failed; Fatigue +1")

        effect_summary, attack_stance, target_name = self._apply_item_power_effect(
            cairn,
            power=power,
            intent=intent,
        )
        effect_notes.insert(0, effect_summary)

        item_removed = self._spend_item_use(character, item, power)
        uses_after = None if item_removed else item.cairn.uses
        summary = self._item_use_summary(
            item,
            power=power,
            effect_notes=effect_notes,
            uses_before=uses_before,
            uses_after=uses_after,
            item_removed=item_removed,
        )
        return ItemUseResolution(
            summary=summary,
            effect_summary="; ".join(note for note in effect_notes if note),
            rolls=rolls,
            uses_before=uses_before,
            uses_after=uses_after,
            item_removed=item_removed,
            hp_before=hp_before,
            hp_after=cairn.hp,
            str_before=str_before,
            str_after=cairn.str_score,
            dex_before=dex_before,
            dex_after=cairn.dex_score,
            wil_before=wil_before,
            wil_after=cairn.wil_score,
            fatigue_before=fatigue_before,
            fatigue_after=cairn.fatigue,
            attack_stance=attack_stance,
            target_name=target_name,
            wil_save_target=wil_save_target,
            wil_save_success=wil_save_success,
        )

    def _effective_item_power(self, item: InventoryItem) -> CairnItemPower:
        power = item.cairn.power
        if power.kind != CairnItemPowerKind.NONE or power.effect != CairnItemEffectKind.NONE:
            return power
        tags = set(item.cairn.tags)
        if CairnItemTag.HOLY in tags and CairnItemTag.RELIC in tags:
            return CairnItemPower(
                kind=CairnItemPowerKind.HOLY_RELIC,
                name=item.name,
                summary=item.details,
                effect=CairnItemEffectKind.REVEAL_SIGN,
            )
        if CairnItemTag.RELIC in tags:
            return CairnItemPower(
                kind=CairnItemPowerKind.RELIC,
                name=item.name,
                summary=item.details,
                effect=CairnItemEffectKind.REVEAL_SIGN,
            )
        return power

    def _item_use_requires_wil_save(
        self,
        state: GameState,
        character: CharacterSheet,
        power: CairnItemPower,
    ) -> bool:
        if not power.requires_wil_save_in_danger and power.kind != CairnItemPowerKind.SPELLBOOK:
            return False
        return state.encounter.active or character.cairn.deprived

    def _apply_item_power_effect(
        self,
        cairn: CairnCharacterState,
        *,
        power: CairnItemPower,
        intent: str,
    ) -> tuple[str, AttackStance | None, str | None]:
        amount = power.effect_amount
        if power.effect == CairnItemEffectKind.RESTORE_HP:
            before = cairn.hp
            cairn.hp = cairn.max_hp if amount == 0 else min(cairn.max_hp, cairn.hp + amount)
            return (f"HP restored {before}->{cairn.hp}", None, None)
        if power.effect == CairnItemEffectKind.RESTORE_ATTRIBUTE:
            ability = power.effect_ability or (
                CairnAbility.WIL if power.kind == CairnItemPowerKind.HOLY_RELIC else None
            )
            if ability is None:
                return ("no attribute named for restoration", None, None)
            before, after = self._restore_attribute(cairn, ability, amount)
            return (f"{ability.value} restored {before}->{after}", None, None)
        if power.effect == CairnItemEffectKind.CLEAR_CONDITION:
            condition = power.clears_condition
            if condition is None:
                return ("no condition named to clear", None, None)
            cleared = self._clear_condition(cairn, condition)
            return (
                f"{condition.value.replace('_', ' ')} {'cleared' if cleared else 'unchanged'}",
                None,
                None,
            )
        if power.effect == CairnItemEffectKind.ENHANCE_ATTACK:
            return ("next relevant attack is Enhanced by position or permission", AttackStance.ENHANCED, None)
        if power.effect == CairnItemEffectKind.IMPAIR_TARGET:
            return ("target opposition is Impaired by the item effect", AttackStance.IMPAIRED, intent)
        if power.effect == CairnItemEffectKind.FORCE_SAVE:
            ability = power.effect_ability or CairnAbility.WIL
            return (f"the target must make a {ability.value} save if they resist", None, intent)
        if power.effect == CairnItemEffectKind.CREATE_SAFE_PASSAGE:
            return ("a narrow safe passage or escape permission is established", None, None)
        if power.effect == CairnItemEffectKind.WARD_OR_PACIFY:
            return ("nearby violence or hostile will is warded or pacified if the fiction allows", None, None)
        if power.effect == CairnItemEffectKind.EXTRAORDINARY_AID:
            before_hp = cairn.hp
            cairn.hp = cairn.max_hp
            cairn.critically_wounded = False
            return (f"extraordinary aid restores HP {before_hp}->{cairn.hp} and stabilizes critical harm", None, None)
        if power.effect == CairnItemEffectKind.RESURRECT:
            cairn.dead = False
            cairn.critically_wounded = False
            cairn.str_score = max(1, cairn.str_score)
            cairn.hp = cairn.max_hp
            return ("extraordinary aid returns the dead to full health", None, None)
        if power.effect == CairnItemEffectKind.REVEAL_SIGN:
            if power.kind == CairnItemPowerKind.HOLY_RELIC:
                return ("intercession yields a subtle sign, not a standing buff", None, None)
            return ("the item reveals a bounded sign or direction", None, None)
        if power.summary:
            return (power.summary, None, None)
        return (f"used for its ordinary purpose: {intent}", None, None)

    def _restore_attribute(
        self,
        cairn: CairnCharacterState,
        ability: CairnAbility,
        amount: int,
    ) -> tuple[int, int]:
        if ability == CairnAbility.STR:
            before = cairn.str_score
            cairn.str_score = cairn.max_str_score if amount == 0 else min(
                cairn.max_str_score,
                cairn.str_score + amount,
            )
            return (before, cairn.str_score)
        if ability == CairnAbility.DEX:
            before = cairn.dex_score
            cairn.dex_score = cairn.max_dex_score if amount == 0 else min(
                cairn.max_dex_score,
                cairn.dex_score + amount,
            )
            return (before, cairn.dex_score)
        before = cairn.wil_score
        cairn.wil_score = cairn.max_wil_score if amount == 0 else min(
            cairn.max_wil_score,
            cairn.wil_score + amount,
        )
        return (before, cairn.wil_score)

    def _clear_condition(self, cairn: CairnCharacterState, condition: CairnConditionKey) -> bool:
        if condition == CairnConditionKey.DEPRIVED:
            was_active = cairn.deprived
            cairn.survival.food_deprived = False
            cairn.survival.sleep_deprived = False
            cairn.survival.other_deprived = False
            self._sync_survival_flags(cairn)
            return was_active
        if condition == CairnConditionKey.CRITICALLY_WOUNDED:
            was_active = cairn.critically_wounded
            cairn.critically_wounded = False
            return was_active
        if condition == CairnConditionKey.DOOMED:
            was_active = cairn.doomed
            cairn.doomed = False
            return was_active
        if condition == CairnConditionKey.PARALYZED:
            was_active = cairn.paralyzed
            cairn.dex_score = max(1, cairn.dex_score)
            cairn.paralyzed = False
            return was_active
        was_active = cairn.delirious
        cairn.wil_score = max(1, cairn.wil_score)
        cairn.delirious = False
        return was_active

    def _spend_item_use(
        self,
        character: CharacterSheet,
        item: InventoryItem,
        power: CairnItemPower,
    ) -> bool:
        if item.cairn.uses is not None:
            item.cairn.uses = max(0, item.cairn.uses - 1)
        should_remove = (
            power.consumed_on_use
            or power.kind == CairnItemPowerKind.SCROLL
            or CairnItemTag.CONSUMABLE in item.cairn.tags
        )
        if should_remove and (item.cairn.uses is None or item.cairn.uses == 0):
            character.inventory = [
                candidate for candidate in character.inventory if candidate.id != item.id
            ]
            return True
        return False

    def _item_use_summary(  # noqa: PLR0913
        self,
        item: InventoryItem,
        *,
        power: CairnItemPower,
        effect_notes: list[str],
        uses_before: int | None,
        uses_after: int | None,
        item_removed: bool,
    ) -> str:
        label = power.name.strip() or item.name
        effect = "; ".join(note for note in effect_notes if note)
        if item_removed:
            return f"Used {label}: {effect}. Item consumed."
        if uses_before is not None:
            recharge = f" Recharge: {power.recharge_condition}." if power.recharge_condition else ""
            return f"Used {label}: {effect}. Uses {uses_before}->{uses_after}.{recharge}"
        return f"Used {label}: {effect}. No limited uses were consumed."

    def drop_item(
        self,
        state: GameState,
        *,
        item_id: str,
        actor_id: str | None = None,
    ) -> str:
        self._require_ready(state)
        actor = self._resolve_actor(state, actor_id)
        target = self._find_item(actor.sheet, item_id)
        if target is None:
            message = f"Unknown inventory item: {item_id}"
            raise ValueError(message)

        actor.sheet.inventory = [
            item for item in actor.sheet.inventory if item.id != item_id
        ]
        self._recompute_derived(actor.sheet)
        actor_prefix = "" if actor.is_player else f"{actor.name} "
        return f"{actor_prefix}dropped {target.name}."

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
            .replace("<<CURRENT_SCENE>>", state.current_scene)
            .replace("<<SETTING_NOTES>>", self._prompt_setting_context(state))
            .replace("<<THREAD_TITLES>>", ", ".join(thread.title for thread in state.threads) or "(none)")
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
                reasoning=encounter_profile.reasoning(default_exclude=self._config.exclude_reasoning),
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
            notes="Fallback encounter seed created because no combat seed model response was available.",
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

    def _require_target(self, encounter: EncounterState, target_name: str) -> EnemyCombatant:
        target = self._find_combatant(encounter, target_name)
        if target is None:
            message = f"No active foe matches '{target_name}'."
            raise ValueError(message)
        return target

    def _resolve_opening_attack_target(
        self,
        encounter: EncounterState,
        target_name: str,
    ) -> EnemyCombatant:
        matched = self._find_combatant(encounter, target_name)
        if matched is not None:
            return matched

        active = [combatant for combatant in encounter.combatants if not combatant.defeated and not combatant.fled]
        if not active:
            message = "No active foe is available for the opening attack."
            raise ValueError(message)

        leader = next((combatant for combatant in active if combatant.leader), None)
        return leader or active[0]

    def _find_combatant(self, encounter: EncounterState, target_name: str) -> EnemyCombatant | None:
        cleaned = target_name.strip().lower()
        active = [combatant for combatant in encounter.combatants if not combatant.defeated and not combatant.fled]
        for combatant in active:
            name = combatant.name.lower()
            if cleaned == name or cleaned in name or name in cleaned:
                return combatant
        return None

    def _has_active_enemies(self, encounter: EncounterState) -> bool:
        return any(not combatant.defeated and not combatant.fled for combatant in encounter.combatants)

    def _consume_pending_advantage(
        self,
        encounter: EncounterState,
        actor: ResolvedActor,
        target: EnemyCombatant,
    ) -> PendingEncounterAdvantage | None:
        for index, advantage in enumerate(encounter.pending_advantages):
            actor_matches = advantage.actor_id == (None if actor.is_player else actor.id)
            target_matches = (
                advantage.target_combatant_id == target.id
                or advantage.target_name.lower() == target.name.lower()
            )
            if actor_matches and target_matches:
                return encounter.pending_advantages.pop(index)
        return None

    def _save_succeeds(self, result: int, target: int) -> bool:
        return result == 1 or (result != D20_SIDES and result <= target)

    def _apply_harm_to_character(
        self,
        cairn: CairnCharacterState,
        *,
        amount: int,
        source: str,
        in_combat: bool,
        armor_applies: bool,
    ) -> HarmApplication:
        armor_value = cairn.armor if armor_applies and in_combat else 0
        damage_after_armor = max(0, amount - armor_value)
        hp_before = cairn.hp
        str_before = cairn.str_score
        rolls: list[Roll] = []
        scar_result: str | None = None

        if damage_after_armor == 0:
            summary = f"No harm taken from {source}; armor absorbed the blow."
        elif in_combat:
            hp_after = hp_before - damage_after_armor
            if hp_after > 0:
                cairn.hp = hp_after
                summary = f"Took {damage_after_armor} damage from {source}."
            elif hp_after == 0:
                cairn.hp = 0
                scar_result, scar_rolls = self._apply_scar(cairn, damage_after_armor)
                rolls.extend(scar_rolls)
                summary = f"Reduced to 0 HP by {source}; scar rolled: {scar_result}"
            else:
                cairn.hp = 0
                overflow = abs(hp_after)
                cairn.str_score = max(0, cairn.str_score - overflow)
                save_roll = self._roll(D20_SIDES, "critical_damage")
                rolls.append(save_roll)
                success = self._save_succeeds(save_roll.result, cairn.str_score)
                if not success:
                    cairn.critically_wounded = True
                if cairn.str_score == 0:
                    cairn.dead = True
                summary = (
                    f"Critical damage from {source}: {overflow} STR lost and "
                    f"critical save {'passed' if success else 'failed'}."
                )
        else:
            cairn.str_score = max(0, cairn.str_score - damage_after_armor)
            if cairn.str_score == 0:
                cairn.dead = True
            summary = f"Suffered {damage_after_armor} STR damage from {source}."

        return HarmApplication(
            source=source,
            summary=summary,
            rolls=rolls,
            armor_value=armor_value,
            damage_after_armor=damage_after_armor,
            hp_before=hp_before,
            hp_after=cairn.hp,
            str_before=str_before,
            str_after=cairn.str_score,
            scar_result=scar_result,
        )

    def _apply_harm_to_combatant(
        self,
        combatant: EnemyCombatant,
        damage_after_armor: int,
    ) -> tuple[str, list[Roll], bool, bool]:
        rolls: list[Roll] = []
        lone_zero_triggered = False
        if damage_after_armor == 0:
            return ("Armor or poor positioning turned the blow aside.", rolls, False, False)

        hp_after = combatant.hp - damage_after_armor
        if hp_after > 0:
            combatant.hp = hp_after
            return (f"{combatant.name} loses {damage_after_armor} HP.", rolls, False, False)

        if hp_after == 0:
            combatant.hp = 0
            lone_zero_triggered = True
            return (f"{combatant.name} is driven to 0 HP and wavers.", rolls, False, lone_zero_triggered)

        combatant.hp = 0
        overflow = abs(hp_after)
        combatant.str_score = max(0, combatant.str_score - overflow)
        save_roll = self._roll(D20_SIDES, "enemy_critical_damage")
        rolls.append(save_roll)
        success = self._save_succeeds(save_roll.result, combatant.str_score)
        if not success or combatant.str_score == 0:
            combatant.critically_wounded = True
            combatant.defeated = True
            return (
                f"{combatant.name} suffers critical damage, loses {overflow} STR, and collapses.",
                rolls,
                True,
                False,
            )
        combatant.critically_wounded = True
        return (
            f"{combatant.name} suffers critical damage but remains in the fight.",
            rolls,
            False,
            False,
        )

    def _resolve_enemy_turn(
        self,
        state: GameState,
        encounter: EncounterState,
        *,
        defender: CharacterSheet | None = None,
        preferred_attacker_name: str | None = None,
    ) -> HarmApplication:
        target_sheet = defender or state.character
        active = [
            combatant
            for combatant in encounter.combatants
            if not combatant.defeated and not combatant.fled
        ]
        if not active:
            return HarmApplication(
                source="No active foes",
                summary="No enemy retaliation; no active foes remain.",
                rolls=[],
                armor_value=target_sheet.cairn.armor,
                damage_after_armor=0,
                hp_before=target_sheet.cairn.hp,
                hp_after=target_sheet.cairn.hp,
                str_before=target_sheet.cairn.str_score,
                str_after=target_sheet.cairn.str_score,
                scar_result=None,
            )

        preferred_attacker = (
            self._find_combatant(encounter, preferred_attacker_name)
            if preferred_attacker_name is not None
            else None
        )
        if preferred_attacker is not None and not preferred_attacker.defeated and not preferred_attacker.fled:
            enemy_rolls = [
                (
                    preferred_attacker,
                    self._roll(
                        preferred_attacker.weapon_damage_die,
                        f"enemy_damage_{preferred_attacker.id}",
                    ),
                ),
            ]
        else:
            enemy_rolls = [
                (combatant, self._roll(combatant.weapon_damage_die, f"enemy_damage_{combatant.id}"))
                for combatant in active
            ]
        highest_combatant, highest_roll = max(enemy_rolls, key=lambda pair: pair[1].result)
        applied = self._apply_harm_to_character(
            target_sheet.cairn,
            amount=highest_roll.result,
            source=highest_combatant.name,
            in_combat=True,
            armor_applies=True,
        )
        return HarmApplication(
            source=highest_combatant.name,
            summary=applied.summary,
            rolls=[roll for _, roll in enemy_rolls] + applied.rolls,
            armor_value=applied.armor_value,
            damage_after_armor=applied.damage_after_armor,
            hp_before=applied.hp_before,
            hp_after=applied.hp_after,
            str_before=applied.str_before,
            str_after=applied.str_after,
            scar_result=applied.scar_result,
        )

    def _empty_harm_application(
        self,
        state: GameState,
        *,
        source: str,
        defender: CharacterSheet | None = None,
    ) -> HarmApplication:
        target_sheet = defender or state.character
        return HarmApplication(
            source=source,
            summary="No enemy retaliation landed.",
            rolls=[],
            armor_value=target_sheet.cairn.armor,
            damage_after_armor=0,
            hp_before=target_sheet.cairn.hp,
            hp_after=target_sheet.cairn.hp,
            str_before=target_sheet.cairn.str_score,
            str_after=target_sheet.cairn.str_score,
            scar_result=None,
        )

    def _highest_enemy_pursuit_target(self, encounter: EncounterState) -> int:
        active = [
            combatant
            for combatant in encounter.combatants
            if not combatant.defeated and not combatant.fled
        ]
        if not active:
            return 1
        return max(combatant.dex_score for combatant in active)

    def _maybe_resolve_enemy_morale(
        self,
        encounter: EncounterState,
        *,
        lone_zero_triggered: bool,
    ) -> tuple[Roll | None, int | None, bool | None, list[str]]:
        active = [
            combatant
            for combatant in encounter.combatants
            if not combatant.defeated and not combatant.fled
        ]
        total = len(encounter.combatants)
        defeated_or_fled = [
            combatant for combatant in encounter.combatants if combatant.defeated or combatant.fled
        ]
        if not active:
            encounter.active = False
            encounter.end_reason = EncounterEndReason.VICTORY
            return (None, None, None, [])

        check_needed = False
        if lone_zero_triggered and len(active) == 1 and active[0].hp == 0:
            check_needed = True
        elif not encounter.casualty_morale_checked and defeated_or_fled:
            check_needed = True
            encounter.casualty_morale_checked = True
            if len(defeated_or_fled) * 2 >= total:
                encounter.half_force_morale_checked = True
        elif not encounter.half_force_morale_checked and len(defeated_or_fled) * 2 >= total:
            check_needed = True
            encounter.half_force_morale_checked = True

        if not check_needed:
            return (None, None, None, [])

        leader = next((combatant for combatant in active if combatant.leader), active[0])
        target = leader.wil_score
        roll = self._roll(D20_SIDES, "morale")
        success = self._save_succeeds(roll.result, target)
        if success:
            return (roll, target, True, [])

        fled_ids: list[str] = []
        for combatant in active:
            combatant.fled = True
            fled_ids.append(combatant.id)
        encounter.active = False
        encounter.end_reason = EncounterEndReason.ENEMY_ROUT
        encounter.notes = "The remaining enemies broke and fled."
        return (roll, target, False, fled_ids)

    def _resolve_enemy_morale(
        self,
        encounter: EncounterState,
    ) -> tuple[Roll | None, int | None, bool | None, list[str]]:
        active = [
            combatant
            for combatant in encounter.combatants
            if not combatant.defeated and not combatant.fled
        ]
        if not active:
            encounter.active = False
            encounter.end_reason = EncounterEndReason.VICTORY
            return (None, None, None, [])
        leader = next((combatant for combatant in active if combatant.leader), active[0])
        target = leader.wil_score
        roll = self._roll(D20_SIDES, "morale")
        success = self._save_succeeds(roll.result, target)
        if success:
            return (roll, target, True, [])
        fled_ids: list[str] = []
        for combatant in active:
            combatant.fled = True
            fled_ids.append(combatant.id)
        encounter.active = False
        encounter.end_reason = EncounterEndReason.ENEMY_ROUT
        encounter.notes = "The remaining enemies broke and fled."
        return (roll, target, False, fled_ids)

    def _attack_summary(
        self,
        *,
        attack_summary: str,
        enemy_summary: str,
        encounter: EncounterState,
    ) -> str:
        if encounter.active:
            return f"{attack_summary} {enemy_summary} Combat presses into round {encounter.round_number}."
        return f"{attack_summary} {enemy_summary} The immediate fight is no longer active."

    def _require_ready(self, state: GameState) -> None:
        if state.character.cairn.source == CairnMechanicsSource.UNSET:
            message = "Cairn mechanics are not available for this character yet."
            raise ValueError(message)

    def _resolve_actor(self, state: GameState, actor_id: str | None) -> ResolvedActor:
        if actor_id is None or actor_id == "player":
            return ResolvedActor(
                id="player",
                name=state.character.name,
                sheet=state.character,
                is_player=True,
            )
        for member in state.party_members:
            if member.id == actor_id and member.active:
                if member.sheet.cairn.source == CairnMechanicsSource.UNSET:
                    message = f"Cairn mechanics are not available for {member.display_label()} yet."
                    raise ValueError(message)
                return ResolvedActor(
                    id=member.id,
                    name=member.display_label(),
                    sheet=member.sheet,
                    is_player=False,
                )
        message = f"Unknown active party member: {actor_id}"
        raise ValueError(message)

    def _recompute_derived(self, character: CharacterSheet) -> None:
        cairn = character.cairn
        first_weapon_id: str | None = None
        any_weapon_equipped = False
        armor_value = 0
        slots_used = cairn.fatigue

        for item in character.inventory:
            slots_used += item.cairn.slots
            if CairnItemTag.WEAPON in item.cairn.tags and first_weapon_id is None:
                first_weapon_id = item.id
            if CairnItemTag.WEAPON in item.cairn.tags and item.cairn.equipped:
                any_weapon_equipped = True
                cairn.primary_weapon_item_id = item.id
            if item.cairn.equipped and (
                CairnItemTag.ARMOR in item.cairn.tags or CairnItemTag.SHIELD in item.cairn.tags
            ):
                armor_value += item.cairn.armor_bonus

        if not any_weapon_equipped and first_weapon_id is not None:
            for item in character.inventory:
                if CairnItemTag.WEAPON in item.cairn.tags:
                    item.cairn.equipped = item.id == first_weapon_id
                if item.id == first_weapon_id:
                    cairn.primary_weapon_item_id = item.id

        cairn.armor = min(MAX_ARMOR, armor_value)
        cairn.slots_used = slots_used
        cairn.overloaded = slots_used >= cairn.slots_total
        self._sync_survival_flags(cairn)
        if cairn.overloaded:
            cairn.hp = 0
        cairn.paralyzed = cairn.dex_score == 0
        cairn.delirious = cairn.wil_score == 0
        cairn.dead = cairn.dead or cairn.str_score == 0

    def _apply_scar(self, cairn: CairnCharacterState, hp_lost: int) -> tuple[str, list[Roll]]:
        rolls: list[Roll] = []
        entry = max(1, min(12, hp_lost))
        if entry == 1:
            location_roll = self._roll(D6_SIDES, "scar_location")
            hp_roll = self._roll(D6_SIDES, "scar_hp")
            rolls.extend((location_roll, hp_roll))
            cairn.max_hp = max(cairn.max_hp, hp_roll.result)
            return (
                f"Lasting Scar ({LASTING_SCAR_LOCATIONS[location_roll.result - 1]})",
                rolls,
            )
        if entry == 2:
            hp_roll = self._roll(D6_SIDES, "scar_hp")
            rolls.append(hp_roll)
            cairn.max_hp = max(cairn.max_hp, hp_roll.result)
            return ("Rattling Blow", rolls)
        if entry == 3:
            hp_roll = self._roll(D6_SIDES, "scar_hp")
            rolls.append(hp_roll)
            cairn.max_hp += hp_roll.result
            cairn.survival.other_deprived = True
            self._sync_survival_flags(cairn)
            return ("Walloped", rolls)
        if entry == 4:
            part_roll = self._roll(D6_SIDES, "scar_part")
            hp_roll = self._roll(D8_SIDES, "scar_hp")
            rolls.extend((part_roll, hp_roll))
            cairn.max_hp = max(cairn.max_hp, hp_roll.result)
            cairn.critically_wounded = True
            return (f"Broken Limb ({BROKEN_LIMB_PARTS[part_roll.result - 1]})", rolls)
        if entry == 5:
            hp_roll = self._roll(D8_SIDES, "scar_hp")
            rolls.append(hp_roll)
            cairn.max_hp = max(cairn.max_hp, hp_roll.result)
            return ("Diseased", rolls)
        if entry == 6:
            ability_roll = self._roll(D6_SIDES, "scar_ability")
            stat_roll = self._roll_nd6(3, "scar_attribute")
            rolls.extend((ability_roll, stat_roll))
            value = stat_roll.result
            if ability_roll.result <= STR_BRANCH_MAX:
                cairn.max_str_score = max(cairn.max_str_score, value)
                cairn.str_score = min(value, cairn.max_str_score)
                ability = CairnAbility.STR
            elif ability_roll.result <= DEX_BRANCH_MAX:
                cairn.max_dex_score = max(cairn.max_dex_score, value)
                cairn.dex_score = min(value, cairn.max_dex_score)
                ability = CairnAbility.DEX
            else:
                cairn.max_wil_score = max(cairn.max_wil_score, value)
                cairn.wil_score = min(value, cairn.max_wil_score)
                ability = CairnAbility.WIL
            return (f"Reorienting Head Wound ({ability.value})", rolls)
        if entry == 7:
            dex_roll = self._roll_nd6(3, "scar_dex")
            rolls.append(dex_roll)
            value = dex_roll.result
            cairn.max_dex_score = max(cairn.max_dex_score, value)
            return ("Hamstrung", rolls)
        if entry == 8:
            save_roll = self._roll(D20_SIDES, "scar_wil_save")
            bonus_roll = self._roll(D4_SIDES, "scar_wil_bonus")
            rolls.extend((save_roll, bonus_roll))
            success = save_roll.result == 1 or (
                save_roll.result != D20_SIDES and save_roll.result <= cairn.wil_score
            )
            if success:
                cairn.max_wil_score += bonus_roll.result
            return ("Deafened", rolls)
        if entry == 9:
            wil_roll = self._roll_nd6(3, "scar_wil")
            rolls.append(wil_roll)
            value = wil_roll.result
            cairn.max_wil_score = max(cairn.max_wil_score, value)
            return ("Re-brained", rolls)
        if entry == 10:
            save_roll = self._roll(D20_SIDES, "scar_wil_save")
            bonus_roll = self._roll(D6_SIDES, "scar_wil_bonus")
            rolls.extend((save_roll, bonus_roll))
            success = save_roll.result == 1 or (
                save_roll.result != D20_SIDES and save_roll.result <= cairn.wil_score
            )
            if success:
                cairn.max_wil_score += bonus_roll.result
            cairn.critically_wounded = True
            return ("Sundered", rolls)
        if entry == 11:
            hp_roll = self._roll(D8_SIDES, "scar_hp")
            rolls.append(hp_roll)
            cairn.max_hp = hp_roll.result
            cairn.survival.other_deprived = True
            self._sync_survival_flags(cairn)
            cairn.critically_wounded = True
            return ("Mortal Wound", rolls)

        hp_roll = self._roll_nd6(3, "scar_hp")
        rolls.append(hp_roll)
        cairn.max_hp = max(cairn.max_hp, hp_roll.result)
        cairn.doomed = True
        return ("Doomed", rolls)

    def _sync_survival_flags(self, cairn: CairnCharacterState) -> None:
        cairn.survival.food_deprived = cairn.survival.watches_since_meal >= FOOD_DEPRIVED_WATCHES
        cairn.survival.sleep_deprived = cairn.survival.watches_since_sleep >= SLEEP_DEPRIVED_WATCHES
        cairn.deprived = (
            cairn.survival.food_deprived
            or cairn.survival.sleep_deprived
            or cairn.survival.other_deprived
        )

    def _watch_count_for_time_advance(
        self,
        watch_index: int,
        time_advance: CairnTimeAdvance,
    ) -> int:
        if time_advance in (CairnTimeAdvance.NONE, CairnTimeAdvance.BRIEF):
            return 0
        if time_advance == CairnTimeAdvance.WATCH:
            return 1
        if time_advance == CairnTimeAdvance.DAY:
            return 3
        return WATCHES_PER_DAY - watch_index if watch_index > 0 else WATCHES_PER_DAY

    def _advance_survival_watches(self, cairn: CairnCharacterState, watches: int) -> None:
        if watches <= 0:
            return
        total = cairn.survival.watch_index + watches
        day_increment, watch_index = divmod(total, WATCHES_PER_DAY)
        cairn.survival.day_number += day_increment
        cairn.survival.watch_index = watch_index
        cairn.survival.day_phase = self._phase_for_watch_index(watch_index)
        cairn.survival.watches_since_meal += watches
        cairn.survival.watches_since_sleep += watches
        self._sync_survival_flags(cairn)

    def _phase_for_watch_index(self, watch_index: int) -> CairnDayPhase:
        phases = (
            CairnDayPhase.DAWN,
            CairnDayPhase.DAY,
            CairnDayPhase.DAY,
            CairnDayPhase.DUSK,
            CairnDayPhase.NIGHT,
            CairnDayPhase.DEEP_NIGHT,
        )
        return phases[watch_index]

    def _find_ration_item(self, character: CharacterSheet) -> InventoryItem | None:
        candidates = [
            item
            for item in character.inventory
            if CairnItemTag.SUPPLIES in item.cairn.tags and (item.cairn.uses is None or item.cairn.uses > 0)
        ]
        if not candidates:
            return None
        candidates.sort(
            key=lambda item: (
                CairnItemTag.CONSUMABLE not in item.cairn.tags,
                item.cairn.uses is None,
                item.cairn.slots,
                item.name,
            ),
        )
        return candidates[0]

    def _consume_ration(
        self,
        character: CharacterSheet,
        item: InventoryItem,
    ) -> tuple[int, int]:
        uses_before = item.cairn.uses if item.cairn.uses is not None else max(1, item.cairn.slots * 3)
        uses_after = max(0, uses_before - 1)
        if uses_after == 0:
            character.inventory = [candidate for candidate in character.inventory if candidate.id != item.id]
        else:
            item.cairn.uses = uses_after
        self._recompute_derived(character)
        return (uses_before, uses_after)

    def _resolve_weapon(
        self,
        character: CharacterSheet,
        weapon_item_id: str | None,
    ) -> InventoryItem | None:
        if weapon_item_id is not None:
            explicit = self._find_item(character, weapon_item_id)
            if explicit is not None and CairnItemTag.WEAPON in explicit.cairn.tags:
                return explicit
        if character.cairn.primary_weapon_item_id is not None:
            primary = self._find_item(character, character.cairn.primary_weapon_item_id)
            if primary is not None:
                return primary
        return next(
            (item for item in character.inventory if CairnItemTag.WEAPON in item.cairn.tags),
            None,
        )

    def _attack_die(self, weapon: InventoryItem | None, stance: AttackStance) -> int:
        if stance == AttackStance.IMPAIRED:
            return D4_SIDES
        if stance == AttackStance.ENHANCED:
            return D12_SIDES
        if weapon is None or weapon.cairn.weapon_damage_die is None:
            return D4_SIDES
        return weapon.cairn.weapon_damage_die

    def _find_item(self, character: CharacterSheet, item_id: str) -> InventoryItem | None:
        return next((item for item in character.inventory if item.id == item_id), None)

    def _ability_score(self, cairn: CairnCharacterState, ability: CairnAbility) -> int:
        if ability == CairnAbility.STR:
            return cairn.str_score
        if ability == CairnAbility.DEX:
            return cairn.dex_score
        return cairn.wil_score

    def _roll(self, sides: int, label: str) -> Roll:
        return Roll(sides=sides, result=self._rng.randint(1, sides), label=label)

    def _roll_nd6(self, count: int, label: str) -> Roll:
        return Roll(
            sides=D6_SIDES * count,
            result=sum(self._rng.randint(1, D6_SIDES) for _ in range(count)),
            label=label,
        )
