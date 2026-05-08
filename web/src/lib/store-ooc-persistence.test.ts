// @vitest-environment jsdom
//
// Integration test for the OOC explainer reload-survival promise.
// We exercise the store's `#explanationNote` write-path and its
// `#hydrateOocNotes` read-path by going through the public surface
// (`game.submit("/explain …")` and `game.bootstrap()`), which is
// exactly the contract the App shell relies on.
//
// jsdom is required so localStorage exists; the rest of the store
// tests run on plain node and ooc-storage degrades to a no-op
// there, so this file's env scope is intentionally narrow.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "./api";
import { game } from "./store.svelte";

const SAVE_ID = "save_persistence_check";

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
    stages: [],
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

describe("OOC explainer persistence across reloads", () => {
  beforeEach(() => {
    window.localStorage.clear();
    resetGameStore();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    window.localStorage.clear();
    resetGameStore();
  });

  it("writes the explainer answer to localStorage scoped to the active save", async () => {
    // The streaming explainer must flush its answer to per-save
    // localStorage as soon as the note lands. Without this, hitting
    // reload (or even closing the tab) loses the OOC scrollback —
    // which is the bug we're fixing.
    game.activeSaveId = SAVE_ID;
    vi.spyOn(api, "streamExplain").mockImplementation((_question, handlers) => {
      handlers.onFinalPayload?.({
        type: "final_payload",
        kind: "explanation",
        payload: { answer: "Saves use a d20 vs the relevant attribute." },
        thinking: null,
      });
      return Promise.resolve({ kind: "final" } as never);
    });

    await game.submit("/explain how do saves work?");

    const persisted = window.localStorage.getItem(`dm.ooc.${SAVE_ID}`);
    expect(persisted).not.toBeNull();
    const parsed = JSON.parse(persisted!) as Array<{ kind: string; question: string; text: string }>;
    expect(parsed).toHaveLength(1);
    expect(parsed[0]?.kind).toBe("explanation");
    expect(parsed[0]?.question).toBe("how do saves work?");
    expect(parsed[0]?.text).toContain("Saves use a d20");
  });

  it("does not persist /ask oracle previews to localStorage", async () => {
    game.activeSaveId = SAVE_ID;
    vi.spyOn(api, "previewYesNo").mockResolvedValue({
      id: "oracle_preview_1",
      created_at: "2025-01-01T00:00:00Z",
      kind: "yes_no",
      summary: "No: Is the crypt quiet?",
      rolls: [{ label: "fate", result: 88, sides: 100 }],
      question: "Is the crypt quiet?",
      likelihood: "Even odds",
      answer: "No",
      probability: 50,
      chaos_factor: 5,
      event_focus: null,
      event_action: null,
      event_tone: null,
      event_subject: null,
      referenced_thread_id: null,
      referenced_thread_ids: [],
      referenced_npc_id: null,
      referenced_npc_ids: [],
      scene_status: null,
      cairn: null,
    } as never);

    await game.submit("/ask Is the crypt quiet?");

    expect(window.localStorage.getItem(`dm.ooc.${SAVE_ID}`)).toBeNull();
    expect(game.notes.some((n) => n.kind === "oracle_preview")).toBe(true);
  });

  it("rehydrates persisted OOC notes after bootstrap so reload preserves the scrollback", async () => {
    // Simulate "the player closed the tab and came back later":
    // localStorage already has a prior exchange, the bootstrap call
    // returns the active save, and the in-memory `notes` list must
    // come back populated without us re-running /explain.
    window.localStorage.setItem(
      `dm.ooc.${SAVE_ID}`,
      JSON.stringify([
        {
          id: "note_old",
          kind: "explanation",
          text: "Retreat is its own oracle, not an attack.",
          question: "what does retreat do?",
          created_at: "2025-01-01T00:00:00Z",
        },
      ]),
    );

    vi.spyOn(api, "bootstrapLibrary").mockResolvedValue({
      saves: [
        {
          save_id: SAVE_ID,
          label: "fixture",
          created_at: "2025-01-01T00:00:00Z",
          updated_at: "2025-01-01T00:00:00Z",
          turn_count: 0,
          chaos_factor: 5,
          current_scene: "",
          character_name: null,
        },
      ],
      active_save_id: SAVE_ID,
    } as never);
    vi.spyOn(api, "getState").mockResolvedValue({
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
    } as never);

    await game.bootstrap();

    const oocNotes = game.notes.filter((n) => n.kind === "explanation");
    expect(oocNotes).toHaveLength(1);
    expect(oocNotes[0]?.id).toBe("note_old");
    expect(oocNotes[0]?.question).toBe("what does retreat do?");
    expect(game.libraryStatus).toBe("ready");
  });

  it("dropping an OOC note also removes it from localStorage so the dismissal sticks across reloads", async () => {
    // Without the write-through dismissal, the dismissed entry would
    // come right back next bootstrap — turning the X into a "hide
    // until reload" rather than a real dismiss.
    game.activeSaveId = SAVE_ID;
    window.localStorage.setItem(
      `dm.ooc.${SAVE_ID}`,
      JSON.stringify([
        {
          id: "note_alpha",
          kind: "explanation",
          text: "alpha",
          question: "qa",
          created_at: "2025-01-01T00:00:00Z",
        },
        {
          id: "note_beta",
          kind: "explanation",
          text: "beta",
          question: "qb",
          created_at: "2025-01-01T00:00:01Z",
        },
      ]),
    );
    // Force hydrate by going through the same path the store does.
    // We don't bootstrap here because we don't need the GameState —
    // we just want notes loaded so dismissNote has something to act
    // on.
    const ocs = await import("./ooc-storage");
    game.notes = ocs.loadOocNotes(SAVE_ID);
    expect(game.notes).toHaveLength(2);

    game.dismissNote("note_alpha");

    expect(game.notes.map((n) => n.id)).toEqual(["note_beta"]);
    const persisted = JSON.parse(
      window.localStorage.getItem(`dm.ooc.${SAVE_ID}`) ?? "[]",
    ) as Array<{ id: string }>;
    expect(persisted.map((n) => n.id)).toEqual(["note_beta"]);
  });
});
