// @vitest-environment jsdom
//
// localStorage-backed persistence for the "resume an in-flight stream
// after a reload" descriptor. We run under jsdom because the helper
// needs `window.localStorage`; the rest of the stream-transport tests
// run on plain node and don't care about persistence.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  clearStreamResume,
  loadStreamResume,
  saveStreamResume,
  STREAM_RESUME_TTL_MS,
} from "./stream-resume";

const SAVE_A = "save_alpha";
const SAVE_B = "save_beta";

describe("stream-resume", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.useRealTimers();
  });

  afterEach(() => {
    window.localStorage.clear();
    vi.useRealTimers();
  });

  it("returns null when nothing has been persisted", () => {
    expect(loadStreamResume(SAVE_A)).toBeNull();
  });

  it("returns null and never touches storage when save id is null", () => {
    // The store passes `activeSaveId` directly; a null save id is
    // the "no save bound" signal and must short-circuit without
    // attempting a read or a write.
    saveStreamResume(null, {
      request_id: "req_1",
      route: "player_action",
      started_at: new Date().toISOString(),
    });
    expect(loadStreamResume(null)).toBeNull();
    expect(window.localStorage.length).toBe(0);
  });

  it("persists the descriptor scoped per save id", () => {
    const startedAt = new Date().toISOString();
    saveStreamResume(SAVE_A, {
      request_id: "req_alpha",
      route: "player_action",
      started_at: startedAt,
    });
    const loaded = loadStreamResume(SAVE_A);
    expect(loaded).toEqual({
      save_id: SAVE_A,
      request_id: "req_alpha",
      route: "player_action",
      started_at: startedAt,
    });
    // Different save → different bucket. We rely on this isolation
    // in bootstrap so a multi-tab scenario can't leak one campaign's
    // in-flight request id into another's resume attempt.
    expect(loadStreamResume(SAVE_B)).toBeNull();
  });

  it("evicts descriptors past the TTL window", () => {
    // Anything older than the TTL would 404 on a reattach attempt
    // anyway because the backend GC's finished sessions. Evicting
    // on read keeps the failure mode silent for the player.
    const stale = new Date(Date.now() - STREAM_RESUME_TTL_MS - 1000).toISOString();
    saveStreamResume(SAVE_A, {
      request_id: "req_stale",
      route: "player_action",
      started_at: stale,
    });
    expect(loadStreamResume(SAVE_A)).toBeNull();
    // Eviction should have purged the row, not just hidden it.
    expect(window.localStorage.getItem(`dm.stream-resume.${SAVE_A}`)).toBeNull();
  });

  it("keeps descriptors that are within the TTL window", () => {
    const fresh = new Date(Date.now() - 60_000).toISOString();
    saveStreamResume(SAVE_A, {
      request_id: "req_fresh",
      route: "player_action",
      started_at: fresh,
    });
    expect(loadStreamResume(SAVE_A)?.request_id).toBe("req_fresh");
  });

  it("drops corrupt entries on hydration without throwing", () => {
    // A schema-drifted or hand-edited entry must not crash the
    // bootstrap path; we evict and return null.
    window.localStorage.setItem(
      `dm.stream-resume.${SAVE_A}`,
      JSON.stringify({ request_id: 7, save_id: SAVE_A }),
    );
    expect(loadStreamResume(SAVE_A)).toBeNull();
    expect(window.localStorage.getItem(`dm.stream-resume.${SAVE_A}`)).toBeNull();
  });

  it("returns null and evicts when JSON is malformed", () => {
    window.localStorage.setItem(`dm.stream-resume.${SAVE_A}`, "{not json");
    expect(loadStreamResume(SAVE_A)).toBeNull();
    expect(window.localStorage.getItem(`dm.stream-resume.${SAVE_A}`)).toBeNull();
  });

  it("evicts descriptors whose save_id field doesn't match the bucket key", () => {
    // Defensive: if a previous bug ever wrote the wrong save_id into
    // a bucket, silently mis-resuming would be worse than treating
    // the row as corrupt. We anchor that guard here.
    window.localStorage.setItem(
      `dm.stream-resume.${SAVE_A}`,
      JSON.stringify({
        request_id: "req_x",
        save_id: SAVE_B,
        route: "player_action",
        started_at: new Date().toISOString(),
      }),
    );
    expect(loadStreamResume(SAVE_A)).toBeNull();
    expect(window.localStorage.getItem(`dm.stream-resume.${SAVE_A}`)).toBeNull();
  });

  it("clearStreamResume removes the per-save bucket", () => {
    saveStreamResume(SAVE_A, {
      request_id: "req_clear",
      route: "player_action",
      started_at: new Date().toISOString(),
    });
    clearStreamResume(SAVE_A);
    expect(loadStreamResume(SAVE_A)).toBeNull();
  });
});
