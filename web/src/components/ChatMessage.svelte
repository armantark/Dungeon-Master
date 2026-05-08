<!--
@component
ChatMessage — one entry in the chat feed.

Four speakers:
  dm        — narrative voice (Cormorant), parchment-tinted left rail
  player    — first-person action, plain
  system    — engine voice (Alagard pixel), subdued
  ooc       — Archivist / out-of-character rules explainer (F-10).
              Same Alagard pixel voice as `system` but with a
              verdigris rail + an "OOC" speaker tag so the player
              can tell at a glance that the bubble is non-canonical.
              When `question` is set, it renders above the answer
              as a `Q:` row to keep the exchange visually paired.

DM messages produced by an oracle outcome carry a collapsible
MechanicalReceipt so the player can verify the dice on demand.
-->
<script lang="ts">
  import CollapsedThinking from "./CollapsedThinking.svelte";
  import MechanicalReceipt from "./MechanicalReceipt.svelte";
  import MessageActions from "./MessageActions.svelte";
  import StageChecklist from "./StageChecklist.svelte";
  import { liveTime } from "../lib/live-time.svelte";
  import { renderMarkdown } from "../lib/markdown";
  import {
    formatRoundtripMs,
    stageTimingsToProgress,
    totalRoundtripMs,
  } from "../lib/stage-timings";
  import type { GameThread, NPC, OracleOutcome, StageTiming } from "../lib/types";

  type Props = {
    eventId: string;
    speaker: "dm" | "player" | "system" | "ooc";
    text: string;
    timestamp?: string | null;
    outcome?: OracleOutcome | null;
    canRegenerate?: boolean;
    thinking?: string | null;
    // Persisted pipeline timings for this message (narrative events
    // only). When present the reasoning-trace strip surfaces a
    // "Total · 12.4s" pill that stays visible even when collapsed,
    // and expanding the trace shows a compact stage checklist above
    // the text. Empty / undefined → no checklist, no pill — keeps
    // legacy saves and non-narrative speakers rendering unchanged.
    stageTimings?: readonly StageTiming[];
    streaming?: boolean;
    resuming?: boolean;
    question?: string | null;
    threads?: readonly GameThread[];
    npcs?: readonly NPC[];
  };
  const {
    eventId,
    speaker,
    text,
    timestamp = null,
    outcome = null,
    canRegenerate = false,
    thinking = null,
    stageTimings = [],
    streaming = false,
    resuming = false,
    question = null,
    threads = [],
    npcs = [],
  }: Props = $props();

  // Derive the renderer-friendly progress shape and the total-roundtrip
  // pill label up-front so the template stays declarative. Both
  // collapse to empty when no timings are present, and downstream
  // components already handle that gracefully.
  const stageProgress = $derived(stageTimingsToProgress(stageTimings));
  const totalSummary = $derived.by<string | null>(() => {
    const ms = totalRoundtripMs(stageTimings);
    if (ms === null) return null;
    return `Total · ${formatRoundtripMs(ms)}`;
  });
  const hasTimings = $derived(stageTimings.length > 0);

  // Reactive relative-time label. We read `liveTime.now` (the shared
  // 5s tick) inside a $derived so every ChatMessage re-derives its
  // label as the clock advances — without each row spinning up its
  // own setInterval. Reading `timestamp` *and* `liveTime.now` inside
  // a derived is what makes the label live; if we kept the old
  // `function relative(iso)` the value would be frozen at first
  // render even though the underlying state changes.
  const relativeLabel = $derived.by<string | null>(() => {
    if (!timestamp) return null;
    const seconds = Math.max(
      0,
      (liveTime.now - new Date(timestamp).getTime()) / 1000,
    );
    if (seconds < 60) return `${Math.round(seconds)}s ago`;
    if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
    return new Date(timestamp).toLocaleString();
  });

  // Model-authored bubbles render as markdown (DM narration, OOC
  // explainer answers, and system event prose). Player-typed messages
  // stay literal so a stray underscore in a character name doesn't
  // accidentally flip into italics. The renderer is sync + sanitized;
  // see lib/markdown.ts for the rationale.
  const isMarkdownSpeaker = $derived(
    speaker === "dm" || speaker === "ooc" || speaker === "system",
  );
  const renderedHtml = $derived(isMarkdownSpeaker ? renderMarkdown(text) : "");
</script>

