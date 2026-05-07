// Helpers for the NPCs inspector surface.
//
// F-04 (Dynamic NPC Updates) gave the backend turn pipeline a bounded
// post-outcome `NPCUpdater` that can create, update, or retire NPCs.
// Mirroring F-03 for threads, every touched NPC id lands on the most
// recent `OracleOutcome.referenced_npc_ids`, and retired NPCs stay in
// canon (`status: "retired"`) instead of being deleted so memory can
// still reference them.
//
// This module is deliberately the dual of `threads.ts` — same shape of
// "recently touched" lookup + same kind of stable display sort — so the
// two panels feel coherent and the tests can rehearse the same edge
// cases (legacy singular fallback, multi-outcome lookback, stable
// canonical ordering).
//
// Pure module: no Svelte runes, no DOM. The Inspector derives the
// touched set and hands it down so the helpers stay unit-testable.

import type { GameState, NPC, OracleOutcome } from "./types";

/**
 * Default trailing-outcome window for "recently advanced" highlights.
 * One outcome — the latest — matches what the player just did, which is
 * the only thing the panel pulse is meant to call attention to. The
 * parameter exists so a future surface (e.g. a "this scene's NPCs"
 * hint) can widen without forking the helper.
 */
export const DEFAULT_NPC_LOOKBACK = 1;

/**
 * Player-facing label for a visible NPC.
 *
 * H-01 makes the backend keep two identities at once: canonical `name`
 * for continuity, safe `player_label` for anything the player can see.
 * The roster and receipt surfaces must always prefer the safe label so a
 * recurring figure can remain "the ash-veiled bellringer" until the
 * fiction explicitly grants their true name.
 */
export function npcDisplayLabel(npc: NPC): string {
  const label = npc.player_label.trim();
  return label === "" ? npc.name : label;
}

/**
 * True when the player currently knows this figure by descriptor/sign
 * rather than by proper name.
 */
export function npcKnownByDescriptor(npc: NPC): boolean {
  return npc.player_label_kind === "descriptor";
}

/**
 * Collect the set of NPC ids touched by the latest `lookback` oracle
 * outcomes.
 *
 * Reads `OracleOutcome.referenced_npc_ids` (plural, F-04) and falls
 * back to the legacy singular `referenced_npc_id` so older state blobs
 * still highlight correctly. Both lists are merged and deduplicated;
 * the returned set has no meaningful iteration order.
 */
export function recentlyTouchedNpcIds(
  state: GameState,
  lookback: number = DEFAULT_NPC_LOOKBACK,
): ReadonlySet<string> {
  if (lookback <= 0 || state.oracle_history.length === 0) return new Set();

  const ids = new Set<string>();
  const start = Math.max(0, state.oracle_history.length - lookback);
  for (let i = start; i < state.oracle_history.length; i += 1) {
    const outcome = state.oracle_history[i];
    if (outcome === undefined) continue;
    addOutcomeNpcIds(outcome, ids);
  }
  return ids;
}

/**
 * Visible NPCs referenced by an outcome, in receipt order.
 *
 * The backend already filters `referenced_npc_ids` down to the visible
 * roster (H-02), but we still resolve through the live `npcs` array so
 * stale ids or legacy singular-only outcomes safely collapse away in the
 * UI instead of rendering dead pills.
 */
export function referencedNpcsForOutcome(
  npcs: readonly NPC[],
  outcome: OracleOutcome,
): NPC[] {
  const byId = new Map(npcs.map((npc) => [npc.id, npc] as const));
  return referencedNpcIds(outcome)
    .map((id) => byId.get(id) ?? null)
    .filter((npc): npc is NPC => npc !== null);
}

/**
 * Sort NPCs for display in the NPCs panel.
 *
 * Layout invariant:
 *   [active, recently-touched first] → [active, untouched]
 *   → [retired, recently-touched first] → [retired, untouched]
 *
 * Retired NPCs sink because they no longer drive play, but they stay
 * visible so the player can see who has left the cast (and so the
 * canonical roster matches what the backend actually persists). Within
 * a status group, recently-touched cards float to the top so the eye
 * lands on what just changed; the panel paints those cards with a
 * one-shot pulse so the visual cue compounds.
 *
 * The original `npcs` array is not mutated — we return a new array.
 */
export function sortNpcsForDisplay(
  npcs: readonly NPC[],
  recentlyTouched: ReadonlySet<string>,
): NPC[] {
  // We attach the original index as a stable secondary key so NPCs
  // that tie on (status, touched) preserve their canonical order.
  // Array.sort is stable in modern runtimes, but tying through an
  // explicit index keeps the contract obvious without depending on
  // engine spec, and matches what `sortThreadsForDisplay` does.
  const decorated = npcs.map((npc, index) => ({
    npc,
    index,
    statusRank: npc.status === "active" ? 0 : 1,
    touchedRank: recentlyTouched.has(npc.id) ? 0 : 1,
  }));
  decorated.sort((a, b) => {
    if (a.statusRank !== b.statusRank) return a.statusRank - b.statusRank;
    if (a.touchedRank !== b.touchedRank) return a.touchedRank - b.touchedRank;
    return a.index - b.index;
  });
  return decorated.map((entry) => entry.npc);
}

function addOutcomeNpcIds(outcome: OracleOutcome, target: Set<string>): void {
  for (const id of outcome.referenced_npc_ids) {
    if (id !== "") target.add(id);
  }
  // Older outcomes (pre-F-04) only carry the singular id. We still
  // honor it so a freshly-loaded older campaign doesn't lose the
  // highlight cue when its newest turn predates the plural field.
  if (outcome.referenced_npc_id !== null && outcome.referenced_npc_id !== "") {
    target.add(outcome.referenced_npc_id);
  }
}

function referencedNpcIds(outcome: OracleOutcome): string[] {
  const ids = new Set<string>();
  addOutcomeNpcIds(outcome, ids);
  return [...ids];
}
