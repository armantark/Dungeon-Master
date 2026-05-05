<!--
@component
Inspector — sliding side drawer with the full mechanical state.

This is the "peek if curious" surface. Closed by default. Holds:
  - ChaosDial (the wax seal that distorts as chaos climbs)
  - Threads (active campaign threads)
  - NPCs (current cast)
  - Notes editor (setting + player premise)
  - Oracle history (every roll, with chaos-at-time and structured fields)

We don't keep the dial in the chat-side strip because committing a new
chaos value mid-conversation is a deliberate, infrequent act; pulling
it into a drawer keeps that ceremony.
-->
<script lang="ts">
  import { hasCairnMechanics } from "../lib/cairn";
  import { combatFromState } from "../lib/combat";
  import { game } from "../lib/store.svelte";
  import type { GameState } from "../lib/types";
  import ThreadsPanel from "./ThreadsPanel.svelte";
  import NPCsPanel from "./NPCsPanel.svelte";
  import NotesEditor from "./NotesEditor.svelte";
  import MechanicalReceipt from "./MechanicalReceipt.svelte";
  import CombatTracker from "./CombatTracker.svelte";
  import Drawer from "./Drawer.svelte";

  type Props = { state: GameState };
  // Renamed to `gs` to avoid the Svelte 5 `$state` rune / `state`
  // identifier collision (see store_rune_conflict).
  const { state: gs }: Props = $props();

  // History is shown newest-first inside the inspector because, unlike
  // the chat (forward narrative), this is a reference surface.
  const history = $derived([...gs.oracle_history].reverse());

  // The build-notes drawer surfaces the LLM-authored Cairn backfill
  // rationale (`character.cairn.notes`). The folio rail intentionally
  // doesn't show this — it would crowd the always-visible surface — so
  // the inspector is the right home for "why these stats / why this
  // loadout?". We hide the drawer entirely when:
  //   - the character hasn't been backfilled yet (`source === "unset"`),
  //     because there's nothing real to show; or
  //   - the backfill ran but didn't author any notes,
  // to avoid an empty collapsed flap pretending to hold information.
  const cairnNotes = $derived(gs.character?.cairn.notes ?? "");
  const cairnSource = $derived(gs.character?.cairn.source ?? "unset");
  const showCairnNotes = $derived(
    hasCairnMechanics(cairnSource) && cairnNotes.trim() !== "",
  );

  // The combat tracker only renders when an encounter is being
  // tracked. We fold it into a Drawer (default-open) rather than a
  // raw block so the player can collapse it during exploration even if
  // a stale encounter still lingers in state.
  const encounter = $derived(combatFromState(gs));
  const hasCombat = $derived(encounter !== null);
  let pendingChaos: number | null = $state(null);
  const displayChaos = $derived(pendingChaos ?? gs.chaos_factor);

  function adjustChaos(delta: number): void {
    pendingChaos = Math.min(9, Math.max(1, displayChaos + delta));
  }

  async function commitChaos(): Promise<void> {
    if (pendingChaos === null || pendingChaos === gs.chaos_factor) {
      pendingChaos = null;
      return;
    }
    const next = pendingChaos;
    pendingChaos = null;
    await game.setChaos(next);
  }
</script>

