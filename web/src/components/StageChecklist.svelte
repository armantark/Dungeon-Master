<!--
@component
StageChecklist — live backend pipeline progress.

Why this exists: the model used to take several seconds before any
prose token arrived because the turn pipeline runs a chain of
LLM-backed steps (planner → mechanics → continuity classifier →
thread/NPC updaters → narration prep) before the narrator actually
streams. The hybrid continuity path can also add a short
post-narration reconciliation step before the final state commits.
The chat surface had no way to surface that work, so a long turn felt
like a freeze.

The backend now emits a typed `stage` NDJSON event for each step, in
canonical pipeline order, with `pending` / `active` / `done` /
`skipped` statuses. This component is the visual receipt for that
stream — a compact checklist that reads like a "the engine is
working" status panel rather than a generic spinner.

Design intent:
  - Engine voice (Alagard pixel) so the strip reads as machinery,
    subordinate to the DM's parchment voice once prose arrives.
  - Status glyphs ahead of the label:
      pending  — empty box  ☐
      active   — filled gold dot pulsing (the engine is here right now)
      done     — checkmark in tarnished gold
      skipped  — em-dash, dimmed, and strikethrough on the label so
                 the player can scan past it without confusion
  - We never render an empty checklist; the parent gates on
    `stages.length > 0` so the strip doesn't claim space pre-stream.
