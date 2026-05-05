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
  CairnItemState,
  CairnItemTag,
  CairnMechanicsSource,
  CairnRestKind,
  OracleOutcome,
} from "./types";

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
    notes: "",
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
  if (dmg === null) return `Attack · ${target}`;
  return `Attack · ${target} · ${dmg} dmg`;
}

function formatHarmHeadline(outcome: OracleOutcome): string {
  const cairn = outcome.cairn;
  if (cairn === null) return "Harm";
  const dmg = cairn.damage_after_armor;
  const hpAfter = cairn.hp_after;
  const head = dmg === null ? "Harm" : `Harm · ${dmg}`;
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
