// Pure formatting helpers for the read-only Cairn surface.
//
// This module is **strictly presentational**. It never infers meaning from
// free text and never mutates state. Every function takes already-resolved
// backend data and produces a string / chip / tier suitable for UI render.
// Keeping inference and rendering separate is the whole reason the heavier
// classification work moved into `TurnRouter` and `CairnEngine` server-side;
// this file is the rendering counterpart.

import type {
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
  CairnSurvivalClock,
  CairnTimeAdvance,
  EncounterInitiator,
  OracleOutcome,
} from "./types";

// --- Survival-clock thresholds -----------------------------------------
//
// Mirrors the constants in src/dungeon_master/cairn.py. We hand-mirror
// them rather than fetch them from the backend because the frontend
// only uses them to color the pressure meters — never to decide
// deprivation, which is always the backend's call. Keeping the numbers
// in lockstep is enforced by Vitest cross-checks against
// `CairnSurvivalClock.food_deprived` / `sleep_deprived`: if the
// thresholds drift, those tests start failing because the warning tier
// stops bracketing the deprivation tier.
export const FOOD_WARNING_WATCHES = 2;
export const FOOD_DEPRIVED_WATCHES = 3;
export const SLEEP_WARNING_WATCHES = 4;
export const SLEEP_DEPRIVED_WATCHES = 6;
export const WATCHES_PER_DAY = 6;

// --- Defaults ----------------------------------------------------------

// Mirrors `CairnCharacterState` defaults in src/dungeon_master/models.py.
// Used by client-only synthetic sheets (blank drafts, folio fallbacks)
// so the type stays exhaustive without forcing every call site to spell
// out twenty-odd zeroes. Source stays "unset" so render gates know this
// is not a real backfill yet.
export function defaultCairnCharacterState(): CairnCharacterState {
  return {
    source: "unset",
    backfill_version: 0,
    skills: [],
    abilities: [],
    str_score: 10,
    dex_score: 10,
    wil_score: 10,
    max_str_score: 10,
    max_dex_score: 10,
    max_wil_score: 10,
    hp: 1,
    max_hp: 1,
    armor: 0,
    fatigue: 0,
    deprived: false,
    critically_wounded: false,
    doomed: false,
    paralyzed: false,
    delirious: false,
    dead: false,
    slots_total: 10,
    backpack_slots: 6,
    comfortable_slots: 5,
    slots_used: 0,
    overloaded: false,
    primary_weapon_item_id: null,
    survival: defaultCairnSurvivalClock(),
    notes: "",
  };
}

// Mirrors `CairnSurvivalClock` defaults in models.py. Day 1 / dawn /
// no pressure / no flags is the resting state of a fresh sheet — the
// backend uses the same starting point so any draft and any started
// campaign read identically until the engine actually advances time.
export function defaultCairnSurvivalClock(): CairnSurvivalClock {
  return {
    day_number: 1,
    watch_index: 0,
    day_phase: "dawn",
    watches_since_meal: 0,
    watches_since_sleep: 0,
    food_deprived: false,
    sleep_deprived: false,
    other_deprived: false,
  };
}

// Mirrors `CairnItemState` defaults in models.py.
export function defaultCairnItemState(): CairnItemState {
  return {
    source: "unset",
    backfill_version: 0,
    tags: [],
    slots: 1,
    weapon_damage_die: null,
    armor_bonus: 0,
    uses: null,
    equipped: false,
    power: defaultCairnItemPower(),
  };
}

export function defaultCairnItemPower(): CairnItemPower {
  return {
    kind: "none",
    name: "",
    summary: "",
    effect: "none",
    effect_amount: 1,
    effect_ability: null,
    clears_condition: null,
    recharge_condition: "",
    requires_wil_save_in_danger: false,
    adds_fatigue: false,
    consumed_on_use: false,
  };
}

// --- Render gating -----------------------------------------------------

// True when the backend has actually derived Cairn mechanics for the
// character. Renderers should hide the entire Cairn block when this is
// false, even if individual numeric fields look populated — `unset`
// means the backfill hasn't run yet and the numbers are placeholders.
export function hasCairnMechanics(source: CairnMechanicsSource): boolean {
  return source !== "unset";
}

// --- Burden ------------------------------------------------------------

// "comfortable" is the no-fatigue carry tier (0..comfortable_slots).
// "backpack" is the still-functional carry tier (..backpack_slots).
// "overloaded" is the deprivation-risking tier or any state where the
// backend flagged `overloaded`. We trust the backend's `overloaded` flag
// over the raw arithmetic in case rules ever shift; we only fall back to
// arithmetic when the flag is false but the slot count exceeds backpack.
export type BurdenTier = "comfortable" | "backpack" | "overloaded";

