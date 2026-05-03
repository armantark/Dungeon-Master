<!--
@component
MechanicalReceipt — the "what did the dice actually say" panel that hangs
under any DM message produced by an oracle outcome.

Default collapsed because we want the chat to feel like a conversation.
Expanded shows the dice number(s), the oracle's structured summary, and
the chaos factor at the time. This is the "trust signal" surface: any
time the player suspects the model invented a roll, they can verify.
-->
<script lang="ts">
  import { untrack } from "svelte";
  import type { OracleOutcome } from "../lib/types";

  type Props = { outcome: OracleOutcome; defaultOpen?: boolean };
  const { outcome, defaultOpen = false }: Props = $props();

  let open: boolean = $state(untrack(() => defaultOpen));

  // Build a single human-readable line that captures the mechanic; this
  // is what shows on the collapsed strip. The kind switch is exhaustive.
  const headline = $derived.by(() => {
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
    }
  });
</script>

<div class="receipt" class:open>
  <button class="strip" type="button" onclick={() => (open = !open)}>
    <span class="tag tag--{outcome.kind === 'player_action' ? 'system' : 'oracle'}">
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
  }
  .rolls {
    list-style: none;
    padding: 0;
    margin: 0 0 0.7rem;
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
