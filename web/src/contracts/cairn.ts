// Character, inventory, survival, and deterministic Cairn wire contracts.

import type {
  EncounterAdvantagePayoff,
  EncounterEndReason,
  EncounterInitiator,
} from "./encounter";

// `unset` means the backend has not yet derived Cairn mechanics for this
// record. The frontend uses it as a gate: never render the mechanics
// block while a sheet/item is still in `unset`, even if other fields
// happen to look populated.
export type CairnMechanicsSource = "unset" | "narrative_backfill" | "explicit";

export type CairnAbility = "STR" | "DEX" | "WIL";

export const CAIRN_ABILITIES: readonly CairnAbility[] = ["STR", "DEX", "WIL"] as const;

export type AttackStance = "normal" | "impaired" | "enhanced";

export type CairnRestKind = "breather" | "full_rest" | "week_recovery";

// Mirrors backend `CairnDayPhase`. The phase is a *derived* read of
// `watch_index` (see _WATCH_PHASES in models.py) — the frontend never
// recomputes it from the index, it only renders what the wire reports.
// Keeping the union exhaustive lets `formatDayPhase` fail at type-check
// time when the backend grows another phase.
export type CairnDayPhase = "dawn" | "day" | "dusk" | "night" | "deep_night";

// Mirrors backend `CairnTimeAdvance`. The router classifies how much
// fiction time a turn cost; the engine then advances the watch clock
// by that bucket. We mirror it so the receipt can render the time
// bucket the player just spent — useful when the player rereads
// history to see why a `watch` push tipped them into food deprivation.
export type CairnTimeAdvance = "none" | "brief" | "watch" | "day" | "overnight";

// Mirrors backend `CairnSurvivalAction`. Only `eat` and `sleep` are
// modeled because the survival clock cares only about what clears
// food / sleep pressure; other "actions" like resting briefly have
// always belonged to the recovery surface, not the survival clock.
export type CairnSurvivalAction = "eat" | "sleep";

export type RetreatOutcome = "caught" | "disengaged" | "escaped";

export type CairnItemTag =
  | "petty"
  | "bulky"
  | "weapon"
  | "ranged"
  | "armor"
  | "shield"
  | "tool"
  | "light"
  | "relic"
  | "holy"
  | "healing"
  | "consumable"
  | "supplies"
  | "magic"
  | "utility";

export const CAIRN_ITEM_TAGS: readonly CairnItemTag[] = [
  "petty",
  "bulky",
  "weapon",
  "ranged",
  "armor",
  "shield",
  "tool",
  "light",
  "relic",
  "holy",
  "healing",
  "consumable",
  "supplies",
  "magic",
  "utility",
] as const;

export type CairnItemPowerKind =
  | "none"
  | "spellbook"
  | "scroll"
  | "relic"
  | "holy_relic";

export type CairnItemEffectKind =
  | "none"
  | "restore_hp"
  | "restore_attribute"
  | "clear_condition"
  | "enhance_attack"
  | "impair_target"
  | "force_save"
  | "reveal_sign"
  | "create_safe_passage"
  | "ward_or_pacify"
  | "extraordinary_aid"
  | "resurrect";

export type CairnConditionKey =
  | "deprived"
  | "critically_wounded"
  | "doomed"
  | "paralyzed"
  | "delirious";

export type CairnResourceKind =
  | "ammo"
  | "charge"
  | "fuel"
  | "component"
  | "mind"
  | "durability"
  | "supply"
  | "custom";

export type CairnResourceRechargePolicy =
  | "none"
  | "per_turn"
  | "per_watch"
  | "per_day"
  | "on_rest"
  | "in_sunlight"
  | "manual_condition";

export type CairnResourceDrawPolicy =
  | "self"
  | "actor_inventory"
  | "linked_item"
  | "actor_pool";

export type CairnResourceDeltaReason =
  | "attack"
  | "item_use"
  | "recharge"
  | "survival";

