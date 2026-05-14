<!--
@component
SaveLibrary — F-12 save selector splash.

Two distinct entry conditions, one component:
  1. Empty library (first run, or every save deleted on disk):
     `libraryStatus === "empty"`. Only legal action is "Begin a new
     campaign". We show a pixelated frontispiece instead of an empty
     grid so the screen still feels intentional rather than broken.
  2. Mid-session selector (`libraryStatus === "selecting"`):
     player invoked the system menu's "Switch save" while in play.
     The active campaign stays bound until they pick something —
     "Cancel" returns to play without a refetch.

Card body: character name + epithet + identifying line (the backstory
blurb the backend chose; falls back to archetype / current scene).
Hover/focus reveals `state_summary` — scene number, encounter status,
or "Ended by death/retirement/victory." for archived saves. We keep
the reveal CSS-only (no JS hover tracking) so keyboard focus and
touch long-press both surface it.

We deliberately do NOT expose a "delete save" action in v1. Save
deletion is a destructive op that needs a real confirmation flow and
on-disk archive policy decisions (do we move-to-trash? hard-delete?
keep checkpoint zips?), and that work isn't scoped into F-12.
-->
<script lang="ts">
  import { DANGER_PROFILE_LABEL } from "../lib/campaign-seed";
  import { game } from "../lib/store.svelte";
  import type { SaveSummary } from "../lib/types";

  type Props = { mode: "empty" | "selecting" };
  const { mode }: Props = $props();

  // Distinct loading flags for the two CTAs so a click on "Begin new"
  // doesn't grey out every card; otherwise the player can't tell which
  // option fired the request when the network is slow.
  let isCreating = $state(false);
  let switchingTo: string | null = $state(null);

  const sortedSaves = $derived<SaveSummary[]>(game.library);

  async function beginNewCampaign(): Promise<void> {
    if (isCreating) return;
    isCreating = true;
    try {
      await game.createSave(true);
    } finally {
      isCreating = false;
    }
  }

  async function pickSave(save: SaveSummary): Promise<void> {
    if (switchingTo !== null) return;
    if (save.save_id === game.activeSaveId && mode === "selecting") {
      // Picking the active save in the mid-session selector is a soft
      // close — we don't refetch state, we just collapse the splash.
      game.closeLibrary();
      return;
    }
    switchingTo = save.save_id;
    try {
      await game.selectSave(save.save_id);
    } finally {
      switchingTo = null;
    }
  }

  function cancel(): void {
    game.closeLibrary();
  }

  function endedKicker(save: SaveSummary): string | null {
    if (save.campaign_status !== "ended") return null;
    const reason = save.campaign_end_reason ?? "retirement";
    if (reason === "death") return "Fallen";
    if (reason === "victory") return "Triumphant";
    return "Retired";
  }

  function statusKicker(save: SaveSummary): string {
    if (save.campaign_status === "ended") return endedKicker(save) ?? "Closed";
    if (save.campaign_status === "active") return "In play";
    if (save.campaign_status === "ready_to_start") return "Ready";
    return "Setup";
  }

  // F-15 / F-19: surface the campaign preset + danger profile on each
  // card so the player can scan their shelf for the right vibe before
  // binding. We render the preset and danger as a stacked pair (rather
  // than concatenating with " · ") because long preset names would
  // otherwise wrap awkwardly under the kicker; keeping them visually
  // separate also lets the danger pip carry its own color tier.
  function presetLabel(save: SaveSummary): string {
    const trimmed = save.campaign_preset.trim();
    return trimmed === "" ? "Unscoped campaign" : trimmed;
  }

  function dangerLabel(save: SaveSummary): string {
    return DANGER_PROFILE_LABEL[save.danger_profile];
  }
</script>

