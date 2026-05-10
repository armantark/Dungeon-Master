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
  CampaignEndReason,
  CampaignSeed,
  CharacterDraftResponse,
  CharacterQuizAnswer,
  CharacterQuizResponse,
  CharacterSheet,
  CharacterTemplatesResponse,
  ExplanationResponse,
  GameState,
  Likelihood,
  LLMProvider,
  LLMPreset,
  LLMSettingsResponse,
  OracleOutcome,
  SaveLibraryBootstrapResponse,
} from "./types";

const DEFAULT_API_BASE = "/api";
const ENV_API_BASE =
  typeof import.meta.env.VITE_API_BASE_URL === "string"
    ? import.meta.env.VITE_API_BASE_URL
    : "";
let runtimeApiBase = normalizeApiBase(ENV_API_BASE || DEFAULT_API_BASE);

function normalizeApiBase(base: string): string {
  const cleaned = base.trim();
  if (!cleaned) return DEFAULT_API_BASE;
  return cleaned.endsWith("/") ? cleaned.slice(0, -1) : cleaned;
}

function apiUrl(path: string): string {
  return `${runtimeApiBase}${path}`;
}

export function setApiBase(base: string): void {
  runtimeApiBase = normalizeApiBase(base);
}

export function getApiBase(): string {
  return runtimeApiBase;
}

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

  const response = await fetch(apiUrl(path), {
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

  // F-12 Save Library --------------------------------------------------------
  //
  // The library endpoints are intentionally split out from `getState`. A
  // bootstrap call describes "which save, if any, is active and what's
  // the rest of the shelf?" before we know whether `getState` can even be
  // called — and on a fresh install, calling `/state` prematurely would
  // return a 409 ("No active save selected.") that we'd have to suppress.
  // Routing through `bootstrapLibrary` first keeps the empty-library
  // splash screen reachable without a noisy 409 in the network panel.
  bootstrapLibrary: (signal?: AbortSignal): Promise<SaveLibraryBootstrapResponse> =>
    request("/library/bootstrap", { signal }),

  // `select` defaults to true — the common case for both the empty-shelf
  // splash and the "Begin a new campaign" CTA in the system menu is
  // "create + immediately switch to it". Tests pass `select: false` when
  // they want to assert the create path doesn't accidentally rebind the
  // active service.
  createSave: (
    select: boolean = true,
    signal?: AbortSignal,
  ): Promise<SaveLibraryBootstrapResponse> =>
    request("/library/saves", { method: "POST", signal, json: { select } }),

  selectSave: (
    save_id: string,
    signal?: AbortSignal,
  ): Promise<SaveLibraryBootstrapResponse> =>
    request("/library/select", { method: "POST", signal, json: { save_id } }),

  // App-global LLM preset surface. The backend owns the source of
  // truth (`data/runtime_settings.json`) and the UI just round-trips
  // it: GET to populate the modal on open, POST to persist a swap.
  // The backend rejects POSTs while a streamed turn is in flight
  // (HTTP 409); the modal surfaces that as a non-fatal error so the
  // player can wait for the current turn to finish and try again.
  getLlmSettings: (signal?: AbortSignal): Promise<LLMSettingsResponse> =>
    request("/settings/llm", { signal }),

  updateLlmSettings: (
    preset: LLMPreset,
    signal?: AbortSignal,
  ): Promise<LLMSettingsResponse> =>
    request("/settings/llm", {
      method: "POST",
      signal,
      json: { preset },
    }),

  updateLlmCredentials: (
    provider: LLMProvider,
    api_key: string,
    signal?: AbortSignal,
  ): Promise<LLMSettingsResponse> =>
    request("/settings/credentials", {
      method: "POST",
      signal,
      json: { provider, api_key },
    }),

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

  // F-06 explicit terminal close. The backend rejects any non-DEATH
  // reason while an encounter is still active, and rejects DEATH while
  // the character is alive — we surface those 409s as errors via the
  // store so the player sees why the close was refused. Auto-deaths
  // don't go through this endpoint; they fold into the regular turn
  // pipeline server-side. See memory-bank/featureKanban.md F-06.
  endCampaign: (
    reason: CampaignEndReason,
    summary: string | null,
    signal?: AbortSignal,
  ): Promise<GameState> =>
    request("/campaign/end", {
      method: "POST",
      signal,
      json: { reason, summary },
    }),

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

  // B-02 Campaign directives. Distinct endpoint from `updateNotes`
  // because the two surfaces have different meanings server-side:
  // `setting_notes`/`player_notes` are the *canonical* campaign /
  // backstory canon, while directives are persistent OOC steering
  // that explicitly does *not* land in the action log. We keep
  // empty strings legal on the wire so "clear my guidance" stays a
  // single round-trip — the backend treats "" as "no guidance" and
  // simply skips the directives prompt block.
  updateDirectives: (
    world_guidance: string,
    play_guidance: string,
    signal?: AbortSignal,
  ): Promise<GameState> =>
    request("/state/directives", {
      method: "POST",
      signal,
      json: { world_guidance, play_guidance },
    }),

  // F-15 campaign-seed update. The backend's `update_campaign_seed`
  // rejects with 409 once the campaign has already started — the
  // seed is meant to be authored before generation runs and locked
  // afterwards so the generated world stays coherent with the seed
  // it was given. We surface 409s through the normal `state.error`
  // sink so the editor can roll the picker back without a special
  // error type.
  updateCampaignSeed: (
    campaign_seed: CampaignSeed,
    signal?: AbortSignal,
  ): Promise<GameState> =>
    request("/state/campaign-seed", {
      method: "POST",
      signal,
      json: { campaign_seed },
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

  previewYesNo: (
    question: string,
    likelihood: Likelihood,
    signal?: AbortSignal,
  ): Promise<OracleOutcome> =>
    request("/oracle/yes-no/preview", {
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

  // F-10 OOC rules explainer. Returns a non-canonical `ExplanationResponse`
  // (answer + thinking trace) and does *not* mutate `GameState` — see
  // `service.py::_load_state_readonly`. We expose the unary endpoint here
  // even though the streaming variant below is what the store actually
  // calls in practice; the unary endpoint exists as the fallback when
  // the streaming route 404s during the backend transition window, and
  // because exercising it directly is the simplest no-mutation guarantee
  // to assert in tests.
  explain: (question: string, signal?: AbortSignal): Promise<ExplanationResponse> =>
    request("/explain", { method: "POST", signal, json: { question } }),

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
    consumeStream(apiUrl("/turn/stream"), handlers, { signal, json: { text } }),

  streamSubmitAction: (
    action: string,
    handlers: StreamHandlers,
    signal?: AbortSignal,
  ): Promise<StreamResult<StreamEvent>> =>
    consumeStream(apiUrl("/action/stream"), handlers, { signal, json: { action } }),

  streamRegenerateMessage: (
    eventId: string,
    handlers: StreamHandlers,
    signal?: AbortSignal,
  ): Promise<StreamResult<StreamEvent>> =>
    consumeStream(
      apiUrl(`/messages/${eventId}/regenerate/stream`),
      handlers,
      { signal },
    ),

  streamStartCampaign: (
    handlers: StreamHandlers,
    signal?: AbortSignal,
  ): Promise<StreamResult<StreamEvent>> =>
    consumeStream(apiUrl("/campaign/start/stream"), handlers, { signal }),

  streamCharacterQuiz: (
    concept: string,
    handlers: StreamHandlers,
    signal?: AbortSignal,
  ): Promise<StreamResult<StreamEvent>> =>
    consumeStream(apiUrl("/character/quiz/stream"), handlers, {
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
    consumeStream(apiUrl("/character/draft/stream"), handlers, {
      signal,
      json: { mode, prompt, template },
    }),

  // F-10 streaming variant of the OOC explainer. Mirrors the
  // quiz/draft pattern (`final_payload` + endpoint-specific
  // discriminator) rather than `final_state` because the explainer
  // never mutates canonical state. The store consumes the answer
  // through #runStreamingPayload and persists it as an ephemeral
  // ClientNote — never as a canonical action_log entry.
  streamExplain: (
    question: string,
    handlers: StreamHandlers,
    signal?: AbortSignal,
  ): Promise<StreamResult<StreamEvent>> =>
    consumeStream(apiUrl("/explain/stream"), handlers, {
      signal,
      json: { question },
    }),

  // Re-subscribe to a stream that was started by an earlier page load
  // (typically: the player refreshed the tab while a turn was still
  // generating). The backend's GET /api/requests/{id}/stream endpoint
  // replays the buffered NDJSON and continues tailing live deltas, so
  // we can drive it through the exact same `StreamHandlers` plumbing
  // as the POST routes — the only thing we need to tell `consumeStream`
  // is "use GET, don't send a body."
  //
  // The 404 / 409 cases (request unknown or belongs to a different
  // active save) surface via `StreamTransportError` exactly like every
  // other transport failure; the store's resume path catches those and
  // clears the localStorage descriptor so we don't loop on a stale id.
  reattachStream: (
    requestId: string,
    handlers: StreamHandlers,
    signal?: AbortSignal,
  ): Promise<StreamResult<StreamEvent>> =>
    consumeStream(
      apiUrl(`/requests/${encodeURIComponent(requestId)}/stream`),
      handlers,
      { signal, method: "GET" },
    ),

  streamQuizzedCharacterDraft: (
    concept: string,
    answers: CharacterQuizAnswer[],
    finalNote: string | null,
    handlers: StreamHandlers,
    signal?: AbortSignal,
  ): Promise<StreamResult<StreamEvent>> =>
    consumeStream(apiUrl("/character/draft/quizzed/stream"), handlers, {
      signal,
      json: { concept, answers, final_note: finalNote },
    }),
};

export { ApiError, StreamTransportError };
