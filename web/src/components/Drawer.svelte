<!--
@component
Drawer — a leather-flap panel that pulls down with a creak.

Used as the host for ThreadsPanel, NPCsPanel, and notes.
-->
<script lang="ts">
  import { untrack, type Snippet } from "svelte";
  import { randomTexturePosition } from "../lib/randomTexturePosition";

  type Props = {
    title: string;
    open?: boolean;
    maxHeight?: string;
    reopenToken?: number;
    children: Snippet;
  };
  const { title, open = true, maxHeight = "none", reopenToken = 0, children }: Props = $props();

  // The prop is intentionally one-shot: the parent specifies the initial
  // openness, then the user toggles it locally. `untrack` makes that
  // contract explicit (and silences the static-analysis warning).
  let isOpen: boolean = $state(untrack(() => open));
  let lastReopenToken: number = $state(untrack(() => reopenToken));

  // H-02 inspector-focus requests need a way to reopen a closed drawer
  // without taking ownership of its open/closed state away from the user.
  // `reopenToken` is a one-shot nudge: when it changes, we open the
  // drawer, then local toggling resumes as normal.
  $effect(() => {
    if (reopenToken === lastReopenToken) return;
    lastReopenToken = reopenToken;
    isOpen = true;
  });
</script>

<section class="drawer iron" data-open={isOpen}>
  <button class="flap" use:randomTexturePosition onclick={() => (isOpen = !isOpen)}>
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
    /*
     * B-01: the inspector lays drawers out in a `display: flex;
     * flex-direction: column` body. Without this, each drawer's
     * `flex-shrink: 1` (the flexbox default) lets the section be
     * vertically compressed below the flap button's intrinsic
     * 3.55rem min-height, and the parent's `overflow: hidden` then
     * clips the flap mid-button — labels and chevrons end up
     * visually hidden under the next drawer's flap. Pinning
     * `flex-shrink: 0` keeps each drawer at its natural height; the
     * inspector body's `overflow-y: auto` is what should produce
     * the scrollbar when the stack is taller than the viewport,
     * not flex shrinking.
     */
    flex-shrink: 0;
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
    padding: 0.65rem 0.85rem 0.75rem;
    overflow-y: auto;
    /*
     * B-01: when a drawer's content overflows its `maxHeight`, the
     * inner scrollbar used to overlap the right padding and crowd
     * the prose against text-on-scrollbar (Chrome/Safari render
     * scrollbars inside the right padding area). `scrollbar-gutter:
     * stable` reserves the gutter unconditionally — content stays
     * put whether or not the scrollbar is visible, and the bumped
     * 0.85rem right padding keeps a comfortable gap between text
     * and gutter so prose never sits flush against the scrollbar.
     * `overflow-wrap: anywhere` is a defensive fallback for the
     * occasional unbreakable string (a long item id pasted into
     * notes, a URL the LLM emits) so it can never push the layout
     * horizontally and reintroduce a horizontal scrollbar.
     */
    scrollbar-gutter: stable;
    overflow-wrap: anywhere;
  }
</style>
