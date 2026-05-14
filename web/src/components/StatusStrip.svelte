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
  import { combatFromState, enemyInitiated, encounterHeadline } from "../lib/combat";
  import { game } from "../lib/store.svelte";
  import type { GameState } from "../lib/types";
  import SystemMenu from "./SystemMenu.svelte";

  type Props = { chaos: number; sceneNumber: number; state: GameState };
  const { chaos, sceneNumber, state: gs }: Props = $props();

  // The combat badge appears only when an encounter is active. Clicking
  // it opens the inspector — the tracker lives there. Keeping the
  // badge inline (not a separate region) means the strip only grows in
  // height when combat is happening, so the chat doesn't jump under
  // the player on every encounter start.
  const encounter = $derived(combatFromState(gs));
  const combatHeadline = $derived(encounterHeadline(encounter));
  const showCombat = $derived(encounter !== null && encounter.active);
  // F-05: when the foe opened the fight, swap the kicker to "Ambush"
  // so the player's at-a-glance read of the strip is the cause of the
  // fight, not a generic "Combat" label. The button title gains the
  // same hint so screen-readers / hover tooltips agree.
  const ambushed = $derived(showCombat && enemyInitiated(encounter));
  const combatKicker = $derived(ambushed ? "Ambush" : "Combat");
  const combatTooltip = $derived(
    ambushed ? "Open ambush tracker — a foe seized initiative." : "Open combat tracker",
  );
</script>

<header class="strip iron">
  <div class="brand">
    <span class="kicker">Oracle's Ledger</span>
    <h1>Dungeon Master</h1>
  </div>

  <div class="meta">
    {#if showCombat}
      <button
        class="badge badge--combat"
        class:badge--ambush={ambushed}
        type="button"
        onclick={() => game.openInspector()}
        title={combatTooltip}
      >
        <span class="kicker">{combatKicker}</span>
        <span class="pixel value combat-value">{combatHeadline ?? "Active"}</span>
      </button>
    {/if}
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
    <!--
      F-12 system menu lives at the far-right of the strip so that "leave
      this campaign" actions are spatially separated from "look at this
      campaign" actions (Inspect, Chaos). Same reason settings menus
      typically live opposite the navigation in OS shells.
    -->
    <SystemMenu />
  </div>
</header>

<style>
  /*
   * Top bar styled as draped black cloth/felt instead of the leather
   * chassis material. Felt has finer, more uniform fibre than leather
   * pores — reads as fabric stretched across the top of the workspace
   * rather than another panel of the codex.
   *
   * The `.strip` overrides `.iron::after`'s default leather PNG with
   * black-felt.png. A subtle vertical draped-fold gradient adds
   * dimension along the X axis so the cloth reads as hanging cloth,
   * not flat fabric.
   */
  .strip {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    padding: 0.7rem 1.4rem;
    border-left: 0;
    border-right: 0;
    border-top: 0;
    position: relative;
    z-index: 900; /* force strip to sit above everything else */
    background:
      /* Top bar gradient */
      linear-gradient(
        180deg,
        #161310 0%,
        #0a0807 100%
      );
  }
  .strip::after {
    content: "";
    position: absolute;
    inset: 0;
    pointer-events: none;
    z-index: 0;
    background-image:
      linear-gradient(180deg, rgba(0, 0, 0, 0.18), rgba(0, 0, 0, 0.45)),
      url("/textures/linen.jpg");
    background-size: cover, cover;
    background-position: center, center;
    background-repeat: no-repeat, no-repeat;
  }
  .strip > * {
    position: relative;
    z-index: 1;
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

  /* The combat badge uses rust-iron rather than gold so the player's
   * eye distinguishes "live encounter" from the always-visible chaos
   * number at a glance. The animated underline keeps it from reading
   * as a static decoration when combat starts. */
  .badge--combat {
    border-color: var(--rust-iron);
    background: color-mix(in oklab, var(--rust-blood) 18%, transparent);
  }
  .badge--combat:hover {
    border-color: var(--rust-iron);
    background: color-mix(in oklab, var(--rust-blood) 32%, transparent);
  }
  .badge--combat .kicker {
    color: var(--rust-iron);
  }
  /*
   * Ambush variant: deeper blood tint + brighter kicker so the player
   * sees a stronger "you got jumped" cue at a glance. The headline
   * already carries "Ambush · Round N", so the badge color is the
   * second redundant cue and the kicker swap is the third — three
   * layered cues match how the threads / NPCs panels do recency.
   */
  .badge--ambush {
    border-color: var(--rust-blood);
    background: color-mix(in oklab, var(--rust-blood) 30%, transparent);
  }
  .badge--ambush:hover {
    border-color: var(--rust-blood);
    background: color-mix(in oklab, var(--rust-blood) 45%, transparent);
  }
  .badge--ambush .kicker {
    color: var(--rust-blood);
  }
  .badge--combat .combat-value {
    /* Smaller because the headline can be long ("Round 1 · DEX save
     * to act") and this badge sits in a horizontal strip with limited
     * room before the chaos / scene badges shift right. */
    color: var(--paper-warm);
    font-size: 0.85rem;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    padding: 0 0.15rem;
  }
</style>
