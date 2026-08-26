import { describe, expect, it, vi } from "vitest";

import {
  applyStageEvent,
  applyStateTerminal,
  stateTerminal,
} from "./stream-runner";

describe("stream runner", () => {
  it("keeps stage order while reducing status updates", () => {
    const pending = applyStageEvent([], {
      type: "stage",
      stage_id: "planning",
      label: "Planning",
      status: "pending",
    }, 10);
    const done = applyStageEvent(pending, {
      type: "stage",
      stage_id: "planning",
      label: "Planning",
      status: "done",
    }, 20);

    expect(done).toEqual([{
      stageId: "planning",
      label: "Planning",
      status: "done",
      order: 0,
      startedAt: null,
      completedAt: 20,
    }]);
  });

  it("applies one returned final state exactly once", () => {
    const replaceState = vi.fn();
    const reportError = vi.fn();
    const result = {
      kind: "final" as const,
      final: {
        type: "final_state" as const,
        state: { id: "state_final" },
        thinking: null,
      },
    } as never;

    const applied = applyStateTerminal(stateTerminal(result), {
      replaceState,
      reportError,
    });

    expect(applied).toBe(true);
    expect(replaceState).toHaveBeenCalledTimes(1);
    expect(replaceState).toHaveBeenCalledWith({ id: "state_final" });
    expect(reportError).not.toHaveBeenCalled();
  });

  it("applies a backend error and its partial state once", () => {
    const replaceState = vi.fn();
    const reportError = vi.fn();
    const result = {
      kind: "error" as const,
      event: {
        type: "error" as const,
        message: "Narration failed.",
        code: "narration_failed",
        state: { id: "state_partial" },
      },
    } as never;

    applyStateTerminal(stateTerminal(result), { replaceState, reportError });

    expect(reportError).toHaveBeenCalledTimes(1);
    expect(replaceState).toHaveBeenCalledTimes(1);
  });
});