<article class="msg msg--{speaker}" class:streaming>
  <div class="meta pixel">
    <span class="speaker">
      {#if speaker === "dm"}DM
      {:else if speaker === "player"}You
      {:else if speaker === "ooc"}OOC · Archivist
      {:else}Engine{/if}
    </span>
    {#if streaming}
      <!--
        We split "resuming" out from "streaming" in the meta tag so
        the player has an unambiguous cue that the bubble below
        started its life on a previous page (the alternative — both
        states sharing the "streaming…" label — would silently hide
        a non-trivial state transition). The `resuming` class
        carries a different accent so reduced-motion users can
        still tell them apart at a glance.
      -->
      <span class="streaming-tag" class:resuming>
        {resuming ? "resuming…" : "streaming…"}
      </span>
    {:else if relativeLabel}
      <span class="time">{relativeLabel}</span>
    {/if}
  </div>

  {#snippet stageHeader()}
    <!--
      Compact, frameless stage checklist embedded at the top of the
      reasoning-trace expansion. We reuse the same renderer as the
      live in-flight checklist so persisted and live timings look
      identical — the only difference is `framed={false}` because
      the trace already provides the panel border.
    -->
    <StageChecklist stages={stageProgress} framed={false} />
  {/snippet}

  {#if speaker === "dm" || speaker === "ooc"}
    <!--
      OOC bubbles also surface the model's reasoning trace via the
      collapsed-thinking block. The explainer is OOC anyway, so
      letting the player peek at the trace is consistent with how
      DM bubbles already expose thinking; it doesn't break the
      no-mutation contract because the trace is ephemeral and never
      enters action_log.

      `forceVisible` is set when we have stage timings even if the
      model produced no reasoning text — the timings alone justify
      keeping the strip on screen so the player can read the total
      roundtrip and inspect per-stage breakdown.
    -->
    <CollapsedThinking
      text={thinking ?? ""}
      streaming={streaming && (thinking ?? "") !== ""}
      hideWhenEmpty={!streaming && !hasTimings}
      forceVisible={hasTimings && !streaming}
      summary={totalSummary}
      headerSnippet={hasTimings ? stageHeader : undefined}
    />
  {/if}

  {#if speaker === "ooc" && question !== null && question !== ""}
    <!--
      We render the question as a `Q:` row up-front so the OOC card
      reads as a self-contained Q+A pair even after the page is
      reloaded (well, until reload clears the ephemeral note, at
      which point the whole exchange is gone — but during a session
      the player can still scan back through the log without
      having to remember which question fired which answer).
    -->
    <div class="ooc-question pixel">
      <span class="ooc-question-label">Q</span>
      <span class="ooc-question-body">{question}</span>
    </div>
  {/if}

  <div class="body">
    {#if text === "" && streaming}
      <p class="muted pixel awaiting">Awaiting first token…</p>
    {:else if isMarkdownSpeaker}
      <!--
        We render model-authored prose through the markdown pipeline
        so emphasis/lists/code land as real structure, then append
        the streaming caret outside the parsed HTML so it doesn't
        get swallowed by an unclosed inline mark mid-stream.
      -->
      <div class="prose">{@html renderedHtml}{#if streaming}<span class="caret" aria-hidden="true">▌</span>{/if}</div>
    {:else}
      <p>{text}{#if streaming}<span class="caret" aria-hidden="true">▌</span>{/if}</p>
    {/if}
  </div>

  {#if outcome}
    <MechanicalReceipt {outcome} {threads} {npcs} defaultOpen={streaming} />
  {/if}

  <MessageActions eventId={eventId} visible={!streaming && speaker === "dm" && canRegenerate} />
</article>

<style>
  .msg {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    padding: 0.4rem 0;
  }
  .meta {
    display: flex;
    align-items: baseline;
    gap: 0.6rem;
    font-size: 0.72rem;
    color: var(--gold-tarnished);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  .meta .speaker {
    color: var(--gold-bright);
  }
  .meta .time {
    color: var(--paper-shadow);
    font-size: 0.65rem;
  }
  .meta .streaming-tag {
    color: var(--gold-candle);
    font-size: 0.65rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
  }
  .meta .streaming-tag.resuming {
    /*
     * Verdigris/teal accent matches the OOC rail and visually
     * distances "resuming…" from "streaming…" without inventing a
     * new color in the system. The connotation is "we picked this
     * up from somewhere else", which the cooler hue carries.
     */
    color: color-mix(in oklab, var(--verdigris, #4a7c74) 75%, var(--gold-candle));
  }
  .awaiting {
    /* Holding line that fills the bubble until the first content token
     * arrives. Without it, the provisional bubble would render as an
     * empty <p> and look like a layout glitch on slow connections. */
    color: var(--paper-shadow);
    font-style: italic;
  }
  .caret {
    /* The blinking caret is the universal "still typing" cue. We use
     * the lower-half block so it lines up with the cap height of
     * Cormorant; a vertical bar would float above the baseline. */
    display: inline-block;
    margin-left: 0.15rem;
    color: var(--gold-bright);
    animation: caret-blink 0.95s steps(2, jump-none) infinite;
  }
  @keyframes caret-blink {
    50% { opacity: 0.15; }
  }
  @media (prefers-reduced-motion: reduce) {
    .caret { animation: none; opacity: 0.6; }
  }
  .msg.streaming {
    /* Subtle outer glow so the streaming bubble stands out from the
     * persisted ones without feeling like a different surface. */
    background: linear-gradient(
      90deg,
      color-mix(in oklab, var(--gold-tarnished) 8%, transparent),
      transparent 40%
    );
  }
  .body p {
    margin: 0;
    white-space: pre-wrap;
  }

  /*
   * Markdown surface. The renderer produces standard block elements
   * (p, ul, ol, blockquote, h1-h6, code, pre, table) and we tune
   * each so the parchment voice is preserved across DM/OOC/system.
   * Per-speaker color/family/size overrides live further down — we
   * keep the structural rules here so they don't have to be repeated
   * three times.
   */
  .body .prose {
    display: block;
  }
  .body .prose > :global(*:first-child) {
    margin-top: 0;
  }
  .body .prose > :global(*:last-child) {
    margin-bottom: 0;
  }
  .body .prose :global(p) {
    margin: 0 0 0.6em;
    line-height: inherit;
  }
  .body .prose :global(p:last-child) {
    margin-bottom: 0;
  }
  .body .prose :global(ul),
  .body .prose :global(ol) {
    margin: 0.2em 0 0.6em;
    padding-left: 1.4em;
  }
  .body .prose :global(li) {
    margin: 0.1em 0;
  }
  .body .prose :global(li > p) {
    margin: 0;
  }
  .body .prose :global(strong) {
    color: var(--gold-bright);
    font-weight: 600;
  }
  .body .prose :global(em) {
    font-style: italic;
  }
  .body .prose :global(blockquote) {
    margin: 0.4em 0;
    padding: 0.1em 0.9em;
    border-left: 2px solid color-mix(in oklab, var(--gold-tarnished) 65%, transparent);
    color: color-mix(in oklab, var(--paper-bone) 80%, transparent);
    font-style: italic;
  }
  .body .prose :global(code) {
    /*
     * Inline code: the model often quotes JSON keys or short symbols
     * (`"active": false`) in the OOC voice — a monospace tint lets
     * those read as machine voice without breaking the parchment.
     */
    padding: 0.05em 0.35em;
    border-radius: 2px;
    background: color-mix(in oklab, var(--ink-deep) 80%, transparent);
    color: color-mix(in oklab, var(--paper-bone) 92%, transparent);
    font-family: var(--font-pixel, ui-monospace, SFMono-Regular, Menlo, monospace);
    font-size: 0.92em;
  }
  .body .prose :global(pre) {
    margin: 0.4em 0;
    padding: 0.6em 0.8em;
    border: 1px solid color-mix(in oklab, var(--gold-tarnished) 40%, transparent);
    border-radius: 3px;
    background: color-mix(in oklab, var(--ink-deep) 92%, transparent);
    overflow-x: auto;
  }
  .body .prose :global(pre code) {
    padding: 0;
    background: transparent;
    font-size: 0.88em;
    line-height: 1.45;
  }
  .body .prose :global(h1),
  .body .prose :global(h2),
  .body .prose :global(h3),
  .body .prose :global(h4),
  .body .prose :global(h5),
  .body .prose :global(h6) {
    margin: 0.4em 0 0.3em;
    font-family: var(--font-display, var(--font-serif, serif));
    color: var(--gold-bright);
    letter-spacing: 0.02em;
    line-height: 1.25;
  }
  .body .prose :global(h1) { font-size: 1.35em; }
  .body .prose :global(h2) { font-size: 1.22em; }
  .body .prose :global(h3) { font-size: 1.1em; }
  .body .prose :global(h4),
  .body .prose :global(h5),
  .body .prose :global(h6) { font-size: 1em; }
  .body .prose :global(hr) {
    margin: 0.7em 0;
    border: 0;
    border-top: 1px solid color-mix(in oklab, var(--gold-tarnished) 40%, transparent);
  }
  .body .prose :global(a) {
    color: var(--gold-bright);
    text-decoration: underline;
    text-decoration-color: color-mix(in oklab, var(--gold-tarnished) 70%, transparent);
  }
  .body .prose :global(a:hover) {
    text-decoration-color: var(--gold-bright);
  }
  .body .prose :global(table) {
    margin: 0.4em 0;
    border-collapse: collapse;
    font-size: 0.95em;
  }
  .body .prose :global(th),
  .body .prose :global(td) {
    padding: 0.3em 0.55em;
    border: 1px solid color-mix(in oklab, var(--gold-tarnished) 35%, transparent);
    text-align: left;
  }
  .body .prose :global(th) {
    color: var(--gold-bright);
    font-weight: 600;
  }

  .msg--dm {
    border-left: 2px solid var(--gold-tarnished);
    padding-left: 1rem;
  }
  .msg--dm .body p,
  .msg--dm .body .prose {
    color: color-mix(in oklab, var(--paper-warm) 95%, transparent);
    font-size: 1.08rem;
    line-height: 1.65;
    /* The DM speaks. Italics here make the narration feel like it's being
       *spoken to you*, not read off a sheet. */
    font-style: normal;
  }

  .msg--player {
    border-left: 2px dashed color-mix(in oklab, var(--paper-bone) 35%, transparent);
    padding-left: 1rem;
  }
  .msg--player .body p {
    color: color-mix(in oklab, var(--paper-bone) 85%, transparent);
    font-style: italic;
  }

  .msg--system {
    border-left: 2px solid color-mix(in oklab, var(--rust-iron) 60%, transparent);
    padding-left: 1rem;
  }
  .msg--system .body p,
  .msg--system .body .prose {
    color: color-mix(in oklab, var(--paper-shadow) 95%, transparent);
    font-family: var(--font-pixel);
    font-size: 0.85rem;
    line-height: 1.45;
    -webkit-font-smoothing: none;
  }
  .msg--system .meta .speaker {
    color: color-mix(in oklab, var(--rust-iron) 70%, var(--paper-stained));
  }

  /*
   * F-10 OOC Archivist voice. Verdigris rail (greenish-blue) sets it
   * apart from DM/player/system at a glance — the player is a
   * pattern-matcher and rail color is the cheapest cue. Body type is
   * a slightly more legible Cormorant than `system` because OOC
   * answers can run several paragraphs and pixel font at length is
   * fatiguing. We still keep the OOC tag pixelated so the
   * "engine voice" connotation lands.
   */
  .msg--ooc {
    border-left: 2px solid color-mix(in oklab, var(--verdigris, #4a7c74) 70%, var(--gold-tarnished));
    padding-left: 1rem;
    background: linear-gradient(
      90deg,
      color-mix(in oklab, var(--verdigris, #4a7c74) 6%, transparent),
      transparent 65%
    );
  }
  .msg--ooc .meta .speaker {
    color: color-mix(in oklab, var(--verdigris, #4a7c74) 70%, var(--paper-bone));
    letter-spacing: 0.06em;
  }
  .msg--ooc .body p,
  .msg--ooc .body .prose {
    color: color-mix(in oklab, var(--paper-bone) 95%, transparent);
    font-family: var(--font-prose, var(--font-serif, serif));
    font-size: 0.98rem;
    line-height: 1.6;
  }
  .ooc-question {
    display: flex;
    gap: 0.5rem;
    align-items: baseline;
    padding: 0.25rem 0;
    color: color-mix(in oklab, var(--paper-shadow) 95%, transparent);
    font-size: 0.78rem;
    line-height: 1.4;
  }
  .ooc-question-label {
    flex: 0 0 auto;
    color: color-mix(in oklab, var(--verdigris, #4a7c74) 75%, var(--paper-bone));
    letter-spacing: 0.08em;
  }
  .ooc-question-body {
    flex: 1 1 auto;
    color: color-mix(in oklab, var(--paper-bone) 80%, transparent);
    font-style: italic;
  }
</style>
