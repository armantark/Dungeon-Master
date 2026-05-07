// Slash-command parser for the Composer.
//
// Why explicit slash commands instead of inferring intent from natural
// language: the player almost always knows when they want a roll vs. a
// pure narrative beat, and inferring wrong is worse than asking for
// punctuation. Free text still works (and the LLM-backed planner will
// classify it), but slashes are the durable explicit fallback when the
// player wants to skip ambiguity.

import type { CampaignEndReason, Likelihood } from "./types";

/**
 * Verbs that route to the planner's ACQUIRE_ITEM op. We preserve the
 * literal verb the player typed so the prose we hand the planner reads
 * naturally — looting feels different from buying, and the LLM-backed
 * narrator can lean on that fictional framing without us having to
 * smuggle it through structured fields.
 */
export type AcquireVerb = "acquire" | "loot" | "take" | "buy";

export type ParsedTurn =
  | { kind: "ask"; question: string; likelihood: Likelihood }
  | { kind: "event" }
  | { kind: "scene"; expected: string }
  | { kind: "chaos"; value: number }
  | { kind: "reset" }
  | { kind: "action"; text: string }
  | { kind: "retreat"; reason: string }
  | { kind: "acquire"; verb: AcquireVerb; body: string }
  // F-06 terminal-close commands. `summary` is optional — when the
  // player types just `/retire` or `/victory`, the backend writes a
  // deterministic default summary so the End-Banner still has prose
  // to render. The reason is fixed by the verb the player chose
  // (retirement vs. victory), so we don't expose a `reason` argument
  // separately.
  | { kind: "end"; reason: CampaignEndReason; summary: string }
  | { kind: "help" }
  // F-10 OOC rules explainer. The body is the player's question; we
  // do *not* parse hint-fields or sub-commands because the explainer
  // is grounded in the LLM's reading of GameState, not in keyword
  // routing. An empty body is a parse error so the player gets a
  // hint about the required argument rather than firing a useless
  // "explain what?" round-trip to the backend.
  | { kind: "explain"; question: string }
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
  // The four acquisition verbs are listed as separate descriptors
  // (rather than aliases of one canonical command) because their
  // fictional flavor differs — looting a corpse, taking a found
  // object, buying at a market, and a generic acquire all read
  // differently in narration. The planner classifies all four as
  // ACQUIRE_ITEM, but we hand it the verb the player chose so the
  // prose lands cleanly.
  {
    name: "loot",
    aliases: [],
    summary: "Loot something from a corpse, chest, or scene.",
    usage: "/loot <description>",
  },
  {
    name: "take",
    aliases: [],
    summary: "Take a found object into inventory.",
    usage: "/take <description>",
  },
  {
    name: "buy",
    aliases: ["purchase"],
    summary: "Acquire an item or bundle through purchase or trade.",
    usage: "/buy <description>",
  },
  {
    name: "acquire",
    aliases: ["gain"],
    summary: "Generic catch-all for adding gear, loot, gifts, or rewards.",
    usage: "/acquire <description>",
  },
  {
    name: "chaos",
    aliases: ["ch"],
    summary: "Set the chaos factor (1–9).",
    usage: "/chaos <1-9>",
  },
  // The two F-06 terminal-close commands sit *after* play-time
  // commands so the suggestion menu surfaces them only when the
  // player deliberately types `/r…` or `/v…`. We keep them as
  // separate descriptors (rather than aliases of one /end) because
  // their fictional flavor differs and the End-Banner branches on
  // the chosen reason — collapsing them would force a `/end retire`
  // sub-arg parse that adds friction without any payoff.
  {
    name: "retire",
    aliases: [],
    summary: "End the campaign — your character walks away from this story.",
    usage: "/retire [final words]",
  },
  {
    name: "victory",
    aliases: [],
    summary: "End the campaign — declare it won.",
    usage: "/victory [closing notes]",
  },
  {
    name: "reset",
    aliases: [],
    summary: "Regenerate the campaign opening.",
    usage: "/reset",
  },
  // F-10 OOC explainer. We deliberately keep this as a separate
  // descriptor (not an alias of /help) because /help is the static
  // command-list reference and /explain is a live LLM-backed,
  // state-aware question. The two surfaces are visually and
  // mechanically distinct: /help is deterministic text; /explain
  // streams an OOC answer and lands as an ephemeral note.
  {
    name: "explain",
    aliases: [],
    summary: "Out-of-character: ask how a mechanic or recent event works.",
    usage: "/explain <question>",
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

    case "retire":
      // The body is the player's optional final-words / closing
      // summary. We treat it as free prose and pass it through to
      // the backend; the backend writes a deterministic default
      // when summary is empty, so the End-Banner always has
      // canonical text to render.
      return { kind: "end", reason: "retirement", summary: rest };

    case "victory":
      return { kind: "end", reason: "victory", summary: rest };

    case "explain": {
      // Empty-body is rejected here so the player sees what's
      // missing immediately, instead of round-tripping to the
      // backend and getting a 422 from `min_length=1` validation
      // on the ExplainRequest. The error message matches the
      // discoverable usage hint from SLASH_COMMANDS so /help and
      // the inline error read consistently.
      if (!rest) {
        return {
          kind: "error",
          message: "/explain needs a question, e.g. /explain how does atk work?",
        };
      }
      return { kind: "explain", question: rest };
    }

    case "acquire":
    case "gain":
    case "loot":
    case "take":
    case "buy":
    case "purchase": {
      // Acquisition verbs *require* a body — "I acquire what?" has no
      // referent for the planner to seed an item from. We surface a
      // verb-specific error so the player knows what's missing
      // (`/loot needs something to loot`, not just `bad command`).
      if (!rest) {
        return {
          kind: "error",
          message: `/${cmd} needs a description of what you're acquiring.`,
        };
      }
      const verb = canonicalAcquireVerb(cmd);
      return { kind: "acquire", verb, body: rest };
    }

    default:
      return { kind: "error", message: `Unknown command: /${cmd}. Try /help.` };
  }
}

function canonicalAcquireVerb(cmd: string): AcquireVerb {
  // `gain` is just an alias for `acquire`, and `purchase` for `buy`.
  // The four canonical verbs map 1:1 to the descriptors in
  // SLASH_COMMANDS so the suggestion menu and the parser stay in sync.
  switch (cmd) {
    case "loot":
      return "loot";
    case "take":
      return "take";
    case "buy":
    case "purchase":
      return "buy";
    case "acquire":
    case "gain":
    default:
      return "acquire";
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
