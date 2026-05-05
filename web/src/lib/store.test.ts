import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "./api";
import { game } from "./store.svelte";

describe("GameStore setup streaming", () => {
  afterEach(() => {
    vi.restoreAllMocks();
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
    };
    game.notes = [];
    game.inspectorOpen = false;
  });

  it("translates /retreat into a free-text turn so the planner runs", async () => {
    const streamSpy = vi
      .spyOn(api, "streamSubmitTurn")
      .mockResolvedValue({ kind: "final" } as never);

    const consumed = await game.submit("/retreat down the chapel stair");

    expect(consumed).toBe(true);
    expect(streamSpy).toHaveBeenCalledTimes(1);
    const [textArg] = streamSpy.mock.calls[0]!;
    expect(textArg).toBe(
      "I attempt to retreat from combat: down the chapel stair",
    );
  });

  it("uses a neutral default text when /retreat has no reason", async () => {
    const streamSpy = vi
      .spyOn(api, "streamSubmitTurn")
      .mockResolvedValue({ kind: "final" } as never);

    await game.submit("/retreat");

    const [textArg] = streamSpy.mock.calls[0]!;
    expect(textArg).toBe("I attempt to retreat from combat.");
  });

  it("surfaces server-aborted setup streams as an error instead of silent null", async () => {
    vi.spyOn(api, "streamCharacterQuiz").mockResolvedValue({
      kind: "aborted",
      reason: "server",
    } as never);
    vi.spyOn(api, "generateCharacterQuiz").mockResolvedValue({
      quiz: {
        concept: "unused",
        questions: [],
      },
      thinking: "",
    } as never);

    const result = await game.generateCharacterQuiz("A scarred deserter.");

    expect(result).toBeNull();
    expect(game.error).toBe("The request ended before a final result arrived.");
    expect(game.isLoading).toBe(false);
  });
});
