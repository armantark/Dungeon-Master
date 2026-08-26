import { api, StreamTransportError } from "../lib/api";
import type { GameState, OracleOutcome } from "../lib/types";
import { createClientNote, type ClientNote } from "./play";
import {
  clearStreamResume,
  loadStreamResume,
  saveStreamResume,
  updateStreamResumeStages,
} from "./save/stream-resume";
import type { StreamRoute } from "./stream/streaming-types";
import type { StageProgress } from "./stream-runner";
import {
  applyStageEvent,
  applyStateTerminal,
  payloadTerminal,
  stateTerminal,
} from "./stream-runner";
import type { StreamHandlers, StreamResult } from "./stream/streaming";
import { formatRuntimeError } from "./runtime";

export type RollPhase = "idle" | "rolling" | "settling";

export interface StreamingState {
  active: boolean;
  route: StreamRoute | null;
  requestId: string | null;
  content: string;
  thinking: string;
  pendingOutcome: OracleOutcome | null;
  resuming: boolean;
  stages: StageProgress[];
}

export function emptyStreamingState(): StreamingState {
  return {
    active: false,
    route: null,
    requestId: null,
    content: "",
    thinking: "",
    pendingOutcome: null,
    resuming: false,
    stages: [],
  };
}

interface StreamingStateOwner {
  state: GameState | null;
  isLoading: boolean;
  error: string | null;
  rollPhase: RollPhase;
  pendingOracle: OracleOutcome | null;
  cancelLabel: string | null;
  streaming: StreamingState;
  notes: ClientNote[];
  activeSaveId: string | null;
}

export interface StateStreamRequest {
  stream: (handlers: StreamHandlers, signal: AbortSignal) => Promise<StreamResult>;
  fallback: (signal: AbortSignal) => Promise<GameState>;
  cancelLabel?: string;
  rollAware: boolean;
}

export interface PayloadStreamRequest<TFinal> {
  stream: (handlers: StreamHandlers, signal: AbortSignal) => Promise<StreamResult>;
  fallback: (signal: AbortSignal) => Promise<TFinal>;
  finalKind: "character_quiz" | "character_draft" | "explanation";
  extract: (payload: unknown) => TFinal;
  cancelLabel?: string;
}

/** Owns cancellation, stream projection, resume persistence, and unary fallback. */
export class StreamWorkflow {
  readonly #owner: StreamingStateOwner;
  #abortController: AbortController | null = null;
  #cancelRequested = false;

  constructor(owner: StreamingStateOwner) {
    this.#owner = owner;
  }

