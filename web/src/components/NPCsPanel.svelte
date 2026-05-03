<!--
@component
NPCsPanel — current cast.
-->
<script lang="ts">
  import type { NPC } from "../lib/types";

  type Props = { npcs: readonly NPC[] };
  const { npcs }: Props = $props();
</script>

{#if npcs.length === 0}
  <p class="muted">No NPCs in scene.</p>
{:else}
  <ul>
    {#each npcs as npc (npc.id)}
      <li>
        <h4>{npc.name}</h4>
        <p class="meta">
          <span class="mono small">{npc.role}</span>
          <span class="dot">•</span>
          <span class="muted" title={npc.disposition}>{npc.disposition}</span>
        </p>
      </li>
    {/each}
  </ul>
{/if}

<style>
  ul {
    list-style: none;
    padding: 0;
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
  }
  li {
    border-left: 2px solid color-mix(in oklab, var(--gold-tarnished) 60%, transparent);
    padding: 0.32rem 0.6rem;
    background: rgba(0, 0, 0, 0.18);
  }
  h4 {
    font-family: var(--font-display);
    font-size: 0.96rem;
    margin: 0;
    color: var(--paper-warm);
  }
  .meta {
    margin: 0.15rem 0 0;
    font-size: 0.82rem;
    display: flex;
    align-items: center;
    gap: 0.4rem;
  }
  .muted {
    display: -webkit-box;
    line-clamp: 2;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .small {
    font-size: 0.72rem;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: var(--gold-tarnished);
  }
  .dot {
    color: var(--paper-shadow);
  }
</style>
