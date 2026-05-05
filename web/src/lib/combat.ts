// Frontend adapter for the backend's canonical encounter state.
//
// The backend publishes the encounter under `GameState.encounter`
// (mirrors `src/dungeon_master/models.py::EncounterState`). The shape
// the combat tracker UI was originally drafted against is slightly
// richer than the backend exposes — separate `status` + `morale`
// fields per foe rather than the backend's flat `defeated`/`fled`/
// `critically_wounded` flags. We *keep* the richer frontend shape
// because the tracker is a player-facing readout where deriving status
// at render time would just push the same logic into the components.
// Instead, this module owns the one-way adapt from the backend
// `EncounterState` → the tracker's `CombatEncounterState`.
//
// All formatting helpers in this module are strictly presentational.
// They never infer state, never mutate state, and never roll dice.

// `dead` and `fled` exist as separate flags because Cairn distinguishes
// "removed from the encounter by lethal damage" from "broke and ran on
// a morale check" — both end participation but they read very
// differently in narration and only one of them counts toward "first
// casualty" morale triggers later in the same fight.
export type CombatantStatus =
  | "active"
  | "incapacitated"
  | "dead"
  | "fled";

export interface CombatantState {
  id: string;
  name: string;
  // Free-text descriptors carried from generation (e.g. "halfwit
  // marauder", "cult abbot"). The frontend renders them as flavor
  // chips. Empty array = no chips.
  tags: string[];
  hp: number;
  max_hp: number;
  str_score: number;
  max_str_score: number;
  dex_score: number;
  wil_score: number;
  armor: number;
  // Damage die for the combatant's primary weapon. Cairn-style
  // weapons report a single `dN`; null for foes that don't deal
  // standard weapon damage (e.g. a horror that auto-applies STR
  // critical effects or a non-combat NPC tracked for color).
  weapon_damage_die: number | null;
  // Cairn morale = WIL save target by default; backend may override
  // per-combatant. Null = use default WIL.
  morale: number | null;
  morale_broken: boolean;
  status: CombatantStatus;
}

// Round metadata. `round` is 1-indexed; `0` means "encounter declared
// but not begun" (rare — the backend should rarely surface this state,
// but we model it so the UI doesn't render `Round 0` as a bug).
export interface CombatEncounterState {
  active: boolean;
  round: number;
  // Cairn 2e: the first round of combat requires a DEX save to act if
  // the side wasn't ready. Backend tracks this per side; the frontend
  // only needs the boolean for the player so it can label the round
  // strip ("First round — DEX save to act").
  player_ready: boolean;
  morale_triggered: boolean;
  // Tracked hostile combatants. The list is the source of truth — the
  // backend should not also publish a flat `combatants` field on
  // GameState. Empty when the encounter is brewing or already cleared.
  combatants: CombatantState[];
  // Optional readable summary the backend can author for the inspector
  // strip. Null when the encounter has no summary yet.
  summary: string | null;
}

// `null` here means "no encounter is being tracked" — explicit absence
// rather than an empty struct. This is how we distinguish "out of
// combat" (which is most of the game) from "between rounds with zero
// foes still standing" (which is a transient win state).
export type CombatStateSlot = CombatEncounterState | null;

// --- Backend wire shape -------------------------------------------------
//
// We define the backend shapes inline (rather than touching types.ts)
// because they're internal to this adapter — only `combatFromState`
// needs them. If the encounter shape ever stabilizes enough that the
// rest of the app reads it directly, promote these to types.ts.

interface BackendEnemyCombatant {
  id: string;
  name: string;
  description: string;
  hp: number;
  max_hp: number;
  str_score: number;
  dex_score: number;
  wil_score: number;
  armor: number;
  weapon_name: string;
  weapon_damage_die: number;
  leader: boolean;
  critically_wounded: boolean;
  defeated: boolean;
  fled: boolean;
  notes: string;
}

interface BackendEncounterState {
  active: boolean;
  round_number: number;
  first_round_dex_gate_pending: boolean;
  casualty_morale_checked: boolean;
  half_force_morale_checked: boolean;
  combatants: BackendEnemyCombatant[];
  notes: string;
}

