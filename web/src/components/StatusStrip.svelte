<!--
@component
StatusStrip — slim header bar with title, chaos badge, inspector toggle.

Why a strip instead of a sidebar:
The user wants the chat to be primary and mechanics to recede. A 60px
strip carries the brand and the *one* mechanical signal that has to
stay visible (chaos), and offers a single button into the inspector.
Anything more would compete with the conversation below.
-->
<script lang="ts">
  import { game } from "../lib/store.svelte";

  type Props = { chaos: number; sceneNumber: number };
  const { chaos, sceneNumber }: Props = $props();
</script>

<header class="strip iron">
  <div class="brand">
    <span class="kicker">Oracle's Ledger</span>
    <h1>Dungeon Master</h1>
  </div>

  <div class="meta">
    <button class="badge" type="button" onclick={() => game.openInspector()} title="Open inspector">
      <span class="kicker">Chaos</span>
      <span class="pixel value">{chaos}</span>
    </button>
    <div class="scene">
      <span class="kicker">Scene</span>
      <span class="pixel value">{sceneNumber}</span>
    </div>
    <button class="ghost inspect" onclick={() => game.toggleInspector()}>
      {game.inspectorOpen ? "Close" : "Inspect"}
    </button>
  </div>
</header>

<style>
  .strip {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    padding: 0.7rem 1.4rem;
    border-left: 0;
    border-right: 0;
    border-top: 0;
  }
  .brand {
    display: flex;
    flex-direction: column;
    gap: 0.05rem;
  }
  .brand h1 {
    font-size: 1.4rem;
    margin: 0;
  }
  .brand .kicker {
    margin-bottom: 0;
    font-size: 0.72rem;
  }
  .meta {
    display: flex;
    align-items: stretch;
    gap: 0.7rem;
  }
  .badge,
  .scene {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 0.3rem 0.85rem;
    border: 1px solid color-mix(in oklab, var(--gold-tarnished) 50%, transparent);
    background: rgba(0, 0, 0, 0.25);
    text-transform: none;
    letter-spacing: 0;
    cursor: default;
  }
  .badge {
    cursor: pointer;
  }
  .badge:hover {
    border-color: var(--gold-bright);
  }
  .badge .kicker,
  .scene .kicker {
    margin: 0;
    font-size: 0.66rem;
    color: var(--gold-tarnished);
    line-height: 1;
  }
  .badge .value,
  .scene .value {
    font-size: 1.4rem;
    color: var(--gold-bright);
    line-height: 1.05;
  }
  button.inspect {
    align-self: stretch;
    padding: 0.4rem 0.9rem;
    font-size: 0.85rem;
  }
</style>
