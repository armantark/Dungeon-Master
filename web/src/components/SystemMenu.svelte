<!--
@component
SystemMenu — F-12 top-right hamburger that owns lifecycle ops.

Why a small menu instead of an inline button row in StatusStrip:
The strip already carries chaos / scene / inspector controls. Pinning
"switch save" or "begin new campaign" inline would push the chaos
badge off-center on narrow viewports and read as more noise than the
chat-first layout wants. A single hamburger collapses every save-
library affordance behind one icon, opens on click, and stays out of
the way the rest of the time.

We deliberately keep the menu *behavioral*-only here: this component
doesn't know about combat or chaos, only about the library + reset
actions. That keeps the StatusStrip free to grow more menu items in
later tickets (settings, theme, model picker) without having to
re-shape three different surfaces.

Closing behavior: click-outside (window listener), Escape, or
selecting any item all close the menu. The menu uses `aria-expanded`
on the trigger and `role="menu"` on the panel for screen readers.
-->
<script lang="ts">
  import { game } from "../lib/store.svelte";

  let open = $state(false);
  let triggerRef: HTMLButtonElement | null = $state(null);
  let panelRef: HTMLDivElement | null = $state(null);

  // Click-outside: we listen on `window` while open, not on every
  // mount, because the menu is closed >95% of the time and a global
  // listener that does nothing on every click is wasted churn. The
  // pointerdown handler runs in the capture phase so we close before
  // any inner button's onclick fires — otherwise picking a menu item
  // would race the close-on-outside check and toggle twice.
  function handlePointerDown(event: PointerEvent): void {
    if (!open) return;
    const target = event.target;
    if (!(target instanceof Node)) return;
    if (panelRef !== null && panelRef.contains(target)) return;
    if (triggerRef !== null && triggerRef.contains(target)) return;
    open = false;
  }

  function handleKey(event: KeyboardEvent): void {
    if (event.key === "Escape" && open) {
      open = false;
      triggerRef?.focus();
    }
  }

  $effect(() => {
    if (!open) return;
    window.addEventListener("pointerdown", handlePointerDown, true);
    window.addEventListener("keydown", handleKey);
    return () => {
      window.removeEventListener("pointerdown", handlePointerDown, true);
      window.removeEventListener("keydown", handleKey);
    };
  });

  function toggle(): void {
    open = !open;
  }

  function openLibrary(): void {
    open = false;
    game.openLibrary();
  }

  async function newCampaign(): Promise<void> {
    open = false;
    // Routing through the store's createSave (rather than reset) keeps
    // the existing save's archive intact — F-12's whole point is that
    // "Begin a new campaign" no longer overwrites the prior canon.
    await game.createSave(true);
  }

  // Settings modal owns its own load lifecycle (re-fetch on open), so
  // we just close the menu and hand off to the store. The void-return
  // is intentional: the menu shouldn't block on the GET completing.
  function openSettings(): void {
    open = false;
    void game.openSettings();
  }

  // Library entry copy adapts to whether there's anything to actually
  // switch to. The prior version had two menu items ("Save library"
  // and "Switch save") that both called `openLibrary()` — pure copy
  // redundancy with no behavioural distinction, because the splash
  // itself already handles both browse and pick. We keep one row and
  // let the label/hint shift with the shelf state.
  const libraryLabel = $derived(
    game.library.length > 1 ? "Switch save" : "Save library",
  );
  const libraryHint = $derived(
    game.library.length > 1
      ? "Bind a different campaign — the active save stays archived."
      : "Browse archived and active wanderers.",
  );
</script>

<div class="system-menu">
  <button
    bind:this={triggerRef}
    class="trigger ghost"
    type="button"
    aria-haspopup="menu"
    aria-expanded={open}
    title="Open system menu"
    onclick={toggle}
  >
    <span class="bars" aria-hidden="true">
      <span></span><span></span><span></span>
    </span>
    <span class="visually-hidden">System menu</span>
  </button>

  {#if open}
    <div bind:this={panelRef} class="panel iron" role="menu" aria-label="System menu">
      <button class="link item" type="button" role="menuitem" onclick={openLibrary}>
        <span class="item__label">{libraryLabel}</span>
        <span class="item__hint">{libraryHint}</span>
      </button>
      <button
        class="link item"
        type="button"
        role="menuitem"
        onclick={() => void newCampaign()}
      >
        <span class="item__label">Begin a new campaign</span>
        <span class="item__hint">Adds a fresh tome — the current archive is preserved.</span>
      </button>
      <button class="link item" type="button" role="menuitem" onclick={openSettings}>
        <span class="item__label">Narrative model</span>
        <span class="item__hint">Swap between Kimi and the Gemini split routing.</span>
      </button>
    </div>
  {/if}
</div>

<style>
  .system-menu {
    position: relative;
    z-index: 100;
  }
  .trigger {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0.4rem 0.7rem;
    min-width: 0;
  }
  /*
   * Three short bars hand-drawn with stacked spans rather than an SVG:
   * the rest of the UI uses CSS-only iconography so the binary stays
   * font-and-pigment, no vector assets. Spans inherit color from
   * `currentColor` so the hover-glow on .ghost flows through.
   */
  .bars {
    display: inline-flex;
    flex-direction: column;
    gap: 3px;
    width: 18px;
  }
  .bars span {
    display: block;
    height: 2px;
    background: currentColor;
  }

  .panel {
    /*
     * Anchor: top-right of the strip's right edge. We use absolute
     * positioning rather than `position: fixed` because the strip is
     * itself sticky-but-not-fixed and we want the panel to scroll
     * away if the player scrolls the chat in the rare case the
     * viewport is shorter than the menu height.
     */
    position: absolute;
    top: calc(100% + 6px);
    right: 0;
    z-index: 100;
    min-width: 240px;
    padding: 0.45rem 0.4rem;
    display: flex;
    flex-direction: column;
    gap: 0.1rem;
    box-shadow: var(--shadow-deep);
  }
  .item {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 0.1rem;
    text-align: left;
    padding: 0.45rem 0.6rem;
    text-transform: none;
    letter-spacing: 0;
    font-family: var(--font-body);
    font-size: 0.95rem;
    color: var(--paper-warm);
    border: 1px solid transparent;
  }
  .item:hover:not(:disabled),
  .item:focus-visible:not(:disabled) {
    color: var(--gold-bright);
    background: color-mix(in oklab, var(--gold-tarnished) 18%, transparent);
    border-color: color-mix(in oklab, var(--gold-tarnished) 50%, transparent);
  }
  .item__label {
    font-family: var(--font-pixel);
    font-size: 0.85rem;
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }
  .item__hint {
    font-family: var(--font-body);
    font-size: 0.78rem;
    line-height: 1.3;
    color: var(--paper-shadow);
  }

  .visually-hidden {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    margin: -1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
    border: 0;
  }
</style>