export interface CairnItemPower {
  kind: CairnItemPowerKind;
  name: string;
  summary: string;
  effect: CairnItemEffectKind;
  effect_amount: number;
  effect_ability: CairnAbility | null;
  clears_condition: CairnConditionKey | null;
  recharge_condition: string;
  requires_wil_save_in_danger: boolean;
  adds_fatigue: boolean;
  consumed_on_use: boolean;
}

export interface CairnResourcePool {
  id: string;
  label: string;
  kind: CairnResourceKind;
  current: number;
  max: number | null;
  recharge_policy: CairnResourceRechargePolicy;
  recharge_amount: number;
  recharge_condition: string;
  notes: string;
}

export interface CairnResourceCost {
  label: string;
  kind: CairnResourceKind;
  amount: number;
  draw_policy: CairnResourceDrawPolicy;
  resource_id: string | null;
  linked_item_id: string | null;
  required: boolean;
}

export interface CairnResourceDelta {
  actor_id: string | null;
  actor_name: string | null;
  item_id: string | null;
  item_name: string | null;
  resource_id: string | null;
  resource_label: string;
  resource_kind: CairnResourceKind;
  before: number;
  after: number;
  amount: number;
  reason: CairnResourceDeltaReason;
  note: string;
}

// Mirrors `CairnItemState` in models.py. `weapon_damage_die` is the d-side
// for the item's weapon roll (4–12 in models.py); `armor_bonus` adds to
// the wearer's armor pool (0–3); `uses` is null for unlimited consumables
// (e.g. lanterns aren't consumed per scene), or a positive count for
// charge-tracked items. `power` is the backend's typed Cairn item-power
// contract for spellbooks, scrolls, relics, and holy relics; renderers
// must use it as data, never infer powers from item prose.
export interface CairnItemState {
  source: CairnMechanicsSource;
  backfill_version: number;
  tags: CairnItemTag[];
  slots: number;
  weapon_damage_die: number | null;
  armor_bonus: number;
  uses: number | null;
  equipped: boolean;
  power: CairnItemPower;
  resources: CairnResourcePool[];
  attack_costs: CairnResourceCost[];
  use_costs: CairnResourceCost[];
}

export interface InventoryItem {
  id: string;
  name: string;
  details: string;
  cairn: CairnItemState;
}

// Mirrors backend `CairnSurvivalClock`. The clock lives nested on the
// character so it travels with whoever is being tracked, instead of
// hanging off `GameState` (party members can in principle drift apart
// in deprivation). `day_phase` is derived from `watch_index` on the
// backend; the frontend treats both as authoritative and never
// recomputes one from the other.
//
// `food_deprived` / `sleep_deprived` / `other_deprived` are individual
// causes; the aggregate `deprived` flag on `CairnCharacterState` is
// what gates HP recovery. We mirror the disaggregated flags so the
// folio can label *why* the character is deprived without re-deriving
// from the pressure counters (the backend's threshold could shift).
export interface CairnSurvivalClock {
  day_number: number;
  watch_index: number;
  day_phase: CairnDayPhase;
  watches_since_meal: number;
  watches_since_sleep: number;
  food_deprived: boolean;
  sleep_deprived: boolean;
  other_deprived: boolean;
}

// Mirrors `CairnCharacterState`. We keep the field names identical to
// the Pydantic model so the JSON wire format is the source of truth and
// no transformation layer hides drift. `*_before` / `*_after` snapshots
// live on `CairnResolution`, not here — this struct is the live state.
export interface CairnCharacterState {
  source: CairnMechanicsSource;
  backfill_version: number;
  skills: string[];
  abilities: string[];
  str_score: number;
  dex_score: number;
  wil_score: number;
  max_str_score: number;
  max_dex_score: number;
  max_wil_score: number;
  hp: number;
  max_hp: number;
  armor: number;
  fatigue: number;
  deprived: boolean;
  critically_wounded: boolean;
  doomed: boolean;
  paralyzed: boolean;
  delirious: boolean;
  dead: boolean;
  slots_total: number;
  backpack_slots: number;
  comfortable_slots: number;
  slots_used: number;
  overloaded: boolean;
  primary_weapon_item_id: string | null;
  // Survival clock + day-night phase, populated even on freshly created
  // characters (defaults to dawn / day 1 / no pressure). The folio gates
  // its rendering on `source !== "unset"` like every other Cairn block,
  // so a draft sheet never shows a misleading watch counter.
  survival: CairnSurvivalClock;
  notes: string;
}

