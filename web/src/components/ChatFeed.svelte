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

Auto-scroll to bottom whenever the message count grows. We don't try to
preserve scroll on history-deep navigation because the chat is a forward
narrative, not a browsing surface.
-->
<script lang="ts">
  import { onMount } from "svelte";
  import ChatMessage from "./ChatMessage.svelte";
  import { canRegenerateMessage } from "../lib/message-actions";
  import { game } from "../lib/store.svelte";
  import type { GameState, GameEvent, OracleOutcome } from "../lib/types";
  import type { ClientNote } from "../lib/store.svelte";

  type Props = { state: GameState };
  // Renamed to `gs` because Svelte's compiler treats a local identifier
  // `state` as a store-subscription target whenever the `$state` rune
  // also appears in the file - see store_rune_conflict.
  const { state: gs }: Props = $props();

  type Msg =
    | {
        kind: "dm" | "player" | "system";
        id: string;
        text: string;
        timestamp: string;
        outcome?: OracleOutcome | null;
        thinking?: string | null;
        streaming?: boolean;
      };

  // Read `event.thinking` as an optional extension. The backend pass
  // adds a `thinking` field to GameEvent; until that lands, every
  // message renders with `null` and the CollapsedThinking block hides
  // itself. On merge this becomes a direct field read.
  function thinkingFor(event: GameEvent): string | null {
    const ext = (event as unknown as { thinking?: string | null }).thinking;
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
  const provisional: Msg | null = $derived.by(() => {
    if (!game.streaming.active) return null;
    const route = game.streaming.route;
    if (route !== null && !PROSE_ROUTES.has(route)) return null;
    return {
      kind: "dm",
      id: `provisional_${game.streaming.requestId ?? "live"}`,
      text: game.streaming.content,
      timestamp: new Date().toISOString(),
      outcome: game.streaming.pendingOutcome,
      thinking: game.streaming.thinking,
      streaming: true,
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

  function scrollToBottom(): void {
    if (!scroller) return;
    scroller.scrollTo({ top: scroller.scrollHeight, behavior: "smooth" });
  }

  // Scroll trigger: rerun when *either* the persisted message count or
  // the provisional bubble's content length changes. We don't track
  // provisional thinking because that block is collapsed by default
  // and shouldn't pull the viewport. Tracking provisional content
  // length keeps the bubble visible as tokens arrive (auto-follow);
  // a player who scrolled up to read backstory won't get yanked
  // because the scroll behavior is `smooth` and we only nudge to
  // bottom on count changes, not on every keystroke.
  const totalCount = $derived(
    messages.length
      + (provisional !== null ? 1 : 0)
      + (provisional !== null ? Math.floor(provisional.text.length / 80) : 0),
  );

  $effect(() => {
    if (totalCount !== lastCount) {
      lastCount = totalCount;
      requestAnimationFrame(scrollToBottom);
    }
  });

  onMount(() => {
    requestAnimationFrame(scrollToBottom);
  });
</script>

<section class="feed" bind:this={scroller}>
  {#if messages.length === 0 && provisional === null}
    <div class="empty muted">The DM is preparing the opening scene…</div>
  {:else}
    {#each messages as message (message.id)}
      <ChatMessage
        eventId={message.id}
        speaker={message.kind}
        text={message.text}
        timestamp={message.timestamp}
        outcome={message.outcome ?? null}
        thinking={message.thinking ?? null}
        canRegenerate={canRegenerateMessage(message.kind, message.id, latestNarrativeId)}
      />
    {/each}
    {#if provisional}
      <ChatMessage
        eventId={provisional.id}
        speaker={provisional.kind}
        text={provisional.text}
        timestamp={provisional.timestamp}
        outcome={provisional.outcome ?? null}
        thinking={provisional.thinking ?? null}
        streaming={true}
        canRegenerate={false}
      />
    {/if}
  {/if}

  {#if game.isLoading && game.rollPhase === "idle" && provisional === null}
    <div class="composing"><span class="spinner-row">DM is composing</span></div>
  {/if}
</section>

<style>
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
</style>
