<!--
@component
ChatFeed — the chronological conversation surface.

How messages are derived from state:
  1. ORACLE events are NOT rendered as their own message - they collapse
     into the receipt under the next narrative message that references
     them. Showing both as separate bubbles would double the noise.
  2. NARRATIVE events render as DM messages and pull in the matching
     OracleOutcome from state.oracle_history (matched by id).
  3. PLAYER events render as player messages.
  4. SYSTEM events render as system messages (e.g. "Campaign initialized",
     "Chaos factor changed").
  5. If no NARRATIVE events exist yet, we synthesize an opening DM
     message from state.current_scene + state.setting_notes so the
     player has somewhere to start the conversation.
  6. Client-side notes (slash help, slash errors) are interleaved by
     timestamp.

F-09 browsing behavior:
  - Each rendered row carries a `data-event-id` anchor matching its
    canonical event id (or the synthesized `opening_<state-id>` for
    the first DM beat).
  - Auto-follow to bottom suspends as soon as the player scrolls up
    out of the bottom band (default 120px). It resumes automatically
    when they scroll back into the band, or explicitly when they hit
    the floating "Jump to latest" pill.
  - The Inspector commands cross-surface scrolls via
    `game.scrollRequest`; we react to a fresh request by scrolling
    the matching anchor into view and applying a one-shot flash
    highlight, then clear the request from the store.
-->

