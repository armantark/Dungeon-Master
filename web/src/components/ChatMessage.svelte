<!--
@component
ChatMessage — one entry in the chat feed.

Three speakers:
  dm        — narrative voice (Cormorant), parchment-tinted left rail
  player    — first-person action, plain
  system    — engine voice (Alagard pixel), subdued

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
    speaker: "dm" | "player" | "system";
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
      {:else}Engine{/if}
    </span>
    {#if streaming}
      <span class="streaming-tag">streaming…</span>
    {:else if timestamp}
      <span class="time">{relative(timestamp)}</span>
    {/if}
  </div>

  {#if speaker === "dm"}
    <CollapsedThinking
      text={thinking ?? ""}
      streaming={streaming && (thinking ?? "") !== ""}
      hideWhenEmpty={!streaming}
    />
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
</style>
