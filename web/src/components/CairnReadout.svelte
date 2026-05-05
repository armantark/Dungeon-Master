<!--
@component
CairnReadout — read-only Cairn 2e-inspired mechanical readout.

Used by:
- CharacterFolio (the persistent left rail during play)
- CharacterEditor (the draft preview after one-time backfill)

This component is intentionally surface-agnostic: it renders inside an
iron-voiced wrapper so it reads as the engine speaking, regardless of
whether its host is parchment (editor) or iron (folio). All numerals
use the Alagard pixel font, matching the chaos numeral and dice readouts
elsewhere in the UI. The readout is also strictly *display* — it never
mutates state and never proposes an action. Mutation lives behind explicit
backend endpoints that this pass deliberately does not bind to controls.
-->
<script lang="ts">
  import {
    activeStatuses,
    formatBurden,
    type StatusKey,
  } from "../lib/cairn";
  import type { CairnCharacterState } from "../lib/types";

  type Props = {
    cairn: CairnCharacterState;
    /**
     * When true, render the LLM-authored backfill rationale at the foot
     * of the readout. Folio leaves this off to keep the rail quiet; the
     * inspector turns it on so the player can see why these stats and
     * this loadout were chosen.
     */
    showNotes?: boolean;
  };

  const { cairn, showNotes = false }: Props = $props();

  const burden = $derived(formatBurden(cairn));
  const statuses = $derived(activeStatuses(cairn));
  const stats = $derived([
    { key: "STR", current: cairn.str_score, max: cairn.max_str_score },
    { key: "DEX", current: cairn.dex_score, max: cairn.max_dex_score },
    { key: "WIL", current: cairn.wil_score, max: cairn.max_wil_score },
  ] as const);

  // The bar is segmented at three thresholds so the player can read the
  // tier transition at a glance: comfortable -> backpack -> overloaded.
  // We render `total` segments (clamped to a sane upper bound) so the
  // resolution stays meaningful even on edge cases (e.g. a brief over-
  // burdened spike during play).
  const segments = $derived.by(() => {
    const total = Math.max(burden.total, 1);
    const items = [];
    for (let i = 1; i <= total; i += 1) {
      const filled = i <= burden.used;
      const tier: StatusKey | "comfortable" | "backpack" | "overloaded" =
        i <= burden.comfortable
          ? "comfortable"
          : i <= burden.backpack
            ? "backpack"
            : "overloaded";
      items.push({ filled, tier });
    }
    return items;
  });
</script>

