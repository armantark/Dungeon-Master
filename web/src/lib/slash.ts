// Slash-command parser for the Composer.
//
// Why explicit slash commands instead of inferring intent from natural
// language: the player almost always knows when they want a roll vs. a
// pure narrative beat, and inferring wrong is worse than asking for
// punctuation. A future iteration may layer LLM-based intent detection
// on top, but the slash form is the durable explicit fallback.

import type { Likelihood } from "./types";

export type ParsedTurn =
  | { kind: "ask"; question: string; likelihood: Likelihood }
  | { kind: "event" }
  | { kind: "scene"; expected: string }
  | { kind: "chaos"; value: number }
  | { kind: "reset" }
  | { kind: "action"; text: string }
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

const HELP_TEXT = `Commands:
  /ask <question> [likely|unlikely|even|...]   yes/no oracle
  /event                                       random event from the campaign tables
  /scene <expected scene>                      scene check (expected / altered / interrupted)
  /chaos <1-9>                                 set the chaos factor
  /reset                                       regenerate the campaign
  /help                                        this list

Anything not starting with / is sent as a free-text player action and the DM narrates it without a roll.`;

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

  // Split on the first whitespace; everything else is the command body.
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

    case "ask":
    case "?": {
      if (!rest) return { kind: "error", message: "/ask needs a question." };
      return parseAsk(rest);
    }

    default:
      return { kind: "error", message: `Unknown command: /${cmd}. Try /help.` };
  }
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