  cancel(): void {
    const owner = this.#owner;
    if (!owner.isLoading || this.#abortController === null || this.#cancelRequested) return;
    this.#cancelRequested = true;
    const requestId = owner.streaming.requestId;
    if (requestId !== null) void api.cancelRequest(requestId).catch(() => undefined);
    owner.streaming = emptyStreamingState();
    this.#abortController.abort();
  }

  async call<T>(
    request: (signal: AbortSignal) => Promise<T>,
    options?: { cancelLabel?: string },
  ): Promise<T | null> {
    const owner = this.#owner;
    owner.isLoading = true;
    owner.error = null;
    owner.cancelLabel = options?.cancelLabel ?? "Stop response";
    const signal = this.#beginRequest();
    try {
      return await request(signal);
    } catch (error) {
      if (this.#isAbortError(error)) {
        if (this.#cancelRequested) this.#noteStopped();
        return null;
      }
      owner.error = formatRuntimeError(error);
      return null;
    } finally {
      this.#finishRequest();
      owner.cancelLabel = null;
      owner.isLoading = false;
    }
  }

  async runState(
    request: (signal: AbortSignal) => Promise<GameState>,
    options?: { cancelLabel?: string },
  ): Promise<void> {
    const next = await this.call(request, options);
    if (next !== null) this.#owner.state = next;
  }

  async runWithRoll(
    request: (signal: AbortSignal) => Promise<GameState>,
    options?: { cancelLabel?: string },
  ): Promise<void> {
    const owner = this.#owner;
    owner.error = null;
    owner.rollPhase = "rolling";
    owner.isLoading = true;
    owner.cancelLabel = options?.cancelLabel ?? "Stop response";
    const signal = this.#beginRequest();
    try {
      const previousLength = owner.state?.oracle_history.length ?? 0;
      const next = await request(signal);
      owner.pendingOracle = next.oracle_history[next.oracle_history.length - 1] ?? null;
      if (next.oracle_history.length > previousLength) {
        await this.#sleep(900);
        owner.rollPhase = "settling";
        await this.#sleep(380);
      }
      owner.state = next;
    } catch (error) {
      if (this.#isAbortError(error)) {
        if (this.#cancelRequested) this.#noteStopped();
      } else {
        owner.error = formatRuntimeError(error);
      }
    } finally {
      this.#finishRequest();
      owner.cancelLabel = null;
      owner.pendingOracle = null;
      owner.rollPhase = "idle";
      owner.isLoading = false;
    }
  }

  async tryResume(): Promise<void> {
    const owner = this.#owner;
    const descriptor = loadStreamResume(owner.activeSaveId);
    if (descriptor === null || owner.streaming.active || owner.isLoading) return;

    const stages: StageProgress[] = (descriptor.stages ?? []).map((stage) => ({
      stageId: stage.stageId,
      label: stage.label,
      status: stage.status as StageProgress["status"],
      order: stage.order,
      startedAt: stage.startedAt,
      completedAt: stage.completedAt,
    }));
    owner.streaming = { ...emptyStreamingState(), active: true, resuming: true, stages };
    owner.error = null;
    owner.isLoading = true;
    owner.cancelLabel = "Stop response";
    const signal = this.#beginRequest();
    let observedTerminal = false;
    const handlers = this.#stateHandlers(false);
    try {
      try {
        const result = await api.reattachStream(descriptor.request_id, handlers, signal);
        observedTerminal = applyStateTerminal(stateTerminal(result), {
          replaceState: (state) => {
            owner.state = state;
          },
          reportError: (message) => {
            owner.error = message;
          },
        });
      } catch (error) {
        if (this.#isAbortError(error)) {
          // A remount can tear down a bootstrap resume without user-visible failure.
        } else if (
          error instanceof StreamTransportError &&
          (error.status === 404 || error.status === 409)
        ) {
          observedTerminal = true;
        } else {
          owner.error = formatRuntimeError(error);
          observedTerminal = true;
        }
      }
      if (observedTerminal) clearStreamResume(owner.activeSaveId);
    } finally {
      this.#finishRequest();
      owner.cancelLabel = null;
      owner.pendingOracle = null;
      owner.isLoading = false;
      owner.streaming = emptyStreamingState();
    }
  }

  async runStateStream(options: StateStreamRequest): Promise<void> {
    const owner = this.#owner;
    owner.error = null;
    owner.isLoading = true;
    owner.cancelLabel = options.cancelLabel ?? "Stop response";
    owner.streaming = { ...emptyStreamingState(), active: true };
    if (options.rollAware) owner.rollPhase = "rolling";
    const signal = this.#beginRequest();
    const previousLength = owner.state?.oracle_history.length ?? 0;
    let mechanicsArrived = false;
    let didFallback = false;
    let observedTerminal = false;
    const handlers = this.#stateHandlers(options.rollAware, () => {
      mechanicsArrived = true;
    });

    try {
      const result = await options.stream(handlers, signal);
      const terminal = stateTerminal(result);
      observedTerminal = applyStateTerminal(terminal, {
        replaceState: (state) => {
          owner.state = state;
        },
        reportError: (message) => {
          owner.error = message;
        },
      });
      if (terminal.kind === "aborted" && terminal.reason === "client") {
        if (this.#cancelRequested) this.#noteStopped();
      } else if (terminal.kind === "aborted" && terminal.reason === "server") {
        owner.error = "Stream ended unexpectedly. The server may have timed out.";
      }
    } catch (error) {
      if (this.#isAbortError(error)) {
        if (this.#cancelRequested) this.#noteStopped();
      } else if (
        this.#isFallbackEligible(error) &&
        !mechanicsArrived &&
        owner.streaming.content === ""
      ) {
        didFallback = true;
        try {
          const next = await options.fallback(signal);
          owner.state = next;
          owner.pendingOracle = next.oracle_history[next.oracle_history.length - 1] ?? null;
          if (next.oracle_history.length > previousLength && options.rollAware) {
            await this.#sleep(900);
            owner.rollPhase = "settling";
            await this.#sleep(380);
          }
        } catch (fallbackError) {
          if (this.#isAbortError(fallbackError)) {
            if (this.#cancelRequested) this.#noteStopped();
          } else {
            owner.error = formatRuntimeError(fallbackError);
          }
        }
      } else {
        owner.error = formatRuntimeError(error);
      }
    } finally {
      if (observedTerminal || didFallback || this.#cancelRequested) {
        clearStreamResume(owner.activeSaveId);
      }
      this.#finishRequest();
      owner.cancelLabel = null;
      owner.pendingOracle = null;
      owner.rollPhase = "idle";
      owner.isLoading = false;
      owner.streaming = emptyStreamingState();
    }
  }

  async runPayloadStream<TFinal>(options: PayloadStreamRequest<TFinal>): Promise<TFinal | null> {
    const owner = this.#owner;
    owner.error = null;
    owner.isLoading = true;
    owner.cancelLabel = options.cancelLabel ?? "Stop response";
    owner.streaming = { ...emptyStreamingState(), active: true };
    const signal = this.#beginRequest();
    let extracted: TFinal | null = null;
    let observedAnyEvent = false;
    const handlers = this.#payloadHandlers(() => {
      observedAnyEvent = true;
    });

    try {
      const result = await options.stream(handlers, signal);
      const terminal = payloadTerminal(result);
      if (terminal.kind === "payload") {
        if (terminal.event.kind !== options.finalKind) {
          owner.error = `Unexpected payload kind '${terminal.event.kind}' for this request.`;
        } else {
          try {
            extracted = options.extract(terminal.event.payload);
          } catch (error) {
            owner.error = formatRuntimeError(error);
          }
        }
      } else if (terminal.kind === "error") {
        owner.error = terminal.event.message;
      } else if (terminal.reason === "server" && !this.#cancelRequested) {
        owner.error = "The request ended before a final result arrived.";
      }
    } catch (error) {
      if (this.#isAbortError(error)) {
        if (this.#cancelRequested) this.#noteStopped();
      } else if (this.#isFallbackEligible(error) && !observedAnyEvent) {
        try {
          extracted = await options.fallback(signal);
        } catch (fallbackError) {
          if (this.#isAbortError(fallbackError)) {
            if (this.#cancelRequested) this.#noteStopped();
          } else {
            owner.error = formatRuntimeError(fallbackError);
          }
        }
      } else {
        owner.error = formatRuntimeError(error);
      }
    } finally {
      this.#finishRequest();
      owner.cancelLabel = null;
      owner.isLoading = false;
      owner.streaming = emptyStreamingState();
    }
    return extracted;
  }

  #stateHandlers(rollAware: boolean, onMechanics?: () => void): StreamHandlers {
    const owner = this.#owner;
    return {
      onMeta: (event) => {
        owner.streaming = { ...owner.streaming, route: event.route, requestId: event.request_id };
        if (!owner.streaming.resuming) {
          saveStreamResume(owner.activeSaveId, {
            request_id: event.request_id,
            route: event.route,
            started_at: new Date().toISOString(),
          });
        }
      },
      onStage: (event) => {
        const stages = applyStageEvent(owner.streaming.stages, event);
        owner.streaming = { ...owner.streaming, stages };
        updateStreamResumeStages(owner.activeSaveId, stages);
      },
      onMechanics: (event) => {
        owner.streaming = { ...owner.streaming, pendingOutcome: event.outcome };
        owner.pendingOracle = event.outcome;
        onMechanics?.();
        if (rollAware) void this.#tumbleAfterMechanics();
      },
      onOracleOutcome: (event) => {
        owner.streaming = { ...owner.streaming, pendingOutcome: event.outcome };
        owner.pendingOracle = event.outcome;
        onMechanics?.();
        if (rollAware) void this.#tumbleAfterMechanics();
      },
      onThinkingDelta: (event) => {
        owner.streaming = { ...owner.streaming, thinking: owner.streaming.thinking + event.text };
      },
      onContentDelta: (event) => {
        owner.streaming = { ...owner.streaming, content: owner.streaming.content + event.text };
      },
    };
  }

  #payloadHandlers(onEvent: () => void): StreamHandlers {
    const owner = this.#owner;
    return {
      onMeta: (event) => {
        onEvent();
        owner.streaming = { ...owner.streaming, route: event.route, requestId: event.request_id };
      },
      onStage: (event) => {
        onEvent();
        owner.streaming = {
          ...owner.streaming,
          stages: applyStageEvent(owner.streaming.stages, event),
        };
      },
      onThinkingDelta: (event) => {
        onEvent();
        owner.streaming = { ...owner.streaming, thinking: owner.streaming.thinking + event.text };
      },
      onContentDelta: (event) => {
        onEvent();
        owner.streaming = { ...owner.streaming, content: owner.streaming.content + event.text };
      },
    };
  }

  #beginRequest(): AbortSignal {
    this.#abortController = new AbortController();
    this.#cancelRequested = false;
    return this.#abortController.signal;
  }

  #finishRequest(): void {
    this.#abortController = null;
    this.#cancelRequested = false;
  }

  async #tumbleAfterMechanics(): Promise<void> {
    await this.#sleep(700);
    if (this.#owner.rollPhase === "rolling") this.#owner.rollPhase = "settling";
    await this.#sleep(280);
    if (this.#owner.rollPhase === "settling") this.#owner.rollPhase = "idle";
  }

  #noteStopped(): void {
    this.#owner.notes = [
      ...this.#owner.notes,
      createClientNote("info", "Stopped waiting for the current response."),
    ];
  }

  #isFallbackEligible(error: unknown): boolean {
    return error instanceof StreamTransportError && (error.status === 404 || error.status === 405);
  }

  #isAbortError(error: unknown): boolean {
    return error instanceof DOMException && error.name === "AbortError";
  }

  #sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }
}
