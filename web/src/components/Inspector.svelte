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
  import { hasCairnMechanics } from "../lib/cairn";
  import {
    DANGER_PROFILE_BLURB,
    DANGER_PROFILE_LABEL,
    GENRE_LABEL,
    MAGIC_LEVEL_LABEL,
    STAKES_SCALE_LABEL,
    TECH_LEVEL_LABEL,
    TIME_PERIOD_LABEL,
    TONE_DARK_BRIGHT_LABEL,
    TONE_GRIM_NOBLE_LABEL,
    seedBadgeLabel,
  } from "../lib/campaign-seed";
  import { combatFromState } from "../lib/combat";
  import {
    deriveTranscriptRows,
    filterOracleHistory,
    findNarrativeEventForOracle,
    searchTranscript,
    type SearchMatch,
  } from "../lib/history";
  import { game } from "../lib/store.svelte";
  import { recentlyTouchedNpcIds } from "../lib/npcs";
  import { recentlyTouchedThreadIds } from "../lib/threads";
  import type { GameState, OracleKind } from "../lib/types";
  import ThreadsPanel from "./ThreadsPanel.svelte";
  import NPCsPanel from "./NPCsPanel.svelte";
  import DirectivesEditor from "./DirectivesEditor.svelte";
  import MechanicalReceipt from "./MechanicalReceipt.svelte";
  import CombatTracker from "./CombatTracker.svelte";
  import Drawer from "./Drawer.svelte";

  type Props = { state: GameState };
  // Renamed to `gs` to avoid the Svelte 5 `$state` rune / `state`
  // identifier collision (see store_rune_conflict).
  const { state: gs }: Props = $props();

  // F-09 transcript search lives in the inspector rather than as a
  // top-bar control on the chat surface so the chat itself stays a
  // pure forward-narrative. The query state is component-local — a
  // playtest pattern saw the same query needing to survive
  // close/reopen, so we keep it on the Inspector instance rather
  // than pushing it to the store; closing the inspector preserves
  // the query, but a full page reload clears it (a stronger
  // persistence is out of scope until F-12 when save-slots arrive).
  let transcriptQuery: string = $state("");
  // Oracle history filters. The kinds set is empty by default = "all
  // kinds pass" so the drawer's first-look behavior is unchanged.
  let oracleQuery: string = $state("");
  let oracleKinds: Set<OracleKind> = $state(new Set<OracleKind>());

  // Toggle helper for the Cairn-style pixel pill toggles. We
  // reassign instead of mutating in place so Svelte's reactivity
  // sees the change — `Set.add`/`Set.delete` mutate-in-place don't
  // trigger an update on a `$state` Set.
  function toggleOracleKind(kind: OracleKind): void {
    const next = new Set(oracleKinds);
    if (next.has(kind)) {
      next.delete(kind);
    } else {
      next.add(kind);
    }
    oracleKinds = next;
  }

  function clearOracleFilters(): void {
    oracleQuery = "";
    oracleKinds = new Set();
  }

  // History is shown newest-first inside the inspector because, unlike
  // the chat (forward narrative), this is a reference surface.
  const history = $derived([...gs.oracle_history].reverse());
  // Filtered view used when the oracle drawer has any active filter.
  // We pass the original (newest-last) array to `filterOracleHistory`
  // and reverse afterwards so order semantics match the unfiltered
  // case; reversing first would force the helper to know about
  // display order, which it shouldn't.
  const filteredHistory = $derived(
    [...filterOracleHistory(gs.oracle_history, {
      query: oracleQuery,
      kinds: oracleKinds,
    })].reverse(),
  );
  const oracleFiltersActive = $derived(
    oracleQuery.trim() !== "" || oracleKinds.size > 0,
  );

  // F-09 transcript search index. We rebuild on every state /
  // notes change because the cost is `O(action_log)` and a long
  // campaign caps out at a few hundred events — well below the
  // threshold where caching would matter. Search itself is
  // `O(rows * tokens)` linear scan; real-world latencies stayed
  // sub-frame in playtests up through ~4 hours of session.
  const transcriptRows = $derived(deriveTranscriptRows(gs, game.notes));
  const transcriptHits = $derived<readonly SearchMatch[]>(
    transcriptQuery.trim() === ""
      ? []
      : searchTranscript(transcriptRows, transcriptQuery, { limit: 80 }),
  );

  /**
   * Jump from an oracle row to the narrative event that surfaces it.
   * If no narrative event has committed yet (regenerate-cancel,
   * mid-stream), we fall through to opening the chat anyway — the
   * `requestScrollTo` no-ops on missing anchors, so the inspector
   * just closes silently. We close the drawer because the player's
   * goal here is to read the prose, not to keep scanning history.
   */
  function jumpFromOracle(outcomeId: string): void {
    const eventId = findNarrativeEventForOracle(gs, outcomeId);
    if (eventId === null) return;
    game.requestScrollTo(eventId);
    game.inspectorOpen = false;
  }

  /**
   * Jump from a transcript search hit to the chat anchor. Works for
   * both real action_log events and the synthesized opening row
   * (`opening_<state-id>`) because the ChatFeed renders the same
   * anchor id for both.
   */
  function jumpFromTranscript(rowId: string): void {
    game.requestScrollTo(rowId);
    game.inspectorOpen = false;
  }

  /**
   * Speaker label for transcript hits. The chat shows DM/You/Engine;
   * we mirror that vocabulary so the search list reads as the same
   * surface the player is about to be teleported into.
   */
  function speakerLabel(kind: SearchMatch["kind"]): string {
    switch (kind) {
      case "dm":
        return "DM";
      case "player":
        return "You";
      case "system":
        return "Engine";
    }
  }

  function relativeTime(iso: string): string {
    const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
    if (seconds < 60) return `${Math.round(seconds)}s ago`;
    if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
    return new Date(iso).toLocaleDateString();
  }

  // Pre-compute speaker / time for each hit so the markup stays
  // declarative. We also slice the snippet into `[before, match,
  // after]` so the renderer can wrap the match in a <mark> without
  // re-running a search.
  type RenderedHit = SearchMatch & {
    speaker: string;
    when: string;
    before: string;
    match: string;
    after: string;
  };
  const renderedHits = $derived<readonly RenderedHit[]>(
    transcriptHits.map((hit) => ({
      ...hit,
      speaker: speakerLabel(hit.kind),
      when: relativeTime(hit.timestamp),
      before: hit.snippet.slice(0, hit.highlightStart),
      match: hit.snippet.slice(hit.highlightStart, hit.highlightEnd),
      after: hit.snippet.slice(hit.highlightEnd),
    })),
  );

  // Static OracleKind list for the filter pills. Order intentionally
  // groups by source: oracle (yes_no/random_event/scene_check) first,
  // then player_action, then Cairn-determinist
  // (save/attack/harm/recovery/retreat). The labels match the same
  // vocabulary `MechanicalReceipt` uses on its tag chip.
  const KIND_FILTER_OPTIONS: ReadonlyArray<{ kind: OracleKind; label: string }> = [
    { kind: "yes_no", label: "Yes/No" },
    { kind: "random_event", label: "Event" },
    { kind: "scene_check", label: "Scene" },
    { kind: "player_action", label: "Action" },
    { kind: "save", label: "Save" },
    { kind: "attack", label: "Attack" },
    { kind: "harm", label: "Harm" },
    { kind: "recovery", label: "Recover" },
    { kind: "retreat", label: "Retreat" },
  ];

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
  const showCairnNotes = $derived(
    hasCairnMechanics(cairnSource) && cairnNotes.trim() !== "",
  );

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
        <button
          class="ghost"
          onclick={() => adjustChaos(-1)}
          aria-label="Decrease chaos"
          disabled={archived}
        >−</button>
        <span class="pixel chaos-value">{displayChaos}</span>
        <button
          class="ghost"
          onclick={() => adjustChaos(1)}
          aria-label="Increase chaos"
          disabled={archived}
        >+</button>
        <button
          onclick={commitChaos}
          disabled={archived || pendingChaos === null || pendingChaos === gs.chaos_factor || game.isLoading}
        >
          Commit
        </button>
      </div>
      {#if archived}
        <p class="archived-hint muted">Archived — chaos is preserved as canon.</p>
      {/if}
    </div>

    {#if hasCombat}
      <Drawer title="Combat" open={true} maxHeight="22rem">
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
      <div class="seed-readout">
        <p class="seed-readout__head pixel">{seedBadgeLabel(gs.campaign_seed)}</p>
        <p class="muted seed-readout__danger">
          {DANGER_PROFILE_BLURB[gs.campaign_seed.danger_profile]}
        </p>
        <dl class="seed-readout__grid">
          <dt>Era</dt>
          <dd>{TIME_PERIOD_LABEL[gs.campaign_seed.time_period]}</dd>
          <dt>Tone</dt>
          <dd>
            {TONE_GRIM_NOBLE_LABEL[gs.campaign_seed.tone_grim_noble]}
            ·
            {TONE_DARK_BRIGHT_LABEL[gs.campaign_seed.tone_dark_bright]}
          </dd>
          <dt>Difficulty</dt>
          <dd class="pixel">{DANGER_PROFILE_LABEL[gs.campaign_seed.danger_profile]}</dd>
          <dt>Genres</dt>
          <dd>
            {gs.campaign_seed.genres.map((g) => GENRE_LABEL[g]).join(", ")}
          </dd>
          <dt>Magic</dt>
          <dd>{MAGIC_LEVEL_LABEL[gs.campaign_seed.magic_level]}</dd>
          <dt>Tech</dt>
          <dd>{TECH_LEVEL_LABEL[gs.campaign_seed.tech_level]}</dd>
          <dt>Stakes</dt>
          <dd>{STAKES_SCALE_LABEL[gs.campaign_seed.stakes_scale]}</dd>
          {#if gs.campaign_seed.inspirations.trim() !== ""}
            <dt>Inspirations</dt>
            <dd>{gs.campaign_seed.inspirations}</dd>
          {/if}
          {#if gs.campaign_seed.restrictions.trim() !== ""}
            <dt>Restrictions</dt>
            <dd>{gs.campaign_seed.restrictions}</dd>
          {/if}
        </dl>
      </div>
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
      <!--
        F-09 transcript search. Stays inside the inspector — the chat
        surface is for forward-only narration, the inspector is for
        "peek if curious" reference. Hits link back into the chat
        and trigger a flash highlight on the matched anchor.
      -->
      <div class="search">
        <input
          type="search"
          class="search__input"
          placeholder="Search the chat — names, events, items…"
          aria-label="Search transcript"
          bind:value={transcriptQuery}
        />
        {#if transcriptQuery.trim() !== ""}
          <button
            type="button"
            class="ghost search__clear"
            onclick={() => (transcriptQuery = "")}
            aria-label="Clear search"
          >Clear</button>
        {/if}
      </div>

      {#if transcriptQuery.trim() === ""}
        <p class="muted search__hint">
          Search every committed beat — DM prose, your actions, engine
          notes. Hits jump the chat to the moment.
        </p>
      {:else if renderedHits.length === 0}
        <p class="muted search__hint">
          Nothing matches “{transcriptQuery.trim()}”.
        </p>
      {:else}
        <ul class="search__hits">
          {#each renderedHits as hit (`${hit.rowId}_${hit.source}`)}
            <li>
              <button
                type="button"
                class="hit"
                onclick={() => jumpFromTranscript(hit.rowId)}
                title="Jump to this moment in the chat"
              >
                <span class="hit__meta pixel">
                  <span class="hit__speaker">{hit.speaker}</span>
                  {#if hit.source === "outcome"}
                    <span class="hit__source">in receipt</span>
                  {/if}
                  <span class="hit__time">{hit.when}</span>
                </span>
                <span class="hit__snippet">
                  {hit.before}<mark>{hit.match}</mark>{hit.after}
                </span>
              </button>
            </li>
          {/each}
        </ul>
      {/if}
    </Drawer>

    <!--
      B-01: keep the Oracle history drawer last — it's the only drawer
      tall enough to ever push the inspector body past viewport height,
      so anchoring it at the bottom of the scroll surface keeps the
      "peek if curious" drawers visible without scrolling on tall
      viewports.
    -->
    <Drawer title="Oracle history" open={false} maxHeight="18rem">
      <!--
        F-09 filters. The text query and the kind whitelist are
        ANDed together — a query of "abbot" with `Yes/No` selected
        only surfaces yes/no rolls that mention "abbot". An empty
        filter set (no query, no kinds) renders the full reversed
        history exactly as before.
      -->
      <div class="search">
        <input
          type="search"
          class="search__input"
          placeholder="Filter rolls — names, scars, weapons…"
          aria-label="Filter oracle history"
          bind:value={oracleQuery}
        />
        {#if oracleFiltersActive}
          <button
            type="button"
            class="ghost search__clear"
            onclick={clearOracleFilters}
            aria-label="Clear filters"
          >Clear</button>
        {/if}
      </div>

      <div
        class="kind-pills"
        role="group"
        aria-label="Filter by roll kind"
      >
        {#each KIND_FILTER_OPTIONS as option (option.kind)}
          <button
            type="button"
            class="kind-pill pixel"
            class:kind-pill--on={oracleKinds.has(option.kind)}
            aria-pressed={oracleKinds.has(option.kind)}
            onclick={() => toggleOracleKind(option.kind)}
          >
            {option.label}
          </button>
        {/each}
      </div>

      {#if history.length === 0}
        <p class="muted">No rolls yet.</p>
      {:else if filteredHistory.length === 0}
        <p class="muted search__hint">
          No rolls match the current filter.
        </p>
      {:else}
        <ul class="history">
          {#each filteredHistory as outcome (outcome.id)}
            <li class="history__row">
              <MechanicalReceipt
                {outcome}
                threads={gs.threads}
                npcs={gs.npcs}
                defaultOpen={false}
              />
              {#if findNarrativeEventForOracle(gs, outcome.id) !== null}
                <button
                  type="button"
                  class="ghost history__jump pixel"
                  onclick={() => jumpFromOracle(outcome.id)}
                  title="Show this roll's narration in the chat"
                >
                  Show in chat
                </button>
              {/if}
            </li>
          {/each}
        </ul>
      {/if}
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
  .seed-readout {
    display: grid;
    gap: 0.5rem;
  }
  .seed-readout__head {
    margin: 0;
    color: var(--gold-bright);
    font-size: 0.92rem;
    letter-spacing: 0.04em;
  }
  .seed-readout__danger {
    margin: 0;
    font-size: 0.85rem;
    line-height: 1.4;
  }
  .seed-readout__grid {
    margin: 0;
    display: grid;
    grid-template-columns: max-content 1fr;
    column-gap: 0.85rem;
    row-gap: 0.25rem;
    font-size: 0.88rem;
  }
  .seed-readout__grid dt {
    margin: 0;
    font-family: var(--font-pixel);
    font-size: 0.7rem;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    color: var(--gold-tarnished);
  }
  .seed-readout__grid dd {
    margin: 0;
    color: var(--paper-bone);
  }
  .archived-hint {
    margin: 0;
    font-size: 0.74rem;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: var(--paper-shadow);
  }

  /*
   * F-09 search controls. We share styles between the transcript
   * search and the oracle filter because the affordance is
   * conceptually identical — a text input with an inline Clear,
   * sometimes followed by a pill row. Differentiating their
   * styling would just teach the player two layouts for the same
   * action.
   */
  .search {
    display: flex;
    gap: 0.45rem;
    align-items: center;
    margin-bottom: 0.4rem;
  }
  .search__input {
    flex: 1;
    min-width: 0;
    padding: 0.4rem 0.55rem;
    font-family: var(--font-body);
    font-size: 0.9rem;
    line-height: 1.3;
    color: var(--paper-bone);
    background: rgba(0, 0, 0, 0.35);
    border: 1px solid color-mix(in oklab, var(--gold-tarnished) 35%, transparent);
    border-radius: 2px;
    transition: border-color 140ms ease, box-shadow 140ms ease;
  }
  .search__input::placeholder {
    color: color-mix(in oklab, var(--paper-shadow) 80%, transparent);
    font-style: italic;
  }
  .search__input:focus {
    outline: none;
    border-color: var(--gold-bright);
    box-shadow: 0 0 0 1px var(--gold-bright) inset;
  }
  .search__clear {
    padding: 0.32rem 0.55rem;
    font-size: 0.7rem;
    letter-spacing: 0.05em;
    text-transform: uppercase;
  }
  .search__hint {
    margin: 0.2rem 0 0;
    font-size: 0.78rem;
    line-height: 1.4;
    font-style: italic;
  }
  .search__hits {
    list-style: none;
    padding: 0;
    margin: 0.35rem 0 0;
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
  }
  .hit {
    display: flex;
    flex-direction: column;
    gap: 0.2rem;
    width: 100%;
    text-align: left;
    padding: 0.45rem 0.55rem;
    background: rgba(0, 0, 0, 0.25);
    border: 1px solid color-mix(in oklab, var(--gold-tarnished) 25%, transparent);
    border-radius: 2px;
    color: var(--paper-bone);
    cursor: pointer;
    transition: border-color 140ms ease, background 140ms ease;
  }
  .hit:hover {
    background: rgba(0, 0, 0, 0.4);
    border-color: var(--gold-bright);
  }
  .hit:focus-visible {
    outline: 2px solid var(--gold-bright);
    outline-offset: 1px;
  }
  .hit__meta {
    display: flex;
    align-items: baseline;
    gap: 0.5rem;
    font-size: 0.65rem;
    color: var(--gold-tarnished);
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }
  .hit__speaker {
    color: var(--gold-bright);
  }
  .hit__source {
    color: color-mix(in oklab, var(--rust-iron) 70%, var(--paper-stained));
  }
  .hit__time {
    margin-left: auto;
    color: var(--paper-shadow);
  }
  .hit__snippet {
    font-family: var(--font-body);
    font-size: 0.86rem;
    line-height: 1.45;
    color: var(--paper-warm);
  }
  .hit__snippet mark {
    background: color-mix(in oklab, var(--gold-bright) 32%, transparent);
    color: var(--paper-warm);
    padding: 0 1px;
    border-radius: 2px;
  }

  /*
   * F-09 oracle-kind filter pills. Visually paired with the search
   * input above so the two filter dimensions read as one control.
   * On-state uses a subtle inset glow rather than a fill so an
   * all-on row doesn't look like a solid blob.
   */
  .kind-pills {
    display: flex;
    flex-wrap: wrap;
    gap: 0.3rem;
    margin-bottom: 0.45rem;
  }
  .kind-pill {
    padding: 0.28rem 0.5rem;
    font-size: 0.66rem;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: color-mix(in oklab, var(--paper-shadow) 92%, transparent);
    background: rgba(0, 0, 0, 0.25);
    border: 1px solid color-mix(in oklab, var(--gold-tarnished) 30%, transparent);
    border-radius: 2px;
    cursor: pointer;
    transition: color 140ms ease, border-color 140ms ease, background 140ms ease;
  }
  .kind-pill:hover {
    color: var(--paper-bone);
    border-color: var(--gold-tarnished);
  }
  .kind-pill:focus-visible {
    outline: 2px solid var(--gold-bright);
    outline-offset: 1px;
  }
  .kind-pill--on {
    color: var(--gold-bright);
    border-color: var(--gold-bright);
    background: color-mix(in oklab, var(--gold-bright) 10%, transparent);
    box-shadow: 0 0 0 1px color-mix(in oklab, var(--gold-bright) 18%, transparent) inset;
  }

  /*
   * F-09 jump-to-chat button paired with each oracle row. Sits
   * directly below the receipt so the player's eye lands on it
   * after they've scanned the dice readout.
   */
  .history__row {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }
  .history__jump {
    align-self: flex-start;
    padding: 0.28rem 0.55rem;
    font-size: 0.66rem;
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }
</style>
