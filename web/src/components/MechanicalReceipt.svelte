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
  import {
    cairnHeadline,
    formatAbility,
    formatRestKind,
    formatStance,
  } from "../lib/cairn";
  import type { OracleOutcome } from "../lib/types";

  type Props = { outcome: OracleOutcome; defaultOpen?: boolean };
  const { outcome, defaultOpen = false }: Props = $props();

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
        return "No roll";
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
        return "system";
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
      || outcome.kind === "retreat",
  );
</script>

<div class="receipt" class:open>
  <button class="strip" type="button" onclick={() => (open = !open)}>
    <span class="tag tag--{tagFlavor}">
      {outcome.kind.replace("_", " ")}
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

      {#if isCairnKind && cairn !== null}
        <dl class="cairn">
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
          {#if cairn.attack_stance !== null}
            <dt>Stance</dt>
            <dd class="pixel">{formatStance(cairn.attack_stance)}</dd>
          {/if}
          {#if cairn.weapon_name !== null}
            <dt>Weapon</dt>
            <dd>{cairn.weapon_name}</dd>
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
    </div>
  {/if}
</div>

<style>
  .receipt {
    border-left: 2px solid color-mix(in oklab, var(--gold-tarnished) 60%, transparent);
    margin-top: 0.3rem;
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
</style>
