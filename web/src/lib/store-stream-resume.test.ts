// @vitest-environment jsdom
//
// Integration test for the "reload survives an in-flight stream"
// promise. The contract has two halves:
//   1. While a stream is running, the store must drop a resume
//      descriptor into localStorage scoped to the active save (see
//      stream-resume.ts) so a fresh page load can find it.
//   2. On bootstrap, when a descriptor is present, the store calls
//      `api.reattachStream` and surfaces a `streaming.resuming`
//      flag while the buffered + live tail is consumed.
//
// We exercise the public surface (`game.submitTurn`, `game.bootstrap`)
// rather than the private helpers because the contract the App shell
// depends on is exactly that surface — anything narrower would let an
// internal refactor silently break the player-visible promise.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, StreamTransportError } from "./api";
import { game } from "./store.svelte";
import {
  loadStreamResume,
  saveStreamResume,
  type StreamResumeDescriptor,
} from "./stream-resume";

const SAVE_ID = "save_resume_check";

function resetGameStore(): void {
  game.state = null;
  game.isLoading = false;
  game.error = null;
  game.rollPhase = "idle";
  game.pendingOracle = null;
  game.cancelLabel = null;
  game.streaming = {
    active: false,
    route: null,
    requestId: null,
    content: "",
    thinking: "",
    pendingOutcome: null,
    resuming: false,
  };
  game.notes = [];
  game.inspectorOpen = false;
  game.scrollRequest = null;
  game.inspectorFocusRequest = null;
  game.activeSaveId = null;
  game.library = [];
  game.libraryStatus = "loading";
  game.libraryError = null;
}

function fakeState(): unknown {
  return {
    id: SAVE_ID,
    created_at: "2025-01-01T00:00:00Z",
    updated_at: "2025-01-01T00:00:00Z",
    action_log: [],
    oracle_history: [],
    threads: [],
    npcs: [],
    chaos_factor: 5,
    setting_notes: "",
    player_notes: "",
    current_scene: "",
    campaign_directives: [],
    character: null,
    combat: null,
  };
}

function fakeSaveSummary(): unknown {
  return {
    save_id: SAVE_ID,
    label: "fixture",
    created_at: "2025-01-01T00:00:00Z",
    updated_at: "2025-01-01T00:00:00Z",
    turn_count: 0,
    chaos_factor: 5,
    current_scene: "",
    character_name: null,
  };
}

