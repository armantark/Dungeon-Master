<!--
@component
MechanicalReceipt — the "what did the dice actually say" panel that hangs
under any DM message produced by an oracle outcome.

Default collapsed because we want the chat to feel like a conversation.
Expanded shows the dice number(s), the oracle's structured summary, and
the chaos factor at the time. This is the "trust signal" surface: any
time the player suspects the model invented a roll, they can verify.

The receipt is exhaustive over OracleKind by design. Every kind that
the backend can emit must have a stable headline branch and a body
section that exposes its mechanical fields. Cairn-flavored outcomes
(`save`, `attack`, `harm`, `recovery`) reuse the existing dice readout
and add a Cairn-specific dl block with the resolution snapshot.
-->
<script lang="ts">
  import { untrack } from "svelte";
  import { ADVANTAGE_PAYOFF_LABEL } from "../lib/campaign-seed";
  import {
    cairnHeadline,
    formatAbility,
    formatCombatInitiator,
    formatDayPhase,
    formatResourceDelta,
    formatRestKind,
    formatStance,
    formatTurnTimeAdvance,
    isAmbushOpener,
    itemEffectLabel,
    itemPowerKindLabel,
    survivalChanged,
  } from "../lib/cairn";
  import {
    npcDisplayLabel,
    npcKnownByDescriptor,
    referencedNpcsForOutcome,
  } from "../lib/npcs";
  import { game } from "../lib/store.svelte";
  import { referencedThreadsForOutcome } from "../lib/threads";
  import type { GameThread, NPC, OracleOutcome } from "../lib/types";

  type Props = {
    outcome: OracleOutcome;
    threads?: readonly GameThread[];
    npcs?: readonly NPC[];
    defaultOpen?: boolean;
  };
  const {
    outcome,
    threads = [],
    npcs = [],
    defaultOpen = false,
  }: Props = $props();

  let open: boolean = $state(untrack(() => defaultOpen));

  // The kind switch is exhaustive on OracleKind. Adding a new kind to
  // types.ts will surface here as a TS error, which is the whole point.
  const headline = $derived.by((): string => {
    switch (outcome.kind) {
      case "yes_no":
        return outcome.answer
          ? `${outcome.answer} (${outcome.probability ?? "?"}%)`
          : "Oracle answered.";
      case "random_event":
        return `Event · ${outcome.event_focus ?? "?"}`;
      case "scene_check":
        return `Scene · ${outcome.scene_status ?? "?"}`;
      case "player_action":
        return cairnHeadline(outcome) ?? "No roll";
      case "save":
      case "attack":
      case "harm":
      case "recovery":
      case "retreat":
        return cairnHeadline(outcome) ?? "Cairn resolution";
    }
  });

  // Cairn outcomes get a distinct tag color so the player's eye separates
  // engine-determinist (oracle) from Cairn-determinist (mechanical) at a
  // glance. We keep the existing oracle/system distinction for the rest.
  const tagFlavor = $derived.by((): "oracle" | "system" | "cairn" => {
    switch (outcome.kind) {
      case "save":
      case "attack":
      case "harm":
      case "recovery":
      case "retreat":
        return "cairn";
      case "player_action":
        return outcome.cairn?.item_name == null ? "system" : "cairn";
      case "yes_no":
      case "random_event":
      case "scene_check":
        return "oracle";
    }
  });

  // Cairn body content is grouped through these getters so the Svelte
  // markup stays focused. Each getter surfaces the fields the backend's
  // CairnResolution actually populates for that kind. Fields that aren't
  // populated (null) are skipped — the receipt renders only what's real.
  const cairn = $derived(outcome.cairn);
  const isCairnKind = $derived(
    outcome.kind === "save"
      || outcome.kind === "attack"
      || outcome.kind === "harm"
      || outcome.kind === "recovery"
      || outcome.kind === "retreat"
      || (outcome.kind === "player_action" && outcome.cairn?.item_name != null),
  );

  // F-05 surfacing.
  // - `ambush` lights up the strip (collapsed receipt) so the player
  //   sees the cause of a harm row at a glance — relevant when
  //   scrolling oracle history later in the campaign.
  // - `initiatorLabel` populates an Initiative row in the dl when the
  //   resolution belongs to a tracked encounter (player attack OR
  //   enemy opener); null for harm outside combat, so the row
  //   disappears for trap damage etc.
  const ambush = $derived(isAmbushOpener(outcome));
  const initiatorLabel = $derived(
    cairn === null ? null : formatCombatInitiator(cairn.combat_initiator),
  );
  const coordinatedParticipants = $derived(cairn?.coordinated_participants ?? []);
  const resourceDeltas = $derived(cairn?.resource_deltas ?? []);

  // Survival-clock deltas. The backend stamps `time_advance` on every
  // resolution that billed time and a *_before/*_after snapshot pair
  // on every counter that moved. We render survival rows only when
  // any of those pairs actually shifted (or the turn ate); a
  // `time_advance` of `none` with no eat leaves the section silent so
  // pure-roll outcomes (a save with no fiction time) don't add noise.
  const showSurvival = $derived(cairn !== null && survivalChanged(cairn));
  const turnTimeLabel = $derived(
    cairn === null ? null : formatTurnTimeAdvance(cairn.time_advance),
  );
  // We collapse the day / phase / watch trio into one human row when
  // any of them moved. The wire stores them independently, but the
  // player reads them as a single "where am I in the day" beat.
  const dayPhaseLine = $derived.by((): string | null => {
    if (cairn === null) return null;
    const dayBefore = cairn.day_number_before;
    const dayAfter = cairn.day_number_after;
    const phaseBefore = cairn.day_phase_before;
    const phaseAfter = cairn.day_phase_after;
    if (dayBefore === null || dayAfter === null) return null;
    if (phaseBefore === null || phaseAfter === null) return null;
    const before = `Day ${dayBefore} · ${formatDayPhase(phaseBefore)}`;
    const after = `Day ${dayAfter} · ${formatDayPhase(phaseAfter)}`;
    if (before === after) return before;
    return `${before} → ${after}`;
  });
  // Aggregate "Deprived" delta — true → false (cleared by eating /
  // sleeping) or false → true (newly deprived). We render it as the
  // single most legible deprivation row so the player sees the
  // verdict before the disaggregated food/sleep flips. If neither
  // changed, this returns null and the row disappears.
  const deprivedDelta = $derived.by((): string | null => {
    if (cairn === null) return null;
    const before = cairn.deprived_before;
    const after = cairn.deprived_after;
    if (before === null || after === null) return null;
    if (before === after) return null;
    return after ? "Newly deprived" : "Deprivation cleared";
  });
  const foodDelta = $derived.by((): string | null => {
    if (cairn === null) return null;
    const before = cairn.food_deprived_before;
    const after = cairn.food_deprived_after;
    if (before === null || after === null || before === after) return null;
    return after ? "Hungry to deprived" : "Food deprivation cleared";
  });
  const sleepDelta = $derived.by((): string | null => {
    if (cairn === null) return null;
    const before = cairn.sleep_deprived_before;
    const after = cairn.sleep_deprived_after;
    if (before === null || after === null || before === after) return null;
    return after ? "Weary to deprived" : "Sleep deprivation cleared";
  });
  const referencedThreads = $derived(referencedThreadsForOutcome(threads, outcome));
  const referencedNpcs = $derived(referencedNpcsForOutcome(npcs, outcome));

  function focusThread(threadId: string): void {
    game.requestInspectorFocus("threads", threadId);
  }

  function focusNpc(npcId: string): void {
    game.requestInspectorFocus("npcs", npcId);
  }
