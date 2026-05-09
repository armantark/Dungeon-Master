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
    foodPressureMeter,
    formatBurden,
    formatSurvivalLine,
    sleepPressureMeter,
    type StatusKey,
    type SurvivalMeter,
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

  // Survival readout. We display the day-night line + two pressure
  // meters (food, sleep). The meters are tier-colored from the helper:
  // `easy` is the comfortable green of the burden bar, `warning` is
  // the gold-tarnished pre-deprivation hint, `deprived` is the
  // blood-rust everything-is-bad tier shared with overloaded burden.
  // We deliberately avoid spelling out the watch counts as raw numbers
  // — the meter is the read; the chip is the verdict.
  const survivalLine = $derived(formatSurvivalLine(cairn.survival));
  const foodMeter: SurvivalMeter = $derived(foodPressureMeter(cairn.survival));
  const sleepMeter: SurvivalMeter = $derived(sleepPressureMeter(cairn.survival));

  // The bar segments grow with the deprivation threshold, so the eye
  // can read "two ticks shy of deprivation" rather than parsing a
  // percent. We render a tick at the warning watermark to make that
  // intermediate stage visible at a glance.
  function meterSegments(meter: SurvivalMeter): Array<{
    filled: boolean;
    warning: boolean;
    tier: SurvivalMeter["tier"];
  }> {
    const segments = [];
    for (let i = 1; i <= meter.threshold; i += 1) {
      segments.push({
        filled: i <= meter.value,
        warning: i === meter.warning,
        tier: meter.tier,
      });
    }
    return segments;
  }
  const foodSegments = $derived(meterSegments(foodMeter));
  const sleepSegments = $derived(meterSegments(sleepMeter));

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

  <!--
    Survival clock — the watch-based day-night + food/sleep pressure
    surface. We render it after burden because deprivation propagates
    upward into the status chips below; the player's eye reads
    "Day 2 · Dusk · Watch 4/6" first, then sees the meters that explain
    why "Deprived" is lit on the chip strip. We never expose buttons
    here: the player triggers eat / sleep / rest through natural
    language, and this surface is strictly the receipt of what the
    backend has decided.
  -->
  <section class="survival" aria-label="Survival clock">
    <div class="survival__head">
      <span class="kicker">Survival</span>
      <span class="pixel survival__line" aria-label="Day, phase, and watch">
        {survivalLine}
      </span>
    </div>
    <div class="survival__rail">
      <div class="meter" data-axis="food" data-tier={foodMeter.tier}>
        <div class="meter__head">
          <span class="kicker">Food</span>
          <span class="meter__count pixel" aria-label="Watches without food">
            {foodMeter.value}/{foodMeter.threshold}
          </span>
          <span class="meter__chip pixel" data-tier={foodMeter.tier}>
            {#if foodMeter.deprived}
              Deprived
            {:else if foodMeter.tier === "warning"}
              Hungry
            {:else}
              Fed
            {/if}
          </span>
        </div>
        <div
          class="meter__bar"
          role="meter"
          aria-valuenow={foodMeter.value}
          aria-valuemin={0}
          aria-valuemax={foodMeter.threshold}
          aria-label="Watches without food"
        >
          {#each foodSegments as segment, idx (idx)}
            <span
              class="meter__seg"
              data-filled={segment.filled}
              data-warning={segment.warning}
              data-tier={segment.tier}
              aria-hidden="true"
            ></span>
          {/each}
        </div>
      </div>

      <div class="meter" data-axis="sleep" data-tier={sleepMeter.tier}>
        <div class="meter__head">
          <span class="kicker">Sleep</span>
          <span class="meter__count pixel" aria-label="Watches without sleep">
            {sleepMeter.value}/{sleepMeter.threshold}
          </span>
          <span class="meter__chip pixel" data-tier={sleepMeter.tier}>
            {#if sleepMeter.deprived}
              Deprived
            {:else if sleepMeter.tier === "warning"}
              Weary
            {:else}
              Rested
            {/if}
          </span>
        </div>
        <div
          class="meter__bar"
          role="meter"
          aria-valuenow={sleepMeter.value}
          aria-valuemin={0}
          aria-valuemax={sleepMeter.threshold}
          aria-label="Watches without sleep"
        >
          {#each sleepSegments as segment, idx (idx)}
            <span
              class="meter__seg"
              data-filled={segment.filled}
              data-warning={segment.warning}
              data-tier={segment.tier}
              aria-hidden="true"
            ></span>
          {/each}
        </div>
      </div>
    </div>
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

  /*
   * Survival rail. We mirror the burden block visually (kicker + pixel
   * readout, segmented bar) so the rail reads as a consistent stack of
   * mechanical meters: Burden, Food, Sleep. The two pressure meters
   * sit on a single row at desktop widths to keep the rail compact
   * and stack at narrower widths so the labels never crowd the chips.
   */
  .survival {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
  }
  .survival__head {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 0.5rem;
    font-size: 0.78rem;
  }
  .survival__head .kicker {
    margin: 0;
  }
  .survival__line {
    color: var(--gold-bright);
    letter-spacing: 0.05em;
  }
  .survival__rail {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0.45rem;
  }
  @media (max-width: 320px) {
    .survival__rail {
      grid-template-columns: 1fr;
    }
  }
  .meter {
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
  }
  /*
   * The head row carries three children: kicker, numeric `n/N` count,
   * and tier chip. We use a 3-track grid so the count sits in the
   * middle and the chip pins to the right at any container width —
   * a simple flex `space-between` would let the chip hop tracks at
   * narrow widths.
   */
  .meter__head {
    display: grid;
    grid-template-columns: max-content 1fr max-content;
    align-items: baseline;
    gap: 0.45rem;
  }
  .meter__head .kicker {
    margin: 0;
  }
  .meter__count {
    font-size: 0.7rem;
    letter-spacing: 0.04em;
    color: var(--gold-tarnished);
    text-align: right;
  }
  .meter__chip {
    font-size: 0.62rem;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    padding: 0.05rem 0.35rem;
    border: 1px solid color-mix(in oklab, var(--gold-tarnished) 50%, transparent);
    color: var(--gold-tarnished);
    white-space: nowrap;
  }
  .meter__chip[data-tier="warning"] {
    color: var(--gold-bright);
    border-color: var(--gold-tarnished);
  }
  .meter__chip[data-tier="deprived"] {
    color: var(--paper-warm);
    border-color: var(--rust-blood);
    background: color-mix(in oklab, var(--rust-blood) 30%, var(--ink-deep));
  }
  .meter__bar {
    display: flex;
    gap: 2px;
    height: 0.7rem;
    border: 1px solid color-mix(in oklab, var(--gold-tarnished) 50%, transparent);
    background: rgba(0, 0, 0, 0.6);
    padding: 1px;
  }
  /*
   * Each segment carries a faint baseline so the bar reads as a
   * "tracked but empty" meter even at zero pressure — the eye sees
   * the segment grid and intuitively knows what filling does next.
   * Without this baseline the bar at 0/3 looks like a hollow strip.
   */
  .meter__seg {
    flex: 1 1 0;
    background: color-mix(in oklab, var(--gold-tarnished) 14%, transparent);
    border-right: 1px solid color-mix(in oklab, var(--gold-tarnished) 25%, transparent);
    transition: background 120ms ease;
    position: relative;
  }
  .meter__seg:last-child {
    border-right: 0;
  }
  /*
   * Warning watermark: an in-bar vertical line at the LEFT edge of
   * the warning segment, so the eye reads it as "you cross this line
   * and you're hungry / weary." We render it inside the bar instead
   * of floating above it so it never reads as a stray tick mark.
   * Using a left-edge inset rule keeps the tick exactly at the
   * boundary between safe and warning even when segment width
   * changes (food has 3 segments, sleep has 6, but the tick still
   * lands on the threshold for both).
   */
  .meter__seg[data-warning="true"]::before {
    content: "";
    position: absolute;
    inset: -1px auto -1px -1px;
    width: 2px;
    background: color-mix(in oklab, var(--gold-bright) 85%, transparent);
    box-shadow: 0 0 3px color-mix(in oklab, var(--gold-bright) 50%, transparent);
  }
  .meter__seg[data-filled="true"][data-tier="easy"] {
    background: color-mix(in oklab, var(--green-verdigris) 75%, var(--gold-tarnished));
  }
  .meter__seg[data-filled="true"][data-tier="warning"] {
    background: var(--gold-bright);
  }
  .meter__seg[data-filled="true"][data-tier="deprived"] {
    background: var(--rust-blood);
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