describe("stream resume across reloads", () => {
  beforeEach(() => {
    window.localStorage.clear();
    resetGameStore();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    window.localStorage.clear();
    resetGameStore();
  });

  it("writes the resume descriptor on `meta` and clears it on `final_state`", async () => {
    // The descriptor must land as soon as the backend's request_id
    // is known (the `meta` event) — an immediate refresh in that
    // window is the failure mode this whole feature exists to fix.
    // Once the stream finalizes cleanly, the descriptor must
    // disappear so the next bootstrap doesn't try to reattach to a
    // request that already committed.
    game.activeSaveId = SAVE_ID;
    // Holder object so TypeScript's flow analysis doesn't narrow
    // the captured descriptor to `null` based on the initializer
    // (the assignment happens inside a callback the compiler can't
    // prove fires before the await).
    const captured: { value: StreamResumeDescriptor | null } = { value: null };
    vi.spyOn(api, "streamSubmitTurn").mockImplementation((_text, handlers) => {
      handlers.onMeta?.({
        type: "meta",
        request_id: "req_inflight",
        route: "player_action",
      });
      captured.value = loadStreamResume(SAVE_ID);
      handlers.onFinalState?.({
        type: "final_state",
        state: fakeState() as never,
        thinking: null,
      });
      return Promise.resolve({ kind: "final" } as never);
    });

    await game.submitTurn("I look around");

    expect(captured.value?.request_id).toBe("req_inflight");
    expect(captured.value?.route).toBe("player_action");
    // Final landed → descriptor cleared.
    expect(loadStreamResume(SAVE_ID)).toBeNull();
  });

  it("keeps the descriptor when the stream dies mid-flight without a final event", async () => {
    // This is the "user closed the tab while the model was still
    // streaming" path. The transport ends without observing
    // final_state / error, so the next page load must still find
    // the descriptor and try to reattach.
    game.activeSaveId = SAVE_ID;
    vi.spyOn(api, "streamSubmitTurn").mockImplementation((_text, handlers) => {
      handlers.onMeta?.({
        type: "meta",
        request_id: "req_orphaned",
        route: "player_action",
      });
      handlers.onContentDelta?.({ type: "content_delta", text: "The wind " });
      // No onFinalState — simulate the connection dying.
      return Promise.resolve({ kind: "aborted", reason: "server" } as never);
    });

    await game.submitTurn("I listen");

    const persisted = loadStreamResume(SAVE_ID);
    expect(persisted?.request_id).toBe("req_orphaned");
  });

  it("attempts reattach during bootstrap when a fresh descriptor exists, surfacing the resuming flag", async () => {
    // Simulate "previous page wrote the descriptor; this page
    // boots up." The bootstrap path should call `reattachStream`
    // with the persisted request_id and flip
    // `streaming.resuming` while the reattach is in progress.
    saveStreamResume(SAVE_ID, {
      request_id: "req_resume",
      route: "player_action",
      started_at: new Date().toISOString(),
    });
    vi.spyOn(api, "bootstrapLibrary").mockResolvedValue({
      saves: [fakeSaveSummary()],
      active_save_id: SAVE_ID,
    } as never);
    vi.spyOn(api, "getState").mockResolvedValue(fakeState() as never);

    let resumingDuringMeta = false;
    const reattachSpy = vi
      .spyOn(api, "reattachStream")
      .mockImplementation((_requestId, handlers) => {
        // The resuming flag is set *before* reattachStream is awaited
        // so we can sample it from inside the handler. This anchors
        // the contract that ChatFeed reads `game.streaming.resuming`
        // as soon as the bubble is on screen, not only after the
        // first event lands.
        resumingDuringMeta = game.streaming.resuming;
        handlers.onMeta?.({
          type: "meta",
          request_id: "req_resume",
          route: "player_action",
        });
        handlers.onFinalState?.({
          type: "final_state",
          state: fakeState() as never,
          thinking: null,
        });
        return Promise.resolve({ kind: "final" } as never);
      });

    await game.bootstrap();
    // Resume runs fire-and-forget against bootstrap, but submit/finalize
    // here happen synchronously inside the mock. A microtask flush is
    // enough to let the `void this.#tryResumeStream()` chain settle.
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(reattachSpy).toHaveBeenCalledWith(
      "req_resume",
      expect.any(Object),
      expect.any(Object),
    );
    expect(resumingDuringMeta).toBe(true);
    // After completion the streaming buffer collapses and the
    // descriptor is cleared so the next bootstrap doesn't try
    // again.
    expect(game.streaming.active).toBe(false);
    expect(game.streaming.resuming).toBe(false);
    expect(loadStreamResume(SAVE_ID)).toBeNull();
  });

  it("does not call reattachStream when no descriptor exists", async () => {
    // The cold-start path: nothing in localStorage, nothing to
    // resume. The reattach endpoint must not be called — otherwise
    // a fresh tab would 404 the GET and clutter the network panel.
    vi.spyOn(api, "bootstrapLibrary").mockResolvedValue({
      saves: [fakeSaveSummary()],
      active_save_id: SAVE_ID,
    } as never);
    vi.spyOn(api, "getState").mockResolvedValue(fakeState() as never);
    const reattachSpy = vi.spyOn(api, "reattachStream");

    await game.bootstrap();
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(reattachSpy).not.toHaveBeenCalled();
    expect(game.streaming.active).toBe(false);
  });

  it("clears the descriptor when the reattach endpoint 404s (session is gone)", async () => {
    // The backend GC's finished sessions after ~120s. A descriptor
    // older than that window will 404 on reattach. The store must
    // swallow the failure silently and evict the descriptor so we
    // don't loop on it next reload.
    saveStreamResume(SAVE_ID, {
      request_id: "req_gone",
      route: "player_action",
      started_at: new Date().toISOString(),
    });
    vi.spyOn(api, "bootstrapLibrary").mockResolvedValue({
      saves: [fakeSaveSummary()],
      active_save_id: SAVE_ID,
    } as never);
    vi.spyOn(api, "getState").mockResolvedValue(fakeState() as never);
    vi.spyOn(api, "reattachStream").mockRejectedValue(
      new StreamTransportError("Unknown request", { status: 404 }),
    );

    await game.bootstrap();
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(loadStreamResume(SAVE_ID)).toBeNull();
    // No banner — the player just sees their persisted state.
    expect(game.error).toBeNull();
  });
});