export interface CoordinatedAttackParticipant {
  actor_id: string | null;
  actor_name: string;
  weapon_item_id: string | null;
  weapon_name: string;
  base_damage: number | null;
  damage_after_armor: number;
  target_hp_before: number;
  target_hp_after: number;
  target_str_before: number;
  target_str_after: number;
  target_defeated: boolean;
  target_fled: boolean;
  acted: boolean;
}

// Mirrors `CairnResolution`. Every field is nullable because a single
// resolution only fills the slots relevant to its kind: a save uses
// `ability/target/success`; an attack uses `weapon_*`/`base_damage`/
// `damage_after_armor`; harm uses `hp_before`/`hp_after` and possibly
// `str_*`/`scar_result`; recovery uses `rest_kind`/`hp_*`/`fatigue_*`.
export interface CairnResolution {
  ability: CairnAbility | null;
  target: number | null;
  success: boolean | null;
  rest_kind: CairnRestKind | null;
  // Survival-clock attribution. `time_advance` is the bucket the router
  // billed this turn for; the `*_before` / `*_after` pairs and ration
  // fields are what the engine actually applied. They are independently
  // optional because not every Cairn outcome touches the clock — only
  // turns that consume time, sleep, eat, or take a rest do — and a
  // resolution with no clock movement leaves them all null. Receipts
  // render only the rows where a `before` / `after` pair actually
  // shifted, so unchanged counters disappear instead of cluttering the
  // strip.
  time_advance: CairnTimeAdvance | null;
  day_number_before: number | null;
  day_number_after: number | null;
  watch_index_before: number | null;
  watch_index_after: number | null;
  day_phase_before: CairnDayPhase | null;
  day_phase_after: CairnDayPhase | null;
  watches_since_meal_before: number | null;
  watches_since_meal_after: number | null;
  watches_since_sleep_before: number | null;
  watches_since_sleep_after: number | null;
  food_deprived_before: boolean | null;
  food_deprived_after: boolean | null;
  sleep_deprived_before: boolean | null;
  sleep_deprived_after: boolean | null;
  // Aggregate deprived flag snapshot. We surface this even though the
  // disaggregated food/sleep flags are also present so the receipt can
  // narrate "Deprived cleared" / "Deprived gained" in one row when a
  // turn touched both axes (e.g. a full rest that ate *and* slept).
  deprived_before: boolean | null;
  deprived_after: boolean | null;
  // Ration consumed on this turn (when the turn ate). Always together:
  // either all four are populated for an `eat` turn, or all four are
  // null. The receipt renders item name + uses delta as one row.
  ration_item_id: string | null;
  ration_item_name: string | null;
  ration_uses_before: number | null;
  ration_uses_after: number | null;
  actor_id: string | null;
  actor_name: string | null;
  item_id: string | null;
  item_name: string | null;
  item_power_kind: CairnItemPowerKind | null;
  item_effect_kind: CairnItemEffectKind | null;
  effect_summary: string | null;
  uses_before: number | null;
  uses_after: number | null;
  recharge_condition: string | null;
  attack_stance: AttackStance | null;
  weapon_item_id: string | null;
  weapon_name: string | null;
  target_combatant_id?: string | null;
  target_name: string | null;
  target_armor: number | null;
  base_damage: number | null;
  damage_after_armor: number | null;
  hp_before: number | null;
  hp_after: number | null;
  str_before: number | null;
  str_after: number | null;
  dex_before: number | null;
  dex_after: number | null;
  wil_before: number | null;
  wil_after: number | null;
  fatigue_before: number | null;
  fatigue_after: number | null;
  target_hp_before?: number | null;
  target_hp_after?: number | null;
  target_str_before?: number | null;
  target_str_after?: number | null;
  target_defeated?: boolean | null;
  target_fled?: boolean | null;
  // Combat-context fields published when the resolution belongs to an
  // active encounter (F-05). All optional because most non-combat
  // outcomes (yes/no oracle, scene check, recovery outside the fight)
  // simply omit them. We don't promote them into the required side of
  // the union because that would force the rest of the codebase — and
  // every existing test factory — to provide them everywhere.
  combat_round?: number | null;
  combat_started?: boolean | null;
  combat_active?: boolean | null;
  // Tells the receipt / tracker who started the fight when this
  // outcome opened or escalated combat. `enemy` is the F-05 ambush
  // path; `player` is the normal attack path. Null for resolutions
  // that didn't seed an encounter (e.g. trap harm).
  combat_initiator?: EncounterInitiator | null;
  // False for the F-05 enemy-opener path because the player didn't
  // get to act yet — the foe seized initiative. We use this on the
  // receipt to render "(no player action)" / "Initiative · enemy".
  player_acted?: boolean | null;
  initiative_target?: number | null;
  // Damage the foe applied to the player on this very resolution.
  // F-05 enemy openers always populate this (the opener strike is
  // the whole point); player attacks may also set it when the
  // counterattack landed in the same turn.
  enemy_damage?: number | null;
  enemy_damage_source?: string | null;
  // F-18 Fictional advantage. `advantage_setup` / `advantage_payoff`
  // are populated on the resolution that *creates* the advantage
  // (the SETUP_ADVANTAGE planner op). On the follow-up attack that
  // consumes it, the same fields are echoed alongside `advantage_id`
  // and `advantage_consumed=true` so the receipt can label the swing
  // as "powered by your earlier setup". `advantage_target_name`
  // mirrors the foe the setup pinned; `advantage_applied` is the
  // boolean "did this turn actually attach a setup" used by the
  // setup-side receipt to render success/no-op explicitly. The
  // `weakness` field carries any per-foe weakness the LLM authored
  // when it generated this encounter (F-19) — used by the inspector
  // to surface "this foe has a weakness you can target" hints.
  advantage_id?: string | null;
  advantage_setup?: string | null;
  advantage_payoff?: EncounterAdvantagePayoff | null;
  advantage_target_name?: string | null;
  advantage_applied?: boolean | null;
  advantage_consumed?: boolean | null;
  weakness?: string | null;
  morale_target?: number | null;
  morale_success?: boolean | null;
  coordinated_attack?: boolean;
  coordinated_participants?: CoordinatedAttackParticipant[];
  resource_deltas?: CairnResourceDelta[];
  defeated_combatant_ids?: string[];
  fled_combatant_ids?: string[];
  retreat_outcome?: RetreatOutcome | null;
  player_disengaged?: boolean | null;
  pursuit_active?: boolean | null;
  encounter_end_reason?: EncounterEndReason | null;
  scar_result: string | null;
  overloaded: boolean | null;
}

export interface CharacterSheet {
  name: string;
  archetype: string;
  epithet: string;
  backstory: string;
  drive: string;
  flaw: string;
  condition: string;
  inventory: InventoryItem[];
  cairn: CairnCharacterState;
}

export type PartyMemberKind = "companion" | "hireling" | "animal";

export interface PartyMember {
  id: string;
  kind: PartyMemberKind;
  sheet: CharacterSheet;
  npc_id: string | null;
  active: boolean;
  loyalty: string;
  notes: string;
}

export interface CharacterTemplatesResponse {
  templates: CharacterSheet[];
}

export interface CharacterDraftResponse {
  draft: CharacterSheet;
}

export interface CharacterQuizOption {
  label: string;
}

export interface CharacterQuizQuestion {
  id: string;
  prompt: string;
  options: CharacterQuizOption[];
}

export interface CharacterQuiz {
  concept: string;
  questions: CharacterQuizQuestion[];
}

export interface CharacterQuizAnswer {
  question_id: string;
  prompt: string;
  value: string;
  is_other: boolean;
}

export interface CharacterQuizResponse {
  quiz: CharacterQuiz;
}