<section class="readout" aria-label="Cairn mechanics readout">
  <header class="head">
    <span class="kicker">Mechanics</span>
    <span class="hp pixel" aria-label="Hit points">
      <span class="hp__num">{cairn.hp}</span>
      <span class="hp__sep" aria-hidden="true">/</span>
      <span class="hp__num hp__num--max">{cairn.max_hp}</span>
      <span class="hp__label">HP</span>
    </span>
  </header>

  <ul class="stats" aria-label="Attribute scores">
    {#each stats as stat (stat.key)}
      <li>
        <span class="stat__label kicker">{stat.key}</span>
        <span class="stat__current pixel">{stat.current}</span>
        <span class="stat__max pixel" aria-label={`Maximum ${stat.key}`}>
          / {stat.max}
        </span>
      </li>
    {/each}
  </ul>

  {#if cairn.armor > 0}
    <p class="armor pixel" aria-label="Armor">
      <span class="armor__label">Armor</span>
      <span class="armor__value">{cairn.armor}</span>
    </p>
  {/if}

  <section class="burden" aria-label="Inventory burden">
    <div class="burden__head">
      <span class="kicker">Burden</span>
      <span class="pixel">
        {burden.used}/{burden.total}
      </span>
    </div>
    <div
      class="burden__bar"
      role="meter"
      aria-valuenow={burden.used}
      aria-valuemin={0}
      aria-valuemax={burden.total}
      aria-label="Slot usage"
    >
      {#each segments as segment, idx (idx)}
        <span
          class="burden__seg"
          data-tier={segment.tier}
          data-filled={segment.filled}
          aria-hidden="true"
        ></span>
      {/each}
    </div>
    {#if cairn.fatigue > 0}
      <p class="fatigue pixel" aria-label="Fatigue slots used">
        Fatigue · {cairn.fatigue}
      </p>
    {/if}
  </section>

  {#if statuses.length > 0}
    <ul class="statuses" aria-label="Active conditions">
      {#each statuses as status (status.key)}
        <li class="chip pixel" data-status={status.key}>{status.label}</li>
      {/each}
    </ul>
  {/if}

  {#if cairn.skills.length > 0}
    <section class="list" aria-label="Skills">
      <span class="kicker">Skills</span>
      <ul>
        {#each cairn.skills as skill (skill)}
          <li>{skill}</li>
        {/each}
      </ul>
    </section>
  {/if}

  {#if cairn.abilities.length > 0}
    <section class="list" aria-label="Abilities">
      <span class="kicker">Abilities</span>
      <ul>
        {#each cairn.abilities as ability (ability)}
          <li>{ability}</li>
        {/each}
      </ul>
    </section>
  {/if}

  {#if showNotes && cairn.notes !== ""}
    <section class="notes" aria-label="Backfill notes">
      <span class="kicker">Build notes</span>
      <p>{cairn.notes}</p>
    </section>
  {/if}
</section>

<style>
  .readout {
    display: flex;
    flex-direction: column;
    gap: 0.55rem;
    padding: 0.7rem 0.8rem;
    background: rgba(0, 0, 0, 0.32);
    border: 1px solid color-mix(in oklab, var(--gold-tarnished) 30%, transparent);
    color: var(--paper-bone);
  }

  .head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
  }
  .head .kicker {
    margin: 0;
  }

  .hp {
    display: inline-flex;
    align-items: baseline;
    gap: 0.18rem;
    color: var(--gold-bright);
    font-size: 1.1rem;
    line-height: 1;
  }
  .hp__num--max {
    color: var(--gold-tarnished);
  }
  .hp__sep {
    color: var(--gold-tarnished);
  }
  .hp__label {
    margin-left: 0.35rem;
    font-size: 0.7rem;
    color: var(--gold-tarnished);
    letter-spacing: 0.06em;
  }

  .stats {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 0.4rem;
  }
  .stats li {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.1rem;
    padding: 0.4rem 0.3rem;
    border: 1px solid color-mix(in oklab, var(--gold-tarnished) 35%, transparent);
    background: rgba(0, 0, 0, 0.35);
  }
  .stat__label {
    margin: 0;
    font-size: 0.7rem;
    color: var(--gold-tarnished);
  }
  .stat__current {
    color: var(--gold-bright);
    font-size: 1.2rem;
    line-height: 1;
  }
  .stat__max {
    color: var(--gold-tarnished);
    font-size: 0.72rem;
  }

  .armor {
    margin: 0;
    display: flex;
    gap: 0.35rem;
    align-items: baseline;
    font-size: 0.85rem;
  }
  .armor__label {
    color: var(--gold-tarnished);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    font-size: 0.7rem;
  }
  .armor__value {
    color: var(--gold-bright);
    font-size: 1rem;
  }

  .burden {
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
  }
  .burden__head {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 0.5rem;
    font-size: 0.78rem;
    color: var(--gold-tarnished);
  }
  .burden__head .kicker {
    margin: 0;
  }
  .burden__bar {
    display: flex;
    gap: 2px;
    height: 0.55rem;
    border: 1px solid color-mix(in oklab, var(--gold-tarnished) 40%, transparent);
    background: rgba(0, 0, 0, 0.55);
    padding: 1px;
  }
  .burden__seg {
    flex: 1 1 0;
    background: transparent;
    transition: background 120ms ease;
  }
  .burden__seg[data-filled="true"][data-tier="comfortable"] {
    background: color-mix(in oklab, var(--green-verdigris) 75%, var(--gold-tarnished));
  }
  .burden__seg[data-filled="true"][data-tier="backpack"] {
    background: var(--gold-tarnished);
  }
  .burden__seg[data-filled="true"][data-tier="overloaded"] {
    background: var(--rust-iron);
  }
  .fatigue {
    margin: 0;
    color: var(--rust-iron);
    font-size: 0.78rem;
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }

  .statuses {
    list-style: none;
    padding: 0;
    margin: 0;
    display: flex;
    flex-wrap: wrap;
    gap: 0.3rem;
  }
  .chip {
    display: inline-block;
    padding: 0.15rem 0.45rem;
    font-size: 0.72rem;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    border: 1px solid color-mix(in oklab, var(--gold-tarnished) 50%, transparent);
    color: var(--gold-bright);
    background: rgba(0, 0, 0, 0.3);
  }
  .chip[data-status="dead"] {
    color: var(--paper-warm);
    border-color: var(--ink-bruise);
    background: var(--ink-deep);
  }
  .chip[data-status="doomed"] {
    color: var(--paper-warm);
    border-color: var(--rust-blood);
    background: color-mix(in oklab, var(--rust-blood) 38%, var(--ink-deep));
  }
  .chip[data-status="critically_wounded"] {
    color: var(--paper-warm);
    border-color: var(--rust-iron);
    background: color-mix(in oklab, var(--rust-iron) 32%, var(--ink-deep));
  }
  .chip[data-status="paralyzed"] {
    color: var(--paper-bone);
    border-color: var(--paper-shadow);
  }
  .chip[data-status="delirious"] {
    color: var(--gold-bright);
    border-color: var(--gold-tarnished);
    border-style: dashed;
  }
  .chip[data-status="deprived"] {
    color: var(--paper-warm);
    border-color: var(--paper-shadow);
  }
  .chip[data-status="overloaded"] {
    color: var(--paper-warm);
    border-color: var(--rust-iron);
  }

  .list {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }
  .list .kicker {
    margin: 0;
  }
  .list ul {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.2rem;
  }
  .list li {
    font-family: var(--font-body);
    font-size: 0.92rem;
    line-height: 1.3;
    color: var(--paper-warm);
    padding-left: 0.55rem;
    border-left: 2px solid color-mix(in oklab, var(--gold-tarnished) 55%, transparent);
  }

  .notes {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }
  .notes .kicker {
    margin: 0;
  }
  .notes p {
    margin: 0;
    font-size: 0.9rem;
    line-height: 1.4;
    color: var(--paper-bone);
  }
</style>
