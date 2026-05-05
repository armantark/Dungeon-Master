// Svelte 5 runes-based store for the entire client.
//
// Why a single store instead of one-store-per-feature:
// - The backend always returns the whole GameState, so the natural unit of
//   reactivity is "the whole game". Splitting would introduce cross-store
//   ordering bugs (e.g. "did the chaos factor update before the action log?").
// - The dice-tumble animation needs to know about pending oracle calls, so
//   the latest pending OracleOutcome and the in-flight request live in the
//   same state object as the persisted state.

import { api, ApiError, StreamTransportError } from "./api";
import { parseTurn, SLASH_HELP } from "./slash";
import type { StreamHandlers, StreamResult } from "./streaming";
import type { StreamRoute } from "./streaming-types";
import type {
  CharacterQuiz,
  CharacterQuizAnswer,
  CharacterSheet,
  GameState,
  Likelihood,
  OracleOutcome,
} from "./types";

// Rolling animation phase. We deliberately gate the narrative reveal on
// the dice landing because it sells the fiction that mechanics are real.
type RollPhase = "idle" | "rolling" | "settling";

// Provisional streaming buffer shape. We keep these flat on the store
// (rather than in a nested `streaming: { ... }` object) because Svelte
// 5 runes pick up direct field reads cheaply, and the chat feed needs
// to subscribe to `provisionalContent` independently of `provisionalThinking`
// without forcing a deep proxy. `route` lets the chat label a
// provisional DM bubble before any tokens arrive ("composing a scene
// check…"); `requestId` is surfaced in error toasts so the player can
// reference a specific run if they file an issue.
interface StreamingState {
  active: boolean;
  route: StreamRoute | null;
  requestId: string | null;
  content: string;
  thinking: string;
  // mechanics_ready / oracle_outcome events arrive *before* content
  // deltas. We pin the deterministic outcome here so the receipt can
  // render even mid-stream without waiting for the final state.
  pendingOutcome: OracleOutcome | null;
}

/**
 * Compose the natural-language prompt sent to the turn planner for a
 * `/retreat` slash command. The planner is already trained to route
 * "I retreat" / "I disengage" / "I fall back" as RETREAT, so we use
 * that same vocabulary verbatim. An optional reason from the player is
 * appended so the resulting narration can lean on the player's framing
 * (where they're heading, what they're sacrificing) instead of inventing
 * its own.
 */
function buildRetreatPrompt(reason: string): string {
  const cleaned = reason.trim();
  if (!cleaned) return "I attempt to retreat from combat.";
  return `I attempt to retreat from combat: ${cleaned}`;
}

function emptyStreamingState(): StreamingState {
  return {
    active: false,
    route: null,
    requestId: null,
    content: "",
    thinking: "",
    pendingOutcome: null,
  };
}

// Inline "system message" that the chat surfaces alongside server events.
// We keep these client-only because they're transient feedback (help
// text, slash-error hints) and don't belong in the persisted action log.
export interface ClientNote {
  id: string;
  kind: "help" | "error" | "info";
  text: string;
  created_at: string;
}

// Note: never write `$state<T>(...)` with explicit type arguments. Svelte 5
// silently initializes the rune to `undefined` in that case (the type-arg
// syntax is treated as an untyped call). Use a separate annotation on the
// declaration when you need to widen / narrow the inferred type.
class GameStore {
  state: GameState | null = $state(null);
  isLoading: boolean = $state(false);
  error: string | null = $state(null);
  rollPhase: RollPhase = $state("idle");
  pendingOracle: OracleOutcome | null = $state(null);
  cancelLabel: string | null = $state(null);

  // Provisional streaming buffer. While `streaming.active` is true, the
  // chat feed renders a provisional DM bubble that mirrors `content`,
  // a thinking bubble that mirrors `thinking`, and a receipt pinned to
  // `pendingOutcome`. On stream completion, the canonical event lands
  // in `state.action_log` and the provisional bubble is replaced
  // wholesale — no delta merging, no "did this token come from the
  // stream or the final?" reconciliation logic.
  streaming: StreamingState = $state(emptyStreamingState());

