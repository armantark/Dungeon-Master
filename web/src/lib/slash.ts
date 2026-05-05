// Slash-command parser for the Composer.
//
// Why explicit slash commands instead of inferring intent from natural
// language: the player almost always knows when they want a roll vs. a
// pure narrative beat, and inferring wrong is worse than asking for
// punctuation. Free text still works (and the LLM-backed planner will
// classify it), but slashes are the durable explicit fallback when the
// player wants to skip ambiguity.

import type { Likelihood } from "./types";

export type ParsedTurn =
  | { kind: "ask"; question: string; likelihood: Likelihood }
  | { kind: "event" }
  | { kind: "scene"; expected: string }
  | { kind: "chaos"; value: number }
  | { kind: "reset" }
  | { kind: "action"; text: string }
  | { kind: "retreat"; reason: string }
  | { kind: "help" }
  | { kind: "error"; message: string };

const LIKELIHOOD_HINTS: Record<string, Likelihood> = {
  impossible: "Impossible",
  "very-unlikely": "Very unlikely",
  "very_unlikely": "Very unlikely",
  unlikely: "Unlikely",
  even: "Even odds",
  "even-odds": "Even odds",
  likely: "Likely",
  "very-likely": "Very likely",
  "very_likely": "Very likely",
  certain: "Nearly certain",
  "nearly-certain": "Nearly certain",
  "nearly_certain": "Nearly certain",
};

/**
 * Discoverable slash command descriptors.
 *
 * The suggestion menu and `/help` both consume this list, so the player
 * sees the same vocabulary in both surfaces. Aliases come last so the
 * canonical name is what the menu surfaces; we still match on aliases.
 */
export interface SlashCommandDescriptor {
  /** Canonical name (without leading slash). */
  name: string;
  /** Alternate names, also accepted by the parser. */
  aliases: readonly string[];
  /** One-line description, surfaced in the suggestion menu and /help. */
  summary: string;
  /** Usage hint (e.g. `/ask <question> [likely|unlikely|...]`). */
  usage: string;
}

export const SLASH_COMMANDS: readonly SlashCommandDescriptor[] = [
  {
    name: "ask",
    aliases: [],
    summary: "Yes/no oracle question (optionally weighted).",
    usage: "/ask <question> [likely|unlikely|even|...]",
  },
  {
    name: "event",
    aliases: ["ev"],
    summary: "Roll a random campaign event.",
    usage: "/event",
  },
  {
    name: "scene",
    aliases: ["sc"],
    summary: "Scene check — expected / altered / interrupted.",
    usage: "/scene <expected scene>",
  },
  {
    name: "retreat",
    aliases: ["flee", "disengage"],
    summary: "Attempt to disengage from an active encounter.",
    usage: "/retreat [reason]",
  },
  {
    name: "chaos",
    aliases: ["ch"],
    summary: "Set the chaos factor (1–9).",
    usage: "/chaos <1-9>",
  },
  {
    name: "reset",
    aliases: [],
    summary: "Regenerate the campaign opening.",
    usage: "/reset",
  },
  {
    name: "help",
    aliases: ["?"],
    summary: "Show this command list.",
    usage: "/help",
  },
];

const HELP_TEXT = (() => {
  const widest = SLASH_COMMANDS.reduce(
    (acc, cmd) => Math.max(acc, cmd.usage.length),
    0,
  );
  const lines = SLASH_COMMANDS.map((cmd) => {
    const padded = cmd.usage.padEnd(widest, " ");
    return `  ${padded}   ${cmd.summary}`;
  });
  return [
    "Commands:",
    ...lines,
    "",
    "Anything not starting with / is sent as a free-text player action; the GM narrates it and the planner picks any mechanics.",
  ].join("\n");
})();

export const SLASH_HELP = HELP_TEXT;

/**
 * Parse a single composer line into an actionable turn.
 *
 * Whitespace-only input returns `{ kind: 'error' }` so the caller can
 * silently no-op without dispatching anything.
 */
export function parseTurn(input: string): ParsedTurn {
  const trimmed = input.trim();
  if (!trimmed) return { kind: "error", message: "" };

  if (!trimmed.startsWith("/")) {
    return { kind: "action", text: trimmed };
  }

  const spaceIdx = trimmed.indexOf(" ");
  const head = spaceIdx === -1 ? trimmed.slice(1) : trimmed.slice(1, spaceIdx);
  const rest = spaceIdx === -1 ? "" : trimmed.slice(spaceIdx + 1).trim();
  const cmd = head.toLowerCase();

  switch (cmd) {
    case "help":
    case "?":
      return { kind: "help" };

    case "reset":
      return { kind: "reset" };

    case "event":
    case "ev":
      return { kind: "event" };

    case "scene":
    case "sc": {
      if (!rest) return { kind: "error", message: "/scene needs an expected scene description." };
      return { kind: "scene", expected: rest };
    }

    case "chaos":
    case "ch": {
      const value = Number.parseInt(rest, 10);
      if (!Number.isFinite(value) || value < 1 || value > 9) {
        return { kind: "error", message: "/chaos needs a number between 1 and 9." };
      }
      return { kind: "chaos", value };
    }

    case "ask": {
      if (!rest) return { kind: "error", message: "/ask needs a question." };
      return parseAsk(rest);
    }

    case "retreat":
    case "flee":
    case "disengage":
      // No-arg retreat is the common case — the player just wants out.
      // An optional `reason` lets them direct the fiction ("through the
      // window", "down the chapel stair") without leaving chat. Empty
      // reason is preserved so the store can choose a neutral default.
      return { kind: "retreat", reason: rest };

    default:
      return { kind: "error", message: `Unknown command: /${cmd}. Try /help.` };
  }
}

/**
 * Filter `SLASH_COMMANDS` by the partial command head the user is
 * typing. Returns the descriptors whose canonical name or any alias
 * starts with the partial. The leading slash is optional.
 *
 * Returns an empty list when the input has no slash prefix or when a
 * full whitespace-terminated command is already typed (because the
 * argument body is in flight and the menu would just be in the way).
 */
export function suggestSlashCommands(input: string): readonly SlashCommandDescriptor[] {
  const trimmedStart = input.trimStart();
  if (!trimmedStart.startsWith("/")) return [];

  // Once the user has finished typing the head and moved on to args,
  // the suggestion menu is no longer useful (we can't disambiguate
  // their argument), so suppress.
  const head = trimmedStart.slice(1);
  if (head.includes(" ")) return [];

  const partial = head.toLowerCase();
  if (partial === "") return SLASH_COMMANDS;

  return SLASH_COMMANDS.filter((cmd) => {
    if (cmd.name.startsWith(partial)) return true;
    return cmd.aliases.some((alias) => alias.startsWith(partial));
  });
}

function parseAsk(rest: string): ParsedTurn {
  // Look for an optional [likelihood] hint anywhere; we strip it before
  // sending the question so the oracle / DM doesn't see the bracket.
  const hintMatch = rest.match(/\[([^\]]+)\]\s*$/);
  let likelihood: Likelihood = "Even odds";
  let question = rest;

  if (hintMatch) {
    const key = hintMatch[1]!.trim().toLowerCase().replace(/\s+/g, "-");
    const matched = LIKELIHOOD_HINTS[key];
    if (matched !== undefined) {
      likelihood = matched;
      question = rest.slice(0, hintMatch.index).trim();
    }
  }

  if (!question) {
    return { kind: "error", message: "/ask needs a question before the [hint]." };
  }
  return { kind: "ask", question, likelihood };
}
