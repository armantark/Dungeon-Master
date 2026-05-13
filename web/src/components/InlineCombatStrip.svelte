<!--
@component
InlineCombatStrip — the player-facing combat readout that rides inline
with the chat feed (anchored under the latest DM message when an
encounter is active).

Why this exists alongside the existing CombatTracker:
  - The CombatTracker drawer in the Inspector was showing the full
    Warden-side stat block to the player (HP/STR/DEX/WIL/armor/weapon
    die, plus weakness and tactics lines). That violates Cairn's
    fiction-first protocol: the player should read the world through
    diegetic cues ("Bloodied", "Heavily armored", visible openings),
    not a tabletop GM screen.
  - Moving the readout inline with the chat keeps it where the player
    is already looking. Combat is rare relative to exploration, so a
    persistent rail surface burned UI for nothing most of the time.

What this surface intentionally hides by default:
  - Exact HP / max HP. Replaced with `Fresh / Bloodied / Reeling / Down`.
  - Exact armor value. Replaced with `Unarmored / Armored / Heavily armored / Plated`.
  - STR / DEX / WIL. The player only needs these as fiction, not numbers.
  - Weapon damage die. Same — surfaces post-hoc on the MechanicalReceipt.
  - Weakness / tactics lines. These are Warden cues; the narrative is
    supposed to expose openings in-fiction first.

A collapsed `<details>` "Warden details" disclosure keeps every
number reachable for trust/audit, so the Inspector tracker is no
longer the only path to that information. The Inspector keeps the
same tracker behind its own "Warden details" drawer (off by default).

The component is read-only by design. All actions are routed through
the chat composer (`/retreat`, prose attacks, etc.), so the strip is
strictly a trust-surface, never a control.
-->
<script lang="ts">
  import { ADVANTAGE_PAYOFF_LABEL } from "../lib/campaign-seed";
  import {
    advantagesForCombatant,
    combatFromState,
    combatantArmorLabel,
    combatantHpTier,
    combatantStatusLabel,
    combatantWoundLabel,
    encounterHeadline,
    enemyInitiated,
    firstRoundActionGated,
    sortCombatants,
    unattachedAdvantages,
  } from "../lib/combat";
  import type { CombatantState } from "../lib/combat";
  import type { GameState } from "../lib/types";

  type Props = { state: GameState };
  const { state: gs }: Props = $props();

  const encounter = $derived(combatFromState(gs));
  const active = $derived(encounter !== null && encounter.active);
  const combatants = $derived<CombatantState[]>(
    encounter === null ? [] : sortCombatants(encounter.combatants),
  );
  // "Standing" = anyone not down/dead/fled. We use it as the
  // collapsed-summary count so the disclosure header gives the
  // player a single mechanical "how is this fight going?" pulse
  // without unfolding the body. We don't expose individual HP here
  // (that would re-introduce the Warden-style readout the strip is
  // explicitly built to avoid); we just count who's still up.
  const standingCount = $derived(
    combatants.reduce((n, c) => (c.status === "active" ? n + 1 : n), 0),
  );
  const headline = $derived(encounterHeadline(encounter));
  const firstRound = $derived(firstRoundActionGated(encounter));
  const ambushed = $derived(encounter !== null && encounter.active && enemyInitiated(encounter));
  const moraleTriggered = $derived(encounter !== null && encounter.morale_triggered);
  const looseAdvantages = $derived(unattachedAdvantages(encounter));
</script>