export interface BurdenSummary {
  used: number;
  total: number;
  comfortable: number;
  backpack: number;
  tier: BurdenTier;
  overloaded: boolean;
}

export function formatBurden(c: CairnCharacterState): BurdenSummary {
  const used = Math.max(0, c.slots_used);
  const total = Math.max(used, c.slots_total);
  const comfortable = Math.max(0, c.comfortable_slots);
  const backpack = Math.max(comfortable, c.backpack_slots);
  const overloaded = c.overloaded || used > backpack;
  const tier: BurdenTier = overloaded
    ? "overloaded"
    : used <= comfortable
      ? "comfortable"
      : "backpack";
  return { used, total, comfortable, backpack, tier, overloaded };
}

// --- Statuses ----------------------------------------------------------

// Stable status keys used by both the renderer and CSS. Order matters:
// these are listed in display priority — most severe first — so a player
// checking the rail at a glance sees `DEAD` before `DEPRIVED`. The render
// component preserves this order verbatim.
export type StatusKey =
  | "dead"
  | "doomed"
  | "critically_wounded"
  | "paralyzed"
  | "delirious"
  | "deprived"
  | "overloaded";

export interface StatusBadge {
  key: StatusKey;
  label: string;
}

const STATUS_PRIORITY: ReadonlyArray<{ key: StatusKey; label: string }> = [
  { key: "dead", label: "Dead" },
  { key: "doomed", label: "Doomed" },
  { key: "critically_wounded", label: "Critical" },
  { key: "paralyzed", label: "Paralyzed" },
  { key: "delirious", label: "Delirious" },
  { key: "deprived", label: "Deprived" },
  { key: "overloaded", label: "Overloaded" },
];

export function activeStatuses(c: CairnCharacterState): StatusBadge[] {
  return STATUS_PRIORITY.filter(({ key }) => c[key]).map(({ key, label }) => ({
    key,
    label,
  }));
}

// --- Item tags ---------------------------------------------------------

// Order tags so structural / mechanical tags (petty, bulky, weapon, ranged,
// armor, shield) come first, then descriptors (light, holy, relic, ...).
// We keep the canonical CairnItemTag order from types.ts as the authority
// rather than re-sorting alphabetically — the existing order already
// reflects the "structure first" intent.
const TAG_LABEL: Record<CairnItemTag, string> = {
  petty: "Petty",
  bulky: "Bulky",
  weapon: "Weapon",
  ranged: "Ranged",
  armor: "Armor",
  shield: "Shield",
  tool: "Tool",
  light: "Light",
  relic: "Relic",
  holy: "Holy",
  healing: "Healing",
  consumable: "Consumable",
  supplies: "Supplies",
  magic: "Magic",
  utility: "Utility",
};

export function itemTagLabel(tag: CairnItemTag): string {
  return TAG_LABEL[tag];
}

export function itemTagLabels(item: CairnItemState): string[] {
  return item.tags.map(itemTagLabel);
}

// --- Item powers --------------------------------------------------------

const POWER_KIND_LABEL: Record<CairnItemPowerKind, string> = {
  none: "Mundane",
  spellbook: "Spellbook",
  scroll: "Scroll",
  relic: "Relic",
  holy_relic: "Holy relic",
};

const EFFECT_LABEL: Record<CairnItemEffectKind, string> = {
  none: "No special effect",
  restore_hp: "Restore HP",
  restore_attribute: "Restore attribute",
  clear_condition: "Clear condition",
  enhance_attack: "Enhance attack",
  impair_target: "Impair target",
  force_save: "Force save",
  reveal_sign: "Reveal sign",
  create_safe_passage: "Create safe passage",
  ward_or_pacify: "Ward or pacify",
  extraordinary_aid: "Extraordinary aid",
  resurrect: "Resurrect",
};

const CONDITION_LABEL: Record<CairnConditionKey, string> = {
  deprived: "Deprived",
  critically_wounded: "Critical",
  doomed: "Doomed",
  paralyzed: "Paralyzed",
  delirious: "Delirious",
};

export function itemPowerKindLabel(kind: CairnItemPowerKind): string {
  return POWER_KIND_LABEL[kind];
}

export function itemEffectLabel(effect: CairnItemEffectKind): string {
  return EFFECT_LABEL[effect];
}

