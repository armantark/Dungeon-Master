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
  import { tick } from "svelte";
  import { hasCairnMechanics } from "../../lib/cairn";
  import { combatFromState } from "../../lib/combat";
  import { game } from "../../lib/store.svelte";
  import { recentlyTouchedNpcIds } from "../../lib/npcs";
  import { recentlyTouchedThreadIds } from "../../lib/threads";
  import type { GameState } from "../../lib/types";
  import CampaignSetting from "./CampaignSetting.svelte";
  import ChaosControl from "./ChaosControl.svelte";
  import ThreadsPanel from "./ThreadsPanel.svelte";
  import NPCsPanel from "./NPCsPanel.svelte";
  import DirectivesEditor from "./DirectivesEditor.svelte";
  import OracleHistory from "./OracleHistory.svelte";
  import TranscriptSearch from "./TranscriptSearch.svelte";
  import CombatTracker from "../combat/CombatTracker.svelte";
  import Drawer from "./Drawer.svelte";
  import { metalScroll } from "../../lib/metalScroll";

  interface Props {
    state: GameState;
  }
  // Renamed to `gs` to avoid the Svelte 5 `$state` rune / `state`
  // identifier collision (see store_rune_conflict).
  const { state: gs }: Props = $props();

  // Threads the latest resolved turn touched. F-03 made this set
  // canonical: the post-outcome `ThreadUpdater` writes every advanced
  // id onto `OracleOutcome.referenced_thread_ids`, and the panel uses
  // it to float just-changed cards to the top + run a one-shot pulse.
  const touchedThreadIds = $derived(recentlyTouchedThreadIds(gs));

  // NPCs the latest resolved turn touched (F-04). The post-outcome
  // `NPCUpdater` writes created / updated / retired ids onto
  // `OracleOutcome.referenced_npc_ids`. The NPCs panel mirrors the
  // threads pattern — float touched cards, pulse once, mute retired
  // cards instead of deleting them.
  const touchedNpcIds = $derived(recentlyTouchedNpcIds(gs));

  // H-02 receipt-link navigation. A receipt pill can ask the inspector to
  // open one section and spotlight one entity. We keep the request local
  // once consumed so the store stays a one-shot signal bus, not a second
  // persistent UI-state source of truth.
  let threadsDrawerEl: HTMLDivElement | undefined;
  let npcsDrawerEl: HTMLDivElement | undefined;
  let focusedThreadId: string | null = $state(null);
  let focusedNpcId: string | null = $state(null);
  let threadFocusSeq: number = $state(0);
  let npcFocusSeq: number = $state(0);
  let consumedInspectorFocusSeq: number = $state(-1);

  async function applyInspectorFocus(
    request: NonNullable<typeof game.inspectorFocusRequest>,
  ): Promise<void> {
    if (request.section === "threads") {
      focusedThreadId = request.entityId;
      threadFocusSeq = request.seq;
      await tick();
      threadsDrawerEl?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      return;
    }
    focusedNpcId = request.entityId;
    npcFocusSeq = request.seq;
    await tick();
    npcsDrawerEl?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  $effect(() => {
    const request = game.inspectorFocusRequest;
    if (request === null) return;
    if (request.seq === consumedInspectorFocusSeq) return;
    consumedInspectorFocusSeq = request.seq;
    void applyInspectorFocus(request);
    game.consumeInspectorFocusRequest();
  });

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
  const showCairnNotes = $derived(hasCairnMechanics(cairnSource) && cairnNotes.trim() !== "");

  // The combat tracker only renders when an encounter is being
  // tracked. We fold it into a Drawer (default-open) rather than a
  // raw block so the player can collapse it during exploration even if
  // a stale encounter still lingers in state.
  const encounter = $derived(combatFromState(gs));
  const hasCombat = $derived(encounter !== null);
  // F-06: when the campaign is archived, every mutating control in
  // the inspector (chaos commit, notes save, etc.) would be rejected
  // by the backend's `_ensure_active` guard with a 409. Rather than
  // surface that as a failed-toast each time the player twiddles
  // something out of habit, we mark the inspector itself read-only
  // and disable the mutating affordances at the source. The
  // archive-only surfaces (oracle history, threads, NPCs, cairn
  // notes) remain interactive because their interactions are pure
  // navigation — opening a drawer, scrolling history.
  const archived = $derived(gs.campaign_status === "ended");
</script>

{#if game.inspectorOpen}
  <button
    type="button"
    class="scrim no-iron"
    aria-label="Close inspector"
    onclick={() => (game.inspectorOpen = false)}
  ></button>
{/if}

<aside class="inspector iron" data-open={game.inspectorOpen}>
  <header>
    <span class="kicker">Inspector</span>
    <button class="ghost" onclick={() => (game.inspectorOpen = false)}>Close</button>
  </header>

  <div class="body" use:metalScroll>
    <ChaosControl value={gs.chaos_factor} {archived} />

    {#if hasCombat}
      <!--
        The active-combat readout lives inline with the chat now
        (InlineCombatStrip under the latest DM message). The
        inspector keeps the full tracker so the player can still
        audit every number / weakness / tactic line on demand, but
        it's collapsed by default and titled "Warden details" to
        match the fiction-first protocol — the player sees diegetic
        cues in the chat and only opens this drawer when they want
        to peek behind the curtain.
      -->
      <Drawer title="Warden details — combat" open={false} maxHeight="22rem">
        <CombatTracker state={gs} />
      </Drawer>
    {/if}

    <!--
      F-15 / F-19: read-only seed readout. The editor is reachable
      from the character-creation screen; once the campaign is
      `active` (or `ended`), the seed is locked and we surface this
      drawer as the "trust signal" for what the world was generated
      against. Keeping it collapsed by default so the inspector
      doesn't lead with this — it's the kind of thing a player
      consults a few hours into a campaign, not every drawer open.
    -->
    <Drawer title="Campaign setting" open={false} maxHeight="20rem">
      <CampaignSetting seed={gs.campaign_seed} />
    </Drawer>

    <div bind:this={threadsDrawerEl}>
      <Drawer title="Threads" open={false} maxHeight="11rem" reopenToken={threadFocusSeq}>
        <ThreadsPanel
          threads={gs.threads}
          recentlyTouchedIds={touchedThreadIds}
          focusedId={focusedThreadId}
          focusSeq={threadFocusSeq}
        />
      </Drawer>
    </div>

    <div bind:this={npcsDrawerEl}>
      <Drawer title="NPCs" open={false} maxHeight="10rem" reopenToken={npcFocusSeq}>
        <NPCsPanel
          npcs={gs.npcs}
          recentlyTouchedIds={touchedNpcIds}
          focusedId={focusedNpcId}
          focusSeq={npcFocusSeq}
        />
      </Drawer>
    </div>

    <!--
      B-02: the old "Notes" drawer conflated two unrelated surfaces:
      canonical campaign material (`setting_notes` / `player_notes`,
      authored at generation time) and freeform freeform OOC
      preferences. The user explicitly does not want to feel
      nudged into routine journaling — the only durable use-case
      was stable system-prompt steering — so the drawer is now
      "Directives", scoped to that exact OOC surface. The
      canonical setting/player notes still live in `GameState`
      and feed prompts on the backend; we just no longer expose
      an editor for them, which matches the rest of the read-only
      "this is canon, the system tracks it" pattern (threads,
      NPCs, oracle history). DirectivesEditor handles archived /
      empty / read-mode / edit-mode internally so the inspector
      doesn't have to branch.
    -->
    <Drawer title="Directives" open={false} maxHeight="14rem">
      <DirectivesEditor state={gs} {archived} />
    </Drawer>

    {#if showCairnNotes}
      <Drawer title="Cairn build notes" open={false} maxHeight="12rem">
        <p class="cairn-notes">{cairnNotes}</p>
      </Drawer>
    {/if}

    <Drawer title="Transcript" open={false} maxHeight="16rem">
      <TranscriptSearch state={gs} />
    </Drawer>

    <!--
      B-01: keep the Oracle history drawer last — it's the only drawer
      tall enough to ever push the inspector body past viewport height,
      so anchoring it at the bottom of the scroll surface keeps the
      "peek if curious" drawers visible without scrolling on tall
      viewports.
    -->
    <Drawer title="Oracle history" open={false} maxHeight="18rem">
      <OracleHistory state={gs} />
    </Drawer>
  </div>

  <footer class="end">
    <!--
      F-12: the inspector exposes two distinct lifecycle ops:

        - "Reset this save" is destructive and *in-place* — it wipes
          the currently bound save's canon. We keep this around for
          "I don't like this opening, re-roll" without having the
          player accumulate a one-tome-deep shelf of test runs. The
          confirm copy makes the in-place destruction obvious.

        - "Open save library" is the non-destructive escape hatch
          that mirrors the system-menu entry — useful for archived
          campaigns where the player wants to switch to another tome
          rather than wipe the current one.
      -->
    <button
      type="button"
      class="ghost"
      onclick={() => {
        game.openLibrary();
        game.inspectorOpen = false;
      }}
      disabled={game.isLoading}
    >
      Open save library
    </button>
    <button
      class="ghost reset-button"
      onclick={() => {
        const prompt = archived
          ? "Wipe this archived save in place and replace it with a fresh campaign? Other saves on the shelf are untouched."
          : "Reset this save in place? The current canon is destroyed and the model will generate a new opening. Other saves on the shelf are untouched.";
        if (confirm(prompt)) {
          void game.reset();
          game.inspectorOpen = false;
        }
      }}
      disabled={game.isLoading}
    >
      {archived ? "Wipe and re-roll this save" : "Reset this save"}
    </button>
  </footer>
</aside>

<style>
  .scrim {
    position: fixed;
    inset: 0;
    /*
     * Sits above the scrolled content + custom scrollbar (z-index 5 in
     * metalScroll) so the chat scrollbar stops floating over the
     * inspector while the drawer is open, but below the inspector
     * itself (z-index 9) so a click on the drawer doesn't dismiss it.
     */
    z-index: 8;
    background: rgba(0, 0, 0, 0.55);
    border: 0;
    padding: 0;
    cursor: pointer;
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
    padding: 0.7rem 0.95rem 0.9rem;
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
    /*
     * B-01: same fix as Drawer.svelte — reserve the scrollbar gutter
     * so the inspector's outer scroll never shifts content sideways
     * when a drawer expands and pushes the body past the viewport.
     * The right padding is bumped slightly so that even with the
     * gutter reserved there's still a visible gap between drawer
     * flaps and the inspector's outer scrollbar.
     */
    scrollbar-gutter: stable;
  }
  .end {
    /*
     * B-01: the lifecycle footer used to live inside `.body` as a
     * `position: sticky; bottom: 0` block with a fade-to-black
     * gradient. That kept the buttons in view while the body
     * scrolled, but it also clipped the bottom drawer flap behind
     * the gradient — drawers and footer competed for the same
     * scroll surface. Lifting `.end` out of `.body` and into the
     * inspector's flex column means the body owns the scrollable
     * region exclusively and the footer always sits below it,
     * fully visible, without the gradient hack. The horizontal
     * padding matches `.body`'s so the buttons align with the
     * drawer flaps above the dividing rule.
     */
    padding: 0.6rem 0.95rem 0.85rem;
    border-top: var(--rule-hair);
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
    flex-shrink: 0;
  }
  /* The destructive "wipe this save" gets a rust-iron border so it's
   * clearly distinct from the non-destructive "Open save library"
   * button above it. Both are .ghost so they don't compete with the
   * primary CTAs in the splash / end-banner. */
  .end .reset-button {
    border-color: color-mix(in oklab, var(--rust-iron) 70%, transparent);
  }
  .end .reset-button:hover:not(:disabled) {
    border-color: var(--rust-blood);
    color: var(--rust-blood);
  }
  .cairn-notes {
    margin: 0;
    font-family: var(--font-body);
    font-size: 0.92rem;
    line-height: 1.45;
    color: var(--paper-bone);
  }
</style>
