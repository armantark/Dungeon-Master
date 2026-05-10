import { describe, expect, it } from "vitest";

import {
  DEFAULT_NPC_LOOKBACK,
  npcDisplayLabel,
  npcKnownByDescriptor,
  recentlyTouchedNpcIds,
  referencedNpcsForOutcome,
  sortNpcsForDisplay,
} from "./npcs";
import { defaultCampaignSeed } from "./campaign-seed";
import type {
  GameState,
  NPC,
  NPCPlayerLabelKind,
  NPCStatus,
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

function npc(
  id: string,
  status: NPCStatus = "active",
  playerLabel: string = `npc-${id}`,
  labelKind: NPCPlayerLabelKind = "proper_name",
): NPC {
  return {
    id,
    name: `npc-${id}`,
    player_label: playerLabel,
    player_label_kind: labelKind,
    role: "",
    disposition: "",
    status,
  };
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
    party_members: overrides.party_members ?? [],
    npc_roster_version: 2,
    setting_notes: "",
    player_notes: "",
    directives: { world_guidance: "", play_guidance: "" },
    threads: overrides.threads ?? [],
    npcs: overrides.npcs ?? [],
    hidden_npcs: overrides.hidden_npcs ?? [],
    oracle_tables: overrides.oracle_tables ?? emptyOracleTables(),
    oracle_history: overrides.oracle_history ?? [],
    action_log: overrides.action_log ?? [],
    campaign_seed: overrides.campaign_seed ?? defaultCampaignSeed(),
  };
}

describe("recentlyTouchedNpcIds", () => {
  it("returns the plural ids of the latest outcome by default", () => {
    const gs = state({
      oracle_history: [
        outcome({ id: "o1", referenced_npc_ids: ["npc-old"] }),
        outcome({ id: "o2", referenced_npc_ids: ["npc-a", "npc-b"] }),
      ],
    });

    const touched = recentlyTouchedNpcIds(gs);

    expect(DEFAULT_NPC_LOOKBACK).toBe(1);
    expect([...touched].sort()).toEqual(["npc-a", "npc-b"]);
  });

  it("falls back to the legacy singular reference when plural is empty", () => {
    // Older outcomes only carry the singular id. We still want the
    // panel to highlight that NPC on a freshly-loaded older campaign
    // — the alternative is a silent regression where the post-F-04
    // highlight cue disappears for no surfaced reason.
    const gs = state({
      oracle_history: [
        outcome({
          id: "o1",
          referenced_npc_id: "npc-legacy",
          referenced_npc_ids: [],
        }),
      ],
    });

    expect([...recentlyTouchedNpcIds(gs)]).toEqual(["npc-legacy"]);
  });

  it("merges plural and singular without duplicating", () => {
    const gs = state({
      oracle_history: [
        outcome({
          id: "o1",
          referenced_npc_id: "npc-a",
          referenced_npc_ids: ["npc-a", "npc-b"],
        }),
      ],
    });

    expect([...recentlyTouchedNpcIds(gs)].sort()).toEqual(["npc-a", "npc-b"]);
  });

  it("widens to multiple outcomes when lookback > 1", () => {
    const gs = state({
      oracle_history: [
        outcome({ id: "o1", referenced_npc_ids: ["npc-old"] }),
        outcome({ id: "o2", referenced_npc_ids: ["npc-a"] }),
        outcome({ id: "o3", referenced_npc_ids: ["npc-b"] }),
      ],
    });

    expect([...recentlyTouchedNpcIds(gs, 2)].sort()).toEqual(["npc-a", "npc-b"]);
  });

  it("returns an empty set for an empty oracle history", () => {
    expect(recentlyTouchedNpcIds(state({}))).toEqual(new Set());
  });
});

describe("npcDisplayLabel", () => {
  it("prefers the safe player-facing label over the canonical backend name", () => {
    expect(
      npcDisplayLabel(
        npc("a", "active", "the ash-veiled bellringer", "descriptor"),
      ),
    ).toBe("the ash-veiled bellringer");
  });

  it("falls back to the canonical name when the player-facing label is blank", () => {
    expect(npcDisplayLabel(npc("a", "active", "   "))).toBe("npc-a");
  });
});

describe("npcKnownByDescriptor", () => {
  it("is true only for descriptor-visible NPCs", () => {
    expect(
      npcKnownByDescriptor(
        npc("a", "active", "the split-reliquary woman", "descriptor"),
      ),
    ).toBe(true);
    expect(npcKnownByDescriptor(npc("b"))).toBe(false);
  });
});

describe("referencedNpcsForOutcome", () => {
  it("returns visible NPCs in outcome order and drops stale ids", () => {
    const visible = [
      npc("a", "active", "the ash-veiled bellringer", "descriptor"),
      npc("b"),
    ];

    const resolved = referencedNpcsForOutcome(
      visible,
      outcome({
        referenced_npc_ids: ["b", "missing", "a"],
        referenced_npc_id: "a",
      }),
    );

    expect(resolved.map((entry) => entry.id)).toEqual(["b", "a"]);
    expect(resolved.map((entry) => npcDisplayLabel(entry))).toEqual([
      "npc-b",
      "the ash-veiled bellringer",
    ]);
  });
});

describe("sortNpcsForDisplay", () => {
  it("floats active recently-touched NPCs to the top", () => {
    const npcs = [npc("a"), npc("b"), npc("c")];

    const sorted = sortNpcsForDisplay(npcs, new Set(["c"]));

    expect(sorted.map((n) => n.id)).toEqual(["c", "a", "b"]);
  });

  it("sinks retired NPCs below active ones regardless of touch", () => {
    // A retired NPC that was just touched (e.g. they were retired by
    // this very turn) still sinks below active NPCs. The pulse + the
    // "newly retired" pip handle the recency cue; layout-wise, active
    // NPCs own the top of the panel because they still drive play.
    const npcs = [
      npc("a", "active"),
      npc("b", "retired"),
      npc("c", "active"),
    ];

    const sorted = sortNpcsForDisplay(npcs, new Set(["b"]));

    expect(sorted.map((n) => n.id)).toEqual(["a", "c", "b"]);
  });

  it("preserves canonical order within each (status, touched) bucket", () => {
    // NPCs introduced earlier in the campaign should stay above NPCs
    // introduced later when neither was touched in the latest turn —
    // otherwise the panel would reshuffle on every turn even if
    // nothing relevant changed.
    const npcs = [
      npc("a"),
      npc("b"),
      npc("c"),
      npc("d", "retired"),
      npc("e", "retired"),
    ];

    const sorted = sortNpcsForDisplay(npcs, new Set());

    expect(sorted.map((n) => n.id)).toEqual(["a", "b", "c", "d", "e"]);
  });

  it("returns a new array (does not mutate the input)", () => {
    const npcs = [npc("a"), npc("b")];
    const sorted = sortNpcsForDisplay(npcs, new Set(["b"]));

    expect(sorted).not.toBe(npcs);
    expect(npcs.map((n) => n.id)).toEqual(["a", "b"]);
  });
});
