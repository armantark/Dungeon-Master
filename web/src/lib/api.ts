// Thin fetch wrapper around the FastAPI backend.
//
// All endpoints return the entire `GameState`, so the frontend never has
// to reconcile partial diffs - the most recent response is the truth.
// Keeping this in one file means there's exactly one place to edit when
// auth/headers/logging requirements change.

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
};

export { ApiError };
