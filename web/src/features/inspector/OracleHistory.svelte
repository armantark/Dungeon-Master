<script lang="ts">
  import { SvelteSet } from "svelte/reactivity";

  import { filterOracleHistory, findNarrativeEventForOracle } from "../../lib/history";
  import { game } from "../../lib/store.svelte";
  import type { GameState, OracleKind } from "../../lib/types";
  import MechanicalReceipt from "../play/MechanicalReceipt.svelte";

  const { state: gs }: { state: GameState } = $props();
  let query: string = $state("");
  const kinds = new SvelteSet<OracleKind>();

  const history = $derived([...gs.oracle_history].reverse());
  const filteredHistory = $derived(
    [...filterOracleHistory(gs.oracle_history, { query, kinds })].reverse(),
  );
  const filtersActive = $derived(query.trim() !== "" || kinds.size > 0);

  const KIND_FILTER_OPTIONS: readonly { kind: OracleKind; label: string }[] = [
    { kind: "yes_no", label: "Yes/No" },
    { kind: "random_event", label: "Event" },
    { kind: "scene_check", label: "Scene" },
    { kind: "player_action", label: "Action" },
    { kind: "save", label: "Save" },
    { kind: "attack", label: "Attack" },
    { kind: "harm", label: "Harm" },
    { kind: "recovery", label: "Recover" },
    { kind: "retreat", label: "Retreat" },
  ];

  function toggleKind(kind: OracleKind): void {
    if (kinds.has(kind)) kinds.delete(kind);
    else kinds.add(kind);
  }

  function clearFilters(): void {
    query = "";
    kinds.clear();
  }

  function jump(outcomeId: string): void {
    const eventId = findNarrativeEventForOracle(gs, outcomeId);
    if (eventId === null) return;
    game.requestScrollTo(eventId);
    game.inspectorOpen = false;
  }
</script>

<div class="search">
  <input
    type="search"
    class="search__input"
    placeholder="Filter rolls — names, scars, weapons…"
    aria-label="Filter oracle history"
    bind:value={query}
  />
  {#if filtersActive}
    <button
      type="button"
      class="ghost search__clear"
      onclick={clearFilters}
      aria-label="Clear filters">Clear</button
    >
  {/if}
</div>

<div class="kind-pills" role="group" aria-label="Filter by roll kind">
  {#each KIND_FILTER_OPTIONS as option (option.kind)}
    <button
      type="button"
      class="kind-pill pixel"
      class:kind-pill--on={kinds.has(option.kind)}
      aria-pressed={kinds.has(option.kind)}
      onclick={() => toggleKind(option.kind)}>{option.label}</button
    >
  {/each}
</div>

{#if history.length === 0}
  <p class="muted">No rolls yet.</p>
{:else if filteredHistory.length === 0}
  <p class="muted search__hint">No rolls match the current filter.</p>
{:else}
  <ul class="history">
    {#each filteredHistory as outcome (outcome.id)}
      <li class="history__row">
        <MechanicalReceipt {outcome} threads={gs.threads} npcs={gs.npcs} defaultOpen={false} />
        {#if findNarrativeEventForOracle(gs, outcome.id) !== null}
          <button
            type="button"
            class="ghost history__jump pixel"
            onclick={() => jump(outcome.id)}
            title="Show this roll's narration in the chat">Show in chat</button
          >
        {/if}
      </li>
    {/each}
  </ul>
{/if}

<style>
  .search {
    display: flex;
    gap: 0.45rem;
    align-items: center;
    margin-bottom: 0.4rem;
  }
  .search__input {
    flex: 1;
    min-width: 0;
    padding: 0.4rem 0.55rem;
    font-family: var(--font-body);
    font-size: 0.9rem;
    line-height: 1.3;
    color: var(--paper-bone);
    background: rgba(0, 0, 0, 0.35);
    border: 1px solid color-mix(in oklab, var(--gold-tarnished) 35%, transparent);
    border-radius: 2px;
  }
  .search__input::placeholder {
    color: color-mix(in oklab, var(--paper-shadow) 80%, transparent);
    font-style: italic;
  }
  .search__input:focus {
    outline: none;
    border-color: var(--gold-bright);
    box-shadow: 0 0 0 1px var(--gold-bright) inset;
  }
  .search__clear {
    padding: 0.32rem 0.55rem;
    font-size: 0.7rem;
    letter-spacing: 0.05em;
    text-transform: uppercase;
  }
  .search__hint {
    margin: 0.2rem 0 0;
    font-size: 0.78rem;
    line-height: 1.4;
    font-style: italic;
  }
  .kind-pills {
    display: flex;
    flex-wrap: wrap;
    gap: 0.3rem;
    margin-bottom: 0.45rem;
  }
  .kind-pill {
    padding: 0.28rem 0.5rem;
    font-size: 0.66rem;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: color-mix(in oklab, var(--paper-shadow) 92%, transparent);
    background: rgba(0, 0, 0, 0.25);
    border: 1px solid color-mix(in oklab, var(--gold-tarnished) 30%, transparent);
    border-radius: 2px;
    cursor: pointer;
  }
  .kind-pill:hover {
    color: var(--paper-bone);
    border-color: var(--gold-tarnished);
  }
  .kind-pill:focus-visible {
    outline: 2px solid var(--gold-bright);
    outline-offset: 1px;
  }
  .kind-pill--on {
    color: var(--gold-bright);
    border-color: var(--gold-bright);
    background: color-mix(in oklab, var(--gold-bright) 10%, transparent);
    box-shadow: 0 0 0 1px color-mix(in oklab, var(--gold-bright) 18%, transparent) inset;
  }
  .history {
    list-style: none;
    padding: 0;
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
  }
  .history__row {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }
  .history__jump {
    align-self: flex-start;
    padding: 0.28rem 0.55rem;
    font-size: 0.66rem;
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }
</style>
