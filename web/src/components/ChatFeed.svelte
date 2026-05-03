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
      };

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

  $effect(() => {
    // We track length only - scrolling on every state mutation (e.g. a
    // chaos toggle from the inspector) would yank the user away from
    // wherever they were reading.
    if (messages.length !== lastCount) {
      lastCount = messages.length;
      requestAnimationFrame(scrollToBottom);
    }
  });

  onMount(() => {
    requestAnimationFrame(scrollToBottom);
  });
</script>

<section class="feed" bind:this={scroller}>
  {#if messages.length === 0}
    <div class="empty muted">The DM is preparing the opening scene…</div>
  {:else}
    {#each messages as message (message.id)}
      <ChatMessage
        eventId={message.id}
        speaker={message.kind}
        text={message.text}
        timestamp={message.timestamp}
        outcome={message.outcome ?? null}
        canRegenerate={canRegenerateMessage(message.kind, message.id, latestNarrativeId)}
      />
    {/each}
  {/if}

  {#if game.isLoading && game.rollPhase === "idle"}
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
