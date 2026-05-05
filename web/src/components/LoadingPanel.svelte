<!--
@component
LoadingPanel — visible "the model is working" surface.

Why this exists: the only previous progress signal during character
generation was a small "Stop draft" button at the bottom-right, which
made multi-second LLM calls feel like the app had frozen. This panel
fills the active content area so the player has something to read
while they wait, plus a same-place cancel control instead of a
floating one.
-->
<script lang="ts">
  import CollapsedThinking from "./CollapsedThinking.svelte";
  import { game } from "../lib/store.svelte";

  type Props = {
    title: string;
    subtitle?: string;
    cancelLabel?: string | null;
    onCancel?: () => void;
    // When true, the panel pulls live streaming state from the game
    // store and renders a thinking strip + a provisional content
    // preview underneath. Setup flows (quiz, draft, campaign start)
    // pass true so the player sees the model working in real time
    // instead of staring at a static lamp.
    showStream?: boolean;
  };
  const {
    title,
    subtitle,
    cancelLabel,
    onCancel,
    showStream = false,
  }: Props = $props();

  // Truncate the streamed content preview because setup flows produce
  // long structured outputs (a full character sheet's narrative text)
  // that would otherwise blow out the panel's height. The thinking
  // block is the more useful signal during these flows; the content
  // preview is just confirmation that prose is arriving.
  const PREVIEW_CHARS = 360;
  const preview = $derived.by(() => {
    if (!showStream) return "";
    const c = game.streaming.content;
    if (c.length <= PREVIEW_CHARS) return c;
    return `…${c.slice(-PREVIEW_CHARS)}`;
  });
  const hasStreamSignal = $derived(
    showStream && game.streaming.active
      && (game.streaming.thinking !== "" || game.streaming.content !== ""),
  );
</script>

<div class="panel iron" role="status" aria-live="polite">
  <div class="head">
    <div class="lamp" aria-hidden="true">
      <span class="dot"></span>
      <span class="dot"></span>
      <span class="dot"></span>
    </div>
    <div class="text">
      <span class="kicker">Working</span>
      <strong>{title}</strong>
      {#if subtitle}
        <p>{subtitle}</p>
      {/if}
    </div>
    {#if cancelLabel && onCancel}
      <button class="ghost" onclick={onCancel}>{cancelLabel}</button>
    {/if}
  </div>

  {#if showStream && game.streaming.active}
    <CollapsedThinking
      text={game.streaming.thinking}
      streaming={true}
      hideWhenEmpty={false}
    />
  {/if}

  {#if hasStreamSignal && preview !== ""}
    <pre class="preview">{preview}<span class="caret" aria-hidden="true">▌</span></pre>
  {/if}
</div>

<style>
  .panel {
    padding: 1rem 1.1rem;
    display: grid;
    gap: 0.7rem;
  }
  .head {
    display: grid;
    grid-template-columns: auto 1fr auto;
    gap: 0.9rem;
    align-items: center;
  }
  .text {
    display: grid;
    gap: 0.2rem;
  }
  .preview {
    /* Tail-end preview of the streaming narrative — Cormorant so it
     * reads as fiction in motion, but constrained to a few lines so
     * the panel doesn't grow out of frame on long generations. */
    margin: 0;
    padding: 0.6rem 0.75rem;
    background: color-mix(in oklab, var(--ink-black) 55%, transparent);
    border-left: 2px solid color-mix(in oklab, var(--gold-tarnished) 50%, transparent);
    font-family: var(--font-body);
    font-size: 0.95rem;
    line-height: 1.5;
    color: color-mix(in oklab, var(--paper-bone) 88%, transparent);
    white-space: pre-wrap;
    word-wrap: break-word;
    max-height: 8.5rem;
    overflow-y: auto;
  }
  .caret {
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
  .text strong {
    font-family: var(--font-display);
    font-size: 1.05rem;
    color: var(--paper-warm);
  }
  .text p {
    margin: 0;
    color: var(--paper-shadow);
    font-size: 0.92rem;
  }

  /* Three slow-pulsing pixels — Alagard-adjacent and unmistakably
   * "the engine is thinking" without resorting to a generic spinner. */
  .lamp {
    display: inline-flex;
    gap: 0.35rem;
  }
  .dot {
    width: 0.55rem;
    height: 0.55rem;
    background: var(--gold-tarnished);
    box-shadow: 0 0 8px color-mix(in oklab, var(--gold-bright) 60%, transparent);
    animation: pulse 1.1s ease-in-out infinite;
  }
  .dot:nth-child(2) {
    animation-delay: 0.18s;
  }
  .dot:nth-child(3) {
    animation-delay: 0.36s;
  }
  @keyframes pulse {
    0%,
    100% {
      opacity: 0.25;
      transform: scale(0.85);
    }
    50% {
      opacity: 1;
      transform: scale(1.1);
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .dot {
      animation: none;
      opacity: 0.7;
    }
  }
</style>