</script>

<div class="receipt" class:open class:ambush>
  <button class="strip" type="button" onclick={() => (open = !open)}>
    <span class="tag tag--{tagFlavor}">
      <!--
        F-05: when an enemy opener triggered this harm, swap the tag
        text from "harm" to "ambush" so the collapsed strip reads
        true to what just happened. The underlying outcome.kind stays
        "harm" — this is presentational only.
      -->
      {outcome.kind === "player_action" && outcome.cairn?.item_name != null
        ? "item"
        : ambush
          ? "ambush"
          : outcome.kind.replace("_", " ")}
    </span>
    <span class="line pixel">{headline}</span>
    <span class="chev pixel">{open ? "▾" : "▸"}</span>
  </button>

  {#if open}
    <div class="body">
      {#if outcome.rolls.length > 0}
        <ul class="rolls">
          {#each outcome.rolls as roll (roll.label)}
            <li>
              <span class="kicker">{roll.label.replaceAll("_", " ")}</span>
              <span class="pixel die">{roll.result}</span>
              <span class="muted pixel">d{roll.sides}</span>
            </li>
          {/each}
        </ul>
      {/if}

      <dl>
        {#if outcome.question}
          <dt>Question</dt>
          <dd>{outcome.question}</dd>
        {/if}
        {#if outcome.likelihood}
          <dt>Likelihood</dt>
          <dd>{outcome.likelihood}</dd>
        {/if}
        {#if outcome.event_focus}
          <dt>Event</dt>
          <dd>
            <span class="pixel">{outcome.event_focus}</span> ·
            {outcome.event_action} {outcome.event_tone} {outcome.event_subject}
          </dd>
        {/if}
        {#if outcome.scene_status}
          <dt>Scene status</dt>
          <dd class="pixel">{outcome.scene_status}</dd>
        {/if}
        <dt>Chaos at the time</dt>
        <dd class="pixel">{outcome.chaos_factor}</dd>
        <dt>Summary</dt>
        <dd class="muted">{outcome.summary}</dd>
      </dl>

      {#if referencedThreads.length > 0 || referencedNpcs.length > 0}
        <!--
          H-02: receipts are no longer only "trust the dice" surfaces.
          They also surface the continuity objects this turn touched and
          deep-link into the inspector's canonical read-only panels.
          Thread/NPC links stay compact by design — navigation help, not
          a second quest log.
        -->
        <div class="references">
          {#if referencedThreads.length > 0}
            <div class="reference-group">
              <span class="reference-label kicker">Threads</span>
              <div class="reference-pills">
                {#each referencedThreads as thread (thread.id)}
                  <button
                    type="button"
                    class="reference-pill pixel"
                    onclick={() => focusThread(thread.id)}
                    title="Open this thread in the Inspector"
                  >
                    {thread.title}
                  </button>
                {/each}
              </div>
            </div>
          {/if}

          {#if referencedNpcs.length > 0}
            <div class="reference-group">
              <span class="reference-label kicker">Figures</span>
              <div class="reference-pills">
                {#each referencedNpcs as npc (npc.id)}
                  <button
                    type="button"
                    class="reference-pill pixel"
                    class:reference-pill--descriptor={npcKnownByDescriptor(npc)}
                    onclick={() => focusNpc(npc.id)}
                    title={npcKnownByDescriptor(npc)
                      ? "Open this known-by-sign figure in the Inspector"
                      : "Open this NPC in the Inspector"}
                  >
                    {npcDisplayLabel(npc)}
                  </button>
                {/each}
              </div>
            </div>
          {/if}
        </div>
      {/if}

      {#if isCairnKind && cairn !== null}
        <dl class="cairn">
          {#if cairn.actor_name != null}
            <dt>Actor</dt>
            <dd>{cairn.actor_name}</dd>
          {/if}
          {#if initiatorLabel !== null}
            <!--
              F-05: surface who opened the fight inside the receipt so
              the row is searchable / scrubbable later. We render this
              first so it frames the rest of the resolution
              (damage, HP, scar) — "Foe seized initiative · 2 dmg ·
              HP 4" reads as cause then effect. Only present when the
              backend has actually decided an initiator (i.e. the
              resolution belongs to a tracked encounter).
            -->
            <dt>Initiative</dt>
            <dd>{initiatorLabel}</dd>
          {/if}
          {#if cairn.ability !== null}
            <dt>Ability</dt>
            <dd class="pixel">{formatAbility(cairn.ability)}</dd>
          {/if}
          {#if cairn.target !== null}
            <dt>Target</dt>
            <dd class="pixel">≤ {cairn.target}</dd>
          {/if}
          {#if cairn.success !== null}
            <dt>Result</dt>
            <dd class="pixel">{cairn.success ? "Passed" : "Failed"}</dd>
          {/if}
          {#if cairn.item_name != null}
            <dt>Item</dt>
            <dd>{cairn.item_name}</dd>
          {/if}
          {#if cairn.item_power_kind != null}
            <dt>Power</dt>
            <dd class="pixel">{itemPowerKindLabel(cairn.item_power_kind)}</dd>
          {/if}
          {#if cairn.item_effect_kind != null}
            <dt>Effect</dt>
            <dd class="pixel">{itemEffectLabel(cairn.item_effect_kind)}</dd>
          {/if}
          {#if cairn.effect_summary != null}
            <dt>Effect summary</dt>
            <dd>{cairn.effect_summary}</dd>
          {/if}
          {#if cairn.uses_before != null}
            <dt>Uses</dt>
            <dd class="pixel">{cairn.uses_before} → {cairn.uses_after ?? 0}</dd>
          {/if}
          {#if resourceDeltas.length > 0}
            <dt>Resource</dt>
            <dd class="resource-list">
              {#each resourceDeltas as delta, index (`${delta.item_id ?? "item"}-${delta.resource_id ?? "resource"}-${delta.reason}-${index}`)}
                <span class="resource-chip">
                  <span class="pixel">{formatResourceDelta(delta)}</span>
                  <span class="muted">{delta.reason.replaceAll("_", " ")}</span>
                </span>
              {/each}
            </dd>
          {/if}
          {#if cairn.recharge_condition != null && cairn.recharge_condition !== ""}
            <dt>Recharge</dt>
            <dd>{cairn.recharge_condition}</dd>
          {/if}
          {#if cairn.attack_stance !== null}
            <dt>Stance</dt>
            <dd class="pixel">{formatStance(cairn.attack_stance)}</dd>
          {/if}
          <!--
            F-18 fictional advantage. The same fields appear on two
            different resolution shapes:
              1. SETUP_ADVANTAGE op — `advantage_setup` is the prose
                 of the maneuver, `advantage_payoff` is the
                 mechanical lever it commits to, `advantage_target_name`
                 names the foe pinned, and `advantage_applied=true`
                 confirms the engine actually attached it.
              2. The follow-up attack that consumed it — same
                 fields are echoed but `advantage_consumed=true`,
                 so the receipt for the swing reads as "powered by
                 your earlier setup".
            We render both shapes through the same rows; the
            "Setup" label changes meaning by context, but the
            player reads both as the same lineage of cause and
            effect.
          -->
          {#if cairn.advantage_payoff != null}
            <dt>Advantage payoff</dt>
            <dd class="pixel">{ADVANTAGE_PAYOFF_LABEL[cairn.advantage_payoff]}</dd>
          {/if}
          {#if cairn.advantage_setup != null && cairn.advantage_setup !== ""}
            <dt>Setup</dt>
            <dd>{cairn.advantage_setup}</dd>
          {/if}
          {#if cairn.advantage_target_name != null && cairn.advantage_target_name !== ""}
            <dt>Setup target</dt>
            <dd>{cairn.advantage_target_name}</dd>
          {/if}
          {#if cairn.advantage_applied === true || cairn.advantage_consumed === true}
            <dt>Advantage</dt>
            <dd class="pixel">
              {cairn.advantage_consumed === true ? "Consumed" : "Set up"}
            </dd>
          {/if}
          {#if cairn.weakness != null && cairn.weakness !== ""}
            <dt>Weakness</dt>
            <dd>{cairn.weakness}</dd>
          {/if}
          {#if cairn.weapon_name !== null}
            <dt>Weapon</dt>
            <dd>{cairn.weapon_name}</dd>
          {/if}
          {#if cairn.coordinated_attack === true && coordinatedParticipants.length > 0}
            <dt>Coordination</dt>
            <dd class="coordinated-list">
              {#each coordinatedParticipants as participant (participant.actor_id ?? participant.actor_name)}
                <span class="coordinated-chip">
                  <span>{participant.actor_name}</span>
                  <span class="pixel muted">
                    {participant.acted
                      ? `${participant.weapon_name} · ${participant.damage_after_armor} dmg`
                      : `${participant.weapon_name} · no strike`}
                  </span>
                </span>
              {/each}
            </dd>
          {/if}
          {#if cairn.target_name !== null}
            <dt>Target</dt>
            <dd>{cairn.target_name}</dd>
          {/if}
          {#if cairn.target_armor !== null}
            <dt>Armor (target)</dt>
            <dd class="pixel">{cairn.target_armor}</dd>
          {/if}
          {#if cairn.base_damage !== null}
            <dt>Base damage</dt>
            <dd class="pixel">{cairn.base_damage}</dd>
          {/if}
          {#if cairn.damage_after_armor !== null}
            <dt>Damage</dt>
            <dd class="pixel">{cairn.damage_after_armor}</dd>
          {/if}
          {#if cairn.hp_before !== null && cairn.hp_after !== null}
            <dt>HP</dt>
            <dd class="pixel">{cairn.hp_before} → {cairn.hp_after}</dd>
          {/if}
          {#if cairn.str_before !== null && cairn.str_after !== null && cairn.str_before !== cairn.str_after}
            <dt>STR</dt>
            <dd class="pixel">{cairn.str_before} → {cairn.str_after}</dd>
          {/if}
          {#if cairn.dex_before != null && cairn.dex_after != null && cairn.dex_before !== cairn.dex_after}
            <dt>DEX</dt>
            <dd class="pixel">{cairn.dex_before} → {cairn.dex_after}</dd>
          {/if}
          {#if cairn.wil_before != null && cairn.wil_after != null && cairn.wil_before !== cairn.wil_after}
            <dt>WIL</dt>
            <dd class="pixel">{cairn.wil_before} → {cairn.wil_after}</dd>
          {/if}
          {#if cairn.fatigue_before !== null && cairn.fatigue_after !== null && cairn.fatigue_before !== cairn.fatigue_after}
            <dt>Fatigue</dt>
            <dd class="pixel">{cairn.fatigue_before} → {cairn.fatigue_after}</dd>
          {/if}
          {#if cairn.scar_result !== null}
            <dt>Scar</dt>
            <dd>{cairn.scar_result}</dd>
          {/if}
          {#if cairn.rest_kind !== null}
            <dt>Rest</dt>
            <dd>{formatRestKind(cairn.rest_kind)}</dd>
          {/if}
          {#if cairn.retreat_outcome != null}
            <dt>Retreat</dt>
            <dd class="pixel">{cairn.retreat_outcome}</dd>
          {/if}
          {#if cairn.pursuit_active != null}
            <dt>Pursuit</dt>
            <dd class="pixel">{cairn.pursuit_active ? "Active" : "Broken"}</dd>
          {/if}
          {#if cairn.overloaded !== null}
            <dt>Burden</dt>
            <dd class="pixel">{cairn.overloaded ? "Overloaded" : "Within limits"}</dd>
          {/if}
        </dl>
      {/if}

      {#if showSurvival && cairn !== null}
        <!--
          Survival-clock sub-block. We render it independently of the
          Cairn block above because survival can move on any outcome
          (an oracle yes/no that consumed a watch should still show
          its time bill), and because grouping it visually keeps the
          day/watch reads from being lost in the longer save / attack
          / harm rows.
        -->
        <dl class="survival">
          {#if turnTimeLabel !== null}
            <dt>Time</dt>
            <dd class="pixel">{turnTimeLabel}</dd>
          {/if}
          {#if dayPhaseLine !== null}
            <dt>Day-phase</dt>
            <dd class="pixel">{dayPhaseLine}</dd>
          {/if}
          {#if cairn.watches_since_meal_before !== null
              && cairn.watches_since_meal_after !== null
              && cairn.watches_since_meal_before !== cairn.watches_since_meal_after}
            <dt>Food pressure</dt>
            <dd class="pixel">
              {cairn.watches_since_meal_before} → {cairn.watches_since_meal_after}
            </dd>
          {/if}
          {#if cairn.watches_since_sleep_before !== null
              && cairn.watches_since_sleep_after !== null
              && cairn.watches_since_sleep_before !== cairn.watches_since_sleep_after}
            <dt>Sleep pressure</dt>
            <dd class="pixel">
              {cairn.watches_since_sleep_before} → {cairn.watches_since_sleep_after}
            </dd>
          {/if}
          {#if cairn.ration_item_name !== null}
            <dt>Ration</dt>
            <dd>
              {cairn.ration_item_name}
              {#if cairn.ration_uses_before !== null && cairn.ration_uses_after !== null}
                <span class="pixel muted">
                  · {cairn.ration_uses_before} → {cairn.ration_uses_after}
                </span>
              {/if}
            </dd>
          {/if}
          {#if foodDelta !== null}
            <dt>Food</dt>
            <dd>{foodDelta}</dd>
          {/if}
          {#if sleepDelta !== null}
            <dt>Sleep</dt>
            <dd>{sleepDelta}</dd>
          {/if}
          {#if deprivedDelta !== null}
            <dt>Deprived</dt>
            <dd>{deprivedDelta}</dd>
          {/if}
        </dl>
      {/if}
    </div>
  {/if}
</div>

<style>
  .receipt {
    border-left: 2px solid color-mix(in oklab, var(--gold-tarnished) 60%, transparent);
    margin-top: 0.3rem;
  }
  /*
   * F-05: ambush rows get a blood-rust accent on the left bar so the
   * player can scan the oracle history and locate the moment a fight
   * went bad. We don't recolor the whole strip — that would shout
   * over the regular receipt rhythm — just the bar and a faint tint
   * on the strip background.
   */
  .receipt.ambush {
    border-left-color: var(--rust-blood);
  }
  .receipt.ambush .strip {
    background: color-mix(in oklab, var(--rust-blood) 10%, rgba(0, 0, 0, 0.32) 90%);
  }
  .strip {
    width: 100%;
    display: grid;
    grid-template-columns: auto 1fr auto;
    align-items: center;
    gap: 0.6rem;
    padding: 0.4rem 0.6rem;
    background: rgba(0, 0, 0, 0.22);
    color: var(--paper-shadow);
    text-transform: none;
    letter-spacing: 0;
    font-family: var(--font-pixel);
    font-size: 0.8rem;
    border: 0;
    box-shadow: none;
    cursor: pointer;
    text-align: left;
  }
  .strip:hover {
    color: var(--gold-bright);
  }
  .strip .line {
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
  }
  .strip .chev {
    color: var(--gold-tarnished);
  }
  .receipt.open .strip {
    border-bottom: var(--rule-hair);
  }
  .body {
    padding: 0.7rem 0.85rem 0.85rem;
    background: rgba(0, 0, 0, 0.32);
    display: grid;
    gap: 0.6rem;
  }
  .references {
    display: grid;
    gap: 0.45rem;
    border-top: 1px dashed color-mix(in oklab, var(--gold-tarnished) 28%, transparent);
    padding-top: 0.55rem;
  }
  .reference-group {
    display: grid;
    gap: 0.28rem;
  }
  .reference-label {
    margin: 0;
  }
  .reference-pills {
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem;
  }
  .reference-pill {
    padding: 0.3rem 0.5rem;
    font-size: 0.68rem;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    color: var(--paper-bone);
    background: color-mix(in oklab, var(--ink-black) 90%, transparent);
    border: 1px solid color-mix(in oklab, var(--gold-tarnished) 40%, transparent);
    border-radius: 2px;
    cursor: pointer;
    transition: border-color 140ms ease, color 140ms ease, background 140ms ease;
  }
  .reference-pill:hover {
    border-color: var(--gold-bright);
    color: var(--gold-bright);
    background: color-mix(in oklab, var(--ink-black) 76%, transparent);
  }
  .reference-pill:focus-visible {
    outline: 2px solid var(--gold-bright);
    outline-offset: 1px;
  }
  .reference-pill--descriptor {
    border-color: color-mix(in oklab, var(--gold-bright) 28%, var(--paper-shadow));
    color: color-mix(in oklab, var(--paper-bone) 86%, var(--gold-bright));
    font-style: italic;
  }
  .rolls {
    list-style: none;
    padding: 0;
    margin: 0;
    display: flex;
    flex-wrap: wrap;
    gap: 0.6rem;
  }
  .rolls li {
    display: flex;
    align-items: baseline;
    gap: 0.3rem;
    padding: 0.25rem 0.5rem;
    border: 1px solid color-mix(in oklab, var(--gold-tarnished) 50%, transparent);
    background: var(--ink-deep);
  }
  .rolls .kicker {
    margin: 0;
    font-size: 0.65rem;
    color: var(--gold-tarnished);
  }
  .rolls .die {
    color: var(--gold-bright);
    font-size: 1.1rem;
  }
  dl {
    margin: 0;
    display: grid;
    grid-template-columns: max-content 1fr;
    column-gap: 0.85rem;
    row-gap: 0.25rem;
    font-size: 0.85rem;
  }
  dl.cairn {
    border-top: 1px dashed color-mix(in oklab, var(--gold-tarnished) 35%, transparent);
    padding-top: 0.5rem;
  }
  dl.survival {
    border-top: 1px dashed color-mix(in oklab, var(--gold-tarnished) 35%, transparent);
    padding-top: 0.5rem;
  }
  .muted {
    color: var(--gold-tarnished);
  }
  dt {
    font-family: var(--font-pixel);
    font-size: 0.72rem;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: var(--gold-tarnished);
  }
  dd {
    margin: 0;
  }
  .coordinated-list,
  .resource-list {
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem;
  }
  .coordinated-chip,
  .resource-chip {
    display: inline-grid;
    gap: 0.12rem;
    padding: 0.28rem 0.45rem;
    border: 1px solid color-mix(in oklab, var(--gold-tarnished) 38%, transparent);
    background: color-mix(in oklab, var(--ink-black) 82%, transparent);
  }
</style>
