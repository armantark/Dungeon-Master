// Tests for the persisted-StageTiming → live-StageProgress adapter.
//
// These guard the contract that the in-trace checklist rendered from
// `GameEvent.stage_timings` looks identical to the live one rendered
// from `streaming.stages`. If the adapter ever drops a field or
// mishandles a null timestamp, the chat surface would silently disagree
// about whether a stage ran — which is exactly the failure mode this
// helper exists to prevent.

import { describe, expect, it } from "vitest";

import {
  formatRoundtripMs,
  stageTimingsToProgress,
  totalRoundtripMs,
} from "./stage-timings";
import type { StageTiming } from "./types";

const ISO_T0 = "2026-05-08T03:00:00.000Z";
const ISO_T100 = "2026-05-08T03:00:00.100Z";
const ISO_T1500 = "2026-05-08T03:00:01.500Z";
const ISO_T12500 = "2026-05-08T03:00:12.500Z";

describe("stageTimingsToProgress", () => {
  it("preserves stage_id, label, status, and original order, including late post-prose stages", () => {
    const timings: StageTiming[] = [
      {
        stage_id: "planning_turn",
        label: "Planning turn",
        status: "skipped",
        started_at: null,
        completed_at: null,
      },
      {
        stage_id: "preparing_narration",
        label: "Preparing narration",
        status: "done",
        started_at: ISO_T0,
        completed_at: ISO_T100,
      },
      {
        stage_id: "reconciling_continuity",
        label: "Reconciling continuity",
        status: "done",
        started_at: ISO_T100,
        completed_at: ISO_T1500,
      },
    ];
    const progress = stageTimingsToProgress(timings);

    expect(progress).toEqual([
      {
        stageId: "planning_turn",
        label: "Planning turn",
        status: "skipped",
        order: 0,
        startedAt: null,
        completedAt: null,
      },
      {
        stageId: "preparing_narration",
        label: "Preparing narration",
        status: "done",
        order: 1,
        startedAt: Date.parse(ISO_T0),
        completedAt: Date.parse(ISO_T100),
      },
      {
        stageId: "reconciling_continuity",
        label: "Reconciling continuity",
        status: "done",
        order: 2,
        startedAt: Date.parse(ISO_T100),
        completedAt: Date.parse(ISO_T1500),
      },
    ]);
  });

  it("returns empty array for empty input", () => {
    expect(stageTimingsToProgress([])).toEqual([]);
  });
});

describe("totalRoundtripMs", () => {
  it("returns null when no stage has both endpoints somewhere in the list", () => {
    // Both fields nullable: an entirely-skipped pipeline (e.g. a
    // future "all stages skipped" route) should not surface a "Total"
    // pill at all rather than reporting 0ms.
    expect(
      totalRoundtripMs([
        {
          stage_id: "x",
          label: "X",
          status: "skipped",
          started_at: null,
          completed_at: null,
        },
      ]),
    ).toBeNull();
  });

  it("spans earliest start to latest end across the whole pipeline", () => {
    // Anchors the "wall-clock roundtrip" semantics: even when stages
    // overlap (the parallel thread/NPC updaters do), the total is
    // earliest-start to latest-end, not a sum of per-stage durations.
    const timings: StageTiming[] = [
      {
        stage_id: "a",
        label: "A",
        status: "done",
        started_at: ISO_T0,
        completed_at: ISO_T100,
      },
      {
        stage_id: "b",
        label: "B",
        status: "done",
        started_at: ISO_T100,
        completed_at: ISO_T1500,
      },
      {
        stage_id: "c",
        label: "C",
        status: "skipped",
        started_at: null,
        completed_at: null,
      },
      {
        stage_id: "d",
        label: "D",
        status: "done",
        started_at: ISO_T1500,
        completed_at: ISO_T12500,
      },
    ];
    expect(totalRoundtripMs(timings)).toBe(12500);
  });
});

describe("formatRoundtripMs", () => {
  it("uses ms below one second", () => {
    expect(formatRoundtripMs(0)).toBe("0ms");
    expect(formatRoundtripMs(42)).toBe("42ms");
    expect(formatRoundtripMs(999)).toBe("999ms");
  });

  it("uses single-decimal seconds at or above one second", () => {
    expect(formatRoundtripMs(1000)).toBe("1.0s");
    expect(formatRoundtripMs(1234)).toBe("1.2s");
    expect(formatRoundtripMs(12500)).toBe("12.5s");
  });
});
