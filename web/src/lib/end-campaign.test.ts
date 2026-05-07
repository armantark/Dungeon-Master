import { describe, expect, it } from "vitest";

import {
  endHeadline,
  endKicker,
  endSummary,
  formatEndedAt,
  isCampaignEnded,
} from "./end-campaign";
import type { CampaignEndReason, GameState } from "./types";

function emptyOracleTables(): GameState["oracle_tables"] {
  return {
    event_focus: [],
    event_actions: [],
    event_tones: [],
    event_subjects: [],
  };
}

// We build a minimal GameState here rather than importing a fixture
// from another test file because the F-06 helpers only read four
// fields (campaign_status / reason / ended_at / summary). Keeping the
// factory local makes the test's contract obvious — adding
// unrelated GameState fields elsewhere shouldn't perturb this suite.
function endedState(overrides: Partial<GameState>): GameState {
  return {
    id: "state_test",
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
    chaos_factor: 5,
    scene_number: 1,
    current_scene: "",
    scene_status: "expected",
    campaign_status: "ended",
    campaign_end_reason: overrides.campaign_end_reason ?? "retirement",
    campaign_ended_at: overrides.campaign_ended_at ?? null,
    campaign_end_summary: overrides.campaign_end_summary ?? null,
    npc_roster_version: 2,
    setting_notes: "",
    player_notes: "",
    directives: { world_guidance: "", play_guidance: "" },
    threads: [],
    npcs: [],
    hidden_npcs: [],
    oracle_tables: emptyOracleTables(),
    oracle_history: [],
    action_log: [],
    ...overrides,
  };
}

describe("isCampaignEnded", () => {
  it("returns false for null state", () => {
    expect(isCampaignEnded(null)).toBe(false);
  });

  it("returns false for active or setup state", () => {
    expect(
      isCampaignEnded(endedState({ campaign_status: "active" })),
    ).toBe(false);
    expect(
      isCampaignEnded(endedState({ campaign_status: "character_creation" })),
    ).toBe(false);
  });

  it("returns true only when campaign_status is the terminal 'ended'", () => {
    expect(isCampaignEnded(endedState({}))).toBe(true);
  });
});

describe("endKicker / endHeadline", () => {
  // We assert the *shape* of the per-reason copy rather than the
  // exact strings so future tone polish (e.g. "Cairn marker" → "Stone
  // remembers") doesn't churn the test, but a wrong-reason mapping
  // (death copy on a victory close) still fails.
  const reasons: CampaignEndReason[] = ["death", "retirement", "victory"];

  it("returns a non-empty kicker for every reason", () => {
    for (const reason of reasons) {
      expect(endKicker(reason).trim()).not.toBe("");
    }
  });

  it("returns a non-empty headline for every reason", () => {
    for (const reason of reasons) {
      expect(endHeadline(reason).trim()).not.toBe("");
    }
  });

  it("emits distinct headlines per reason so the banner reads as the close that happened", () => {
    const headlines = new Set(reasons.map(endHeadline));
    expect(headlines.size).toBe(reasons.length);
  });
});

describe("endSummary", () => {
  it("returns the backend-authored summary verbatim when present", () => {
    const summary = "I leave the road for the orchard.";
    const gs = endedState({
      campaign_end_reason: "retirement",
      campaign_end_summary: summary,
    });
    expect(endSummary(gs)).toBe(summary);
  });

  it("falls back to a deterministic per-reason default when summary is null", () => {
    const death = endSummary(
      endedState({ campaign_end_reason: "death", campaign_end_summary: null }),
    );
    const victory = endSummary(
      endedState({ campaign_end_reason: "victory", campaign_end_summary: null }),
    );

    expect(death.trim()).not.toBe("");
    expect(victory.trim()).not.toBe("");
    expect(death).not.toBe(victory);
  });

  it("treats an empty / whitespace-only summary the same as null", () => {
    const gs = endedState({
      campaign_end_reason: "victory",
      campaign_end_summary: "   ",
    });
    expect(endSummary(gs).trim()).not.toBe("");
  });

  it("returns an empty string when reason is null (live campaign)", () => {
    const gs = endedState({
      campaign_status: "active",
      campaign_end_reason: null,
    });
    expect(endSummary(gs)).toBe("");
  });
});

describe("formatEndedAt", () => {
  it("returns null for null / empty input", () => {
    expect(formatEndedAt(null)).toBeNull();
    expect(formatEndedAt("")).toBeNull();
  });

  it("returns null for an unparseable date string", () => {
    expect(formatEndedAt("not-a-date")).toBeNull();
  });

  it("returns a non-empty localized string for a valid ISO timestamp", () => {
    // We don't assert the exact format because toLocaleString output
    // varies by locale; we only require that the helper produced
    // *something* for a parseable input. The test environment's
    // locale is stable for the duration of one test run.
    const formatted = formatEndedAt("2024-04-12T09:30:00Z");
    expect(formatted).not.toBeNull();
    expect((formatted ?? "").trim()).not.toBe("");
  });
});