-->
<script lang="ts">
  import type { StageProgress } from "../lib/store.svelte";

  type Props = {
    stages: readonly StageProgress[];
    framed?: boolean;
  };
  const { stages, framed = true }: Props = $props();

  const sorted = $derived(
    stages.slice().sort((a, b) => a.order - b.order),
  );

  // Live tick counter drives reactive re-reads of `performance.now()`
  // for active stages without forcing a per-stage interval.
  let tick = $state(0);
  const hasActive = $derived(sorted.some((s) => s.status === "active"));

  $effect(() => {
    if (!hasActive) return;
    const id = setInterval(() => { tick++; }, 100);
    return () => clearInterval(id);
  });

  function formatMs(ms: number): string {
    if (ms < 1000) return `${Math.round(ms)}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  }

  function stageDuration(s: StageProgress): string | null {
    // Force dependency on `tick` so Svelte re-evaluates while active.
    void tick;
    if (s.startedAt === null) return null;
    if (s.completedAt !== null) return formatMs(s.completedAt - s.startedAt);
    return formatMs(performance.now() - s.startedAt);
  }

  const allDone = $derived(
    sorted.length > 0 &&
    sorted.every((s) => s.status === "done" || s.status === "skipped"),
  );

  const totalDuration = $derived.by(() => {
    if (!allDone) return null;
    const starts = sorted
      .map((s) => s.startedAt)
      .filter((t): t is number => t !== null);
    const ends = sorted
      .map((s) => s.completedAt)
      .filter((t): t is number => t !== null);
    if (starts.length === 0 || ends.length === 0) return null;
    return formatMs(Math.max(...ends) - Math.min(...starts));
  });
</script>

{#if sorted.length > 0}
  <ul class="checklist pixel" class:framed aria-live="polite">
    {#each sorted as stage (stage.stageId)}
      <li class="row row--{stage.status}">
        <span class="glyph" aria-hidden="true">
          {#if stage.status === "active"}
            <span class="dot pulse"></span>
          {:else if stage.status === "done"}
            ✓
          {:else if stage.status === "skipped"}
            —
          {:else}
            ☐
          {/if}
        </span>
        <span class="label">{stage.label}</span>
        <span class="status-group">
          <span class="status pixel">
            {#if stage.status === "active"}…{:else if stage.status === "done"}done{:else if stage.status === "skipped"}skipped{:else}pending{/if}
          </span>
          {#if stageDuration(stage)}
            <span class="timing pixel" class:live={stage.status === "active"}>
              {stageDuration(stage)}
            </span>
          {/if}
        </span>
      </li>
    {/each}
    {#if totalDuration}
      <li class="total-row">
        <span class="total-label pixel">Total</span>
        <span class="total-value pixel">{totalDuration}</span>
      </li>
    {/if}
  </ul>
{/if}

<style>
  .checklist {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 0.18rem;
    font-size: 0.74rem;
    color: var(--paper-shadow);
    -webkit-font-smoothing: none;
  }
  .checklist.framed {
    margin: 0.35rem 0 0.55rem;
    padding: 0.5rem 0.7rem;
    /* Subtle bordered card so the checklist reads as an inset
     * status panel rather than free-floating prose. The verdigris
     * tint mirrors the OOC rail palette since both surfaces are
     * "engine voice over the parchment". */
    background: color-mix(in oklab, var(--ink-deep) 65%, transparent);
    border: 1px solid color-mix(in oklab, var(--gold-tarnished) 45%, transparent);
    border-radius: 3px;
    box-shadow:
      inset 0 1px 0 color-mix(in oklab, var(--gold-tarnished) 14%, transparent);
  }
  .row {
    display: grid;
    grid-template-columns: 1.1rem 1fr auto;
    align-items: center;
    gap: 0.5rem;
    line-height: 1.4;
  }
  .status-group {
    display: flex;
    align-items: baseline;
    gap: 0.45rem;
    justify-content: flex-end;
  }
  .timing {
    font-size: 0.6rem;
    color: color-mix(in oklab, var(--gold-tarnished) 70%, transparent);
    letter-spacing: 0.04em;
    font-variant-numeric: tabular-nums;
    min-width: 2.8em;
    text-align: right;
  }
  .timing.live {
    color: var(--gold-bright);
  }
  .row--done .timing {
    color: color-mix(in oklab, var(--gold-tarnished) 55%, transparent);
  }
  .row--skipped .timing {
    color: color-mix(in oklab, var(--paper-shadow) 45%, transparent);
  }
  .total-row {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-top: 0.25rem;
    padding-top: 0.25rem;
    border-top: 1px solid color-mix(in oklab, var(--gold-tarnished) 25%, transparent);
  }
  .total-label {
    font-size: 0.65rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: color-mix(in oklab, var(--paper-shadow) 80%, transparent);
  }
  .total-value {
    font-size: 0.65rem;
    letter-spacing: 0.04em;
    font-variant-numeric: tabular-nums;
    color: var(--gold-tarnished);
  }
  .glyph {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 1.05rem;
    height: 1.05rem;
    color: var(--paper-shadow);
    font-family: var(--font-pixel);
  }
  .label {
    /*
     * Truncate gracefully if a label is unexpectedly long; the
     * canonical labels are short ("Updating threads" etc.) so this
     * is a safety rail rather than a routine wrap point.
     */
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .status {
    color: color-mix(in oklab, var(--paper-shadow) 70%, transparent);
    font-size: 0.65rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }

  /* --- pending: muted, no animation, holding line for the player */
  .row--pending .glyph {
    color: color-mix(in oklab, var(--paper-shadow) 55%, transparent);
  }
  .row--pending .label {
    color: color-mix(in oklab, var(--paper-bone) 55%, transparent);
  }

  /* --- active: where the engine is right now. Pulsing gold dot. */
  .row--active .label {
    color: var(--paper-warm);
  }
  .row--active .status {
    color: var(--gold-bright);
  }
  .dot {
    display: inline-block;
    width: 0.55rem;
    height: 0.55rem;
    background: var(--gold-bright);
    box-shadow: 0 0 6px color-mix(in oklab, var(--gold-bright) 70%, transparent);
  }
  .dot.pulse {
    animation: stage-pulse 1.05s ease-in-out infinite;
  }
  @keyframes stage-pulse {
    0%, 100% { opacity: 0.55; transform: scale(0.85); }
    50% { opacity: 1; transform: scale(1.1); }
  }
  @media (prefers-reduced-motion: reduce) {
    .dot.pulse { animation: none; opacity: 0.95; }
  }

  /* --- done: tarnished checkmark, label fades to bone */
  .row--done .glyph {
    color: var(--gold-tarnished);
  }
  .row--done .label {
    color: color-mix(in oklab, var(--paper-bone) 78%, transparent);
  }
  .row--done .status {
    color: color-mix(in oklab, var(--gold-tarnished) 80%, transparent);
  }

  /* --- skipped: dimmed em-dash + strikethrough so the player can
   * visually shed them at a glance; we still render them to make the
   * checklist a stable "what would have happened" record rather than
   * silently disappearing rows. */
  .row--skipped .glyph {
    color: color-mix(in oklab, var(--paper-shadow) 50%, transparent);
  }
  .row--skipped .label {
    color: color-mix(in oklab, var(--paper-shadow) 65%, transparent);
    text-decoration: line-through;
    text-decoration-color: color-mix(in oklab, var(--paper-shadow) 50%, transparent);
  }
  .row--skipped .status {
    color: color-mix(in oklab, var(--paper-shadow) 55%, transparent);
  }
</style>
