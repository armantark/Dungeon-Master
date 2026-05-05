// Thin fetch wrapper around the FastAPI backend.
//
// All endpoints return the entire `GameState`, so the frontend never has
// to reconcile partial diffs - the most recent response is the truth.
// Keeping this in one file means there's exactly one place to edit when
// auth/headers/logging requirements change.

import {
  consumeStream,
  StreamTransportError,
  type StreamHandlers,
  type StreamResult,
} from "./streaming";
import type { StreamEvent } from "./streaming-types";
import type {
  CharacterDraftResponse,
  CharacterQuizAnswer,
  CharacterQuizResponse,
  CharacterSheet,
  CharacterTemplatesResponse,
  GameState,
  Likelihood,
} from "./types";

const BASE = "/api";

class ApiError extends Error {
  public readonly status: number;
  public readonly detail: unknown;

  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : `Request failed (${status})`);
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(
  path: string,
  init?: RequestInit & { json?: unknown },
): Promise<T> {
  const headers = new Headers(init?.headers);
  let body: BodyInit | undefined;

  if (init?.json !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(init.json);
  }

  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers,
    body,
  });

  if (!response.ok) {
    let detail: unknown = response.statusText;
    try {
      detail = await response.json();
    } catch {
      // fallthrough to status-text detail
    }
    throw new ApiError(response.status, detail);
  }

  return (await response.json()) as T;
}

