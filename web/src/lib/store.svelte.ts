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
import { parseTurn, SLASH_HELP, type AcquireVerb } from "./slash";
import type { StreamHandlers, StreamResult } from "./streaming";
import type { StreamRoute } from "./streaming-types";
import type {
  CampaignEndReason,
  CharacterQuiz,
  CharacterQuizAnswer,
  CharacterSheet,
  GameState,
  Likelihood,
  OracleOutcome,
  SaveSummary,
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

/**
 * Compose the natural-language prompt sent to the turn planner for the
 * acquisition slash commands. The planner is trained on first-person
 * acquisition phrases ("I take", "I loot", "I buy", etc.), so we use
 * the verb the player typed verbatim — looting a corpse and buying at
 * a market should feel different in the resulting narration, and the
 * narrator picks up that flavor from the verb without us having to
 * smuggle it through structured fields.
 *
 * We don't append a trailing period if the body already ends with
 * sentence-terminal punctuation (`.`, `!`, `?`) so player-authored
 * sentences land verbatim. Otherwise we add one to keep the planner's
 * input grammatically tidy.
 */
function buildAcquirePrompt(verb: AcquireVerb, body: string): string {
  const cleaned = body.trim();
  // The empty-body path is rejected at the parser level, so this is a
  // defensive belt-and-suspenders fallback rather than a real branch.
  if (!cleaned) return `I ${verb} the offered item.`;
  const ending = cleaned.slice(-1);
  const needsTerminator = ending !== "." && ending !== "!" && ending !== "?";
  return `I ${verb} ${cleaned}${needsTerminator ? "." : ""}`;
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
//
// F-10 added an `explanation` kind for the OOC rules explainer. Those
// notes carry both the player's question and the LLM's answer so the
// chat surface can render them as a single OOC card (instead of two
// disjoint bubbles). They live in the same ephemeral buffer as help/
// error/info notes — reload clears them, the action log never sees
// them, and they never round-trip through `memory.json`.
export interface ClientNote {
  id: string;
  kind: "help" | "error" | "info" | "explanation";
  text: string;
  created_at: string;
  // OOC explainer-only: the player's question, preserved verbatim. We
  // store it on the note (rather than reconstructing it from the
  // adjacent player message) because OOC traffic does not become an
  // action_log player event — there's no canonical anchor to pair
  // the answer with otherwise.
  question?: string;
}

// F-12 save library state. We model the library as a discriminated
// status rather than a "ready vs not-ready" boolean because the
// app shell has three distinct splashes to render:
//   - "loading"   : we haven't yet finished the bootstrap call,
//                   so we can't tell whether to show the selector
//                   or auto-load play.
//   - "empty"     : the bootstrap call returned and there are no
//                   saves on disk — the only legal action is to
//                   start a fresh campaign.
//   - "selecting" : the player explicitly opened the save library
//                   from the system menu mid-session. We need to
//                   keep the rest of the app intact (current state,
//                   chat history) until the player picks a save,
//                   so we keep `state` populated while the splash
//                   is open.
//   - "ready"     : an active save is bound and `state` is the
//                   live `GameState` for that save. This is the
//                   normal play path.
// Modeling them as a union forces every consumer to handle the
// loading/empty branches, which we'd otherwise drift on.
export type LibraryStatus = "loading" | "empty" | "selecting" | "ready";

// F-09 cross-component scroll request. The Inspector commands the
// ChatFeed to scroll a particular event into view (oracle deep-link,
// transcript search hit). We model this as a one-shot signal with a
// rotating sequence number rather than a plain `eventId | null`
// because a sequence of clicks on the *same* eventId has to re-trigger
// the scroll/flash effect — without `seq`, Svelte's reactivity would
// see "the same value" and skip the run.
export interface ScrollRequest {
  eventId: string;
  seq: number;
}

export type InspectorSection = "threads" | "npcs";

// H-02 cross-surface continuity jump. A receipt pill can ask the
// inspector to open a specific section and focus one referenced entity.
// The rotating seq mirrors ScrollRequest so repeated clicks on the same
// pill still re-trigger the drawer-open / highlight effect.
export interface InspectorFocusRequest {
  section: InspectorSection;
  entityId: string | null;
  seq: number;
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

  // F-09 history-browser scroll target. Set by `requestScrollTo` and
  // cleared once the ChatFeed has consumed it. The seq counter
  // rotates so identical-eventId requests still fire the scroll/flash
  // effect — see the ScrollRequest type doc.
  scrollRequest: ScrollRequest | null = $state(null);
  #scrollSeq = 0;
  inspectorFocusRequest: InspectorFocusRequest | null = $state(null);
  #inspectorFocusSeq = 0;
  #abortController: AbortController | null = null;
  #cancelRequested = false;

  // F-12 Save library --------------------------------------------------------
  //
  // `library` is the canonical list of saves and `activeSaveId` is the
  // one bound to `state`. We deliberately keep `library` flat at the
  // store level (not nested behind another object) because the StatusStrip
  // hamburger menu and the SaveLibrary splash both subscribe to it
  // independently — flat fields keep Svelte 5's reactivity cheap
  // without forcing both consumers to share a derived selector.
  library: SaveSummary[] = $state([]);
  activeSaveId: string | null = $state(null);
  libraryStatus: LibraryStatus = $state("loading");
  // Distinct from `state.error`: a library failure (bootstrap, switch)
  // can happen before any save is bound, so a top-level surface needs
  // its own error sink. The splash screen renders this verbatim.
  libraryError: string | null = $state(null);

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

  /**
   * F-12 startup bootstrap. Calls `/api/library/bootstrap`, then either
   *   (a) auto-loads the active save's `GameState` and transitions to
   *       `libraryStatus: "ready"` — this is the steady-state launch
   *       experience the user asked for ("if a campaign exists, just
   *       load it"); or
   *   (b) sets `libraryStatus: "empty"` and lets the SaveLibrary splash
   *       render the "begin your first campaign" prompt.
   *
   * We intentionally swallow `getState` errors during auto-load by
   * surfacing them on `state.error` rather than `libraryError`: once an
   * active save is selected, the library was bootstrapped successfully,
   * and a `getState` failure is a normal play-time error (network, etc.)
   * the App-level error rail already knows how to render. Bootstrap
   * itself only fails the splash if the *library manifest* call fails.
   */
  async bootstrap(): Promise<void> {
    this.libraryStatus = "loading";
    this.libraryError = null;
    try {
      const response = await api.bootstrapLibrary();
      this.library = response.saves;
      this.activeSaveId = response.active_save_id;
      if (response.active_save_id === null) {
        this.libraryStatus = "empty";
        this.state = null;
        return;
      }
      await this.#run((signal) => api.getState(signal));
      this.libraryStatus = "ready";
    } catch (exc) {
      this.libraryStatus = "empty";
      this.libraryError = this.#formatError(exc);
    }
  }

  /**
   * F-12 create a new save slot and (by default) immediately select it.
   *
   * Why we always reset client-side ephemera on a save switch:
   *   `notes`, the provisional streaming buffer, and the scroll request
   *   are all keyed off the *current save's* event stream. Carrying any
   *   of them across a switch would mean the new campaign opens with
   *   stale OOC bubbles, mid-stream artifacts, or scroll requests that
   *   point at event ids that no longer exist. Clearing here keeps the
   *   switch atomic — the new save's `GameState` is the only thing the
   *   chat surface reads, and there's nothing left over to filter out.
   *
   * `select=false` exists for an eventual "stage a save without leaving
   * the current campaign" UX (we don't ship that surface in v1, but the
   * backend already supports it and exposing the parameter keeps the
   * call sites uniform).
   */
  async createSave(select: boolean = true): Promise<string | null> {
    this.libraryError = null;
    try {
      const beforeIds = new Set(this.library.map((entry) => entry.save_id));
      const response = await api.createSave(select);
      this.library = response.saves;
      this.activeSaveId = response.active_save_id;
      const created = response.saves.find((entry) => !beforeIds.has(entry.save_id)) ?? null;
      if (select) {
        this.#resetEphemera();
        await this.#run((signal) => api.getState(signal));
        this.libraryStatus = "ready";
      }
      return created?.save_id ?? null;
    } catch (exc) {
      this.libraryError = this.#formatError(exc);
      return null;
    }
  }

  /**
   * F-12 switch the active save. The backend rejects this with 409
   * while a streamed request is in flight (see
   * `_guard_save_library_idle`), so we don't try to be clever about
   * cancelling first — letting the player see "Cannot switch saves
   * while a request is still in flight." is the cleaner contract than
   * silently aborting their current turn under them.
   *
   * On success we wholesale replace `state` and clear ephemera, the
   * same way `createSave` does.
   */
  async selectSave(saveId: string): Promise<void> {
    if (saveId === this.activeSaveId && this.state !== null) {
      // Selecting the already-active save is a no-op rather than a
      // round-trip — the splash uses this path when the player picks
      // their current campaign by mistake.
      this.libraryStatus = "ready";
      return;
    }
    this.libraryError = null;
    try {
      const response = await api.selectSave(saveId);
      this.library = response.saves;
      this.activeSaveId = response.active_save_id;
      this.#resetEphemera();
      await this.#run((signal) => api.getState(signal));
      this.libraryStatus = "ready";
    } catch (exc) {
      this.libraryError = this.#formatError(exc);
    }
  }

  /**
   * F-12 open the save library splash mid-session. We keep `state`
   * populated so that hitting "Cancel" (or hardware back) returns to
   * the live campaign without a refetch, and so the splash can show
   * the active save's "you are here" cue without re-asking the server.
   */
  openLibrary(): void {
    if (this.libraryStatus === "ready") {
      this.libraryStatus = "selecting";
    }
    // Refresh the summaries fire-and-forget so the splash isn't stale
    // (a long-running session may have advanced the active save's
    // scene/encounter counters that the cards display on hover).
    void api
      .bootstrapLibrary()
      .then((response) => {
        this.library = response.saves;
        if (response.active_save_id !== null) {
          this.activeSaveId = response.active_save_id;
        }
      })
      .catch(() => {
        // Stale data is acceptable — the splash still works against
        // whatever we last loaded.
      });
  }

  /**
   * F-12 close the splash without switching. Only valid when an active
   * save is loaded; the empty-library splash is a hard stop until a
   * save is created.
   */
  closeLibrary(): void {
    if (this.activeSaveId !== null && this.state !== null) {
      this.libraryStatus = "ready";
    }
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

  /**
   * B-02 persist campaign directives (OOC steering surface).
   *
   * Routed through the same `#run` plumbing as every other state
   * mutation so the loading shimmer / cancel button behave
   * consistently — the backend swap of "did the action_log gain
   * an entry?" is invisible to the call site, which is the right
   * level of abstraction for the Inspector editor: it just wants
   * to commit and trust that the next render sees the new
   * directives.
   */
  async updateDirectives(worldGuidance: string, playGuidance: string): Promise<void> {
    await this.#run((signal) =>
      api.updateDirectives(worldGuidance, playGuidance, signal),
    );
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

  /**
   * F-10 OOC rules explainer. Streams an explanation through the
   * `final_payload` channel and lands the answer as an ephemeral
   * `ClientNote` (kind `"explanation"`) — the question and answer
   * stay on the same note so the chat surface can render a single
   * OOC card rather than two disjoint bubbles.
   *
   * Why we deliberately do NOT mutate `state.action_log`:
   *   The OOC channel is non-canonical by contract. Persisting the
   *   exchange would mean future memory rebuilds and narrative
   *   prompts include the explainer's prose, which would slowly
   *   poison the in-fiction voice. Keeping the record client-side
   *   matches the backend's `_load_state_readonly` guarantee and
   *   makes "ephemeral" a UX promise we can verify (reload clears).
   *
   * Streaming UI: while in flight, the ChatFeed renders an OOC
   * provisional bubble keyed off `streaming.route === "explanation"`.
   * On stream completion the provisional bubble is replaced by the
   * persisted ClientNote in one tick — the question is captured on
   * the note up-front so the visual identity (Q + A pair) is stable
   * across the swap.
   */
  async explain(question: string): Promise<void> {
    const cleaned = question.trim();
    if (!cleaned) return;
    const answer = await this.#runStreamingPayload<string>({
      stream: (handlers, signal) => api.streamExplain(cleaned, handlers, signal),
      fallback: async (signal) => {
        const response = await api.explain(cleaned, signal);
        return response.answer;
      },
      finalKind: "explanation",
      extract: (payload) => (payload as { answer: string }).answer,
      cancelLabel: "Stop explaining",
    });
    if (answer === null) return;
    const trimmed = answer.trim();
    if (trimmed === "") return;
    this.#explanationNote(cleaned, trimmed);
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

  /**
   * F-06 explicit terminal close. We pass `null` for an empty
   * summary so the backend's deterministic-default branch fires —
   * that keeps the rule "End-Banner always has prose to render"
   * enforced server-side, which means new clients can't accidentally
   * push an empty summary into the canon. The backend rejects this
   * call with a 409 if the encounter is still active or if death
   * is requested while the character is alive; we surface the
   * detail string so the player sees *why* the close was refused.
   */
  async endCampaign(reason: CampaignEndReason, summary: string): Promise<void> {
    const trimmed = summary.trim();
    const payloadSummary = trimmed === "" ? null : trimmed;
    await this.#run(
      (signal) => api.endCampaign(reason, payloadSummary, signal),
      { cancelLabel: "Stop close" },
    );
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
      case "acquire":
        // Same funnel-through-the-planner reasoning as /retreat. The
        // explicit `/api/cairn/acquire` endpoint exists for callers
        // that want a deterministic primitive, but the chat-first
        // invariant says every player turn should produce narration
        // and memory updates. The planner classifies "I take/loot/buy"
        // as ACQUIRE_ITEM, so the slash and natural-language paths
        // converge on the exact same backend pipeline.
        await this.submitTurn(buildAcquirePrompt(parsed.verb, parsed.body));
        return true;
      case "explain":
        // F-10 OOC explainer. The question never round-trips through
        // the planner — the explainer is a separate, read-only LLM
        // path that intentionally does not mutate canon. Routing
        // through `submitTurn` would persist the exchange in
        // `action_log` and contaminate future memory rebuilds, which
        // is exactly what we don't want.
        await this.explain(parsed.question);
        return true;
      case "end":
        // F-06 terminal close. Unlike /retreat and /acquire, this
        // does *not* funnel through the planner — terminal-state
        // transitions are a lifecycle op, not an in-fiction action,
        // so we hit the dedicated `/campaign/end` endpoint directly
        // and let the End-Banner read off the resulting state. The
        // backend writes a system event for the close so the chat
        // archive still has a closing beat.
        await this.endCampaign(parsed.reason, parsed.summary);
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

  /**
   * F-09 cross-component scroll. The Inspector calls this when the
   * player clicks an oracle row's "Show in chat" link or a search hit
   * — `eventId` must be the canonical event id from `action_log` (or
   * the synthesized `opening_<state-id>` for the very first DM beat).
   * We bump the sequence counter on every call so back-to-back
   * requests for the same eventId still re-trigger the feed's
   * scroll/flash effect.
   *
   * Closing the Inspector is the caller's choice, not this method's:
   * "scroll to a row" is sometimes paired with "and keep the panel
   * open so I can scan more results", and sometimes paired with
   * "close the panel out of my way". The signal stays orthogonal.
   */
  requestScrollTo(eventId: string): void {
    this.#scrollSeq += 1;
    this.scrollRequest = { eventId, seq: this.#scrollSeq };
  }

  /**
   * Called by the ChatFeed once it has applied the scroll. Clears
   * the request so a re-render of the feed (e.g. after a stream
   * finalizes) doesn't replay the scroll a second time.
   */
  consumeScrollRequest(): void {
    this.scrollRequest = null;
  }

  /**
   * H-02 receipt-link navigation. Opens the Inspector and asks it to
   * reveal a specific section/entity. This intentionally stays parallel
   * to `requestScrollTo` instead of overloading it — the chat feed and
   * the inspector solve different navigation problems.
   */
  requestInspectorFocus(section: InspectorSection, entityId: string | null = null): void {
    this.#inspectorFocusSeq += 1;
    this.inspectorOpen = true;
    this.inspectorFocusRequest = {
      section,
      entityId,
      seq: this.#inspectorFocusSeq,
    };
  }

  consumeInspectorFocusRequest(): void {
    this.inspectorFocusRequest = null;
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

  /**
   * F-12 clear every client-only buffer that was scoped to the
   * previous save. Called from `createSave` and `selectSave` on the
   * happy path; deliberately *not* called on bootstrap failure (the
   * splash needs to keep its `libraryError` visible).
   *
   * We don't touch `inspectorOpen` because the player's preference for
   * having the inspector open is a UX setting, not save-scoped — if
   * they had it open in their last save, it stays open in the next.
   */
  #resetEphemera(): void {
    this.notes = [];
    this.error = null;
    this.scrollRequest = null;
    this.inspectorFocusRequest = null;
    this.streaming = emptyStreamingState();
    this.pendingOracle = null;
    this.rollPhase = "idle";
  }

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

  // F-10: separate helper because explanation notes carry both the
  // question and answer. We could overload `#note(...)` instead, but
  // that would mean every other call site has to remember to leave
  // the question undefined; a focused helper keeps the OOC shape
  // self-documenting at the call site.
  #explanationNote(question: string, answer: string): void {
    this.notes = [
      ...this.notes,
      {
        id: `note_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
        kind: "explanation",
        text: answer,
        question,
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
    finalKind: "character_quiz" | "character_draft" | "explanation";
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