<script lang="ts">
  import { onMount } from "svelte";
  import ChatMessage from "./ChatMessage.svelte";
  import StageChecklist from "./StageChecklist.svelte";
  import { canRegenerateMessage } from "../lib/message-actions";
  import { game } from "../lib/store.svelte";
  import type { GameState, GameEvent, OracleOutcome, StageTiming } from "../lib/types";
  import type { ClientNote } from "../lib/store.svelte";

  type Props = { state: GameState };
  // Renamed to `gs` because Svelte's compiler treats a local identifier
  // `state` as a store-subscription target whenever the `$state` rune
  // also appears in the file - see store_rune_conflict.
  const { state: gs }: Props = $props();

  type Msg = {
    // F-10 added the `ooc` speaker for OOC explainer answers. See
    // ChatMessage.svelte for the visual treatment; the union here
    // mirrors the speaker prop accepted by that component.
    kind: "dm" | "player" | "system" | "ooc";
    id: string;
    text: string;
    timestamp: string;
    outcome?: OracleOutcome | null;
    thinking?: string | null;
    // F-11 persisted stage timings. Only narrative events carry a
    // non-empty list; the message component hides the checklist /
    // total pill cleanly when this is empty.
    stageTimings?: readonly StageTiming[];
    streaming?: boolean;
    // True only when the in-flight bubble was reattached after a
    // page reload. Surfaces as a "resuming…" tag in ChatMessage
    // so the player can tell the difference between "the model
    // started typing" and "we found a turn the previous page
    // started and we're now tailing it."
    resuming?: boolean;
    // OOC-only: the player's question, rendered as a `Q:` row
    // above the answer body.
    question?: string | null;
  };

  function thinkingFor(event: GameEvent): string | null {
    const ext = event.thinking;
    return typeof ext === "string" && ext.trim() !== "" ? ext : null;
  }

  function findOutcome(events: readonly OracleOutcome[], id: string | null): OracleOutcome | null {
    if (!id) return null;
    return events.find((o) => o.id === id) ?? null;
  }

  function fromEvent(event: GameEvent, outcomes: readonly OracleOutcome[]): Msg | null {
    switch (event.event_type) {
      case "narrative":
        return {
          kind: "dm",
          id: event.id,
          text: event.content,
          timestamp: event.created_at,
          outcome: findOutcome(outcomes, event.oracle_outcome_id),
          thinking: thinkingFor(event),
          stageTimings: event.stage_timings ?? [],
        };
      case "player":
        return {
          kind: "player",
          id: event.id,
          text: event.content,
          timestamp: event.created_at,
        };
      case "system":
        return {
          kind: "system",
          id: event.id,
          text: event.content,
          timestamp: event.created_at,
        };
      case "oracle":
        // Folded into the receipt of the matching narrative message.
        return null;
    }
  }

  function fromNote(note: ClientNote): Msg {
    if (note.kind === "explanation" || note.kind === "oracle_preview") {
      // F-10 OOC notes carry both the question and the answer so the
      // chat surface can render a single Q+A card. We keep them as
      // ClientNotes (not action_log entries) so they're ephemeral by
      // construction — reload clears them and they never feed back
      // into memory rebuilds.
      return {
        kind: "ooc",
        id: note.id,
        text: note.text,
        timestamp: note.created_at,
        question: note.question ?? null,
      };
    }
    return {
      kind: "system",
      id: note.id,
      text: note.text,
      timestamp: note.created_at,
    };
  }

  // The opening message: either we already have narration, or we need a
  // first DM message synthesized from the campaign generation result.
  function openingMessage(s: GameState): Msg | null {
    const hasNarrative = s.action_log.some((e) => e.event_type === "narrative");
    if (hasNarrative) return null;
    return {
      kind: "dm",
      id: `opening_${s.id}`,
      text: `${s.current_scene}\n\n${s.setting_notes}`,
      timestamp: s.created_at,
    };
  }

  const messages: Msg[] = $derived.by(() => {
    const fromEvents: Msg[] = [];
    for (const event of gs.action_log) {
      const m = fromEvent(event, gs.oracle_history);
      if (m) fromEvents.push(m);
    }

    const opening = openingMessage(gs);
    const fromNotes = game.notes.map(fromNote);

    const all = [...(opening ? [opening] : []), ...fromEvents, ...fromNotes];
    all.sort((a, b) => a.timestamp.localeCompare(b.timestamp));
    return all;
  });

  // Provisional DM bubble for an in-flight stream. We append it to the
  // tail (always last in time order) rather than mixing it into the
  // sorted list because:
  //   - Its timestamp doesn't exist yet — the backend assigns one when
  //     the canonical event lands.
  //   - It's always conceptually "newest" until it's replaced by the
  //     real event, so insertion order is correct and we don't have to
  //     fight the sort.
  // We render it only when the stream is producing model output:
  // `streaming.active` plus either content/thinking already streaming
  // or a route that we know produces a DM bubble (turn / action /
  // regenerate). For routes like character_quiz/draft, the streaming
  // surface is the LoadingPanel in CharacterSetup, not the chat — we
  // hide the chat-side bubble in those cases.
  const PROSE_ROUTES = new Set([
    "yes_no",
    "random_event",
    "scene_check",
    "player_action",
    "save",
    "attack",
    "harm",
    "recovery",
    "equip",
    "retreat",
    "regenerate",
  ]);
  // F-10: the explainer streams through the same NDJSON contract
  // but produces an OOC bubble, not a DM bubble. We branch on the
  // route here so the provisional surface gets the right speaker
  // (and the right ChatMessage styling) without requiring a separate
  // streaming buffer.
  const provisional: Msg | null = $derived.by(() => {
    if (!game.streaming.active) return null;
    const route = game.streaming.route;
    if (route === "explanation") {
      // We can't pull the player's verbatim question off the store
      // because /explain is a one-shot dispatch — we don't keep the
      // request body around. For the streaming bubble we leave the
      // Q: row blank; the persisted ClientNote that replaces it
      // carries the captured question and renders the full pair.
      return {
        kind: "ooc",
        id: `provisional_${game.streaming.requestId ?? "live"}`,
        text: game.streaming.content,
        timestamp: new Date().toISOString(),
        thinking: game.streaming.thinking,
        streaming: true,
        resuming: game.streaming.resuming,
        question: null,
      };
    }
    // While `route` is null we still render the bubble because a
    // resumed stream may not have replayed `meta` yet (the buffered
    // history starts arriving before the live tail catches up). The
    // chat surface needs *something* visible the moment we flip into
    // streaming.active, otherwise the player sees nothing during
    // the brief window between resume start and the first event.
    if (route !== null && !PROSE_ROUTES.has(route)) return null;
    return {
      kind: "dm",
      id: `provisional_${game.streaming.requestId ?? "live"}`,
      text: game.streaming.content,
      timestamp: new Date().toISOString(),
      outcome: game.streaming.pendingOutcome,
      thinking: game.streaming.thinking,
      streaming: true,
      resuming: game.streaming.resuming,
    };
  });

  const latestNarrativeId = $derived.by(() => {
    const latest = [...gs.action_log]
      .reverse()
      .find((event) => event.event_type === "narrative");
    return latest?.id ?? null;
  });

  let scroller: HTMLElement | undefined;
  let lastCount: number = $state(0);
  // F-09: auto-follow latches off when the player scrolls up out of
  // the bottom band, on again when they scroll back into it. The
  // alternative ("once unlatched, stay off until the user clicks
  // Jump-to-latest") is more rigid but punishes the common case
  // where the player scrolled up by accident — resuming on
  // re-bottom matches the muscle memory people have from chat apps.
  let pinnedToBottom: boolean = $state(true);
  // Last consumed scroll request seq. We track it instead of clearing
  // `game.scrollRequest` synchronously because a freshly-set request
  // for the same eventId still has to re-run the scroll/flash effect
  // — Svelte's reactivity sees the seq bump even when the eventId
  // didn't change.
  let consumedScrollSeq: number = $state(-1);
  // F-09 cross-component flash highlight. We pin the eventId here so
  // the corresponding wrapper can apply the flash class deterministic-
  // ally, and clear it on a timer so the rule doesn't linger.
  let flashEventId: string | null = $state(null);
  let flashTimer: ReturnType<typeof setTimeout> | null = null;

  // Distance from the bottom edge below which auto-follow is on. We
  // pick a band rather than `scrollTop === scrollBottom` because
  // smooth-scroll animations and message-height changes mean the
  // exact-bottom predicate flickers in/out spuriously.
  const FOLLOW_THRESHOLD_PX = 120;
  const FLASH_DURATION_MS = 1700;

  function distanceFromBottom(): number {
    if (!scroller) return 0;
    return scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight;
  }

  function scrollToBottom(behavior: ScrollBehavior = "smooth"): void {
    if (!scroller) return;
    scroller.scrollTo({ top: scroller.scrollHeight, behavior });
  }

  function jumpToLatest(): void {
    pinnedToBottom = true;
    scrollToBottom();
  }

  function handleScroll(): void {
    if (!scroller) return;
    pinnedToBottom = distanceFromBottom() <= FOLLOW_THRESHOLD_PX;
  }

  function flashRow(eventId: string): void {
    flashEventId = eventId;
    if (flashTimer !== null) clearTimeout(flashTimer);
    flashTimer = setTimeout(() => {
      flashEventId = null;
      flashTimer = null;
    }, FLASH_DURATION_MS);
  }

  function scrollToEvent(eventId: string): void {
    if (!scroller) return;
    // We use a CSS attribute selector instead of a Map<eventId,
    // HTMLElement> because the {#each} block destroys/creates nodes
    // on streaming churn; rebuilding the map after every render
    // would just re-do this lookup work eagerly.
    const target = scroller.querySelector<HTMLElement>(
      `[data-event-id="${CSS.escape(eventId)}"]`,
    );
    if (target === null) return;
    target.scrollIntoView({ behavior: "smooth", block: "center" });
    flashRow(eventId);
  }

  // Scroll trigger: rerun when *either* the persisted message count or
  // the provisional bubble's content length changes. We don't track
  // provisional thinking because that block is collapsed by default
  // and shouldn't pull the viewport. Tracking provisional content
  // length keeps the bubble visible as tokens arrive (auto-follow);
  // a player who scrolled up to read backstory won't get yanked
  // because we gate the scroll on `pinnedToBottom`.
  const totalCount = $derived(
    messages.length
      + (provisional !== null ? 1 : 0)
      + (provisional !== null ? Math.floor(provisional.text.length / 80) : 0),
  );

  $effect(() => {
    if (totalCount !== lastCount) {
      lastCount = totalCount;
      // Auto-follow is opt-out: when the player has scrolled away,
      // we leave the viewport alone and surface the
      // "Jump to latest" pill instead. Without this gate, every
      // streamed token in the in-flight bubble would yank a player
      // who's reading earlier prose back to the bottom.
      //
      // Auto-follow uses *instant* scroll, not smooth, on purpose:
      // a smooth-scroll mid-animation fires `onscroll` repeatedly
      // with `distanceFromBottom > FOLLOW_THRESHOLD_PX`, which
      // would briefly flip `pinnedToBottom` to false and stall the
      // follow on the next streamed token. Smooth scroll is
      // reserved for the explicit jumpToLatest / scrollToEvent
      // paths where the visual cue matters and there's no token
      // race in flight.
      if (pinnedToBottom) {
        requestAnimationFrame(() => scrollToBottom("auto"));
      }
    }
  });

  // Cross-component scroll request consumer. We watch the store
  // signal and run the scroll once per fresh seq value; the explicit
  // seq guard prevents a second run on the same request when the
  // store reactivity re-fires for unrelated reasons (state refresh,
  // notes change). After consuming, we ask the store to clear the
  // request so reloading the page or remounting the feed doesn't
  // replay a stale jump.
  $effect(() => {
    const req = game.scrollRequest;
    if (req === null) return;
    if (req.seq === consumedScrollSeq) return;
    consumedScrollSeq = req.seq;
    requestAnimationFrame(() => {
      scrollToEvent(req.eventId);
      game.consumeScrollRequest();
    });
  });

  onMount(() => {
    requestAnimationFrame(() => scrollToBottom("auto"));
    return () => {
      if (flashTimer !== null) clearTimeout(flashTimer);
    };
  });
