<!--
@component
CombatTracker — round / morale / foe readout for an active encounter.

Why this lives in the inspector rather than the persistent folio rail:
  - Combat is sometimes-on. Pinning it to the folio would burn a real
    chunk of always-visible space on a state that's null for the
    majority of play (exploration, social scenes, downtime).
  - The folio is the *player character's* sheet — keeping enemy state
    on the inspector preserves the symmetry "your stuff lives on the
    rail, the world lives in the drawer".
  - The chat-first principle still holds: the player resolves combat
    through prose; the tracker is the trust signal, not the control.

The component renders nothing when there is no encounter. We read the
encounter via `combatFromState` so the GameState type doesn't have to
carry the optional `combat` field while the backend pass is in flight;
once backend ships the field, this component still works unchanged
(the accessor becomes a direct field read).

The component is read-only. There are no buttons here to attack, harm,
or end combat — those flow through the chat composer and the model's
attack/harm/retreat router. If we ever want explicit controls, they'd
go on a sibling component so this one stays the trust surface.
-->
<script lang="ts">
  import {
    ADVANTAGE_PAYOFF_LABEL,
    THREAT_LEVEL_BLURB,
    THREAT_LEVEL_LABEL,
  } from "../lib/campaign-seed";
  import {
    advantagesForCombatant,
    combatFromState,
    combatantHpTier,
    combatantStatusLabel,
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
  const combatants = $derived<CombatantState[]>(
    encounter === null ? [] : sortCombatants(encounter.combatants),
  );
  const headline = $derived(encounterHeadline(encounter));
  const firstRound = $derived(firstRoundActionGated(encounter));
  const moraleTriggered = $derived(encounter !== null && encounter.morale_triggered);
  // F-18 loose setups (no target_combatant_id pinned). Rendered above
  // the foe list because they apply to the encounter as a whole.
  const looseAdvantages = $derived(unattachedAdvantages(encounter));
  // F-05: surface the ambush cue as long as the encounter is active and
  // the foe was the one who opened it. We keep the flag visible across
  // rounds (not just round 1) because it affects the player's framing
  // for the whole fight — they were jumped, and that pretext shapes
  // disengage / morale narration even later. The flag falls off naturally
  // once the encounter clears (this whole section unmounts).
  const ambushed = $derived(encounter !== null && encounter.active && enemyInitiated(encounter));
</script>

{#if encounter !== null && encounter.active}
  <section class="combat" aria-label="Active combat">
    <header class="combat__head">
      <span class="kicker">Encounter</span>
      <span class="pixel headline">{headline ?? "Active"}</span>
    </header>

    {#if ambushed || firstRound || moraleTriggered}
      <ul class="flags">
        {#if ambushed}
          <!--
            Ambush flag rides above the first-round and morale flags
            because it explains *why* the encounter exists at all (the
            foe seized initiative). When ambush + first-round both
            apply (the most common F-05 case in round 1), the player
            reads the cause first, then the immediate mechanical
            consequence. We don't include a damage number here — the
            receipt directly under the assistant message owns the
            mechanics; this rail is the trust-surface label.
          -->
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

    <p class="retreat-hint small">
      <!--
        Read-only affordance. The tracker is the trust surface, so we
        don't add a button here, but a single italicized tip teaches
        the player the canonical exit path without dragging them into
        /help. Free-text retreats ("I fall back through the gate")
        also work — the planner will route them.
      -->
      Type <code>/retreat</code> to attempt to disengage.
    </p>

    {#if looseAdvantages.length > 0}
      <!--
        F-18: setups that haven't been pinned to a specific foe
        (e.g. a player blinded the room rather than a single
        target). They apply to whichever foe the next attack
        targets, so the tracker keeps them above the foe list as
        a reminder of "live" leverage the player banked.
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
          {@const statusLabel = combatantStatusLabel(foe.status)}
          {@const foeAdvantages = advantagesForCombatant(encounter, foe.id)}
          <li
            class="foe foe--{tier} threat--{foe.threat_level}"
            class:broken={foe.morale_broken}
          >
            <div class="foe__head">
              <span class="foe__name">{foe.name}</span>
              <!--
                F-19: surface the scaling tier on every foe card so
                the player knows whether the rail's HP/armor reflects
                an "ordinary" rabble or a "serious" set-piece. The
                ordinary tier deliberately renders too because
                consistency reads better than "tiers only show up
                on dangerous foes" — the player builds a mental
                model of the difficulty curve over time.
              -->
              <span
                class="foe__threat pixel threat-pip threat-pip--{foe.threat_level}"
                title={THREAT_LEVEL_BLURB[foe.threat_level]}
              >
                {THREAT_LEVEL_LABEL[foe.threat_level]}
              </span>
              {#if statusLabel !== null}
                <span class="foe__status pixel">{statusLabel}</span>
              {/if}
              {#if foe.morale_broken}
                <span class="foe__status pixel">Wavering</span>
              {/if}
            </div>

            {#if foe.tags.length > 0}
              <ul class="tags">
                {#each foe.tags as tag (tag)}
                  <li class="pixel">{tag}</li>
                {/each}
              </ul>
            {/if}

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
              <p class="weakness">
                <span class="kicker">Weakness</span>
                <span>{foe.weakness}</span>
              </p>
            {/if}

            {#if foe.tactics !== ""}
              <p class="tactics muted small">
                <span class="kicker">Tactics</span>
                <span>{foe.tactics}</span>
              </p>
            {/if}

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
          </li>
        {/each}
      </ul>
    {/if}
  </section>
{:else if encounter !== null && !encounter.active && encounter.summary !== null}
  <p class="cleared muted">{encounter.summary}</p>
{/if}

<style>
  .combat {
    display: grid;
    gap: 0.55rem;
  }
  .combat__head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 0.6rem;
  }
  .combat__head .kicker {
    margin: 0;
  }
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
  /*
   * Ambush rides on rust-blood + a slightly heavier left bar so it
   * reads more alarming than the first-round (gold) and morale
   * (rust-iron) cues — the implicit visual hierarchy is "you got
   * jumped" > "you owe a save" > "they're wavering". We tint the
   * background too so the flag stands out from the receipts under it.
   */
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
    padding: 0.5rem 0.65rem;
    border: 1px solid color-mix(in oklab, var(--gold-tarnished) 30%, transparent);
    background: color-mix(in oklab, var(--ink-deep) 80%, transparent);
    display: grid;
    gap: 0.4rem;
  }
  /* HP tier coloring on the left edge — quick scan when the rail is busy. */
  .foe--fresh   { border-left: 3px solid var(--gold-tarnished); }
  .foe--wounded { border-left: 3px solid var(--rust-iron); }
  .foe--critical {
    border-left: 3px solid var(--rust-blood);
    background: color-mix(in oklab, var(--rust-blood) 10%, var(--ink-deep) 90%);
  }
  .foe--down {
    border-left: 3px dashed color-mix(in oklab, var(--paper-shadow) 50%, transparent);
    opacity: 0.65;
  }
  .foe.broken {
    /* Distinct from low-HP — wavering means the morale check connected. */
    box-shadow: inset 0 0 0 1px color-mix(in oklab, var(--gold-bright) 30%, transparent);
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
  .foe__status {
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--gold-tarnished);
  }
  .foe.broken .foe__status,
  .foe--critical .foe__status,
  .foe--down .foe__status {
    color: var(--rust-iron);
  }
  /*
   * F-19 threat tier pip. Sits next to the foe's name as a small
   * uppercase chip. The color tier intentionally matches the
   * difficulty pip on the save card and the danger profile in the
   * seed editor — gold for ordinary / story-tier foes, rust for
   * hardier veterans, blood-red for serious set-piece threats.
   */
  .threat-pip {
    padding: 0.05rem 0.4rem;
    border: 1px solid currentColor;
    font-size: 0.6rem;
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }
  .threat-pip--ordinary {
    color: var(--gold-tarnished);
  }
  .threat-pip--hardier {
    color: var(--rust-iron);
  }
  .threat-pip--serious {
    color: var(--rust-blood);
  }
  /*
   * Threat tier also reinforces the foe-card top-edge hue so a
   * scan of the rail reads tier even before the pip does.
   */
  .foe.threat--serious {
    border-top: 2px solid color-mix(in oklab, var(--rust-blood) 60%, transparent);
  }
  .foe.threat--hardier {
    border-top: 2px solid color-mix(in oklab, var(--rust-iron) 55%, transparent);
  }

  .weakness,
  .tactics {
    margin: 0;
    display: grid;
    gap: 0.18rem;
  }
  .weakness {
    color: var(--paper-warm);
    font-size: 0.86rem;
  }
  .tactics {
    font-size: 0.82rem;
  }
  /*
   * F-18 setups (pinned to a foe or loose). The pill carries the
   * mechanical payoff label so the player reads "Force morale ·
   * (your prose)" and instantly knows what the next swing buys
   * them.
   */
  .setups {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 0.3rem;
  }
  .setups--loose {
    margin: 0;
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
  .setups--pinned {
    margin-top: 0.1rem;
  }
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
  .tags {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-wrap: wrap;
    gap: 0.3rem;
  }
  .tags li {
    padding: 0.05rem 0.35rem;
    border: 1px solid color-mix(in oklab, var(--paper-shadow) 35%, transparent);
    color: var(--paper-shadow);
    font-size: 0.7rem;
    text-transform: lowercase;
  }
  .stats {
    margin: 0;
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
  .stats .muted {
    color: var(--paper-shadow);
  }
  .cleared {
    margin: 0.3rem 0 0;
    font-style: italic;
    font-size: 0.88rem;
  }
  .retreat-hint {
    margin: 0;
    color: var(--paper-shadow);
    font-style: italic;
  }
  .retreat-hint code {
    font-family: var(--font-pixel);
    font-style: normal;
    color: var(--gold-tarnished);
    padding: 0 0.15rem;
  }
  .small {
    font-size: 0.85rem;
  }
</style>