{#if encounter !== null && active}
  <!--
    Top-level disclosure. The strip starts collapsed because combat
    is not the only reason a player looks at the chat: between rounds
    they're often reading prose, and a permanently-expanded tracker
    pushes the latest narrative offscreen. The header (kicker +
    encounter headline + foe count) stays visible as the summary so
    a glance still tells the player "you're in round N, X foes
    standing, DEX gate or not"; opening the strip reveals the foe
    cards, pending advantages, and Warden audit paths.

    We use a native <details> element instead of a hand-rolled
    button + state pair to keep keyboard / a11y behavior free, and
    to mirror the per-foe Warden disclosure idiom that already lives
    inside the strip.
  -->
  <details class="strip iron" aria-label="Active combat">
    <summary class="strip__head">
      <span class="strip__head-main">
        <span class="kicker">Encounter</span>
        <span class="pixel headline">{headline ?? "Active"}</span>
      </span>
      <!--
        Foe count is the smallest possible "should I open this?"
        hint that respects the fiction-first protocol: it's visible
        in the chat narration anyway ("four plague-bearers shamble
        toward you"), so leaking the standing count here doesn't
        add Warden information. The chevron sits next to it so the
        click target reads as a toggle, not a static label.
      -->
      <span class="strip__head-aside pixel">
        <span class="strip__count">
          {standingCount}
          <span class="muted">/ {combatants.length}</span>
        </span>
        <span class="strip__chevron" aria-hidden="true">▸</span>
      </span>
    </summary>

    {#if ambushed || firstRound || moraleTriggered}
      <ul class="flags">
        {#if ambushed}
          <li class="flag flag--ambush">
            <span class="pixel flag-label">Ambush</span>
            <span class="flag-text">A foe opened this fight before you could act.</span>
          </li>
        {/if}
        {#if firstRound}
          <li class="flag flag--first">
            <span class="pixel flag-label">First round</span>
            <span class="flag-text">DEX save to act this turn.</span>
          </li>
        {/if}
        {#if moraleTriggered}
          <li class="flag flag--morale">
            <span class="pixel flag-label">Morale</span>
            <span class="flag-text">A morale check has been triggered.</span>
          </li>
        {/if}
      </ul>
    {/if}

    {#if looseAdvantages.length > 0}
      <!--
        Pending setups apply to whichever foe the next attack
        targets — surface them above the foe list as a reminder
        the player has live leverage banked.
      -->
      <div class="setups setups--loose">
        <span class="kicker">Pending setups</span>
        <ul>
          {#each looseAdvantages as adv (adv.id)}
            <li>
              <span class="pixel pill">{ADVANTAGE_PAYOFF_LABEL[adv.payoff]}</span>
              <span class="setup-text">{adv.setup}</span>
            </li>
          {/each}
        </ul>
      </div>
    {/if}

    {#if combatants.length === 0}
      <p class="muted small">No tracked combatants yet.</p>
    {:else}
      <ul class="foes">
        {#each combatants as foe (foe.id)}
          {@const tier = combatantHpTier(foe)}
          {@const woundLabel = combatantWoundLabel(foe)}
          {@const armorLabel = combatantArmorLabel(foe)}
          {@const statusLabel = combatantStatusLabel(foe.status)}
          {@const foeAdvantages = advantagesForCombatant(encounter, foe.id)}
          {@const description = foe.tags[0] ?? ""}
          <li class="foe foe--{tier} threat--{foe.threat_level}">
            <div class="foe__head">
              <span class="foe__name">{foe.name}</span>
              <!--
                Threat tier pip is only worth showing when the foe
                is hardier or serious. An "ordinary" pip on every
                rabble would be noise; the player's default reading
                should be "ordinary unless flagged".
              -->
              {#if foe.threat_level !== "ordinary"}
                <span class="foe__threat pixel threat-pip threat-pip--{foe.threat_level}">
                  {foe.threat_level === "serious" ? "Serious threat" : "Hardier foe"}
                </span>
              {/if}
              {#if statusLabel !== null}
                <span class="foe__status pixel">{statusLabel}</span>
              {/if}
            </div>

            {#if description !== ""}
              <p class="foe__description">{description}</p>
            {/if}

            <p class="foe__read">
              <!--
                Diegetic readout — the only thing the player sees
                by default. Wound + armor labels are derived from
                the canonical numbers but rendered as fiction-first
                cues so the strip doesn't feel like a tabletop
                stat screen.
              -->
              <span class="cue cue--wound cue--wound--{tier}">{woundLabel}</span>
              <span class="cue cue--armor">{armorLabel}</span>
            </p>

            {#if foeAdvantages.length > 0}
              <ul class="setups setups--pinned">
                {#each foeAdvantages as adv (adv.id)}
                  <li>
                    <span class="pixel pill">{ADVANTAGE_PAYOFF_LABEL[adv.payoff]}</span>
                    <span class="setup-text">{adv.setup}</span>
                  </li>
                {/each}
              </ul>
            {/if}

            <!--
              Warden details disclosure. Collapsed by default. The
              numbers exist for audit / trust, but exposing them as
              the default read would un-do the whole point of the
              strip. Native <details> keeps keyboard / a11y
              behavior without us building a custom toggle.
            -->
            <details class="warden">
              <summary>
                <span class="pixel">Warden details</span>
              </summary>
              <dl class="stats">
                <dt>HP</dt>
                <dd class="pixel">
                  {foe.hp}
                  <span class="muted">/ {foe.max_hp}</span>
                </dd>
                <dt>Armor</dt>
                <dd class="pixel">{foe.armor}</dd>
                {#if foe.weapon_damage_die !== null}
                  <dt>Weapon</dt>
                  <dd class="pixel">d{foe.weapon_damage_die}</dd>
                {/if}
                <dt>STR</dt>
                <dd class="pixel">
                  {foe.str_score}
                  {#if foe.str_score !== foe.max_str_score}
                    <span class="muted">/ {foe.max_str_score}</span>
                  {/if}
                </dd>
                <dt>DEX</dt>
                <dd class="pixel">{foe.dex_score}</dd>
                <dt>WIL</dt>
                <dd class="pixel">{foe.wil_score}</dd>
                {#if foe.morale !== null}
                  <dt>Morale ≤</dt>
                  <dd class="pixel">{foe.morale}</dd>
                {/if}
              </dl>

              {#if foe.weakness !== ""}
                <p class="warden__line warden__line--weakness">
                  <span class="kicker">Weakness</span>
                  <span>{foe.weakness}</span>
                </p>
              {/if}
              {#if foe.tactics !== ""}
                <p class="warden__line warden__line--tactics">
                  <span class="kicker">Tactics</span>
                  <span>{foe.tactics}</span>
                </p>
              {/if}
            </details>
          </li>
        {/each}
      </ul>
    {/if}

    <p class="retreat-hint small">
      Type <code>/retreat</code> to attempt to disengage.
    </p>
  </details>
{:else if encounter !== null && !encounter.active && encounter.summary !== null}
  <p class="cleared muted small">{encounter.summary}</p>
{/if}

<style>
  /*
   * The strip rides inline with chat messages, so its width follows
   * the chat column rather than an aside panel. We keep the parchment-
   * over-iron palette so it visually belongs to the same family as
   * MechanicalReceipt while still standing apart from prose bubbles.
   */
  /*
   * `<details>` defaults give us the right open/closed semantics
   * but the default `<summary>` styling (list marker, default
   * cursor on some platforms) isn't right for an inline panel that
   * sits between chat messages. We strip the marker, then layer
   * the parchment-over-iron palette so the strip visually belongs
   * to the same family as MechanicalReceipt while still standing
   * apart from prose bubbles.
   */
  .strip {
    margin: 0.65rem auto 0.85rem;
    max-width: 72ch;
    border: 1px solid color-mix(in oklab, var(--gold-tarnished) 35%, transparent);
    background: linear-gradient(
      180deg,
      color-mix(in oklab, var(--ink-deep) 92%, var(--rust-iron)) 0%,
      color-mix(in oklab, var(--ink-black) 96%, var(--rust-iron)) 100%
    );
    color: var(--paper-warm);
  }
  .strip__head {
    list-style: none;
    cursor: pointer;
    user-select: none;
    padding: 0.6rem 0.85rem;
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 0.6rem;
  }
  /* Hide the default list marker across browsers. */
  .strip__head::-webkit-details-marker { display: none; }
  .strip__head::marker { content: ""; }
  .strip__head-main {
    display: flex;
    align-items: baseline;
    gap: 0.55rem;
    min-width: 0;
  }
  .strip__head-aside {
    display: inline-flex;
    align-items: baseline;
    gap: 0.5rem;
    color: var(--gold-tarnished);
    font-size: 0.78rem;
    letter-spacing: 0.04em;
  }
  .strip__count .muted { color: var(--paper-shadow); }
  /*
   * Chevron rotates instead of being swapped for "▾" because the
   * open/closed cue should be silent typography, not a glyph
   * change that re-layouts the right edge of the header.
   */
  .strip__chevron {
    display: inline-block;
    font-family: var(--font-pixel);
    color: var(--gold-tarnished);
    transition: transform 120ms ease, color 120ms ease;
  }
  .strip[open] .strip__chevron {
    transform: rotate(90deg);
    color: var(--gold-bright);
  }
  .strip__head:hover .strip__chevron,
  .strip__head:focus-visible .strip__chevron {
    color: var(--gold-bright);
  }
  .strip[open] .strip__head {
    border-bottom: var(--rule-hair);
  }
  /*
   * Direct-child grid on the opened body. We can't put the gap on
   * the host `<details>` because the summary would inherit the
   * gap too and visually drift away from the body when open.
   * Selecting "every direct child after the summary" gives us the
   * vertical rhythm we used to get from the old `display: grid`
   * on the outer aside.
   */
  .strip[open] > :not(summary) {
    margin: 0.55rem 0.9rem 0;
  }
  .strip[open] > :not(summary):last-child {
    margin-bottom: 0.8rem;
  }
  .strip .kicker { margin: 0; }
  .headline {
    color: var(--gold-bright);
    font-size: 0.95rem;
  }

  .flags {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 0.35rem;
  }
  .flag {
    display: grid;
    grid-template-columns: max-content 1fr;
    gap: 0.55rem;
    padding: 0.4rem 0.55rem;
    border-left: 2px solid var(--gold-tarnished);
    background: color-mix(in oklab, var(--ink-black) 60%, transparent);
    align-items: baseline;
  }
  .flag--first {
    border-left-color: var(--gold-bright);
  }
  .flag--morale {
    border-left-color: var(--rust-iron);
  }
  .flag--ambush {
    border-left: 3px solid var(--rust-blood);
    background: color-mix(in oklab, var(--rust-blood) 18%, var(--ink-black) 70%);
  }
  .flag--ambush .flag-label {
    color: var(--rust-blood);
  }
  .flag-label {
    color: var(--gold-tarnished);
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  .flag-text {
    font-size: 0.88rem;
    color: var(--paper-bone);
  }

  .foes {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 0.5rem;
  }
  .foe {
    padding: 0.55rem 0.7rem;
    border: 1px solid color-mix(in oklab, var(--gold-tarnished) 30%, transparent);
    background: color-mix(in oklab, var(--ink-deep) 80%, transparent);
    display: grid;
    gap: 0.35rem;
  }
  /*
   * Wound-tier coloring rides the left edge of the card. It's the
   * only place HP-ratio leaks into the visual hierarchy by default,
   * and even then it's a single bar — the numeric HP is gated behind
   * the Warden disclosure.
   */
  .foe--fresh    { border-left: 3px solid var(--gold-tarnished); }
  .foe--wounded  { border-left: 3px solid var(--rust-iron); }
  .foe--critical {
    border-left: 3px solid var(--rust-blood);
    background: color-mix(in oklab, var(--rust-blood) 10%, var(--ink-deep) 90%);
  }
  .foe--down {
    border-left: 3px dashed color-mix(in oklab, var(--paper-shadow) 50%, transparent);
    opacity: 0.65;
  }
  /*
   * Threat tier hints on the top edge for non-ordinary foes; ordinary
   * gets no extra bar so the rail stays calm on most fights.
   */
  .foe.threat--serious {
    border-top: 2px solid color-mix(in oklab, var(--rust-blood) 60%, transparent);
  }
  .foe.threat--hardier {
    border-top: 2px solid color-mix(in oklab, var(--rust-iron) 55%, transparent);
  }
  .foe__head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 0.5rem;
    flex-wrap: wrap;
  }
  .foe__name {
    font-family: var(--font-display);
    font-size: 1rem;
    color: var(--paper-warm);
  }
  .foe__description {
    margin: 0;
    color: var(--paper-shadow);
    font-style: italic;
    font-size: 0.85rem;
  }
  .foe__status {
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--gold-tarnished);
  }
  .foe--critical .foe__status,
  .foe--down .foe__status {
    color: var(--rust-iron);
  }

  /* Threat tier pip (only shown for hardier / serious — see template). */
  .threat-pip {
    padding: 0.05rem 0.4rem;
    border: 1px solid currentColor;
    font-size: 0.6rem;
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }
  .threat-pip--hardier {
    color: var(--rust-iron);
  }
  .threat-pip--serious {
    color: var(--rust-blood);
  }

  .foe__read {
    margin: 0;
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
    font-size: 0.88rem;
  }
  .cue {
    padding: 0.1rem 0.5rem;
    border: 1px solid color-mix(in oklab, var(--gold-tarnished) 40%, transparent);
    color: var(--paper-warm);
    font-family: var(--font-pixel);
    font-size: 0.72rem;
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }
  .cue--wound--fresh {
    color: var(--gold-bright);
    border-color: color-mix(in oklab, var(--gold-bright) 50%, transparent);
  }
  .cue--wound--wounded {
    color: var(--rust-iron);
    border-color: color-mix(in oklab, var(--rust-iron) 60%, transparent);
  }
  .cue--wound--critical {
    color: var(--rust-blood);
    border-color: color-mix(in oklab, var(--rust-blood) 60%, transparent);
  }
  .cue--wound--down {
    color: var(--paper-shadow);
    border-color: color-mix(in oklab, var(--paper-shadow) 40%, transparent);
  }
  .cue--armor {
    color: var(--paper-bone);
  }

  /* Warden disclosure — collapsed by default; native <details>. */
  .warden {
    margin-top: 0.1rem;
    border-top: var(--rule-hair);
    padding-top: 0.45rem;
  }
  .warden > summary {
    list-style: none;
    cursor: pointer;
    color: var(--gold-tarnished);
    font-size: 0.7rem;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    user-select: none;
  }
  .warden > summary::-webkit-details-marker { display: none; }
  .warden > summary::marker { content: ""; }
  .warden > summary::before {
    content: "▸ ";
    color: var(--gold-tarnished);
  }
  .warden[open] > summary::before {
    content: "▾ ";
    color: var(--gold-bright);
  }
  .warden > summary:hover { color: var(--gold-bright); }
  .warden[open] > summary { color: var(--gold-bright); }

  .stats {
    margin: 0.45rem 0 0.25rem;
    display: grid;
    grid-template-columns: max-content 1fr max-content 1fr;
    column-gap: 0.55rem;
    row-gap: 0.2rem;
    font-size: 0.82rem;
  }
  .stats dt {
    margin: 0;
    font-family: var(--font-pixel);
    font-size: 0.7rem;
    color: var(--gold-tarnished);
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  .stats dd {
    margin: 0;
    color: var(--paper-warm);
  }
  .stats .muted { color: var(--paper-shadow); }
  .warden__line {
    margin: 0.3rem 0 0;
    display: grid;
    gap: 0.18rem;
  }
  .warden__line--weakness { font-size: 0.86rem; }
  .warden__line--tactics  { font-size: 0.82rem; color: var(--paper-shadow); }

  /* F-18 pending setups (loose and per-foe). */
  .setups {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 0.3rem;
  }
  .setups--loose {
    padding: 0.45rem 0.55rem;
    border: 1px dashed color-mix(in oklab, var(--gold-bright) 50%, transparent);
    background: color-mix(in oklab, var(--gold-tarnished) 10%, var(--ink-deep) 90%);
    display: grid;
    gap: 0.3rem;
  }
  .setups--loose ul {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 0.25rem;
  }
  .setups--pinned { margin-top: 0.1rem; }
  .setups li {
    display: grid;
    grid-template-columns: max-content 1fr;
    gap: 0.4rem;
    align-items: baseline;
    font-size: 0.85rem;
    color: var(--paper-bone);
  }
  .pill {
    padding: 0.1rem 0.45rem;
    border: 1px solid var(--gold-bright);
    color: var(--gold-bright);
    font-size: 0.66rem;
    letter-spacing: 0.05em;
    text-transform: uppercase;
  }
  .setup-text {
    font-style: italic;
    color: var(--paper-warm);
  }

  .retreat-hint {
    margin: 0;
    color: var(--paper-shadow);
    font-style: italic;
  }
  .retreat-hint code {
    color: var(--gold-tarnished);
    font-family: var(--font-pixel);
  }

  .cleared {
    margin: 0.65rem auto;
    max-width: 72ch;
    font-style: italic;
    color: var(--paper-shadow);
  }

  .kicker {
    color: var(--gold-tarnished);
    font-size: 0.72rem;
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }
  .small { font-size: 0.78rem; }
  .muted { color: var(--paper-shadow); }
</style>
