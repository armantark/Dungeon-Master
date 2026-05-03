// Svelte 5 runes-based store for the entire client.
//
// Why a single store instead of one-store-per-feature:
// - The backend always returns the whole GameState, so the natural unit of
//   reactivity is "the whole game". Splitting would introduce cross-store
//   ordering bugs (e.g. "did the chaos factor update before the action log?").
// - The dice-tumble animation needs to know about pending oracle calls, so
//   the latest pending OracleOutcome and the in-flight request live in the
//   same state object as the persisted state.

import { api, ApiError } from "./api";
import { parseTurn, SLASH_HELP } from "./slash";
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
    // and just show the loading shimmer.
    await this.#run((signal) => api.submitAction(action, signal), {
      cancelLabel: "Stop response",
    });
  }

  async submitTurn(text: string): Promise<void> {
    // Natural chat may or may not roll; the backend router decides. Use the
    // roll-aware path so receipts animate when the routed turn creates an
    // oracle outcome, while pure narration still resolves normally.
    await this.#runWithRoll((signal) => api.submitTurn(text, signal), {
      cancelLabel: "Stop response",
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
    const response = await this.#call(
      (signal) => api.generateCharacterDraft(mode, prompt, template, signal),
      { cancelLabel: "Stop draft" },
    );
    return response?.draft ?? null;
  }

  async generateCharacterQuiz(concept: string): Promise<CharacterQuiz | null> {
    const response = await this.#call(
      (signal) => api.generateCharacterQuiz(concept, signal),
      { cancelLabel: "Stop interview" },
    );
    return response?.quiz ?? null;
  }

  async generateQuizzedCharacterDraft(
    concept: string,
    answers: CharacterQuizAnswer[],
    finalNote: string | null,
  ): Promise<CharacterSheet | null> {
    const response = await this.#call(
      (signal) => api.generateQuizzedCharacterDraft(concept, answers, finalNote, signal),
      { cancelLabel: "Stop draft" },
    );
    return response?.draft ?? null;
  }

  async finalizeCharacter(character: CharacterSheet): Promise<void> {
    await this.#run((signal) => api.finalizeCharacter(character, signal), {
      cancelLabel: "Stop finalize",
    });
  }

  async startCampaign(): Promise<void> {
    await this.#run((signal) => api.startCampaign(signal), {
      cancelLabel: "Stop generation",
    });
  }

  async regenerateMessage(eventId: string): Promise<void> {
    await this.#run((signal) => api.regenerateMessage(eventId, signal), {
      cancelLabel: "Stop repair",
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
    this.#cancelRequested = true;
    this.#abortController.abort();
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