export function itemConditionLabel(condition: CairnConditionKey): string {
  return CONDITION_LABEL[condition];
}

export function hasItemPower(
  power: CairnItemPower | null | undefined,
): power is CairnItemPower {
  if (power == null) return false;
  return power.kind !== "none" || power.effect !== "none";
}

export function itemPowerTitle(power: CairnItemPower | null | undefined): string | null {
  if (!hasItemPower(power)) return null;
  const name = power.name.trim();
  const kind = itemPowerKindLabel(power.kind);
  return name === "" ? kind : `${kind} · ${name}`;
}

export function itemPowerSummary(power: CairnItemPower | null | undefined): string | null {
  if (!hasItemPower(power)) return null;
  if (power.summary.trim() !== "") return power.summary.trim();
  const parts = [itemEffectLabel(power.effect)];
  if (power.effect_ability !== null) parts.push(power.effect_ability);
  if (power.clears_condition !== null) parts.push(itemConditionLabel(power.clears_condition));
  if (power.adds_fatigue) parts.push("Fatigue");
  if (power.requires_wil_save_in_danger) parts.push("WIL risk");
  return parts.join(" · ");
}

// --- Cairn-flavored receipt headlines ----------------------------------

const ABILITY_LABEL: Record<CairnAbility, string> = {
  STR: "STR",
  DEX: "DEX",
  WIL: "WIL",
};

const STANCE_LABEL: Record<AttackStance, string> = {
  normal: "Normal",
  impaired: "Impaired",
  enhanced: "Enhanced",
};

const REST_KIND_LABEL: Record<CairnRestKind, string> = {
  breather: "Breather",
  full_rest: "Full rest",
  week_recovery: "Week's recovery",
};

export function formatAbility(ability: CairnAbility | null): string | null {
  return ability === null ? null : ABILITY_LABEL[ability];
}

export function formatStance(stance: AttackStance | null): string | null {
  return stance === null ? null : STANCE_LABEL[stance];
}

export function formatRestKind(kind: CairnRestKind | null): string | null {
  return kind === null ? null : REST_KIND_LABEL[kind];
}

// Returns the receipt strip headline for a Cairn-flavored outcome, or
// null when the outcome is not Cairn-flavored. The receipt component
// uses this to render `Save · DEX · passed`-style summaries; if it
// returns null, the receipt falls through to the existing oracle
// headline branches.
export function cairnHeadline(outcome: OracleOutcome): string | null {
  if (outcome.kind === "player_action" && outcome.cairn?.item_name != null) {
    return formatItemUseHeadline(outcome);
  }
  switch (outcome.kind) {
    case "save":
      return formatSaveHeadline(outcome);
    case "attack":
      return formatAttackHeadline(outcome);
    case "harm":
      return formatHarmHeadline(outcome);
    case "recovery":
      return formatRecoveryHeadline(outcome);
    case "retreat":
      return formatRetreatHeadline(outcome);
    case "yes_no":
    case "random_event":
    case "scene_check":
    case "player_action":
      return null;
  }
}

function formatItemUseHeadline(outcome: OracleOutcome): string {
  const cairn = outcome.cairn;
  if (cairn === null) return "Item use";
  const item = cairn.item_name ?? "item";
  const power = cairn.item_power_kind === null
    ? null
    : itemPowerKindLabel(cairn.item_power_kind);
  const uses = cairn.uses_before === null
    ? null
    : `uses ${cairn.uses_before}->${cairn.uses_after ?? 0}`;
  return ["Item", item, power, uses].filter((part) => part !== null && part !== "").join(" · ");
}

function formatSaveHeadline(outcome: OracleOutcome): string {
  const cairn = outcome.cairn;
  if (cairn === null) return "Save";
  const ability = formatAbility(cairn.ability) ?? "Save";
  const verdict =
    cairn.success === null ? "rolled" : cairn.success ? "passed" : "failed";
  return `Save · ${ability} · ${verdict}`;
}

function formatAttackHeadline(outcome: OracleOutcome): string {
  const cairn = outcome.cairn;
  if (cairn === null) return "Attack";
  const target = cairn.target_name ?? "unknown";
  const dmg = cairn.damage_after_armor;
  const prefix = cairn.coordinated_attack === true ? "Coordinated attack" : "Attack";
  if (dmg === null) return `${prefix} · ${target}`;
  return `${prefix} · ${target} · ${dmg} dmg`;
}

