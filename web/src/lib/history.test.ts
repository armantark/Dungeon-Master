import { describe, expect, it } from "vitest";

import {
  deriveTranscriptRows,
  filterOracleHistory,
  findNarrativeEventForOracle,
  searchTranscript,
} from "./history";
import { defaultCampaignSeed } from "./campaign-seed";
import type { ClientNote } from "./store.svelte";
import type {
  CairnResolution,
  GameEvent,
  GameState,
  OracleKind,
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

function event(overrides: Partial<GameEvent>): GameEvent {
  return {
    id: overrides.id ?? "ev",
    created_at: overrides.created_at ?? "2024-01-01T00:00:00Z",
    event_type: overrides.event_type ?? "narrative",
    title: overrides.title ?? "",
    content: overrides.content ?? "",
    oracle_outcome_id: overrides.oracle_outcome_id ?? null,
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

function state(overrides: Partial<GameState> = {}): GameState {
  return {
    id: overrides.id ?? "state_test",
    created_at: overrides.created_at ?? "2024-01-01T00:00:00Z",
    updated_at: overrides.updated_at ?? "2024-01-01T00:00:00Z",
    chaos_factor: overrides.chaos_factor ?? 5,
    scene_number: overrides.scene_number ?? 1,
    current_scene: overrides.current_scene ?? "",
    scene_status: overrides.scene_status ?? "expected",
    campaign_status: overrides.campaign_status ?? "active",
    campaign_end_reason: overrides.campaign_end_reason ?? null,
    campaign_ended_at: overrides.campaign_ended_at ?? null,
    campaign_end_summary: overrides.campaign_end_summary ?? null,
    party_members: overrides.party_members ?? [],
    npc_roster_version: overrides.npc_roster_version ?? 2,
    setting_notes: overrides.setting_notes ?? "",
    player_notes: overrides.player_notes ?? "",
    directives: overrides.directives ?? { world_guidance: "", play_guidance: "" },
    threads: overrides.threads ?? [],
    npcs: overrides.npcs ?? [],
    hidden_npcs: overrides.hidden_npcs ?? [],
    oracle_tables: overrides.oracle_tables ?? emptyOracleTables(),
    oracle_history: overrides.oracle_history ?? [],
    action_log: overrides.action_log ?? [],
    campaign_seed: overrides.campaign_seed ?? defaultCampaignSeed(),
  };
}

function note(id: string, text: string, created_at: string): ClientNote {
  return { id, kind: "info", text, created_at };
}

describe("deriveTranscriptRows", () => {
  it("synthesizes an opening DM row when no narrative events exist", () => {
    const gs = state({
      id: "state_xyz",
      current_scene: "The chapel doors stand open.",
      setting_notes: "Cold rain on slate.",
      action_log: [
        event({
          id: "sys1",
          event_type: "system",
          content: "Campaign initialized",
          created_at: "2024-01-01T00:00:01Z",
        }),
      ],
    });

    const rows = deriveTranscriptRows(gs);

    // Opening row is first because state.created_at < event.created_at.
    expect(rows.length).toBe(2);
    expect(rows[0]!.id).toBe("opening_state_xyz");
    expect(rows[0]!.kind).toBe("dm");
    expect(rows[0]!.isOpening).toBe(true);
    expect(rows[0]!.text).toContain("chapel doors");
    expect(rows[0]!.text).toContain("Cold rain");
    expect(rows[1]!.kind).toBe("system");
  });

  it("suppresses the synthesized opening once any narrative event exists", () => {
    // The opening row is a stand-in for the first DM beat. Once the
    // model has authored real narration, keeping the synthesized row
    // would double-render the opening — exactly the bug ChatFeed
    // already guards against, mirrored here for the search surface.
    const gs = state({
      action_log: [
        event({
          id: "n1",
          event_type: "narrative",
          content: "The doors groan inward.",
          created_at: "2024-01-01T00:01:00Z",
        }),
      ],
    });

    const rows = deriveTranscriptRows(gs);

    expect(rows.length).toBe(1);
    expect(rows[0]!.id).toBe("n1");
    expect(rows[0]!.isOpening).toBe(false);
  });

  it("folds oracle events into receipts under matching narrative rows", () => {
    // Same dedup rule as ChatFeed: an oracle event is *not* its own
    // row. Including it would inflate search results and make the
    // inspector list show two hits ("Yes" plus the prose) for one
    // moment.
    const gs = state({
      oracle_history: [
        outcome({ id: "o1", kind: "yes_no", answer: "Yes", summary: "Yes (78%)" }),
      ],
      action_log: [
        event({
          id: "ev_oracle",
          event_type: "oracle",
          content: "Yes",
          created_at: "2024-01-01T00:02:00Z",
          oracle_outcome_id: "o1",
        }),
        event({
          id: "ev_narr",
          event_type: "narrative",
          content: "The gate is watched.",
          created_at: "2024-01-01T00:02:01Z",
          oracle_outcome_id: "o1",
        }),
      ],
    });

    const rows = deriveTranscriptRows(gs);

    expect(rows.map((r) => r.kind)).toEqual(["dm"]);
    expect(rows[0]!.id).toBe("ev_narr");
    expect(rows[0]!.outcomeSummary).toBe("Yes (78%)");
  });

  it("orders rows chronologically and interleaves client notes", () => {
    const gs = state({
      action_log: [
        event({
          id: "p1",
          event_type: "player",
          content: "I knock.",
          created_at: "2024-01-01T00:00:10Z",
        }),
        event({
          id: "n1",
          event_type: "narrative",
          content: "No answer.",
          created_at: "2024-01-01T00:00:30Z",
        }),
      ],
    });
    const notes: ClientNote[] = [
      note("note1", "Slash help: /ask", "2024-01-01T00:00:20Z"),
    ];

    const rows = deriveTranscriptRows(gs, notes);

    expect(rows.map((r) => r.id)).toEqual(["p1", "note1", "n1"]);
    expect(rows[1]!.isNote).toBe(true);
    expect(rows[1]!.kind).toBe("system");
  });
});

describe("findNarrativeEventForOracle", () => {
  it("returns the narrative event id linked to the outcome", () => {
    const gs = state({
      oracle_history: [outcome({ id: "o1" })],
      action_log: [
        event({ id: "n1", event_type: "narrative", oracle_outcome_id: "o1" }),
      ],
    });

    expect(findNarrativeEventForOracle(gs, "o1")).toBe("n1");
  });

  it("returns null when no narrative event has committed against the outcome", () => {
    // The outcome exists but a regenerate-cancel discarded the prose,
    // so there's nothing to scroll to. Returning null lets the
    // inspector's deep-link button disable itself rather than send
    // the user to a dead anchor.
    const gs = state({
      oracle_history: [outcome({ id: "o1" })],
      action_log: [event({ id: "p1", event_type: "player" })],
    });

    expect(findNarrativeEventForOracle(gs, "o1")).toBeNull();
  });

  it("returns the latest narrative event when regenerate produced a new one", () => {
    // Regenerate keeps the deterministic outcome and replaces only
    // the prose, so two narrative events can share an
    // `oracle_outcome_id`. The freshly-regenerated row is the one
    // the player wants to read, so we pick the chronologically last
    // match in `action_log`.
    const gs = state({
      oracle_history: [outcome({ id: "o1" })],
      action_log: [
        event({
          id: "n_old",
          event_type: "narrative",
          oracle_outcome_id: "o1",
          created_at: "2024-01-01T00:01:00Z",
        }),
        event({
          id: "n_new",
          event_type: "narrative",
          oracle_outcome_id: "o1",
          created_at: "2024-01-01T00:01:30Z",
        }),
      ],
    });

    expect(findNarrativeEventForOracle(gs, "o1")).toBe("n_new");
  });
});

describe("searchTranscript", () => {
  function gsWithRows(): GameState {
    return state({
      action_log: [
        event({
          id: "p1",
          event_type: "player",
          content: "I push past the abbey gate.",
          created_at: "2024-01-01T00:00:01Z",
        }),
        event({
          id: "n1",
          event_type: "narrative",
          content: "The marauders watch from the colonnade.",
          oracle_outcome_id: "o1",
          created_at: "2024-01-01T00:00:02Z",
        }),
        event({
          id: "n2",
          event_type: "narrative",
          content: "An abbot raises his hand.",
          oracle_outcome_id: "o2",
          created_at: "2024-01-01T00:00:03Z",
        }),
      ],
      oracle_history: [
        outcome({ id: "o1", summary: "marauders, three of them" }),
        outcome({ id: "o2", summary: "abbot's blessing" }),
      ],
    });
  }

  it("returns no matches for an empty or whitespace-only query", () => {
    const rows = deriveTranscriptRows(gsWithRows());

    expect(searchTranscript(rows, "").length).toBe(0);
    expect(searchTranscript(rows, "   ").length).toBe(0);
  });

  it("matches case-insensitively on row text", () => {
    const rows = deriveTranscriptRows(gsWithRows());

    const hits = searchTranscript(rows, "ABBEY");

    expect(hits.length).toBe(1);
    expect(hits[0]!.rowId).toBe("p1");
    expect(hits[0]!.source).toBe("text");
    expect(hits[0]!.snippet.toLowerCase()).toContain("abbey");
  });

  it("matches in receipt summary on DM rows when the prose doesn't contain the term", () => {
    // 'three of them' lives only on the outcome summary. A naive
    // search that only walked event text would miss this.
    const rows = deriveTranscriptRows(gsWithRows());

    const hits = searchTranscript(rows, "three of them");

    expect(hits.length).toBe(1);
    expect(hits[0]!.rowId).toBe("n1");
    expect(hits[0]!.source).toBe("outcome");
  });

  it("requires every whitespace-separated token to match (token-AND)", () => {
    const rows = deriveTranscriptRows(gsWithRows());

    // 'abbot' only appears in n2; 'marauders' only in n1/o1. AND
    // semantics means neither row has both -> no hits.
    expect(searchTranscript(rows, "abbot marauders").length).toBe(0);
    // 'abbot blessing' both appear on n2 (prose + outcome). Token-
    // AND is satisfied because we test prose first; the prose
    // contains 'abbot' and would still need a second token. Use
    // 'abbot raises' which is wholly in the prose.
    const hits = searchTranscript(rows, "abbot raises");
    expect(hits.length).toBe(1);
    expect(hits[0]!.rowId).toBe("n2");
  });

  it("excludes ephemeral client notes by default and includes them on opt-in", () => {
    // Notes are slash-help / error toasts. Letting them surface in
    // search by default would teleport the player to a row that has
    // since been dismissed, which is worse than not finding it at
    // all. The opt-in lets a future "include client feedback" toggle
    // turn it on.
    const gs = state({
      action_log: [
        event({
          id: "p1",
          event_type: "player",
          content: "I check the map.",
          created_at: "2024-01-01T00:00:01Z",
        }),
      ],
    });
    const notes: ClientNote[] = [
      note("note1", "Slash help: /ask", "2024-01-01T00:00:02Z"),
    ];
    const rows = deriveTranscriptRows(gs, notes);

    expect(searchTranscript(rows, "slash").length).toBe(0);
    expect(searchTranscript(rows, "slash", { includeNotes: true }).length).toBe(1);
  });

  it("respects the limit option and stops walking once it hits the cap", () => {
    const rows = deriveTranscriptRows(
      state({
        action_log: Array.from({ length: 10 }, (_, i) =>
          event({
            id: `e${i}`,
            event_type: "player",
            content: "I look for the rune.",
            created_at: `2024-01-01T00:00:${String(i).padStart(2, "0")}Z`,
          }),
        ),
      }),
    );

    const hits = searchTranscript(rows, "rune", { limit: 3 });

    expect(hits.length).toBe(3);
    // First 3 chronologically — limit must apply to chronological
    // order, not to insertion order, otherwise scrolling through
    // results would feel non-deterministic across re-mounts.
    expect(hits.map((h) => h.rowId)).toEqual(["e0", "e1", "e2"]);
  });

  it("centers the snippet on the first matched token with ellipsis at trimmed boundaries", () => {
    const rows = deriveTranscriptRows(
      state({
        action_log: [
          event({
            id: "n1",
            event_type: "narrative",
            content: `${"x".repeat(200)} ambush ${"y".repeat(200)}`,
            created_at: "2024-01-01T00:00:01Z",
          }),
        ],
      }),
    );

    const hits = searchTranscript(rows, "ambush");

    expect(hits.length).toBe(1);
    const hit = hits[0]!;
    expect(hit.snippet.startsWith("…")).toBe(true);
    expect(hit.snippet.endsWith("…")).toBe(true);
    // Highlight offsets must point at the matched substring inside
    // the rendered snippet (not the full row text), otherwise a
    // <mark> wrapper would highlight the wrong characters.
    expect(hit.snippet.slice(hit.highlightStart, hit.highlightEnd)).toBe("ambush");
  });
});

describe("filterOracleHistory", () => {
  function harmCairn(overrides: Partial<CairnResolution> = {}): CairnResolution {
    return {
      ability: null,
      target: null,
      success: null,
      rest_kind: null,
      time_advance: null,
      day_number_before: null,
      day_number_after: null,
      watch_index_before: null,
      watch_index_after: null,
      day_phase_before: null,
      day_phase_after: null,
      watches_since_meal_before: null,
      watches_since_meal_after: null,
      watches_since_sleep_before: null,
      watches_since_sleep_after: null,
      food_deprived_before: null,
      food_deprived_after: null,
      sleep_deprived_before: null,
      sleep_deprived_after: null,
      deprived_before: null,
      deprived_after: null,
      ration_item_id: null,
      ration_item_name: null,
      ration_uses_before: null,
      ration_uses_after: null,
      actor_id: null,
      actor_name: null,
      item_id: null,
      item_name: null,
      item_power_kind: null,
      item_effect_kind: null,
      effect_summary: null,
      uses_before: null,
      uses_after: null,
      recharge_condition: null,
      attack_stance: null,
      weapon_item_id: null,
      weapon_name: null,
      target_name: null,
      target_armor: null,
      base_damage: null,
      damage_after_armor: null,
      hp_before: null,
      hp_after: null,
      str_before: null,
      str_after: null,
      dex_before: null,
      dex_after: null,
      wil_before: null,
      wil_after: null,
      fatigue_before: null,
      fatigue_after: null,
      scar_result: null,
      overloaded: null,
      ...overrides,
    };
  }

  function history(): readonly OracleOutcome[] {
    return [
      outcome({ id: "o1", kind: "yes_no", summary: "Yes (78%)" }),
      outcome({
        id: "o2",
        kind: "random_event",
        summary: "Strangers arrive",
        event_focus: "NPC action",
      }),
      outcome({
        id: "o3",
        kind: "harm",
        summary: "Harm 4 HP",
        cairn: harmCairn({
          target_name: "Ash-Bound Leper",
          weapon_name: "rusted hook",
          scar_result: "white scar across the brow",
        }),
      }),
    ];
  }

  it("returns the input array unchanged when no query and no kinds are set", () => {
    const all = history();
    const filtered = filterOracleHistory(all, { query: "", kinds: new Set() });
    expect(filtered).toBe(all);
  });

  it("filters by kind whitelist", () => {
    const filtered = filterOracleHistory(history(), {
      query: "",
      kinds: new Set<OracleKind>(["harm", "yes_no"]),
    });
    expect(filtered.map((o) => o.id)).toEqual(["o1", "o3"]);
  });

  it("filters by free-text query against summary and event-flavor fields", () => {
    const filtered = filterOracleHistory(history(), {
      query: "strangers",
      kinds: new Set(),
    });
    expect(filtered.map((o) => o.id)).toEqual(["o2"]);
  });

  it("matches against Cairn target/weapon/scar text", () => {
    // 'leper' / 'hook' / 'white scar' are the player's actual mental
    // index for a combat moment — the deterministic summary often
    // reads as 'Harm 4 HP', which is unsearchable on its own.
    const cases = ["leper", "hook", "white scar"];
    for (const term of cases) {
      const filtered = filterOracleHistory(history(), {
        query: term,
        kinds: new Set(),
      });
      expect(filtered.map((o) => o.id)).toEqual(["o3"]);
    }
  });

  it("requires both kind and query to match when both are set", () => {
    const filtered = filterOracleHistory(history(), {
      query: "strangers",
      kinds: new Set<OracleKind>(["harm"]),
    });
    expect(filtered.length).toBe(0);
  });
});
