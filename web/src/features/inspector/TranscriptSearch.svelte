<script lang="ts">
  import {
    deriveTranscriptRows,
    searchTranscript,
    type SearchMatch,
  } from "../../lib/history";
  import { game } from "../../lib/store.svelte";
  import type { GameState } from "../../lib/types";

  const { state: gs }: { state: GameState } = $props();
  let query: string = $state("");
  const rows = $derived(deriveTranscriptRows(gs, game.notes));
  const hits = $derived<readonly SearchMatch[]>(
    query.trim() === "" ? [] : searchTranscript(rows, query, { limit: 80 }),
  );

  function speakerLabel(kind: SearchMatch["kind"]): string {
    switch (kind) {
      case "dm": return "DM";
      case "player": return "You";
      case "system": return "Engine";
    }
  }

  function relativeTime(iso: string): string {
    const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
    if (seconds < 60) return `${Math.round(seconds)}s ago`;
    if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
    return new Date(iso).toLocaleDateString();
  }

  const renderedHits = $derived(
    hits.map((hit) => ({
      ...hit,
      speaker: speakerLabel(hit.kind),
      when: relativeTime(hit.timestamp),
      before: hit.snippet.slice(0, hit.highlightStart),
      match: hit.snippet.slice(hit.highlightStart, hit.highlightEnd),
      after: hit.snippet.slice(hit.highlightEnd),
    })),
  );

  function jump(rowId: string): void {
    game.requestScrollTo(rowId);
    game.inspectorOpen = false;
  }
</script>

<div class="search">
  <input type="search" class="search__input" placeholder="Search the chat — names, events, items…" aria-label="Search transcript" bind:value={query} />
  {#if query.trim() !== ""}
    <button type="button" class="ghost search__clear" onclick={() => (query = "")} aria-label="Clear search">Clear</button>
  {/if}
</div>

{#if query.trim() === ""}
  <p class="muted search__hint">Search every committed beat — DM prose, your actions, engine notes. Hits jump the chat to the moment.</p>
{:else if renderedHits.length === 0}
  <p class="muted search__hint">Nothing matches “{query.trim()}”.</p>
{:else}
  <ul class="search__hits">
    {#each renderedHits as hit (`${hit.rowId}_${hit.source}`)}
      <li>
        <button type="button" class="hit" onclick={() => jump(hit.rowId)} title="Jump to this moment in the chat">
          <span class="hit__meta pixel">
            <span class="hit__speaker">{hit.speaker}</span>
            {#if hit.source === "outcome"}<span class="hit__source">in receipt</span>{/if}
            <span class="hit__time">{hit.when}</span>
          </span>
          <span class="hit__snippet">{hit.before}<mark>{hit.match}</mark>{hit.after}</span>
        </button>
      </li>
    {/each}
  </ul>
{/if}

<style>
  .search { display: flex; gap: 0.45rem; align-items: center; margin-bottom: 0.4rem; }
  .search__input { flex: 1; min-width: 0; padding: 0.4rem 0.55rem; font-family: var(--font-body); font-size: 0.9rem; line-height: 1.3; color: var(--paper-bone); background: rgba(0, 0, 0, 0.35); border: 1px solid color-mix(in oklab, var(--gold-tarnished) 35%, transparent); border-radius: 2px; }
  .search__input::placeholder { color: color-mix(in oklab, var(--paper-shadow) 80%, transparent); font-style: italic; }
  .search__input:focus { outline: none; border-color: var(--gold-bright); box-shadow: 0 0 0 1px var(--gold-bright) inset; }
  .search__clear { padding: 0.32rem 0.55rem; font-size: 0.7rem; letter-spacing: 0.05em; text-transform: uppercase; }
  .search__hint { margin: 0.2rem 0 0; font-size: 0.78rem; line-height: 1.4; font-style: italic; }
  .search__hits { list-style: none; padding: 0; margin: 0.35rem 0 0; display: flex; flex-direction: column; gap: 0.35rem; }
  .hit { display: flex; flex-direction: column; gap: 0.2rem; width: 100%; text-align: left; padding: 0.45rem 0.55rem; background: rgba(0, 0, 0, 0.25); border: 1px solid color-mix(in oklab, var(--gold-tarnished) 25%, transparent); border-radius: 2px; color: var(--paper-bone); cursor: pointer; }
  .hit:hover { background: rgba(0, 0, 0, 0.4); border-color: var(--gold-bright); }
  .hit:focus-visible { outline: 2px solid var(--gold-bright); outline-offset: 1px; }
  .hit__meta { display: flex; align-items: baseline; gap: 0.5rem; font-size: 0.65rem; color: var(--gold-tarnished); text-transform: uppercase; letter-spacing: 0.06em; }
  .hit__speaker { color: var(--gold-bright); }
  .hit__source { color: color-mix(in oklab, var(--rust-iron) 70%, var(--paper-stained)); }
  .hit__time { margin-left: auto; color: var(--paper-shadow); }
  .hit__snippet { font-family: var(--font-body); font-size: 0.86rem; line-height: 1.45; color: var(--paper-warm); }
  mark { background: color-mix(in oklab, var(--gold-bright) 32%, transparent); color: var(--paper-warm); padding: 0 1px; border-radius: 2px; }
</style>
