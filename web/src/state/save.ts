import { api } from "../lib/api";
import type { GameState, OracleOutcome, SaveSummary } from "../lib/types";
import type { ClientNote } from "./play";
import { loadOocNotes } from "./save/ooc-notes";
import { emptyStreamingState, type RollPhase, type StreamingState, StreamWorkflow } from "./stream";
import { formatRuntimeError } from "./runtime";

export type LibraryStatus = "loading" | "empty" | "selecting" | "ready";

export function createdSaveId(
  beforeIds: ReadonlySet<string>,
  saves: readonly SaveSummary[],
): string | null {
  return saves.find((entry) => !beforeIds.has(entry.save_id))?.save_id ?? null;
}

export function mergePersistedNotes(
  current: readonly ClientNote[],
  persisted: readonly ClientNote[],
): ClientNote[] {
  if (persisted.length === 0) return [...current];
  const seen = new Set(current.map((note) => note.id));
  const merged = [...persisted.filter((note) => !seen.has(note.id)), ...current];
  merged.sort((a, b) => a.created_at.localeCompare(b.created_at));
  return merged;
}

interface SaveStateOwner {
  state: GameState | null;
  error: string | null;
  rollPhase: RollPhase;
  pendingOracle: OracleOutcome | null;
  streaming: StreamingState;
  notes: ClientNote[];
  scrollRequest: { eventId: string; seq: number } | null;
  inspectorFocusRequest: {
    section: "threads" | "npcs";
    entityId: string | null;
    seq: number;
  } | null;
  library: SaveSummary[];
  activeSaveId: string | null;
  libraryStatus: LibraryStatus;
  libraryError: string | null;
}

/** Owns atomic save binding, shelf refresh, save switching, and save-scoped ephemera. */
export class SaveLibraryWorkflow {
  readonly #owner: SaveStateOwner;
  readonly #requests: StreamWorkflow;

  constructor(owner: SaveStateOwner, requests: StreamWorkflow) {
    this.#owner = owner;
    this.#requests = requests;
  }

  async bootstrap(): Promise<void> {
    const owner = this.#owner;
    owner.libraryStatus = "loading";
    owner.libraryError = null;
    try {
      const response = await api.bootstrapLibrary();
      owner.library = response.saves;
      if (response.active_save_id === null) {
        owner.libraryStatus = "empty";
        owner.activeSaveId = null;
        owner.state = null;
        return;
      }
      const state = await this.#fetchState();
      if (state === null) {
        owner.libraryStatus = "selecting";
        return;
      }
      this.#publish(response.active_save_id, state);
      this.#hydrateNotes();
      owner.libraryStatus = "ready";
      void this.#requests.tryResume();
    } catch (error) {
      owner.libraryStatus = "empty";
      owner.libraryError = formatRuntimeError(error);
    }
  }

  async create(select = true): Promise<string | null> {
    const owner = this.#owner;
    owner.libraryError = null;
    try {
      const beforeIds = new Set(owner.library.map((entry) => entry.save_id));
      const response = await api.createSave(select);
      owner.library = response.saves;
      const newSaveId = createdSaveId(beforeIds, response.saves);
      if (select) {
        if (response.active_save_id === null) {
          throw new Error("The new save was created without becoming active.");
        }
        const state = await this.#fetchState();
        if (state === null) {
          owner.libraryStatus = "selecting";
          return newSaveId;
        }
        this.#resetEphemera();
        this.#publish(response.active_save_id, state);
        this.#hydrateNotes();
        owner.libraryStatus = "ready";
      }
      return newSaveId;
    } catch (error) {
      owner.libraryError = formatRuntimeError(error);
      return null;
    }
  }

  async select(saveId: string): Promise<void> {
    const owner = this.#owner;
    if (saveId === owner.activeSaveId && owner.state !== null) {
      owner.libraryStatus = "ready";
      return;
    }
    owner.libraryError = null;
    try {
      const response = await api.selectSave(saveId);
      owner.library = response.saves;
      if (response.active_save_id === null)
        throw new Error("The selected save did not become active.");
      const state = await this.#fetchState();
      if (state === null) {
        owner.libraryStatus = "selecting";
        return;
      }
      this.#resetEphemera();
      this.#publish(response.active_save_id, state);
      this.#hydrateNotes();
      owner.libraryStatus = "ready";
    } catch (error) {
      owner.libraryError = formatRuntimeError(error);
    }
  }

  open(): void {
    const owner = this.#owner;
    if (owner.libraryStatus === "ready") owner.libraryStatus = "selecting";
    void api
      .bootstrapLibrary()
      .then((response) => {
        owner.library = response.saves;
      })
      .catch(() => undefined);
  }

  close(): void {
    const owner = this.#owner;
    if (owner.activeSaveId !== null && owner.state !== null) owner.libraryStatus = "ready";
  }

  async #fetchState(): Promise<GameState | null> {
    const state = await this.#requests.call((signal) => api.getState(signal));
    if (state === null) this.#owner.libraryError = this.#owner.error;
    return state;
  }

  #publish(saveId: string, state: GameState): void {
    this.#owner.activeSaveId = saveId;
    this.#owner.state = state;
  }

  #resetEphemera(): void {
    const owner = this.#owner;
    owner.notes = [];
    owner.error = null;
    owner.scrollRequest = null;
    owner.inspectorFocusRequest = null;
    owner.streaming = emptyStreamingState();
    owner.pendingOracle = null;
    owner.rollPhase = "idle";
  }

  #hydrateNotes(): void {
    const owner = this.#owner;
    owner.notes = mergePersistedNotes(owner.notes, loadOocNotes(owner.activeSaveId));
  }
}