// Returns the tracker-friendly shape derived from `state.encounter`.
// Returns null when there is no encounter (backend default) or when
// the encounter has no combatants and isn't active — that's the
// "exploration" steady state and the tracker should stay collapsed.
//
// We accept `state: object` rather than `GameState` so this works
// before/after the eventual `encounter` field lands in types.ts; the
// backend publishes it today, but the hand-mirror in types.ts hasn't
// been refreshed and we don't want to force a full mirror update just
// to wire the tracker.
export function combatFromState(state: object): CombatStateSlot {
  const candidate = (state as { encounter?: BackendEncounterState | null }).encounter;
  if (candidate === null || candidate === undefined) return null;
  if (typeof candidate !== "object") return null;

  const combatants = (candidate.combatants ?? []).map(adaptCombatant);
  if (!candidate.active && combatants.length === 0 && !candidate.notes) {
    // Default-empty encounter; treat as "no encounter tracked".
    return null;
  }

  // Morale is encounter-wide: Cairn fires casualty / half-force checks
  // against the foe side as a group, not per-foe. The frontend's
  // per-foe `morale_broken` field is reserved for a future enhancement
  // (a foe specifically broken by a successful morale roll); for now
  // we leave it false everywhere and surface the encounter-level flag
  // via `morale_triggered` instead.
  return {
    active: candidate.active,
    round: candidate.round_number,
    player_ready: !candidate.first_round_dex_gate_pending,
    morale_triggered:
      candidate.casualty_morale_checked || candidate.half_force_morale_checked,
    combatants,
    summary: candidate.notes && candidate.notes.trim() !== "" ? candidate.notes : null,
  };
}

function adaptCombatant(foe: BackendEnemyCombatant): CombatantState {
  return {
    id: foe.id,
    name: foe.name,
    // The backend tracks one free-text `description` per foe; we
    // surface it as a single descriptor chip rather than parsing it
    // into multiple tags. Empty string → no chips.
    tags: foe.description && foe.description.trim() !== "" ? [foe.description] : [],
    hp: foe.hp,
    max_hp: foe.max_hp,
    str_score: foe.str_score,
    // Backend doesn't track current vs. max STR for foes (player STR
    // diminishment is a Cairn-specific harm-overflow rule). Mirror
    // current → max so the tracker doesn't flag a phantom delta.
    max_str_score: foe.str_score,
    dex_score: foe.dex_score,
    wil_score: foe.wil_score,
    armor: foe.armor,
    weapon_damage_die: foe.weapon_damage_die,
    morale: null,
    morale_broken: false,
    status: deriveCombatantStatus(foe),
  };
}

// Status precedence: dead > fled > incapacitated > active. We choose
// "incapacitated" for `critically_wounded` because the player can still
// finish the foe off; Cairn's "critical damage" leaves the target
// alive but downed.
function deriveCombatantStatus(foe: BackendEnemyCombatant): CombatantStatus {
  if (foe.defeated) return "dead";
  if (foe.fled) return "fled";
  if (foe.critically_wounded) return "incapacitated";
  return "active";
}

// --- Render helpers ----------------------------------------------------

// HP bar tier — three states so the rail can color the bar without
// inventing arbitrary thresholds. "fresh" stays gold-tarnished, "wounded"
// shifts to rust, "critical" goes blood-red. The thresholds are halves
// of max because Cairn doesn't define standard HP bands; halves match
// the morale rule (when half are down).
export type CombatantHpTier = "fresh" | "wounded" | "critical" | "down";

export function combatantHpTier(c: CombatantState): CombatantHpTier {
  if (c.hp <= 0) return "down";
  if (c.max_hp <= 0) return "fresh";
  const ratio = c.hp / c.max_hp;
  if (ratio <= 0.34) return "critical";
  if (ratio < 1) return "wounded";
  return "fresh";
}

// Ordered status priority so the chip stack reads "dead → fled →
// incapacitated → active". Active is rendered as no chip — chips are
// only worth screen real estate when they signal something abnormal.
export function combatantStatusLabel(status: CombatantStatus): string | null {
  switch (status) {
    case "dead":
      return "Dead";
    case "fled":
      return "Fled";
    case "incapacitated":
      return "Down";
    case "active":
      return null;
  }
}

// "Round 1 · DEX save to act" / "Round 3" / "Encounter cleared".
// Returns null when no encounter is tracked.
export function encounterHeadline(state: CombatStateSlot): string | null {
  if (state === null) return null;
  if (!state.active) return state.summary ?? "Encounter cleared";
  if (state.round <= 0) return "Encounter brewing";
  if (state.round === 1 && !state.player_ready) {
    return "Round 1 · DEX save to act";
  }
  return `Round ${state.round}`;
}

// True when the player still owes a first-round DEX save before they
// can act. The chat composer uses this to hint at the player without
// blocking input — Cairn allows a failed save, you just lose the
// initial swing.
export function firstRoundActionGated(state: CombatStateSlot): boolean {
  return state !== null && state.active && state.round === 1 && !state.player_ready;
}

// Sort order for the foe list: standing first, then incapacitated,
// then fled, then dead. Within a tier, lower HP first so the player
// sees who's about to drop. Stable on ties via id.
export function sortCombatants(combatants: readonly CombatantState[]): CombatantState[] {
  const STATUS_RANK: Record<CombatantStatus, number> = {
    active: 0,
    incapacitated: 1,
    fled: 2,
    dead: 3,
  };
  return [...combatants].sort((a, b) => {
    const r = STATUS_RANK[a.status] - STATUS_RANK[b.status];
    if (r !== 0) return r;
    if (a.hp !== b.hp) return a.hp - b.hp;
    return a.id.localeCompare(b.id);
  });
}
