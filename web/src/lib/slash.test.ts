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

  it("parses each acquisition verb and preserves the typed verb", () => {
    expect(parseTurn("/loot the captain's chest")).toEqual({
      kind: "acquire",
      verb: "loot",
      body: "the captain's chest",
    });
    expect(parseTurn("/take a wax-sealed letter from the altar")).toEqual({
      kind: "acquire",
      verb: "take",
      body: "a wax-sealed letter from the altar",
    });
    expect(parseTurn("/buy a flagon of ale and a hooded cloak")).toEqual({
      kind: "acquire",
      verb: "buy",
      body: "a flagon of ale and a hooded cloak",
    });
    expect(parseTurn("/acquire the gift the abbess offered me")).toEqual({
      kind: "acquire",
      verb: "acquire",
      body: "the gift the abbess offered me",
    });
  });

  it("collapses /gain and /purchase onto their canonical verbs", () => {
    // We expose `gain` as a synonym for `acquire` and `purchase` for
    // `buy` so the suggestion menu stays compact while still letting
    // players type the verb that matches their fictional intent.
    expect(parseTurn("/gain a healer's kit from Solyn")).toMatchObject({
      kind: "acquire",
      verb: "acquire",
    });
    expect(parseTurn("/purchase rope and a lantern")).toMatchObject({
      kind: "acquire",
      verb: "buy",
    });
  });

  it("parses /retire with no arguments as an unsummarized retirement close", () => {
    expect(parseTurn("/retire")).toEqual({
      kind: "end",
      reason: "retirement",
      summary: "",
    });
  });

  it("parses /retire with an explicit summary as the player's closing prose", () => {
    expect(parseTurn("/retire I hang the blade above the hearth.")).toEqual({
      kind: "end",
      reason: "retirement",
      summary: "I hang the blade above the hearth.",
    });
  });

  it("parses /victory with no arguments as an unsummarized victory close", () => {
    expect(parseTurn("/victory")).toEqual({
      kind: "end",
      reason: "victory",
      summary: "",
    });
  });

  it("parses /victory with an explicit summary as the player's closing prose", () => {
    expect(parseTurn("/victory The crown is unmade.")).toEqual({
      kind: "end",
      reason: "victory",
      summary: "The crown is unmade.",
    });
  });

  it("trims whitespace from the closing summary", () => {
    expect(parseTurn("/retire    a quiet life by the sea   ")).toEqual({
      kind: "end",
      reason: "retirement",
      summary: "a quiet life by the sea",
    });
  });

  it("parses /explain with the question as the body", () => {
    expect(parseTurn("/explain how does atk work?")).toEqual({
      kind: "explain",
      question: "how does atk work?",
    });
  });

  it("trims surrounding whitespace from the explain question", () => {
    expect(parseTurn("/explain    why did that say ambush?   ")).toEqual({
      kind: "explain",
      question: "why did that say ambush?",
    });
  });

  it("rejects /explain with no body and names the command in the error", () => {
    // Empty-body errors live at the parser to avoid round-tripping
    // a request that the backend's `min_length=1` validator would
    // reject anyway. The error message must namedrop /explain so the
    // player doesn't have to consult /help to figure out what
    // command produced the hint.
    const result = parseTurn("/explain");
    expect(result.kind).toBe("error");
    if (result.kind === "error") {
      expect(result.message).toContain("/explain");
    }
  });

  it("rejects acquisition commands without a body and names the verb in the error", () => {
    for (const cmd of ["acquire", "loot", "take", "buy"]) {
      const result = parseTurn(`/${cmd}`);
      expect(result.kind).toBe("error");
      if (result.kind === "error") {
        // The error message should namedrop the verb the player typed
        // so it's obvious which command needs the missing body.
        expect(result.message).toContain(`/${cmd}`);
      }
    }
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

  it("surfaces every acquisition verb under its own descriptor", () => {
    // Each acquisition verb has a fictionally distinct connotation, so
    // we want all four canonical names to appear in the suggestion
    // menu rather than collapsing them under one entry. The /a prefix
    // intersects "acquire" and "ask"; we only assert the acquisition
    // verb is present.
    const acquireMatches = suggestSlashCommands("/ac");
    expect(acquireMatches.map((c) => c.name)).toContain("acquire");
    const lootMatches = suggestSlashCommands("/lo");
    expect(lootMatches.map((c) => c.name)).toContain("loot");
    const takeMatches = suggestSlashCommands("/ta");
    expect(takeMatches.map((c) => c.name)).toContain("take");
    const buyMatches = suggestSlashCommands("/bu");
    expect(buyMatches.map((c) => c.name)).toContain("buy");
  });

  it("matches /purchase and /gain through aliases on the canonical descriptors", () => {
    expect(suggestSlashCommands("/pur").map((c) => c.name)).toContain("buy");
    expect(suggestSlashCommands("/ga").map((c) => c.name)).toContain("acquire");
  });

  it("surfaces /explain as a discoverable descriptor distinct from /help", () => {
    // `/help` is the static command-list reference; `/explain` is a
    // live LLM-backed, state-aware question. They must not collapse
    // into one another in the suggestion menu — players expect
    // typing `/ex` to surface the explainer, and typing `/he` to
    // surface the help reference.
    expect(suggestSlashCommands("/ex").map((c) => c.name)).toContain("explain");
    const explainEntry = SLASH_COMMANDS.find((c) => c.name === "explain");
    expect(explainEntry).toBeDefined();
    expect(explainEntry?.usage).toContain("question");
  });

  it("surfaces /retire and /victory as separate descriptors so the menu reads them as distinct lifecycle ops", () => {
    // Both terminal-close commands have to be discoverable in their
    // own right; collapsing them under one alias would lose the
    // chosen reason at the menu level and force a sub-arg.
    expect(suggestSlashCommands("/ret").map((c) => c.name)).toContain("retire");
    expect(suggestSlashCommands("/vi").map((c) => c.name)).toContain("victory");
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
