<!--
@component
Drawer — a leather-flap panel that pulls down with a creak.

Used as the host for ThreadsPanel, NPCsPanel, and notes.
-->
<script lang="ts">
  import { untrack, type Snippet } from "svelte";

  type Props = {
    title: string;
    open?: boolean;
    maxHeight?: string;
    children: Snippet;
  };
  const { title, open = true, maxHeight = "none", children }: Props = $props();

  // The prop is intentionally one-shot: the parent specifies the initial
  // openness, then the user toggles it locally. `untrack` makes that
  // contract explicit (and silences the static-analysis warning).
  let isOpen: boolean = $state(untrack(() => open));
</script>

<section class="drawer iron" data-open={isOpen}>
  <button class="flap" onclick={() => (isOpen = !isOpen)}>
    <span class="label">{title}</span>
    <span class="chevron" aria-hidden="true">{isOpen ? "▾" : "▸"}</span>
  </button>
  {#if isOpen}
    <div class="body" style:max-height={maxHeight}>
      {@render children()}
    </div>
  {/if}
</section>

<style>
  .drawer {
    padding: 0;
    overflow: hidden;
  }
  .flap {
    width: 100%;
    background: linear-gradient(
      180deg,
      color-mix(in oklab, var(--ink-deep) 95%, var(--rust-iron)) 0%,
      color-mix(in oklab, var(--ink-black) 96%, var(--rust-iron)) 100%
    );
    border: 0;
    border-bottom: var(--rule-hair);
    padding: 0.9rem 0.75rem;
    min-height: 3.55rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
    color: var(--gold-bright);
    text-transform: none;
    letter-spacing: 0;
    font-family: var(--font-display);
    font-size: 1rem;
    line-height: 1.2;
    color: var(--gold-bright);
    line-height: 1.2;
  }
  .label {
    color: var(--gold-bright);
  }
  .chevron {
    font-family: var(--font-pixel);
    color: var(--gold-tarnished);
  }
  .body {
    padding: 0.65rem 0.75rem 0.75rem;
    overflow-y: auto;
  }
</style>