// F-05: a harm outcome that *opened* the fight reads better as
// "Ambush · 2 · HP 4" than the generic "Harm · 2 · HP 4". The backend
// tags this with `combat_started=true` *and* `combat_initiator=enemy`;
// we need both signals because a player attack can also flip
// combat_started=true, but the initiator is then `player` and the
// existing "Harm · …" framing remains correct (the player chose the
// fight). For non-opening harm (trap damage, established round-N foe
// blow), `combat_started` is null/false and we keep the plain prefix.
function harmHeadlinePrefix(outcome: OracleOutcome): string {
  const cairn = outcome.cairn;
  if (
    cairn !== null
    && cairn.combat_started === true
    && cairn.combat_initiator === "enemy"
  ) {
    return "Ambush";
  }
  return "Harm";
}

function formatHarmHeadline(outcome: OracleOutcome): string {
  const cairn = outcome.cairn;
  if (cairn === null) return "Harm";
  const dmg = cairn.damage_after_armor;
  const hpAfter = cairn.hp_after;
  const prefix = harmHeadlinePrefix(outcome);
  const head = dmg === null ? prefix : `${prefix} · ${dmg}`;
  const hp = hpAfter === null ? null : `HP ${hpAfter}`;
  const scar = cairn.scar_result;
  return [head, hp, scar].filter((part) => part !== null && part !== "").join(" · ");
}

function formatRecoveryHeadline(outcome: OracleOutcome): string {
  const cairn = outcome.cairn;
  const kind = cairn === null ? null : formatRestKind(cairn.rest_kind);
  return kind === null ? "Recovery" : `Recovery · ${kind}`;
}

function formatRetreatHeadline(outcome: OracleOutcome): string {
  const cairn = outcome.cairn;
  if (cairn === null || cairn.retreat_outcome == null) return "Retreat";
  switch (cairn.retreat_outcome) {
    case "caught":
      return "Retreat · Caught";
    case "disengaged":
      return "Retreat · Pursuit";
    case "escaped":
      return "Retreat · Escaped";
  }
}

// --- Initiative / ambush surfacing -------------------------------------

// F-05 surfaces who opened the encounter. The receipt uses this to
// render an "Initiative" row inside the Cairn dl block — useful when
// the player scrolls the oracle history and wants to see who started
// each fight. Returns null for outcomes outside any encounter (trap
// harm, off-combat harm) and for legacy outcomes that pre-date the
// field.
const INITIATOR_LABEL: Record<EncounterInitiator, string> = {
  player: "Player opened the fight",
  enemy: "Foe seized initiative",
};

export function formatCombatInitiator(
  initiator: EncounterInitiator | null | undefined,
): string | null {
  if (initiator === null || initiator === undefined) return null;
  return INITIATOR_LABEL[initiator];
}

// True when the resolution opened a tracked fight as an enemy ambush.
// We expose this as a single predicate so the receipt and the chat
// don't each rebuild the same `combat_started && combat_initiator`
// check; if the backend ever loosens the contract (e.g. "the foe
// jumps you but the encounter was already pre-seeded"), this is the
// one place to update.
export function isAmbushOpener(outcome: OracleOutcome): boolean {
  const cairn = outcome.cairn;
  return (
    cairn !== null
    && cairn.combat_started === true
    && cairn.combat_initiator === "enemy"
  );
}

// --- Survival clock ----------------------------------------------------
//
// Pure presentation helpers for the watch-based survival surface. None
// of these decide deprivation themselves; they translate the backend's
// numeric pressure / phase data into player-readable strings and tier
// keys the folio + receipt use for color and copy. Putting the labels
// here (instead of inline in the .svelte) keeps every UI surface that
// renders survival pulling from the same dictionary.

const DAY_PHASE_LABEL: Record<CairnDayPhase, string> = {
  dawn: "Dawn",
  day: "Day",
  dusk: "Dusk",
  night: "Night",
  deep_night: "Deep night",
};

const TIME_ADVANCE_LABEL: Record<CairnTimeAdvance, string> = {
  none: "No time passes",
  brief: "A breath",
  watch: "A watch",
  day: "A day",
  overnight: "Overnight",
};

export function formatDayPhase(phase: CairnDayPhase): string {
  return DAY_PHASE_LABEL[phase];
}

export function formatTimeAdvance(time: CairnTimeAdvance | null): string | null {
  return time === null ? null : TIME_ADVANCE_LABEL[time];
}

