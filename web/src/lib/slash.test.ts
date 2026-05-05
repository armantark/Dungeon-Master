import { describe, expect, it } from "vitest";
import { parseTurn, suggestSlashCommands, SLASH_COMMANDS, SLASH_HELP } from "./slash";

describe("parseTurn", () => {
  it("treats free text as a player action", () => {
    const result = parseTurn("I sift the ash for fresh boot tracks.");
    expect(result).toEqual({
      kind: "action",
      text: "I sift the ash for fresh boot tracks.",
    });
  });

  it("trims whitespace before classifying", () => {
    expect(parseTurn("   /event   ")).toEqual({ kind: "event" });
    expect(parseTurn("   ")).toEqual({ kind: "error", message: "" });
  });

  it("parses /ask with default likelihood", () => {
    const result = parseTurn("/ask Is the gate watched?");
    expect(result).toEqual({
      kind: "ask",
      question: "Is the gate watched?",
      likelihood: "Even odds",
    });
  });

  it("parses /ask with a [likelihood] hint and strips it from the question", () => {
    const result = parseTurn("/ask Is the gate watched? [unlikely]");
    expect(result).toEqual({
      kind: "ask",
      question: "Is the gate watched?",
      likelihood: "Unlikely",
    });
  });

  it("recognizes hyphenated likelihood hints", () => {
    expect(parseTurn("/ask Will it rain? [very-likely]")).toMatchObject({
      kind: "ask",
      likelihood: "Very likely",
    });
    expect(parseTurn("/ask Is it certain? [nearly certain]")).toMatchObject({
      kind: "ask",
      likelihood: "Nearly certain",
    });
  });

  it("falls back to even-odds when the hint is unknown", () => {
    const result = parseTurn("/ask Is it raining? [maybe-someday]");
    expect(result).toMatchObject({
      kind: "ask",
      likelihood: "Even odds",
      // Unknown hints stay attached to the question rather than silently
      // disappearing; the player will see they typed something we didn't
      // understand and can correct it.
      question: "Is it raining? [maybe-someday]",
    });
  });

  it("parses /chaos with bounds checks", () => {
    expect(parseTurn("/chaos 7")).toEqual({ kind: "chaos", value: 7 });
    expect(parseTurn("/chaos 0")).toMatchObject({ kind: "error" });
    expect(parseTurn("/chaos 10")).toMatchObject({ kind: "error" });
    expect(parseTurn("/chaos high")).toMatchObject({ kind: "error" });
  });

  it("parses /scene with the expected scene as the body", () => {
    expect(parseTurn("/scene cross the bone bridge before dawn")).toEqual({
      kind: "scene",
      expected: "cross the bone bridge before dawn",
    });
  });

  it("rejects /scene with no body", () => {
    expect(parseTurn("/scene")).toMatchObject({ kind: "error" });
  });

  it("recognizes /reset and /help and /event aliases", () => {
    expect(parseTurn("/reset")).toEqual({ kind: "reset" });
    expect(parseTurn("/help")).toEqual({ kind: "help" });
    expect(parseTurn("/ev")).toEqual({ kind: "event" });
    expect(parseTurn("/sc bone bridge")).toEqual({
      kind: "scene",
      expected: "bone bridge",
    });
  });

  it("rejects unknown commands", () => {
    const result = parseTurn("/banana");
    expect(result.kind).toBe("error");
    if (result.kind === "error") {
      expect(result.message).toContain("Unknown");
    }
  });

  it("parses /retreat with no arguments as a no-reason retreat", () => {
    expect(parseTurn("/retreat")).toEqual({ kind: "retreat", reason: "" });
  });

  it("parses /retreat with a reason and trims whitespace", () => {
    expect(parseTurn("/retreat   down the chapel stair  ")).toEqual({
      kind: "retreat",
      reason: "down the chapel stair",
    });
  });

  it("treats /flee and /disengage as retreat aliases", () => {
    expect(parseTurn("/flee")).toEqual({ kind: "retreat", reason: "" });
    expect(parseTurn("/disengage through the cloister")).toEqual({
      kind: "retreat",
      reason: "through the cloister",
    });
  });
});

describe("suggestSlashCommands", () => {
  it("returns no suggestions for free-text input", () => {
    expect(suggestSlashCommands("I sneak forward")).toEqual([]);
  });

  it("returns the full command list for a bare slash", () => {
    expect(suggestSlashCommands("/")).toEqual(SLASH_COMMANDS);
  });

  it("filters commands by canonical-name prefix", () => {
    const matches = suggestSlashCommands("/re");
    const names = matches.map((c) => c.name);
    expect(names).toContain("retreat");
    expect(names).toContain("reset");
    expect(names).not.toContain("ask");
    expect(names).not.toContain("event");
  });

  it("matches aliases too", () => {
    const matches = suggestSlashCommands("/fl");
    expect(matches.map((c) => c.name)).toEqual(["retreat"]);
  });

  it("suppresses suggestions once an argument is being typed", () => {
    expect(suggestSlashCommands("/ask Is the gate")).toEqual([]);
    expect(suggestSlashCommands("/retreat down the stair")).toEqual([]);
  });

  it("ignores leading whitespace before the slash", () => {
    expect(suggestSlashCommands("   /he").map((c) => c.name)).toEqual(["help"]);
  });
});

describe("SLASH_HELP", () => {
  it("documents every command in the descriptor list", () => {
    for (const cmd of SLASH_COMMANDS) {
      expect(SLASH_HELP).toContain(cmd.usage);
      expect(SLASH_HELP).toContain(cmd.summary);
    }
  });
});