<div class="library iron iron-grained frontispiece" class:library--empty={mode === "empty"}>
  <header class="library__head">
    <span class="kicker">Oracle's Ledger</span>
    {#if mode === "empty"}
      <h1>An empty shelf.</h1>
      <p class="lead">
        No campaigns are bound to this ledger yet. Begin a wanderer's
        record and the rest of the binding will follow.
      </p>
    {:else}
      <h1>The shelf of bound wanderers.</h1>
      <p class="lead">
        Each tome is a separate canon. Switching binds the chat, the
        oracle history, and the memory to the one you choose.
      </p>
    {/if}
    {#if game.libraryError}
      <div class="error" role="alert">{game.libraryError}</div>
    {/if}
  </header>

  {#if sortedSaves.length > 0}
    <ul class="library__grid">
      {#each sortedSaves as save (save.save_id)}
        {@const isActive = save.save_id === game.activeSaveId}
        {@const isSwitching = switchingTo === save.save_id}
        {@const ended = save.campaign_status === "ended"}
        <li>
          <button
            class="card parchment deckle"
            class:card--active={isActive}
            class:card--ended={ended}
            class:card--busy={isSwitching}
            type="button"
            onclick={() => void pickSave(save)}
            disabled={isSwitching || isCreating}
          >
            <span class="card__rail" aria-hidden="true"></span>
            <div class="card__head">
              <span class="card__kicker">{statusKicker(save)}</span>
              {#if isActive}
                <span class="card__active-pip pixel">Bound</span>
              {/if}
            </div>
            <h2 class="card__name">{save.character_name}</h2>
            {#if save.character_epithet}
              <p class="card__epithet">{save.character_epithet}</p>
            {/if}
            <div class="card__seed">
              <span class="card__seed-preset">{presetLabel(save)}</span>
              <span
                class="pixel card__seed-danger card__seed-danger--{save.danger_profile}"
                title="Campaign difficulty"
              >
                {dangerLabel(save)}
              </span>
            </div>
            {#if save.identifying_line}
              <p class="card__line">{save.identifying_line}</p>
            {/if}
            <div class="card__hover" aria-hidden="true">
              <span class="card__hover-kicker">Now</span>
              <p class="card__hover-text">{save.state_summary}</p>
            </div>
            {#if isSwitching}
              <span class="card__busy pixel">Binding…</span>
            {/if}
          </button>
        </li>
      {/each}
    </ul>
  {/if}

  <footer class="library__foot">
    <button
      type="button"
      class="primary new-campaign"
      onclick={() => void beginNewCampaign()}
      disabled={isCreating || switchingTo !== null}
    >
      {isCreating ? "Composing the binding…" : "Begin a new campaign"}
    </button>
    {#if mode === "selecting"}
      <button
        type="button"
        class="ghost"
        onclick={cancel}
        disabled={isCreating || switchingTo !== null}
      >
        Cancel
      </button>
    {/if}
    <p class="muted hint">
      {#if mode === "empty"}
        Closed wanderers will join this shelf as they fall, retire, or
        win.
      {:else}
        Switching while a turn is in flight is refused — finish or
        stop the current request first.
      {/if}
    </p>
  </footer>
</div>

<style>
  .library {
    margin: 1.4rem auto;
    width: min(960px, 100%);
    padding: 1.6rem 1.8rem 1.4rem;
    display: flex;
    flex-direction: column;
    gap: 1.2rem;
  }

  /*
   * Frontispiece engraving — Dürer plate behind the splash. Used in
   * both modes (empty + selecting). The first version gated this on
   * `mode === "empty"` only; with a populated library that left the
   * selecting splash unchanged, which was the dominant entry point.
   * The plate is now ambient: present at all times, but quieter in
   * the selecting mode so the populated card grid stays legible.
   *
   * Position is anchored on the right so headlines and CTAs read on
   * the left without crashing into the figure.
   */
  .library {
    --frontispiece-position: right -1rem center;
    --frontispiece-blend: screen;
    --frontispiece-size: auto 130%;
    --frontispiece-opacity: 0.10;
    overflow: hidden;
  }
  .library--empty {
    --frontispiece-opacity: 0.24;
    min-height: 420px;
  }
  .library--empty .library__head {
    max-width: 36ch;
  }
  .library--empty .library__foot {
    max-width: 40ch;
  }
  .library__head {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
  }
  .library__head h1 {
    margin: 0;
    font-size: 1.8rem;
  }
  .library__head .lead {
    margin: 0.1rem 0 0;
    color: var(--paper-stained);
    max-width: 60ch;
    line-height: 1.5;
  }
  .library__head .error {
    margin-top: 0.4rem;
    padding: 0.45rem 0.7rem;
    border-left: 3px solid var(--rust-blood);
    background: color-mix(in oklab, var(--rust-blood) 20%, transparent);
    font-family: var(--font-pixel);
    font-size: 0.82rem;
    letter-spacing: 0.04em;
  }

  /*
   * Auto-fitting grid of tomes. We use minmax(260px, 1fr) so a short
   * shelf still fills the row and a long shelf wraps cleanly without
   * media queries. Each card is its own button — the whole tile is
   * the click target, not a small "open" link in a corner, because
   * the player's eye is reading the card body and that's where their
   * cursor already is.
   */
  .library__grid {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    gap: 1rem;
  }

  .card {
    position: relative;
    text-align: left;
    width: 100%;
    padding: 1.1rem 1.2rem 1rem;
    display: flex;
    flex-direction: column;
    gap: 0.2rem;
    cursor: pointer;
    transition: transform 160ms ease, box-shadow 160ms ease;
    text-transform: none;
    letter-spacing: 0;
    color: var(--ink-deep);
    font-family: var(--font-body);
  }
  .card:hover:not(:disabled),
  .card:focus-visible:not(:disabled) {
    transform: translateY(-2px);
    box-shadow:
      inset 0 0 60px rgba(60, 30, 10, 0.3),
      0 22px 36px -10px rgba(0, 0, 0, 0.7);
  }
  .card:disabled {
    cursor: not-allowed;
  }

  .card__rail {
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
    width: 4px;
    background: var(--gold-tarnished);
    opacity: 0.6;
  }
  .card--active .card__rail {
    background: var(--gold-bright);
    opacity: 1;
  }
  .card--ended .card__rail {
    background: var(--rust-iron);
    opacity: 0.85;
  }

  /* Make cards more readable by suppressing the global parchment texture opacity slightly. */
  :global(.card.parchment::before) {
    opacity: 0.25 !important;
  }

  .card__head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.4rem;
  }
  .card__kicker {
    font-family: var(--font-pixel);
    font-size: 0.95rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: color-mix(in oklab, var(--rust-blood) 90%, var(--ink-black));
    font-weight: bold;
  }
  .card__active-pip {
    font-size: 0.72rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: color-mix(in oklab, var(--ink-bruise) 60%, var(--ink-black));
    border: 1px solid color-mix(in oklab, var(--gold-tarnished) 70%, transparent);
    padding: 0.05rem 0.35rem;
    background: color-mix(in oklab, var(--gold-bright) 25%, transparent);
    font-weight: bold;
  }

  .card__name {
    margin: 0.1rem 0 0;
    font-size: 1.85rem;
    line-height: 1.15;
    font-weight: 700;
    color: var(--ink-black);
  }
  .card__epithet {
    margin: 0;
    font-style: italic;
    font-size: 1.25rem;
    line-height: 1.35;
    font-weight: 600;
    color: color-mix(in oklab, var(--ink-bruise) 80%, var(--ink-black));
  }
  /*
   * F-15 + F-19 seed badges sit between the epithet and the
   * identifying-line. The preset is the player's scoping label
   * (verbatim free text from the seed editor); the danger pip
   * inherits the difficulty color tier so the shelf reads in one
   * glance ("Lethal" cards have a blood pip).
   */
  .card__seed {
    display: flex;
    align-items: center;
    gap: 0.45rem;
    margin: 0.35rem 0 0;
    flex-wrap: wrap;
  }
  .card__seed-preset {
    font-family: var(--font-display);
    font-size: 1.25rem;
    font-weight: 700;
    color: var(--ink-black);
  }
  .card__seed-danger {
    padding: 0.05rem 0.4rem;
    border: 1px solid currentColor;
    font-size: 0.72rem;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    font-weight: bold;
  }
  .card__seed-danger--story {
    color: color-mix(in oklab, var(--gold-bright) 60%, var(--ink-black));
  }
  .card__seed-danger--standard {
    color: color-mix(in oklab, var(--gold-tarnished) 90%, var(--ink-black));
  }
  .card__seed-danger--harsh {
    color: var(--rust-iron);
  }
  .card__seed-danger--lethal {
    color: var(--rust-blood);
  }
  .card__line {
    margin: 0.5rem 0 0;
    font-size: 1.2rem;
    line-height: 1.5;
    color: var(--ink-black);
    font-weight: 600;
    /*
     * Cap the identifying line at three lines so a wide-shelf grid stays
     * even — backstory blurbs vary wildly in length and an uncapped card
     * tower would wreck the alignment. The full backstory is reachable
     * via the inspector once the save is bound, so truncating here
     * doesn't hide canon.
     */
    display: -webkit-box;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .card__hover {
    margin-top: 0.55rem;
    padding-top: 0.55rem;
    border-top: 1px dashed color-mix(in oklab, var(--ink-bruise) 50%, transparent);
    opacity: 0;
    max-height: 0;
    transition: opacity 200ms ease, max-height 220ms ease, padding 220ms ease;
    overflow: hidden;
    /* Reserve no space until the hover/focus reveal kicks in. We use
     * max-height + opacity rather than display:none so the transition
     * feels like the card unfolding rather than popping. */
    padding-bottom: 0;
  }
  .card:hover .card__hover,
  .card:focus-visible .card__hover {
    opacity: 1;
    max-height: 6rem;
    padding-bottom: 0.1rem;
  }
  .card__hover-kicker {
    font-family: var(--font-pixel);
    font-size: 0.62rem;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: color-mix(in oklab, var(--rust-blood) 80%, var(--ink-black));
  }
  .card__hover-text {
    margin: 0.15rem 0 0;
    font-size: 0.85rem;
    line-height: 1.4;
    color: color-mix(in oklab, var(--ink-bruise) 70%, var(--ink-black));
  }
  .card__busy {
    position: absolute;
    bottom: 0.5rem;
    right: 0.7rem;
    font-size: 0.62rem;
    letter-spacing: 0.06em;
    color: color-mix(in oklab, var(--rust-blood) 75%, var(--ink-black));
  }
  .card--busy {
    opacity: 0.85;
  }

  .library__foot {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 0.6rem 0.9rem;
    border-top: var(--rule-hair);
    padding-top: 0.9rem;
  }
  .new-campaign {
    border-color: var(--gold-bright);
  }
  .hint {
    margin: 0;
    font-size: 0.78rem;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: var(--paper-shadow);
    flex: 1 1 12rem;
    text-align: right;
  }
</style>
