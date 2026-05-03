<!--
@component
ChaosDial — a wax-seal that distorts the higher chaos climbs.

Why a wax seal and not a slider/gauge:
The chaos factor is a *charged* mechanical concept (it bends the oracle's
likelihood and triggers scene shifts). Rendering it as an instrument with
ticks reads as bureaucratic. A seal pressed harder into wax communicates
the same number while staying in the diegetic frame of the ledger.

Implementation notes:
- The seal is pure SVG so it scales without raster artifacts.
- The "distortion" is a feTurbulence + feDisplacementMap whose `scale`
  is bound to the chaos factor; at chaos 1 the seal is crisp, at chaos 9
  it's nearly cracked apart.
- The dial works as both a display and an input. The user clicks/drags
  the value buttons to commit a new chaos factor.
-->
<script lang="ts">
  import { game } from "../lib/store.svelte";

  type Props = { value: number; compact?: boolean };
  const { value, compact = false }: Props = $props();

  let pending: number | null = $state(null);
  const display = $derived(pending ?? value);

  // Distortion ramps non-linearly: the first few steps barely warp, then
  // the seal cracks visibly past 6. Matches how chaos feels in play.
  const distortion = $derived((display - 1) ** 1.6 * 0.55);

  async function commit(): Promise<void> {
    if (pending === null || pending === value) {
      pending = null;
      return;
    }
    const next = pending;
    pending = null;
    await game.setChaos(next);
  }

  function adjust(delta: number): void {
    const base = pending ?? value;
    pending = Math.min(9, Math.max(1, base + delta));
  }
</script>

<div class="chaos" class:compact>
  <div class="kicker">Chaos Factor</div>

  <div class="dial">
    <svg viewBox="0 0 200 200" role="img" aria-label="Chaos factor seal">
      <defs>
        <filter id="wax-warp" x="-20%" y="-20%" width="140%" height="140%">
          <feTurbulence
            type="fractalNoise"
            baseFrequency="0.018"
            numOctaves="2"
            seed="3"
          />
          <feDisplacementMap in="SourceGraphic" scale={distortion} />
        </filter>
        <radialGradient id="wax-fill" cx="38%" cy="32%" r="80%">
          <stop offset="0%" stop-color="#c33930" />
          <stop offset="55%" stop-color="#7a2820" />
          <stop offset="100%" stop-color="#3d1109" />
        </radialGradient>
        <radialGradient id="wax-rim" cx="50%" cy="50%" r="50%">
          <stop offset="80%" stop-color="transparent" />
          <stop offset="100%" stop-color="rgba(0,0,0,0.65)" />
        </radialGradient>
      </defs>

      <g filter="url(#wax-warp)">
        <circle cx="100" cy="100" r="78" fill="url(#wax-fill)" />
        <circle cx="100" cy="100" r="78" fill="url(#wax-rim)" />
        <circle
          cx="100"
          cy="100"
          r="62"
          fill="none"
          stroke="rgba(255,210,150,0.2)"
          stroke-width="0.6"
          stroke-dasharray="2 4"
        />
        <text
          x="100"
          y="118"
          text-anchor="middle"
          font-family="IM Fell English SC, serif"
          font-size="76"
          fill="rgba(255, 220, 160, 0.92)"
          stroke="rgba(0,0,0,0.55)"
          stroke-width="0.8"
        >
          {display}
        </text>
      </g>
    </svg>
  </div>

  <div class="dial-controls">
    <button class="ghost" onclick={() => adjust(-1)} aria-label="Decrease chaos">−</button>
    <button onclick={commit} disabled={pending === null || pending === value || game.isLoading}>
      Commit
    </button>
    <button class="ghost" onclick={() => adjust(1)} aria-label="Increase chaos">+</button>
  </div>
</div>

<style>
  .chaos {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 1.1rem 0.8rem 1rem;
  }
  .dial {
    width: 168px;
    height: 168px;
    margin: 0.1rem 0 0.8rem;
    filter: drop-shadow(0 8px 14px rgba(0, 0, 0, 0.55));
  }
  .dial svg {
    width: 100%;
    height: 100%;
  }
  .dial-controls {
    display: grid;
    grid-template-columns: auto 1fr auto;
    gap: 0.4rem;
    width: 100%;
  }
  .dial-controls button.ghost {
    font-size: 1.2rem;
    line-height: 1;
    padding: 0.5rem 0.7rem;
  }
  .compact {
    padding: 0.65rem 0.7rem 0.75rem;
  }
  .compact .dial {
    width: 76px;
    height: 76px;
    margin: 0 0 0.45rem;
  }
  .compact .dial-controls {
    max-width: 220px;
  }
  .compact .dial-controls button {
    padding: 0.4rem 0.55rem;
  }
</style>
