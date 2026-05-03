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
  type Props = {
    title: string;
    subtitle?: string;
    cancelLabel?: string | null;
    onCancel?: () => void;
  };
  const { title, subtitle, cancelLabel, onCancel }: Props = $props();
</script>

<div class="panel iron" role="status" aria-live="polite">
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

<style>
  .panel {
    padding: 1rem 1.1rem;
    display: grid;
    grid-template-columns: auto 1fr auto;
    gap: 0.9rem;
    align-items: center;
  }
  .text {
    display: grid;
    gap: 0.2rem;
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
