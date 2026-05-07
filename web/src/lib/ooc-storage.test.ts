// @vitest-environment jsdom
//
// localStorage-backed persistence for OOC explainer notes. We run
// under jsdom because the helper needs `window.localStorage`; the
// rest of the suite stays on plain node.
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { clearOocNotes, loadOocNotes, saveOocNotes } from "./ooc-storage";
import type { ClientNote } from "./store.svelte";

const SAVE_A = "save_alpha";
const SAVE_B = "save_beta";

function makeNote(
  id: string,
  question: string,
  answer: string,
  createdAt: string,
  kind: ClientNote["kind"] = "explanation",
): ClientNote {
  return {
    id,
    kind,
    text: answer,
    question,
    created_at: createdAt,
  };
}

describe("ooc-storage", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    window.localStorage.clear();
  });

  it("returns an empty list when nothing has been persisted", () => {
    expect(loadOocNotes(SAVE_A)).toEqual([]);
  });

  it("returns an empty list when the save id is null", () => {
    // The store passes `activeSaveId` directly; null is the "no save
    // bound yet" signal and must not throw or attempt a read.
    expect(loadOocNotes(null)).toEqual([]);
  });

  it("persists explanation notes round-trip per save id", () => {
    const note = makeNote("n1", "what is HP?", "HP is hit points.", "2025-01-01T00:00:00Z");
    saveOocNotes(SAVE_A, [note]);
    expect(loadOocNotes(SAVE_A)).toEqual([note]);
    // A different save's bucket stays untouched — OOC scrollback is
    // per-campaign, not global, so we anchor that boundary here.
    expect(loadOocNotes(SAVE_B)).toEqual([]);
  });

  it("filters out non-explanation kinds before persisting", () => {
    // Help / error / info notes are transient feedback; they must
    // never enter the persisted bucket or they'd resurrect on every
    // reload as zombie status messages.
    const explanation = makeNote("n1", "q", "a", "2025-01-01T00:00:00Z");
    const error = makeNote("n2", "", "you typed /loot wrong", "2025-01-01T00:00:01Z", "error");
    saveOocNotes(SAVE_A, [explanation, error]);
    const loaded = loadOocNotes(SAVE_A);
    expect(loaded).toHaveLength(1);
    expect(loaded[0]?.id).toBe("n1");
  });

  it("clears the bucket when the persisted list is empty", () => {
    const note = makeNote("n1", "q", "a", "2025-01-01T00:00:00Z");
    saveOocNotes(SAVE_A, [note]);
    saveOocNotes(SAVE_A, []);
    // Empty == removed, so we don't leave behind an empty array
    // entry that future schema migrations would have to deal with.
    expect(window.localStorage.getItem("dm.ooc." + SAVE_A)).toBeNull();
  });

  it("clearOocNotes removes the per-save bucket", () => {
    const note = makeNote("n1", "q", "a", "2025-01-01T00:00:00Z");
    saveOocNotes(SAVE_A, [note]);
    clearOocNotes(SAVE_A);
    expect(loadOocNotes(SAVE_A)).toEqual([]);
  });

  it("drops corrupt entries on hydration without throwing", () => {
    // A hand-edited or schema-drifted entry must not crash the chat
    // feed; we silently filter the bad rows.
    window.localStorage.setItem(
      "dm.ooc." + SAVE_A,
      JSON.stringify([
        { id: "ok", kind: "explanation", text: "answer", question: "q", created_at: "2025-01-01T00:00:00Z" },
        { id: 7, kind: "explanation", text: "bad" }, // wrong shape
        "not even an object",
        { id: "wrong-kind", kind: "error", text: "no", created_at: "2025-01-01T00:00:00Z" },
      ]),
    );
    const loaded = loadOocNotes(SAVE_A);
    expect(loaded.map((n) => n.id)).toEqual(["ok"]);
  });

  it("returns an empty list for malformed JSON", () => {
    window.localStorage.setItem("dm.ooc." + SAVE_A, "{not json");
    expect(loadOocNotes(SAVE_A)).toEqual([]);
  });

  it("caps the persisted history at 200 entries to stay under quota", () => {
    // The MAX_NOTES_PER_SAVE invariant exists so a chatty 100-hour
    // campaign can't blow the localStorage quota. We anchor it as a
    // numeric assertion so a future change to the constant has to
    // update this test on purpose.
    const notes: ClientNote[] = [];
    for (let i = 0; i < 250; i++) {
      notes.push(makeNote(`n${i}`, `q${i}`, `a${i}`, new Date(2025, 0, 1, 0, 0, i).toISOString()));
    }
    saveOocNotes(SAVE_A, notes);
    const loaded = loadOocNotes(SAVE_A);
    expect(loaded).toHaveLength(200);
    // The newest entries win — losing the oldest is the right side
    // to drop because the player is most likely to want to scroll
    // back to recent OOC questions.
    expect(loaded[0]?.id).toBe("n50");
    expect(loaded[loaded.length - 1]?.id).toBe("n249");
  });
});