</script>

<div class="feed-shell">
<section class="feed" bind:this={scroller} onscroll={handleScroll}>
  {#if messages.length === 0 && provisional === null}
    <div class="empty muted">The DM is preparing the opening scene…</div>
  {:else}
    {#each messages as message (message.id)}
      <div
        class="anchor"
        class:flash={flashEventId === message.id}
        data-event-id={message.id}
      >
        <ChatMessage
          eventId={message.id}
          speaker={message.kind}
          text={message.text}
          timestamp={message.timestamp}
          outcome={message.outcome ?? null}
          thinking={message.thinking ?? null}
          stageTimings={message.stageTimings ?? []}
          question={message.question ?? null}
          threads={gs.threads}
          npcs={gs.npcs}
          canRegenerate={canRegenerateMessage(message.kind, message.id, latestNarrativeId)}
        />
      </div>
    {/each}
    {#if provisional}
      <div class="anchor" data-event-id={provisional.id}>
        {#if game.streaming.stages.length > 0}
          <!--
            Stage checklist sits *above* the provisional bubble so the
            player has something to read while the backend is still in
            its pre-narration steps (planner → mechanics → continuity →
            updaters → narration prep). Once the narrator starts
            streaming and `streaming_narration` flips to active, the
            checklist remains visible but the focus naturally moves to
            the prose tokens accumulating below.
          -->
          <StageChecklist stages={game.streaming.stages} />
        {/if}
        <ChatMessage
          eventId={provisional.id}
          speaker={provisional.kind}
          text={provisional.text}
          timestamp={provisional.timestamp}
          outcome={provisional.outcome ?? null}
          thinking={provisional.thinking ?? null}
          question={provisional.question ?? null}
          threads={gs.threads}
          npcs={gs.npcs}
          streaming={true}
          resuming={provisional.resuming ?? false}
          canRegenerate={false}
        />
      </div>
    {/if}
  {/if}

  {#if game.isLoading && game.rollPhase === "idle" && provisional === null}
    {#if game.streaming.stages.length > 0}
      <!--
        Edge case: the stream opened (we received stage frames) but the
        provisional bubble hasn't materialized yet — typically because
        meta hasn't arrived or the route is one we don't render a
        provisional bubble for. Keep the checklist visible so the
        player still gets progress feedback during the wait.
      -->
      <div class="composing-stages"><StageChecklist stages={game.streaming.stages} /></div>
    {:else}
      <div class="composing"><span class="spinner-row">DM is composing</span></div>
    {/if}
  {/if}
</section>

  {#if !pinnedToBottom}
    <button
      type="button"
      class="jump-latest pixel"
      onclick={jumpToLatest}
      aria-label="Jump to latest message"
    >
      ↓ Jump to latest
    </button>
  {/if}
</div>

<style>
  /*
   * Positioned shell so the floating "Jump to latest" pill anchors to
   * the chat region, not the document. The shell is itself a flex
   * column so it can fill whatever vertical slot the parent layout
   * gave it without needing the parent to know about F-09.
   */
  .feed-shell {
    position: relative;
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }
  .feed {
    flex: 1;
    overflow-y: auto;
    padding: 0.4rem 0.2rem 1rem;
    scroll-behavior: smooth;
    /*
     * A faint top fade so messages "emerge" from the strip rather than
     * butting against it - sells the bound-ledger frame.
     */
    mask-image: linear-gradient(to bottom, transparent 0, black 14px);
    -webkit-mask-image: linear-gradient(to bottom, transparent 0, black 14px);
  }
  .empty {
    padding: 2rem 0;
    text-align: center;
    font-style: italic;
  }
  .composing {
    padding: 0.6rem 1rem;
  }
  .composing-stages {
    /*
     * Same horizontal inset as `.composing` so the checklist lines up
     * with the spinner-row when the player switches between the two
     * surfaces across requests; vertical padding is lighter because
     * the StageChecklist already has its own bordered card.
     */
    padding: 0.2rem 1rem 0.6rem;
  }

  /*
   * Anchors are layout-transparent — they exist purely so a
   * `data-event-id` selector can find a stable target node. We avoid
   * adding any margin/padding here so removing/adding the wrapper is
   * a no-op for the chat's existing visual rhythm.
   */
  .anchor {
    display: block;
  }
  /*
   * Flash highlight applied to a row when it's the target of an
   * inspector deep-link. The brief gold wash echoes the candle-lit
   * receipt accent without competing with the receipt's own color.
   * Reduced-motion users get a static dwell tint that fades on the
   * same timer instead of an animation.
   */
  .anchor.flash {
    animation: anchor-flash 1700ms ease-out;
    border-radius: 4px;
  }
  @keyframes anchor-flash {
    0% {
      background: color-mix(in oklab, var(--gold-bright) 28%, transparent);
      box-shadow: 0 0 0 1px color-mix(in oklab, var(--gold-bright) 40%, transparent) inset;
    }
    60% {
      background: color-mix(in oklab, var(--gold-bright) 14%, transparent);
      box-shadow: 0 0 0 1px color-mix(in oklab, var(--gold-bright) 22%, transparent) inset;
    }
    100% {
      background: transparent;
      box-shadow: 0 0 0 1px transparent inset;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .anchor.flash {
      animation: none;
      background: color-mix(in oklab, var(--gold-bright) 18%, transparent);
      transition: background 1500ms ease;
    }
  }

  /*
   * "Jump to latest" floating pill. Sits at the bottom-right of the
   * chat region, hovering above the chat fade. We deliberately
   * mirror the common-actions pill aesthetic (pixel font, gold
   * tarnished border) so the affordance feels native to the
   * Composer's tray rather than a foreign control.
   */
  .jump-latest {
    position: absolute;
    right: 0.9rem;
    bottom: 0.7rem;
    z-index: 4;
    padding: 0.4rem 0.7rem;
    font-size: 0.72rem;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--paper-bone);
    background: color-mix(in oklab, var(--ink-black) 92%, transparent);
    border: 1px solid var(--gold-tarnished);
    border-radius: 2px;
    box-shadow:
      0 1px 0 color-mix(in oklab, var(--gold-tarnished) 30%, transparent) inset,
      0 6px 16px rgba(0, 0, 0, 0.55);
    cursor: pointer;
    transition:
      transform 120ms ease,
      background 160ms ease,
      border-color 160ms ease;
  }
  .jump-latest:hover {
    background: color-mix(in oklab, var(--ink-black) 80%, transparent);
    border-color: var(--gold-bright);
    color: var(--gold-bright);
  }
  .jump-latest:focus-visible {
    outline: 2px solid var(--gold-bright);
    outline-offset: 2px;
  }
  .jump-latest:active {
    transform: translateY(1px);
  }
</style>
