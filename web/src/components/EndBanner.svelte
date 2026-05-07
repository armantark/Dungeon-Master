<!--
@component
EndBanner — F-06 sticky-bottom replacement for the Composer once the
campaign reaches its terminal state.

We intentionally don't render the EndBanner *inside* the chat as a
final message — keeping it as the floor of the chat-column makes the
"play has stopped" state structurally obvious (no input box anywhere
on screen) and lets the player still scroll the archive freely above
it. A finishing line in the chat would compete with the closing
narrative the backend already wrote, and chat-side messages can be
collapsed by future inspector toggles in a way that would let the
player accidentally lose the lifecycle control.

Visual hierarchy mirrors the death-knell feel of a Cairn campaign:
  - kicker (rust-blood for death, paper-shadow for retire/victory)
  - large headline ("The wanderer fell.")
  - the canonical campaign_end_summary as italic prose
  - a single "Begin a new campaign" CTA. Post-F-12 this CTA *adds* a
    new tome to the save library — it does not replace the closed
    archive. The hint copy reflects that ("preserved on the shelf"
    instead of "replaces this archive").
-->
<script lang="ts">
  import {
    endHeadline,
    endKicker,
    endSummary,
    formatEndedAt,
  } from "../lib/end-campaign";
  import { game } from "../lib/store.svelte";
  import type { CampaignEndReason, GameState } from "../lib/types";

  type Props = { state: GameState };
  const { state: gs }: Props = $props();

  // The non-null assertion via fallback is deliberate. The parent
  // (App.svelte) only mounts EndBanner when `campaign_status === "ended"`,
  // and in that branch the backend always sets `campaign_end_reason`.
  // We default to `retirement` rather than throwing because a
  // legacy-state migration that somehow lost the reason field shouldn't
  // brick the UI; the deterministic per-reason fallback prose still
  // reads sensibly under retirement.
  const reason = $derived<CampaignEndReason>(
    gs.campaign_end_reason ?? "retirement",
  );
  const kicker = $derived(endKicker(reason));
  const headline = $derived(endHeadline(reason));
  const summary = $derived(endSummary(gs));
  const closedAt = $derived(formatEndedAt(gs.campaign_ended_at));

  // F-12 swap the lifecycle action: the End-Banner CTA used to call
  // `game.reset()`, which wiped the active save in place. Now it adds
  // a brand-new save to the library and binds it as active — the
  // closed archive stays browsable through the system menu's "Save
  // library". We keep the two-step confirm because "start a fresh
  // wanderer" is still a non-trivial commit (the player has just
  // finished reading their own ending), even though it no longer
  // destroys the previous canon.
  let confirming = $state(false);
  async function startNewCampaign(): Promise<void> {
    if (!confirming) {
      confirming = true;
      return;
    }
    confirming = false;
    await game.createSave(true);
  }

  function cancelConfirm(): void {
    confirming = false;
  }

  function openLibrary(): void {
    game.openLibrary();
  }
</script>

<aside class="end-banner end-banner--{reason}" role="region" aria-label="Campaign closed">
  <div class="banner-body">
    <span class="kicker pixel">{kicker}</span>
    <h2 class="headline">{headline}</h2>
    {#if summary}
      <p class="summary">{summary}</p>
    {/if}
    {#if closedAt}
      <p class="closed-at muted">Closed {closedAt}</p>
    {/if}
  </div>

  <div class="banner-actions">
    <span class="hint pixel">
      {#if confirming}
        A new tome will be bound — this archive stays preserved on the shelf.
      {:else}
        Chat above is preserved as a read-only archive on the shelf.
      {/if}
    </span>
    <div class="actions">
      <button class="ghost" type="button" onclick={openLibrary} disabled={game.isLoading}>
        Open save library
      </button>
      {#if confirming}
        <button class="ghost" type="button" onclick={cancelConfirm} disabled={game.isLoading}>
          Cancel
        </button>
      {/if}
      <button
        type="button"
        class="primary"
        onclick={() => void startNewCampaign()}
        disabled={game.isLoading}
      >
        {confirming ? "Yes, bind a new wanderer" : "Begin a new campaign"}
      </button>
    </div>
  </div>
</aside>

<style>
  .end-banner {
    background: linear-gradient(
      180deg,
      color-mix(in oklab, var(--ink-deep) 92%, var(--ink-black)) 0%,
      color-mix(in oklab, var(--ink-deep) 96%, var(--rust-iron)) 100%
    );
    border-top: var(--rule-hair);
    padding: 1rem 1.2rem 1.1rem;
    display: flex;
    flex-direction: column;
    gap: 0.7rem;
  }
  /* The death variant gets a deeper rust band along the top so the
   * lifecycle-shift cue lands without us having to put a screaming
   * red banner across the whole chat. Retirement and victory share
   * the gold-tarnished hair rule so the close still feels ceremonial
   * but not fatal. */
  .end-banner--death {
    border-top-color: var(--rust-blood);
    background: linear-gradient(
      180deg,
      color-mix(in oklab, var(--ink-deep) 88%, var(--ink-black)) 0%,
      color-mix(in oklab, var(--rust-blood) 18%, var(--ink-deep)) 100%
    );
  }
  .end-banner--victory {
    border-top-color: var(--gold-bright);
  }

  .banner-body {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }
  .kicker {
    margin: 0;
    font-size: 0.72rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--gold-tarnished);
  }
  .end-banner--death .kicker {
    color: var(--rust-blood);
  }
  .end-banner--victory .kicker {
    color: var(--gold-bright);
  }
  .headline {
    margin: 0;
    font-size: 1.4rem;
    color: var(--paper-warm);
    line-height: 1.15;
  }
  .summary {
    margin: 0.2rem 0 0;
    font-style: italic;
    color: var(--paper-bone);
    line-height: 1.45;
    max-width: 60ch;
  }
  .closed-at {
    margin: 0.15rem 0 0;
    font-size: 0.78rem;
    letter-spacing: 0.04em;
  }

  .banner-actions {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    flex-wrap: wrap;
  }
  .hint {
    color: var(--paper-shadow);
    font-size: 0.78rem;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    max-width: 60ch;
  }
  .actions {
    display: flex;
    gap: 0.5rem;
    align-items: center;
  }
  .primary {
    border-color: var(--gold-bright);
  }
</style>