  // Client-only ephemeral messages (slash-help, slash-error). They live
  // alongside the server-canonical action log in the chat feed.
  notes: ClientNote[] = $state([]);

  // Inspector drawer visibility. Lives here (not on App.svelte) so any
  // component - e.g. a chat receipt's "show full mechanics" link - can
  // command the drawer to open without prop drilling.
  inspectorOpen: boolean = $state(false);
  #abortController: AbortController | null = null;
  #cancelRequested = false;

  // Derived: the most recent oracle outcome on the persisted state. Exposed
  // as a getter (via `$derived.by`) so the dice tumbler can subscribe and
  // re-animate when this changes.
  latestOutcome: OracleOutcome | null = $derived.by(() => {
    if (!this.state || this.state.oracle_history.length === 0) return null;
    return this.state.oracle_history[this.state.oracle_history.length - 1] ?? null;
  });

  async refresh(): Promise<void> {
    await this.#run((signal) => api.getState(signal));
  }

  async reset(): Promise<void> {
    await this.#run((signal) => api.reset(signal), { cancelLabel: "Stop reset" });
  }

  async setChaos(value: number): Promise<void> {
    await this.#run((signal) => api.setChaos(value, signal));
  }

  async updateNotes(settingNotes: string, playerNotes: string): Promise<void> {
    await this.#run((signal) => api.updateNotes(settingNotes, playerNotes, signal));
  }

  async askYesNo(question: string, likelihood: Likelihood): Promise<void> {
    await this.#runWithRoll((signal) => api.askYesNo(question, likelihood, signal));
  }

  async randomEvent(): Promise<void> {
    await this.#runWithRoll((signal) => api.randomEvent(signal));
  }

  async sceneCheck(expectedScene: string): Promise<void> {
    await this.#runWithRoll((signal) => api.sceneCheck(expectedScene, signal));
  }