{#if game.inspectorOpen}
  <button
    type="button"
    class="scrim"
    aria-label="Close inspector"
    onclick={() => (game.inspectorOpen = false)}
  ></button>
{/if}

<aside class="inspector iron" data-open={game.inspectorOpen}>
  <header>
    <span class="kicker">Inspector</span>
    <button class="ghost" onclick={() => (game.inspectorOpen = false)}>Close</button>
  </header>

  <div class="body">
    <div class="block block--chaos">
      <span class="kicker">Chaos Factor</span>
      <div class="chaos-row">
        <button class="ghost" onclick={() => adjustChaos(-1)} aria-label="Decrease chaos">−</button>
        <span class="pixel chaos-value">{displayChaos}</span>
        <button class="ghost" onclick={() => adjustChaos(1)} aria-label="Increase chaos">+</button>
        <button
          onclick={commitChaos}
          disabled={pendingChaos === null || pendingChaos === gs.chaos_factor || game.isLoading}
        >
          Commit
        </button>
      </div>
    </div>

    {#if hasCombat}
      <Drawer title="Combat" open={true} maxHeight="22rem">
        <CombatTracker state={gs} />
      </Drawer>
    {/if}

    <Drawer title="Threads" open={false} maxHeight="11rem">
      <ThreadsPanel threads={gs.threads} />
    </Drawer>

    <Drawer title="NPCs" open={false} maxHeight="10rem">
      <NPCsPanel npcs={gs.npcs} />
    </Drawer>

    <Drawer title="Notes" open={false} maxHeight="12rem">
      <NotesEditor state={gs} />
    </Drawer>

    {#if showCairnNotes}
      <Drawer title="Cairn build notes" open={false} maxHeight="12rem">
        <p class="cairn-notes">{cairnNotes}</p>
      </Drawer>
    {/if}

    <Drawer title="Oracle history" open={false} maxHeight="14rem">
      {#if history.length === 0}
        <p class="muted">No rolls yet.</p>
      {:else}
        <ul class="history">
          {#each history as outcome (outcome.id)}
            <li>
              <MechanicalReceipt {outcome} defaultOpen={false} />
            </li>
          {/each}
        </ul>
      {/if}
    </Drawer>

    <footer class="end">
      <button
        class="ghost"
        onclick={() => {
          if (confirm("Reset the campaign? The model will generate a new opening.")) {
            void game.reset();
            game.inspectorOpen = false;
          }
        }}
        disabled={game.isLoading}
      >
        Reset campaign
      </button>
    </footer>
  </div>
</aside>

<style>
  .scrim {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.45);
    z-index: 8;
    border: 0;
    padding: 0;
    cursor: pointer;
    /*
     * The scrim is a button so screen readers can dismiss it; we hide
     * any default button chrome here without clobbering :focus-visible.
     */
    box-shadow: none;
  }
  .scrim:focus-visible {
    outline: 2px solid var(--gold-bright);
    outline-offset: -8px;
  }

  .inspector {
    position: fixed;
    top: 0;
    bottom: 0;
    right: 0;
    width: min(460px, 92vw);
    z-index: 9;
    transform: translateX(100%);
    transition: transform 220ms ease;
    display: flex;
    flex-direction: column;
    border-left: var(--rule-gold);
  }
  .inspector[data-open="true"] {
    transform: translateX(0);
  }

  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.7rem 1rem;
    border-bottom: var(--rule-hair);
  }
  header .kicker {
    margin: 0;
    color: var(--gold-bright);
  }
  .body {
    flex: 1;
    overflow-y: auto;
    padding: 0.7rem 0.8rem 0.9rem;
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
  }
  .block {
    background: rgba(0, 0, 0, 0.25);
    border: 1px solid color-mix(in oklab, var(--gold-tarnished) 30%, transparent);
  }
  .block--chaos {
    padding: 0.65rem 0.75rem;
    display: grid;
    gap: 0.45rem;
  }
  .block--chaos .kicker {
    margin: 0;
    text-align: left;
  }
  .chaos-row {
    display: grid;
    grid-template-columns: auto minmax(2.2rem, auto) auto 1fr;
    align-items: center;
    gap: 0.45rem;
  }
  .chaos-value {
    color: var(--gold-bright);
    font-size: 1.75rem;
    line-height: 1;
    text-align: center;
  }
  .chaos-row button {
    padding: 0.42rem 0.55rem;
  }
  .history {
    list-style: none;
    padding: 0;
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
  }
  .end {
    position: sticky;
    bottom: 0;
    padding-top: 0.55rem;
    background: linear-gradient(180deg, transparent, var(--ink-black) 35%);
    border-top: var(--rule-hair);
  }
  .cairn-notes {
    margin: 0;
    font-family: var(--font-body);
    font-size: 0.92rem;
    line-height: 1.45;
    color: var(--paper-bone);
  }
</style>
