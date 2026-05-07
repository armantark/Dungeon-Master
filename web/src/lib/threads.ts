// Helpers for the Threads inspector surface.
//
// F-03 (Dynamic Thread Updates) made the backend mutate canonical
// threads from the resolved-turn pipeline: a single turn can now
// create, update, or resolve threads through the post-outcome
// `ThreadUpdater`. The TS surface that consumes that is purely
// derived — every advanced thread id lands on the most recent
// OracleOutcome under `referenced_thread_ids`. We turn that into:
//   1. A bounded "recently advanced" set so the Threads panel can
//      pulse / highlight cards the player should look at.
//   2. A sort key so active threads float above resolved ones, and
//      within active, the just-touched ones float to the top.
//
// We deliberately keep this layer pure (no Svelte runes, no DOM) so
// the logic is unit-testable without a component harness.

import type { GameState, GameThread, OracleOutcome } from "./types";

/**
 * Default number of trailing oracle outcomes whose touched-thread ids
 * we surface as "recently advanced". One is enough to ride the latest
 * turn; we expose the param so callers can widen if a future surface
 * (e.g. a "this scene's threads" hint) wants more lookback.
 */
export const DEFAULT_THREAD_LOOKBACK = 1;

/**
 * Collect the set of thread ids touched by the latest `lookback` oracle
 * outcomes.
 *
 * Reads `OracleOutcome.referenced_thread_ids` (plural, F-03) and falls
 * back to the legacy singular `referenced_thread_id` so older state
 * blobs still highlight correctly. Both lists are merged and
 * deduplicated; ordering of the returned set is not meaningful.
 */
export function recentlyTouchedThreadIds(
  state: GameState,
  lookback: number = DEFAULT_THREAD_LOOKBACK,
): ReadonlySet<string> {
  if (lookback <= 0 || state.oracle_history.length === 0) return new Set();

  const ids = new Set<string>();
  const start = Math.max(0, state.oracle_history.length - lookback);
  for (let i = start; i < state.oracle_history.length; i += 1) {
    const outcome = state.oracle_history[i];
    if (outcome === undefined) continue;
    addOutcomeThreadIds(outcome, ids);
  }
  return ids;
}

/**
 * Threads referenced by an outcome, in receipt order.
 *
 * We resolve ids against the current thread list rather than trusting the
 * outcome payload blindly so older/stale ids quietly disappear instead of
 * leaving dead navigation pills behind.
 */
export function referencedThreadsForOutcome(
  threads: readonly GameThread[],
  outcome: OracleOutcome,
): GameThread[] {
  const byId = new Map(threads.map((thread) => [thread.id, thread] as const));
  return referencedThreadIds(outcome)
    .map((id) => byId.get(id) ?? null)
    .filter((thread): thread is GameThread => thread !== null);
}

/**
 * Sort threads for display in the Threads panel.
 *
 * Layout invariant:
 *   [active, recently-touched first] → [active, untouched]
 *   → [resolved, recently-touched first] → [resolved, untouched]
 *
 * Resolved threads sink because their stakes no longer drive play, but
 * we keep them visible so the player can still see what closed. Within
 * a status group, recently-touched cards float to the top so the eye
 * lands on them first; the panel also paints them with a subtle pulse
 * (CSS-side) so the visual cue compounds.
 *
 * The original `threads` array is not mutated — we return a new array.
 */
export function sortThreadsForDisplay(
  threads: readonly GameThread[],
  recentlyTouched: ReadonlySet<string>,
): GameThread[] {
  // We attach the original index as a stable secondary key so threads
  // that tie on (status, touched) preserve their canonical order. JS's
  // Array.sort is stable in modern runtimes, but tying through an
  // index keeps the contract obvious without depending on engine spec.
  const decorated = threads.map((thread, index) => ({
    thread,
    index,
    statusRank: thread.status === "active" ? 0 : 1,
    touchedRank: recentlyTouched.has(thread.id) ? 0 : 1,
  }));
  decorated.sort((a, b) => {
    if (a.statusRank !== b.statusRank) return a.statusRank - b.statusRank;
    if (a.touchedRank !== b.touchedRank) return a.touchedRank - b.touchedRank;
    return a.index - b.index;
  });
  return decorated.map((entry) => entry.thread);
}

function addOutcomeThreadIds(outcome: OracleOutcome, target: Set<string>): void {
  for (const id of outcome.referenced_thread_ids) {
    if (id !== "") target.add(id);
  }
  // Older outcomes (pre-F-03) only carry the singular id. We still
  // honor it so a freshly-loaded older campaign doesn't lose the
  // highlight cue when its newest turn predates the plural field.
  if (outcome.referenced_thread_id !== null && outcome.referenced_thread_id !== "") {
    target.add(outcome.referenced_thread_id);
  }
}

function referencedThreadIds(outcome: OracleOutcome): string[] {
  const ids = new Set<string>();
  addOutcomeThreadIds(outcome, ids);
  return [...ids];
}
