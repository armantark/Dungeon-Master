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
  import type { OracleOutcome } from "../lib/types";

  type Props = {
    eventId: string;
    speaker: "dm" | "player" | "system" | "ooc";
    text: string;
    timestamp?: string | null;
    outcome?: OracleOutcome | null;
    canRegenerate?: boolean;
    // Persisted reasoning trace for this message. Optional because
    // player/system messages never have one, and DM messages only have
    // one once the backend persists thinking on `GameEvent`. Until
    // then, this is null and the block doesn't render.
    thinking?: string | null;
    // True only while the message is being streamed in. The chat feed
    // uses this for the synthetic provisional DM bubble; persisted
    // messages always render with `streaming = false`.
    streaming?: boolean;
    // F-10 OOC explainer: the player's verbatim question, rendered
    // as a `Q:` row above the answer. Only consulted when speaker is
    // `ooc`; ignored otherwise so callers can leave it null without
    // changing other layouts.
    question?: string | null;
  };
  const {
    eventId,
    speaker,
    text,
    timestamp = null,
    outcome = null,
    canRegenerate = false,
    thinking = null,
    streaming = false,
    question = null,
  }: Props = $props();

  function relative(iso: string | null): string | null {
    if (!iso) return null;
    const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
    if (seconds < 60) return `${Math.round(seconds)}s ago`;
    if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
    return new Date(iso).toLocaleString();
  }
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
      <span class="streaming-tag">streaming…</span>
    {:else if timestamp}
      <span class="time">{relative(timestamp)}</span>
    {/if}
  </div>

  {#if speaker === "dm" || speaker === "ooc"}
    <!--
      OOC bubbles also surface the model's reasoning trace via the
      collapsed-thinking block. The explainer is OOC anyway, so
      letting the player peek at the trace is consistent with how
      DM bubbles already expose thinking; it doesn't break the
      no-mutation contract because the trace is ephemeral and never
      enters action_log.
    -->
    <CollapsedThinking
      text={thinking ?? ""}
      streaming={streaming && (thinking ?? "") !== ""}
      hideWhenEmpty={!streaming}
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
    {:else}
      <p>{text}{#if streaming}<span class="caret" aria-hidden="true">▌</span>{/if}</p>
    {/if}
  </div>

  {#if outcome}
    <MechanicalReceipt {outcome} defaultOpen={streaming} />
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

  .msg--dm {
    border-left: 2px solid var(--gold-tarnished);
    padding-left: 1rem;
  }
  .msg--dm .body p {
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
  .msg--system .body p {
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
  .msg--ooc .body p {
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