// Three-tier read of the food / sleep pressure meters. `easy` is "no
// concern yet", `warning` is "this is getting close", `deprived` is
// "the engine has flipped the deprived flag". We return the tier even
// when the flag isn't set yet (warning > easy), so the UI can show a
// soft amber pre-deprivation hint without claiming to be authoritative
// — only `deprived` corresponds to the backend actually gating HP.
export type SurvivalTier = "easy" | "warning" | "deprived";

export function foodPressureTier(survival: CairnSurvivalClock): SurvivalTier {
  if (survival.food_deprived) return "deprived";
  if (survival.watches_since_meal >= FOOD_WARNING_WATCHES) return "warning";
  return "easy";
}

export function sleepPressureTier(survival: CairnSurvivalClock): SurvivalTier {
  if (survival.sleep_deprived) return "deprived";
  if (survival.watches_since_sleep >= SLEEP_WARNING_WATCHES) return "warning";
  return "easy";
}

export interface SurvivalMeter {
  // The current pressure count (watches without food / sleep).
  value: number;
  // The threshold at which the backend flips the deprived flag, used
  // as the meter's max so the bar visually fills toward "Deprived".
  threshold: number;
  // The earlier "warning" watermark, rendered as a tick on the bar.
  warning: number;
  tier: SurvivalTier;
  // True when the backend has already flipped this axis to deprived.
  // The meter renders the "DEPRIVED" chip / bar color from this flag,
  // never from `value >= threshold` alone — the backend is the
  // authority and may grant exceptions (e.g. an item that suppresses
  // deprivation while `value` is still high).
  deprived: boolean;
}

export function foodPressureMeter(survival: CairnSurvivalClock): SurvivalMeter {
  return {
    value: Math.max(0, survival.watches_since_meal),
    threshold: FOOD_DEPRIVED_WATCHES,
    warning: FOOD_WARNING_WATCHES,
    tier: foodPressureTier(survival),
    deprived: survival.food_deprived,
  };
}

export function sleepPressureMeter(survival: CairnSurvivalClock): SurvivalMeter {
  return {
    value: Math.max(0, survival.watches_since_sleep),
    threshold: SLEEP_DEPRIVED_WATCHES,
    warning: SLEEP_WARNING_WATCHES,
    tier: sleepPressureTier(survival),
    deprived: survival.sleep_deprived,
  };
}

// Compact "Day 3 · Dusk · Watch 4/6" line for the folio readout. We
// 1-index the watch in the display because watches are inclusive of the
// current beat — "Watch 0/6" reads as "the day hasn't started" which
// isn't what the player feels at dawn-of-day-1. The underlying field
// stays 0-indexed; this is a pure presentation choice.
export function formatSurvivalLine(survival: CairnSurvivalClock): string {
  const phase = formatDayPhase(survival.day_phase);
  const watchHuman = Math.min(survival.watch_index + 1, WATCHES_PER_DAY);
  return `Day ${survival.day_number} · ${phase} · Watch ${watchHuman}/${WATCHES_PER_DAY}`;
}

// Receipt-side compact representation: only emit a line when the turn
// actually billed time. `none` is genuinely "no fiction time passed"
// and reads as noise on the receipt, so we suppress it. The label is
// short on purpose — it lives in the dl row alongside dice readouts.
export function formatTurnTimeAdvance(time: CairnTimeAdvance | null): string | null {
  if (time === null || time === "none") return null;
  return formatTimeAdvance(time);
}

// True when the survival snapshot pair on a CairnResolution actually
// moved. We consult this from the receipt to decide whether to draw
// the "Survival" sub-block at all. The check is forgiving — any of
// day, watch, meal pressure, sleep pressure, deprivation flags, or
// ration consumption counts as movement — so a turn that only ate
// (no time passed) still surfaces a row.
export function survivalChanged(resolution: CairnResolution): boolean {
  if (resolution.time_advance !== null && resolution.time_advance !== "none") return true;
  if (resolution.ration_item_id !== null) return true;
  const pairs: Array<[number | boolean | null, number | boolean | null]> = [
    [resolution.day_number_before, resolution.day_number_after],
    [resolution.watch_index_before, resolution.watch_index_after],
    [resolution.watches_since_meal_before, resolution.watches_since_meal_after],
    [resolution.watches_since_sleep_before, resolution.watches_since_sleep_after],
    [resolution.food_deprived_before, resolution.food_deprived_after],
    [resolution.sleep_deprived_before, resolution.sleep_deprived_after],
    [resolution.deprived_before, resolution.deprived_after],
  ];
  for (const [before, after] of pairs) {
    if (before !== null && after !== null && before !== after) return true;
  }
  return false;
}
