<script lang="ts">
  import { game } from "../../lib/store.svelte";

  type Props = {
    value: number;
    archived: boolean;
  };

  const { value, archived }: Props = $props();
  let pending: number | null = $state(null);
  const displayValue = $derived(pending ?? value);

  function adjust(delta: number): void {
    pending = Math.min(9, Math.max(1, displayValue + delta));
  }

  async function commit(): Promise<void> {
    if (pending === null || pending === value) {
      pending = null;
      return;
    }
    const next = pending;
    pending = null;
    await game.setChaos(next);
  }
</script>

<div class="chaos-control">
  <span class="kicker">Chaos Factor</span>
  <div class="chaos-row">
    <button class="ghost" onclick={() => adjust(-1)} aria-label="Decrease chaos" disabled={archived}>−</button>
    <span class="pixel chaos-value">{displayValue}</span>
    <button class="ghost" onclick={() => adjust(1)} aria-label="Increase chaos" disabled={archived}>+</button>
    <button onclick={commit} disabled={archived || pending === null || pending === value || game.isLoading}>Commit</button>
  </div>
  {#if archived}
    <p class="archived-hint muted">Archived — chaos is preserved as canon.</p>
  {/if}
</div>

<style>
  .chaos-control {
    padding: 0.65rem 0.75rem;
    display: grid;
    gap: 0.45rem;
    background: rgba(0, 0, 0, 0.25);
    border: 1px solid color-mix(in oklab, var(--gold-tarnished) 30%, transparent);
  }
  .kicker {
    margin: 0;
    text-align: left;
  }
  .chaos-row {
    display: grid;
    grid-template-columns: auto minmax(2.2rem, auto) auto 1fr;
    align-items: center;
    gap: 0.45rem;
  }
  .chaos-value {
    color: var(--gold-bright);
    font-size: 1.75rem;
    line-height: 1;
    text-align: center;
  }
  .chaos-row button {
    padding: 0.42rem 0.55rem;
  }
  .archived-hint {
    margin: 0;
    font-size: 0.74rem;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: var(--paper-shadow);
  }
</style>
