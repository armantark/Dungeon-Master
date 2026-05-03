<!--
@component
ThreadsPanel — open campaign threads with stakes.
-->
<script lang="ts">
  import type { GameThread } from "../lib/types";

  type Props = { threads: readonly GameThread[] };
  const { threads }: Props = $props();
</script>

{#if threads.length === 0}
  <p class="muted">No active threads.</p>
{:else}
  <ul>
    {#each threads as thread (thread.id)}
      <li class:resolved={thread.status === "resolved"}>
        <span class="status mono" data-status={thread.status}>{thread.status}</span>
        <h4>{thread.title}</h4>
        {#if thread.stakes}
          <p class="muted" title={thread.stakes}>{thread.stakes}</p>
        {/if}
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
    gap: 0.65rem;
  }
  li {
    border-left: 2px solid color-mix(in oklab, var(--rust-blood) 70%, transparent);
    padding: 0.32rem 0.6rem;
    background: rgba(0, 0, 0, 0.18);
  }
  li.resolved {
    opacity: 0.55;
    border-left-color: color-mix(in oklab, var(--green-verdigris) 70%, transparent);
  }
  .status {
    font-size: 0.65rem;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: var(--rust-iron);
  }
  .status[data-status="resolved"] {
    color: var(--green-verdigris);
  }
  h4 {
    font-family: var(--font-display);
    font-size: 0.96rem;
    margin: 0.1rem 0 0.15rem;
    color: var(--paper-warm);
  }
  p {
    margin: 0;
    font-size: 0.84rem;
    line-height: 1.3;
    display: -webkit-box;
    line-clamp: 3;
    -webkit-line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
</style>
