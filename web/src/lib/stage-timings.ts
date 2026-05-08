// Pure adapters between persisted `StageTiming[]` and the live
// `StageProgress[]` shape that `StageChecklist.svelte` consumes.
//
// Why an adapter rather than a second renderer:
//   The live checklist (during a stream) and the in-trace checklist
//   (after the turn commits) need to look identical — same glyphs,
//   same per-stage timing, same total row. The data shapes differ,
//   though: live timings are `performance.now()` floats; persisted
//   timings are ISO date strings. Converting persisted strings to ms-
//   since-epoch numbers makes them subtractable in the same way as
//   `performance.now()` deltas, so the renderer never has to branch
//   on which source it's reading.
//
// Why ms-since-epoch is OK:
//   Within one rendered checklist all timestamps come from the same
//   clock domain, so the absolute reference doesn't matter. We only
//   ever subtract pairs of timestamps that share an origin.

import type { StageProgress } from "./store.svelte";
import type { StageTiming } from "./types";

function isoToMs(value: string | null): number | null {
  if (value === null) return null;
  const ms = Date.parse(value);
  return Number.isNaN(ms) ? null : ms;
}

/**
 * Convert the persisted timing shape to the renderer-friendly shape.
 * The output has the same structure as the live `StageProgress` array
 * built by `applyStageEvent`, so `StageChecklist` can render it
 * without knowing which source it came from.
 */
export function stageTimingsToProgress(
  timings: readonly StageTiming[],
): StageProgress[] {
  return timings.map((t, index) => ({
    stageId: t.stage_id,
    label: t.label,
    status: t.status,
    order: index,
    startedAt: isoToMs(t.started_at),
    completedAt: isoToMs(t.completed_at),
  }));
}

/**
 * Compact roundtrip number for the strip pill — the wall-clock span
 * from the earliest started_at to the latest completed_at across all
 * stages that actually ran. Returns null when no stage has both a
 * start and an end (so the renderer can hide the pill cleanly rather
 * than render "0ms").
 */
export function totalRoundtripMs(timings: readonly StageTiming[]): number | null {
  let earliestStart: number | null = null;
  let latestEnd: number | null = null;
  for (const t of timings) {
    const start = isoToMs(t.started_at);
    const end = isoToMs(t.completed_at);
    if (start !== null && (earliestStart === null || start < earliestStart)) {
      earliestStart = start;
    }
    if (end !== null && (latestEnd === null || end > latestEnd)) {
      latestEnd = end;
    }
  }
  if (earliestStart === null || latestEnd === null) return null;
  if (latestEnd < earliestStart) return null;
  return latestEnd - earliestStart;
}

/**
 * Display string for `totalRoundtripMs(...)`. Mirrors the format in
 * `StageChecklist.svelte` so the strip pill and the per-stage timing
 * column read with the same conventions ("ms" under one second,
 * "s" with one decimal otherwise).
 */
export function formatRoundtripMs(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}
