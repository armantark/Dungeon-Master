import { describe, expect, it } from "vitest";

import {
  DEFAULT_THREAD_LOOKBACK,
  recentlyTouchedThreadIds,
  sortThreadsForDisplay,
} from "./threads";
import type {
  GameState,
  GameThread,
  OracleOutcome,
  OracleTables,
} from "./types";

function emptyOracleTables(): OracleTables {
  return {
    event_focus: [],
    event_actions: [],
    event_tones: [],
    event_subjects: [],
  };
}

function outcome(overrides: Partial<OracleOutcome>): OracleOutcome {
  return {
    id: overrides.id ?? "outcome",
    created_at: overrides.created_at ?? "2024-01-01T00:00:00Z",
    kind: overrides.kind ?? "player_action",
    summary: overrides.summary ?? "",
    rolls: overrides.rolls ?? [],
    question: overrides.question ?? null,
    likelihood: overrides.likelihood ?? null,
    answer: overrides.answer ?? null,
    probability: overrides.probability ?? null,
    chaos_factor: overrides.chaos_factor ?? 5,
    event_focus: overrides.event_focus ?? null,
    event_action: overrides.event_action ?? null,
    event_tone: overrides.event_tone ?? null,
    event_subject: overrides.event_subject ?? null,
    referenced_thread_id: overrides.referenced_thread_id ?? null,
    referenced_thread_ids: overrides.referenced_thread_ids ?? [],
    referenced_npc_id: overrides.referenced_npc_id ?? null,
    referenced_npc_ids: overrides.referenced_npc_ids ?? [],
    scene_status: overrides.scene_status ?? null,
    cairn: overrides.cairn ?? null,
  };
}

function thread(id: string, status: "active" | "resolved" = "active"): GameThread {
  return { id, title: `t-${id}`, status, stakes: "" };
}

function state(overrides: Partial<GameState>): GameState {
  return {
    id: "state_test",
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
    chaos_factor: 5,
    scene_number: 1,
    current_scene: "",
    scene_status: "expected",
    campaign_status: "active",
    campaign_end_reason: null,
    campaign_ended_at: null,
    campaign_end_summary: null,
    npc_roster_version: 2,
    setting_notes: "",
    player_notes: "",
    directives: { world_guidance: "", play_guidance: "" },
    threads: overrides.threads ?? [],
    npcs: overrides.npcs ?? [],
    hidden_npcs: [],
    oracle_tables: overrides.oracle_tables ?? emptyOracleTables(),
    oracle_history: overrides.oracle_history ?? [],
    action_log: overrides.action_log ?? [],
  };
}

describe("recentlyTouchedThreadIds", () => {
  it("returns the plural ids of the latest outcome by default", () => {
    const gs = state({
      oracle_history: [
        outcome({ id: "o1", referenced_thread_ids: ["t-old"] }),
        outcome({ id: "o2", referenced_thread_ids: ["t-a", "t-b"] }),
      ],
    });

    const touched = recentlyTouchedThreadIds(gs);

    expect(DEFAULT_THREAD_LOOKBACK).toBe(1);
    expect([...touched].sort()).toEqual(["t-a", "t-b"]);
  });

  it("falls back to the legacy singular reference when plural is empty", () => {
    // Older outcomes only carry the singular id. We still want the
    // panel to highlight that thread on a freshly-loaded older
    // campaign — the alternative is a silent regression where the
    // post-F-03 highlight cue disappears for no surfaced reason.
    const gs = state({
      oracle_history: [
        outcome({
          id: "o1",
          referenced_thread_id: "t-legacy",
          referenced_thread_ids: [],
        }),
      ],
    });

    expect([...recentlyTouchedThreadIds(gs)]).toEqual(["t-legacy"]);
  });

  it("merges plural and singular without duplicating", () => {
    const gs = state({
      oracle_history: [
        outcome({
          id: "o1",
          referenced_thread_id: "t-a",
          referenced_thread_ids: ["t-a", "t-b"],
        }),
      ],
    });

    expect([...recentlyTouchedThreadIds(gs)].sort()).toEqual(["t-a", "t-b"]);
  });

  it("widens to multiple outcomes when lookback > 1", () => {
    const gs = state({
      oracle_history: [
        outcome({ id: "o1", referenced_thread_ids: ["t-old"] }),
        outcome({ id: "o2", referenced_thread_ids: ["t-a"] }),
        outcome({ id: "o3", referenced_thread_ids: ["t-b"] }),
      ],
    });

    expect([...recentlyTouchedThreadIds(gs, 2)].sort()).toEqual(["t-a", "t-b"]);
  });

  it("returns an empty set for an empty oracle history", () => {
    expect(recentlyTouchedThreadIds(state({}))).toEqual(new Set());
  });
});

describe("sortThreadsForDisplay", () => {
  it("floats active recently-touched threads to the top", () => {
    const threads = [
      thread("a"),
      thread("b"),
      thread("c"),
    ];

    const sorted = sortThreadsForDisplay(threads, new Set(["c"]));

    expect(sorted.map((t) => t.id)).toEqual(["c", "a", "b"]);
  });

  it("sinks resolved threads below active ones regardless of touch", () => {
    // A resolved thread that was just touched (e.g. it was the
    // resolution itself) still sinks below active threads. The pulse
    // animation handles the recency cue; layout-wise, active threads
    // own the top of the panel because they still drive play.
    const threads = [
      thread("a", "active"),
      thread("b", "resolved"),
      thread("c", "active"),
    ];

    const sorted = sortThreadsForDisplay(threads, new Set(["b"]));

    expect(sorted.map((t) => t.id)).toEqual(["a", "c", "b"]);
  });

  it("preserves canonical order within each (status, touched) bucket", () => {
    // Threads created earlier in the campaign should stay above
    // threads created later when neither was touched in the latest
    // turn — otherwise the panel would reshuffle on every turn even
    // if nothing relevant changed.
    const threads = [
      thread("a"),
      thread("b"),
      thread("c"),
      thread("d", "resolved"),
      thread("e", "resolved"),
    ];

    const sorted = sortThreadsForDisplay(threads, new Set());

    expect(sorted.map((t) => t.id)).toEqual(["a", "b", "c", "d", "e"]);
  });

  it("returns a new array (does not mutate the input)", () => {
    const threads = [thread("a"), thread("b")];
    const sorted = sortThreadsForDisplay(threads, new Set(["b"]));

    expect(sorted).not.toBe(threads);
    expect(threads.map((t) => t.id)).toEqual(["a", "b"]);
  });
});
