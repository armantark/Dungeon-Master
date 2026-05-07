<!--
@component
ThreadsPanel — open campaign threads with stakes.

Threads are mutated dynamically by the backend turn pipeline (F-03):
each resolved turn can run a structured `ThreadUpdater` pass that
creates / updates / resolves threads and reports the touched ids on
the latest oracle outcome. We surface that recency two ways:

  1. Sort: active threads sit above resolved ones, and within each
     status group the recently-touched cards float to the top so the
     player's eye lands on what just changed.
  2. Pulse: a one-shot CSS animation on freshly-touched cards. We
     re-key the highlighted card's wrapper on every render where the
     same id is in the touched set so the pulse only plays once per
     turn and never loops; reduced-motion users get a static accent
     only.

We deliberately stay read-only here — F-03 made threads canon-driven,
not user-edited, so any "edit" affordance would be a regression
against the working rules in the kanban.
-->
<script lang="ts">
  import { onDestroy, tick } from "svelte";
  import { sortThreadsForDisplay } from "../lib/threads";
  import type { GameThread } from "../lib/types";

  type Props = {
    threads: readonly GameThread[];
    /**
     * Set of thread ids the latest turn touched. Optional so legacy
     * callers (e.g. tests, future read-only embeds) keep working.
     * The Inspector derives this from `recentlyTouchedThreadIds`.
     */
    recentlyTouchedIds?: ReadonlySet<string>;
    focusedId?: string | null;
    focusSeq?: number;
  };
  const {
    threads,
    recentlyTouchedIds = new Set<string>(),
    focusedId = null,
    focusSeq = 0,
  }: Props = $props();

  const ordered = $derived(sortThreadsForDisplay(threads, recentlyTouchedIds));

  let listEl: HTMLUListElement | undefined = $state();
  let flashingId: string | null = $state(null);
  let lastFocusSeq: number = $state(-1);
  let focusTimer: ReturnType<typeof setTimeout> | null = null;

  async function revealFocusedThread(threadId: string): Promise<void> {
    await tick();
    const target = listEl?.querySelector<HTMLElement>(
      `[data-thread-id="${CSS.escape(threadId)}"]`,
    );
    if (target === undefined || target === null) return;
    target.scrollIntoView({ behavior: "smooth", block: "nearest" });
    flashingId = threadId;
    if (focusTimer !== null) clearTimeout(focusTimer);
    focusTimer = setTimeout(() => {
      flashingId = null;
      focusTimer = null;
    }, 1700);
  }

  $effect(() => {
    if (focusedId === null) return;
    if (focusSeq === lastFocusSeq) return;
    lastFocusSeq = focusSeq;
    void revealFocusedThread(focusedId);
  });

  onDestroy(() => {
    if (focusTimer !== null) clearTimeout(focusTimer);
  });
</script>

{#if threads.length === 0}
  <p class="muted">No active threads.</p>
{:else}
  <ul bind:this={listEl}>
    {#each ordered as thread (thread.id)}
      {@const justTouched = recentlyTouchedIds.has(thread.id)}
      <li
        data-thread-id={thread.id}
        class:resolved={thread.status === "resolved"}
        class:advanced={justTouched}
        class:focused={flashingId === thread.id}
      >
        <div class="row">
          <span class="status mono" data-status={thread.status}>{thread.status}</span>
          {#if justTouched}
            <span
              class="status mono advanced-pip"
              title="This thread advanced on the latest turn."
            >
              {thread.status === "resolved" ? "just resolved" : "advanced"}
            </span>
          {/if}
        </div>
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
    /*
     * `position: relative` so the one-shot advanced pulse can paint a
     * faint ring via box-shadow without being clipped by the panel's
     * scroll container.
     */
    position: relative;
  }
  li.resolved {
    opacity: 0.55;
    border-left-color: color-mix(in oklab, var(--green-verdigris) 70%, transparent);
  }
  /*
   * "Advanced" is the visual companion to the `recentlyTouchedIds` set.
   * We brighten the left rail to gold (echoing the engine voice) and
   * play a single short pulse so the card calls attention to itself
   * exactly once when it lands. The pulse is gated by
   * prefers-reduced-motion — accessibility-first wins — and the static
   * gold rail still carries the recency cue when motion is muted.
   */
  li.advanced {
    border-left-color: var(--gold-bright);
  }
  li.advanced:not(.resolved) {
    animation: thread-pulse 1.6s ease-out 1;
  }
  li.focused {
    box-shadow:
      0 0 0 1px color-mix(in oklab, var(--gold-bright) 55%, transparent) inset,
      0 0 0 6px color-mix(in oklab, var(--gold-bright) 16%, transparent);
  }
  @keyframes thread-pulse {
    0% {
      box-shadow: 0 0 0 0 color-mix(in oklab, var(--gold-bright) 55%, transparent);
    }
    100% {
      box-shadow: 0 0 0 6px color-mix(in oklab, var(--gold-bright) 0%, transparent);
    }
  }
  @media (prefers-reduced-motion: reduce) {
    li.advanced:not(.resolved) {
      animation: none;
    }
  }
  .row {
    display: flex;
    align-items: baseline;
    gap: 0.5rem;
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
  .advanced-pip {
    color: var(--gold-bright);
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
    /*
     * B-01: the stakes paragraph used to clamp at 3 lines with an
     * ellipsis, which silently dropped the back half of long stakes
     * and forced the player to read them via the title-tooltip.
     * Now that the drawer reserves a scrollbar gutter and the body
     * is internally scrollable, full prose is the right default;
     * `overflow-wrap: anywhere` is the same defensive fallback we
     * use on the drawer body to keep an exotic unbroken token from
     * ever causing horizontal overflow.
     */
    overflow-wrap: anywhere;
  }
</style>