export const api = {
  health: (signal?: AbortSignal): Promise<{ status: string }> => request("/health", { signal }),

  getState: (signal?: AbortSignal): Promise<GameState> => request("/state", { signal }),

  getCharacterTemplates: (signal?: AbortSignal): Promise<CharacterTemplatesResponse> =>
    request("/character/templates", { signal }),

  generateCharacterDraft: (
    mode: "scratch" | "template",
    prompt?: string,
    template?: CharacterSheet,
    signal?: AbortSignal,
  ): Promise<CharacterDraftResponse> =>
    request("/character/draft", {
      method: "POST",
      signal,
      json: { mode, prompt, template },
    }),

  generateCharacterQuiz: (
    concept: string,
    signal?: AbortSignal,
  ): Promise<CharacterQuizResponse> =>
    request("/character/quiz", {
      method: "POST",
      signal,
      json: { concept },
    }),

  generateQuizzedCharacterDraft: (
    concept: string,
    answers: CharacterQuizAnswer[],
    finalNote: string | null,
    signal?: AbortSignal,
  ): Promise<CharacterDraftResponse> =>
    request("/character/draft/quizzed", {
      method: "POST",
      signal,
      json: { concept, answers, final_note: finalNote },
    }),

  finalizeCharacter: (character: CharacterSheet, signal?: AbortSignal): Promise<GameState> =>
    request("/character/finalize", {
      method: "POST",
      signal,
      json: { character },
    }),

  startCampaign: (signal?: AbortSignal): Promise<GameState> =>
    request("/campaign/start", { method: "POST", signal }),

  reset: (signal?: AbortSignal): Promise<GameState> =>
    request("/state/reset", { method: "POST", signal }),

  setChaos: (value: number, signal?: AbortSignal): Promise<GameState> =>
    request("/state/chaos", { method: "POST", signal, json: { value } }),

  updateNotes: (
    setting_notes: string,
    player_notes: string,
    signal?: AbortSignal,
  ): Promise<GameState> =>
    request("/state/notes", {
      method: "POST",
      signal,
      json: { setting_notes, player_notes },
    }),

  askYesNo: (
    question: string,
    likelihood: Likelihood,
    signal?: AbortSignal,
  ): Promise<GameState> =>
    request("/oracle/yes-no", {
      method: "POST",
      signal,
      json: { question, likelihood },
    }),

  randomEvent: (signal?: AbortSignal): Promise<GameState> =>
    request("/oracle/random-event", { method: "POST", signal }),

  sceneCheck: (expected_scene: string, signal?: AbortSignal): Promise<GameState> =>
    request("/oracle/scene-check", {
      method: "POST",
      signal,
      json: { expected_scene },
    }),

  submitAction: (action: string, signal?: AbortSignal): Promise<GameState> =>
    request("/action", { method: "POST", signal, json: { action } }),

  submitTurn: (text: string, signal?: AbortSignal): Promise<GameState> =>
    request("/turn", { method: "POST", signal, json: { text } }),

  regenerateMessage: (eventId: string, signal?: AbortSignal): Promise<GameState> =>
    request(`/messages/${eventId}/regenerate`, { method: "POST", signal }),

  // Best-effort server-side cancellation for an in-flight streamed request.
  //
  // Why fire-and-forget at the call site rather than awaited:
  //   The frontend invokes this from `cancelCurrentRequest`, which also
  //   aborts the local fetch. The abort already collapses the UI; the
  //   only thing the backend POST adds is "stop the LLM from spending
  //   more tokens on a turn we'll discard." We don't want a transient
  //   network blip on the cancel POST to leave the user staring at a
  //   spinning Stop button. Returning the boolean lets callers log /
  //   surface telemetry if they want, but the store deliberately
  //   ignores the resolution.
  //
  // The backend's contract is that an unknown request_id (race: the
  // request finished before the cancel landed) returns
  // `{cancelled: false}` rather than 404, so we don't have to
  // distinguish "already done" from "actually cancelled" at the call
  // site.
  cancelRequest: (
    requestId: string,
    signal?: AbortSignal,
  ): Promise<{ cancelled: boolean }> =>
    request(`/requests/${encodeURIComponent(requestId)}/cancel`, {
      method: "POST",
      signal,
    }),

  // --- Streaming variants ------------------------------------------------
  //
  // These call the *streaming* version of the same endpoints. The
  // backend pass adds NDJSON streaming for every model-authored route;
  // until that lands, these methods will receive a transport error and
  // the store falls back to the non-streaming path. The fallback is in
  // store.svelte.ts, not here, because the API layer should only
  // describe the contract, not branch on its availability.
  //
  // Why mirror every endpoint instead of one generic streamer:
  //   - The path/body shape varies per endpoint. Generic streamers
  //     hide that and force callers to remember which fields go in.
  //   - tsc enforces the body type per endpoint so a typo in
  //     `concept` (quiz) vs `text` (turn) surfaces here, not at runtime.
  //   - The streaming `final_*` payload type is endpoint-specific;
  //     consuming it generically would erase the type at the call site.

  streamSubmitTurn: (
    text: string,
    handlers: StreamHandlers,
    signal?: AbortSignal,
  ): Promise<StreamResult<StreamEvent>> =>
    consumeStream(`${BASE}/turn/stream`, handlers, { signal, json: { text } }),

  streamSubmitAction: (
    action: string,
    handlers: StreamHandlers,
    signal?: AbortSignal,
  ): Promise<StreamResult<StreamEvent>> =>
    consumeStream(`${BASE}/action/stream`, handlers, { signal, json: { action } }),

  streamRegenerateMessage: (
    eventId: string,
    handlers: StreamHandlers,
    signal?: AbortSignal,
  ): Promise<StreamResult<StreamEvent>> =>
    consumeStream(
      `${BASE}/messages/${eventId}/regenerate/stream`,
      handlers,
      { signal },
    ),

  streamStartCampaign: (
    handlers: StreamHandlers,
    signal?: AbortSignal,
  ): Promise<StreamResult<StreamEvent>> =>
    consumeStream(`${BASE}/campaign/start/stream`, handlers, { signal }),

  streamCharacterQuiz: (
    concept: string,
    handlers: StreamHandlers,
    signal?: AbortSignal,
  ): Promise<StreamResult<StreamEvent>> =>
    consumeStream(`${BASE}/character/quiz/stream`, handlers, {
      signal,
      json: { concept },
    }),

  streamCharacterDraft: (
    mode: "scratch" | "template",
    handlers: StreamHandlers,
    prompt: string | undefined,
    template: CharacterSheet | undefined,
    signal?: AbortSignal,
  ): Promise<StreamResult<StreamEvent>> =>
    consumeStream(`${BASE}/character/draft/stream`, handlers, {
      signal,
      json: { mode, prompt, template },
    }),

  streamQuizzedCharacterDraft: (
    concept: string,
    answers: CharacterQuizAnswer[],
    finalNote: string | null,
    handlers: StreamHandlers,
    signal?: AbortSignal,
  ): Promise<StreamResult<StreamEvent>> =>
    consumeStream(`${BASE}/character/draft/quizzed/stream`, handlers, {
      signal,
      json: { concept, answers, final_note: finalNote },
    }),
};

export { ApiError, StreamTransportError };