  async submitAction(action: string): Promise<void> {
    // Player actions don't roll mechanically, so we skip the tumble phase
    // and just show the loading shimmer. Stream first; fall back to the
    // unary endpoint if the backend hasn't shipped streaming yet.
    await this.#runStreaming({
      stream: (handlers, signal) => api.streamSubmitAction(action, handlers, signal),
      fallback: (signal) => api.submitAction(action, signal),
      cancelLabel: "Stop response",
      rollAware: false,
    });
  }

  async submitTurn(text: string): Promise<void> {
    // Natural chat may or may not roll; the backend router decides. The
    // streaming variant emits a `mechanics_ready` event before any prose
    // tokens, so the dice receipt pins as soon as the deterministic
    // resolution is known and the prose streams on top.
    await this.#runStreaming({
      stream: (handlers, signal) => api.streamSubmitTurn(text, handlers, signal),
      fallback: (signal) => api.submitTurn(text, signal),
      cancelLabel: "Stop response",
      rollAware: true,
    });
  }

  async fetchCharacterTemplates(): Promise<CharacterSheet[]> {
    const response = await this.#call((signal) => api.getCharacterTemplates(signal), {
      cancelLabel: "Stop templates",
    });
    return response?.templates ?? [];
  }

  async generateCharacterDraft(
    mode: "scratch" | "template",
    prompt?: string,
    template?: CharacterSheet,
  ): Promise<CharacterSheet | null> {
    return await this.#runStreamingPayload<CharacterSheet>({
      stream: (handlers, signal) =>
        api.streamCharacterDraft(mode, handlers, prompt, template, signal),
      fallback: async (signal) => {
        const response = await api.generateCharacterDraft(mode, prompt, template, signal);
        return response.draft;
      },
      finalKind: "character_draft",
      extract: (payload) => (payload as { draft: CharacterSheet }).draft,
      cancelLabel: "Stop draft",
    });
  }

  async generateCharacterQuiz(concept: string): Promise<CharacterQuiz | null> {
    return await this.#runStreamingPayload<CharacterQuiz>({
      stream: (handlers, signal) => api.streamCharacterQuiz(concept, handlers, signal),
      fallback: async (signal) => {
        const response = await api.generateCharacterQuiz(concept, signal);
        return response.quiz;
      },
      finalKind: "character_quiz",
      extract: (payload) => (payload as { quiz: CharacterQuiz }).quiz,
      cancelLabel: "Stop interview",
    });
  }

  async generateQuizzedCharacterDraft(
    concept: string,
    answers: CharacterQuizAnswer[],
    finalNote: string | null,
  ): Promise<CharacterSheet | null> {
    return await this.#runStreamingPayload<CharacterSheet>({
      stream: (handlers, signal) =>
        api.streamQuizzedCharacterDraft(concept, answers, finalNote, handlers, signal),
      fallback: async (signal) => {
        const response = await api.generateQuizzedCharacterDraft(
          concept,
          answers,
          finalNote,
          signal,
        );
        return response.draft;
      },
      finalKind: "character_draft",
      extract: (payload) => (payload as { draft: CharacterSheet }).draft,
      cancelLabel: "Stop draft",
    });
  }

  async finalizeCharacter(character: CharacterSheet): Promise<void> {
    await this.#run((signal) => api.finalizeCharacter(character, signal), {
      cancelLabel: "Stop finalize",
    });
  }

  async startCampaign(): Promise<void> {
    await this.#runStreaming({
      stream: (handlers, signal) => api.streamStartCampaign(handlers, signal),
      fallback: (signal) => api.startCampaign(signal),
      cancelLabel: "Stop generation",
      rollAware: false,
    });
  }

  async regenerateMessage(eventId: string): Promise<void> {
    await this.#runStreaming({
      stream: (handlers, signal) =>
        api.streamRegenerateMessage(eventId, handlers, signal),
      fallback: (signal) => api.regenerateMessage(eventId, signal),
      cancelLabel: "Stop repair",
      rollAware: true,
    });
  }

  /**
   * Single entry point for the Composer. Parses slash commands and
   * dispatches; falls back to a free-text player action.
   *
   * Returns true when the input was consumed (so the Composer can
   * clear its buffer). Returns false on a no-op (empty input).
   */
  async submit(rawText: string): Promise<boolean> {
    const parsed = parseTurn(rawText);

    switch (parsed.kind) {
      case "error":
        if (parsed.message) this.#note("error", parsed.message);
        return parsed.message !== "";
      case "help":
        this.#note("help", SLASH_HELP);
        return true;
      case "reset":
        await this.reset();
        return true;
      case "chaos":
        await this.setChaos(parsed.value);
        return true;
      case "event":
        await this.randomEvent();
        return true;
      case "scene":
        await this.sceneCheck(parsed.expected);
        return true;
      case "ask":
        await this.askYesNo(parsed.question, parsed.likelihood);
        return true;
      case "retreat":
        // We deliberately translate `/retreat` into a free-text turn
        // rather than hitting the explicit `/api/cairn/retreat`
        // endpoint. The unified turn pipeline gives us narration,
        // memory updates, and a chat receipt — three things the bare
        // deterministic endpoint doesn't produce. The planner already
        // classifies "I retreat" → RETREAT, so this is the same
        // behavior the player gets from typing it as prose.
        await this.submitTurn(buildRetreatPrompt(parsed.reason));
        return true;
      case "action":
        await this.submitTurn(parsed.text);
        return true;
    }
  }

  toggleInspector(): void {
    this.inspectorOpen = !this.inspectorOpen;
  }

  openInspector(): void {
    this.inspectorOpen = true;
  }

  dismissNote(id: string): void {
    this.notes = this.notes.filter((n) => n.id !== id);
  }

  cancelCurrentRequest(): void {
    if (!this.isLoading || this.#abortController === null) return;
    // A Stop-button mash would otherwise re-fire the backend cancel
    // POST for every click between the abort and the finally-block
    // teardown. Idempotency is fine on the backend side (the registry
    // entry has already been cancelled), but re-firing is wasteful
    // and pollutes browser devtools.
    if (this.#cancelRequested) return;
    this.#cancelRequested = true;

    // Order matters here. We fire the backend cancel BEFORE aborting
    // the local fetch:
    //   1. Aborting the fetch first would tear down the connection
    //      synchronously, which on some browsers cancels in-flight
    //      requests on the same origin during microtask draining. By
    //      kicking the cancel POST first we guarantee the backend
    //      registry sees the request_id while the connection is still
    //      live.
    //   2. The cancel POST is fire-and-forget — we don't await it. The
    //      backend's discard-only persistence contract (see
    //      `service.py::_persist_streamed_state`) means we can rely on
    //      "the server will throw away whatever it had in flight"
    //      without needing the cancel POST's response to update local
    //      state. Awaiting would just delay the UX collapse the user
    //      asked for when they hit Stop.
    //
    // We deliberately use a *fresh* AbortController for the cancel
    // POST itself rather than the one we're about to abort, otherwise
    // the cancel would race against its own teardown and we'd never
    // hit the backend.
    const requestId = this.streaming.requestId;
    if (requestId !== null) {
      void api.cancelRequest(requestId).catch(() => {
        // Swallow: the local abort below collapses the UI either way,
        // and a failed cancel POST just means the LLM keeps burning
        // tokens server-side until it would have completed anyway —
        // which is bad but not user-visible in this client.
      });
    }

    // Clear the provisional buffer up-front so the chat surface
    // collapses the in-flight bubble immediately rather than waiting
    // for the fetch teardown to round-trip through the finally block.
    // The backend discards on cancel, so there is no canonical state
    // we'd ever want to preserve from the partial stream.
    this.streaming = emptyStreamingState();

    this.#abortController.abort();
  }

  // True only while a stream is active for chat-flavored output. The
  // chat feed uses this to render a provisional DM bubble, and the
  // composer uses it to keep the cancel button labeled correctly.
  // This is exposed as a getter (rather than a duplicate $state field)
  // so there's exactly one source of truth: `streaming.active`.
  get isStreaming(): boolean {
    return this.streaming.active;
  }

  // --- internals ---

  #note(kind: ClientNote["kind"], text: string): void {
    this.notes = [
      ...this.notes,
      {
        id: `note_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
        kind,
        text,
        created_at: new Date().toISOString(),
      },
    ];
  }

  async #run(
    call: (signal: AbortSignal) => Promise<GameState>,
    options?: { cancelLabel?: string },
  ): Promise<void> {
    const next = await this.#call(call, options);
    if (next !== null) this.state = next;
  }

  // Streaming run for endpoints that mutate GameState (turn, action,
  // regenerate, campaign/start). The flow is:
  //   1. Open the NDJSON stream. Update `streaming.*` on every event.
  //   2. On `mechanics_ready` / `oracle_outcome`, pin the deterministic
  //      outcome immediately so the receipt animates while prose is
  //      still streaming.
  //   3. On `final_state`, replace `state` wholesale and clear the
  //      provisional buffer. The action_log entry produced by the
  //      backend is the canonical record — the provisional bubble is
  //      replaced, not merged.
  //   4. On any transport error indicating "stream not implemented"
  //      (404 / 405), transparently fall back to the unary endpoint.
  //      This keeps the frontend usable while the backend pass lands.
  //
  // `rollAware` mirrors the old #runWithRoll behavior: when an oracle
  // outcome is produced, animate the dice tumble before revealing the
  // narrative. With streaming, the deterministic outcome arrives
  // before the prose anyway, so we tumble between
  // `mechanics_ready` and the first `content_delta` rather than
  // blocking on a full response.
  async #runStreaming(opts: {
    stream: (handlers: StreamHandlers, signal: AbortSignal) => Promise<StreamResult>;
    fallback: (signal: AbortSignal) => Promise<GameState>;
    cancelLabel?: string;
    rollAware: boolean;
  }): Promise<void> {
    this.error = null;
    this.isLoading = true;
    this.cancelLabel = opts.cancelLabel ?? "Stop response";
    this.#abortController = new AbortController();
    this.#cancelRequested = false;
    this.streaming = { ...emptyStreamingState(), active: true };
    if (opts.rollAware) this.rollPhase = "rolling";

    const previousLength = this.state?.oracle_history.length ?? 0;
    let mechanicsArrived = false;
    let didFallback = false;

    const handlers: StreamHandlers = {
      onMeta: (event) => {
        this.streaming = {
          ...this.streaming,
          route: event.route,
          requestId: event.request_id,
        };
      },
      onMechanics: (event) => {
        this.streaming = { ...this.streaming, pendingOutcome: event.outcome };
        this.pendingOracle = event.outcome;
        mechanicsArrived = true;
        if (opts.rollAware) {
          // Tumble briefly so the receipt feels physical, then settle
          // before prose deltas start arriving.
          void this.#tumbleAfterMechanics();
        }
      },
      onOracleOutcome: (event) => {
        this.streaming = { ...this.streaming, pendingOutcome: event.outcome };
        this.pendingOracle = event.outcome;
        mechanicsArrived = true;
        if (opts.rollAware) void this.#tumbleAfterMechanics();
      },
      onThinkingDelta: (event) => {
        this.streaming = {
          ...this.streaming,
          thinking: this.streaming.thinking + event.text,
        };
      },
      onContentDelta: (event) => {
        this.streaming = {
          ...this.streaming,
          content: this.streaming.content + event.text,
        };
      },
      onFinalState: (event) => {
        this.state = event.state;
      },
      onError: (event) => {
        this.error = event.message;
        if (event.state !== null) this.state = event.state;
      },
    };

    try {
      const result = await opts.stream(handlers, this.#abortController.signal);
      if (result.kind === "aborted" && result.reason === "client") {
        if (this.#cancelRequested) {
          this.#note("info", "Stopped waiting for the current response.");
        }
      } else if (result.kind === "aborted" && result.reason === "server") {
        // Stream closed without a final event. Treat as a recoverable
        // error so the user knows the server bailed; we don't fall
        // back to the unary endpoint here because we may have already
        // mutated the action_log via deltas the backend chose to
        // commit in pieces.
        this.error = "Stream ended unexpectedly. The server may have timed out.";
      } else if (result.kind === "error") {
        // The error handler already set this.error.
      }
      // result.kind === "final" is already handled by onFinalState.
    } catch (exc) {
      if (this.#isAbortError(exc)) {
        if (this.#cancelRequested) {
          this.#note("info", "Stopped waiting for the current response.");
        }
      } else if (this.#isFallbackEligible(exc)) {
        // Backend hasn't shipped streaming for this endpoint yet —
        // run the unary path so the UI keeps working in the
        // transition window. We only fall back when we haven't yet
        // observed any stream events: if mechanics or deltas arrived,
        // the request is already in motion and re-issuing would
        // double-resolve.
        if (!mechanicsArrived && this.streaming.content === "") {
          didFallback = true;
          try {
            const next = await opts.fallback(this.#abortController.signal);
            this.state = next;
            const newOutcome =
              next.oracle_history[next.oracle_history.length - 1] ?? null;
            this.pendingOracle = newOutcome;
            const newOracleArrived = next.oracle_history.length > previousLength;
            if (newOracleArrived && opts.rollAware) {
              await this.#sleep(900);
              this.rollPhase = "settling";
              await this.#sleep(380);
            }
          } catch (fallbackExc) {
            if (this.#isAbortError(fallbackExc)) {
              if (this.#cancelRequested) {
                this.#note("info", "Stopped waiting for the current response.");
              }
            } else {
              this.error = this.#formatError(fallbackExc);
            }
          }
        } else {
          this.error = this.#formatError(exc);
        }
      } else {
        this.error = this.#formatError(exc);
      }
    } finally {
      this.#abortController = null;
      this.#cancelRequested = false;
      this.cancelLabel = null;
      this.pendingOracle = null;
      this.rollPhase = "idle";
      this.isLoading = false;
      this.streaming = emptyStreamingState();
      // `didFallback` is captured for debugging / future telemetry; we
      // intentionally don't surface it to the user. The point of the
      // fallback is that it's invisible.
      void didFallback;
    }
  }

  // Streaming run for non-state endpoints (quiz, draft). Returns the
  // typed final payload. Falls back to the unary endpoint on a 404/405
  // exactly like #runStreaming so quiz/draft generation still works
  // before the backend pass ships streaming for those routes.
  async #runStreamingPayload<TFinal>(opts: {
    stream: (handlers: StreamHandlers, signal: AbortSignal) => Promise<StreamResult>;
    fallback: (signal: AbortSignal) => Promise<TFinal>;
    finalKind: "character_quiz" | "character_draft";
    extract: (payload: unknown) => TFinal;
    cancelLabel?: string;
  }): Promise<TFinal | null> {
    this.error = null;
    this.isLoading = true;
    this.cancelLabel = opts.cancelLabel ?? "Stop response";
    this.#abortController = new AbortController();
    this.#cancelRequested = false;
    this.streaming = { ...emptyStreamingState(), active: true };

    let extracted: TFinal | null = null;
    let observedAnyEvent = false;

    const handlers: StreamHandlers = {
      onMeta: (event) => {
        observedAnyEvent = true;
        this.streaming = {
          ...this.streaming,
          route: event.route,
          requestId: event.request_id,
        };
      },
      onThinkingDelta: (event) => {
        observedAnyEvent = true;
        this.streaming = {
          ...this.streaming,
          thinking: this.streaming.thinking + event.text,
        };
      },
      onContentDelta: (event) => {
        observedAnyEvent = true;
        this.streaming = {
          ...this.streaming,
          content: this.streaming.content + event.text,
        };
      },
      onFinalPayload: (event) => {
        observedAnyEvent = true;
        if (event.kind !== opts.finalKind) {
          // The backend handed us a final_payload of a different kind
          // than this endpoint expects. Surface as an error rather
          // than silently coercing — a misrouted payload usually
          // means the route on the backend got rewired.
          this.error = `Unexpected payload kind '${event.kind}' for this request.`;
          return;
        }
        try {
          extracted = opts.extract(event.payload);
        } catch (exc) {
          this.error = this.#formatError(exc);
        }
      },
      onError: (event) => {
        observedAnyEvent = true;
        this.error = event.message;
      },
    };

    try {
      const result = await opts.stream(handlers, this.#abortController.signal);
      if (result.kind === "error") {
        this.error = result.event.message;
      } else if (result.kind === "aborted" && result.reason === "server" && !this.#cancelRequested) {
        this.error = "The request ended before a final result arrived.";
      }
    } catch (exc) {
      if (this.#isAbortError(exc)) {
        if (this.#cancelRequested) {
          this.#note("info", "Stopped waiting for the current response.");
        }
      } else if (this.#isFallbackEligible(exc) && !observedAnyEvent) {
        try {
          extracted = await opts.fallback(this.#abortController.signal);
        } catch (fallbackExc) {
          if (this.#isAbortError(fallbackExc)) {
            if (this.#cancelRequested) {
              this.#note("info", "Stopped waiting for the current response.");
            }
          } else {
            this.error = this.#formatError(fallbackExc);
          }
        }
      } else {
        this.error = this.#formatError(exc);
      }
    } finally {
      this.#abortController = null;
      this.#cancelRequested = false;
      this.cancelLabel = null;
      this.isLoading = false;
      this.streaming = emptyStreamingState();
    }
    return extracted;
  }

  async #tumbleAfterMechanics(): Promise<void> {
    // Short tumble to sell the physicality of the roll, then settle
    // back to idle so the prose stream isn't dimmed by the rolling
    // animation. We don't reset rollPhase mid-stream if the user
    // already cancelled; the finally block in #runStreaming handles
    // that case by clearing rollPhase to idle.
    await this.#sleep(700);
    if (this.rollPhase === "rolling") this.rollPhase = "settling";
    await this.#sleep(280);
    if (this.rollPhase === "settling") this.rollPhase = "idle";
  }

  // True when the transport failure is recoverable by trying the
  // unary endpoint. We only treat 404/405 as fallback-eligible — every
  // other status (500, 502, 503) is a real failure that the unary
  // endpoint will also fail, and the stream-vs-unary churn would just
  // double the bad-state surface for the user.
  #isFallbackEligible(exc: unknown): boolean {
    if (!(exc instanceof StreamTransportError)) return false;
    return exc.status === 404 || exc.status === 405;
  }

  async #runWithRoll(
    call: (signal: AbortSignal) => Promise<GameState>,
    options?: { cancelLabel?: string },
  ): Promise<void> {
    this.error = null;
    this.rollPhase = "rolling";
    this.isLoading = true;
    this.cancelLabel = options?.cancelLabel ?? "Stop response";
    this.#abortController = new AbortController();
    this.#cancelRequested = false;

    try {
      // We resolve the API call first so we have the deterministic Roll
      // results to animate toward, but we hold the narrative reveal until
      // the dice have visibly settled. Without this, the model's latency
      // would short-circuit the physical tactility we're trying to evoke.
      const previousLength = this.state?.oracle_history.length ?? 0;
      const next = await call(this.#abortController.signal);
      const newOutcome = next.oracle_history[next.oracle_history.length - 1] ?? null;
      this.pendingOracle = newOutcome;

      const newOracleArrived = next.oracle_history.length > previousLength;
      if (newOracleArrived) {
        await this.#sleep(900);
        this.rollPhase = "settling";
        await this.#sleep(380);
      }

      this.state = next;
    } catch (exc) {
      if (this.#isAbortError(exc)) {
        if (this.#cancelRequested) {
          this.#note("info", "Stopped waiting for the current response.");
        }
      } else {
        this.error = this.#formatError(exc);
      }
    } finally {
      this.#abortController = null;
      this.#cancelRequested = false;
      this.cancelLabel = null;
      this.pendingOracle = null;
      this.rollPhase = "idle";
      this.isLoading = false;
    }
  }

  async #call<T>(
    call: (signal: AbortSignal) => Promise<T>,
    options?: { cancelLabel?: string },
  ): Promise<T | null> {
    this.isLoading = true;
    this.error = null;
    this.cancelLabel = options?.cancelLabel ?? "Stop response";
    this.#abortController = new AbortController();
    this.#cancelRequested = false;

    try {
      return await call(this.#abortController.signal);
    } catch (exc) {
      if (this.#isAbortError(exc)) {
        if (this.#cancelRequested) {
          this.#note("info", "Stopped waiting for the current response.");
        }
        return null;
      }
      this.error = this.#formatError(exc);
      return null;
    } finally {
      this.#abortController = null;
      this.#cancelRequested = false;
      this.cancelLabel = null;
      this.isLoading = false;
    }
  }

  #sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  #formatError(exc: unknown): string {
    if (exc instanceof ApiError) {
      const detail = (exc.detail as { detail?: string } | undefined)?.detail;
      return detail ?? exc.message;
    }
    if (exc instanceof Error) return exc.message;
    return "Unknown error";
  }

  #isAbortError(exc: unknown): boolean {
    return exc instanceof DOMException && exc.name === "AbortError";
  }
}

export const game = new GameStore();
