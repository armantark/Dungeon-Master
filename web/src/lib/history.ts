// Pure derivation + search helpers for the F-09 history browser.
//
// The chat feed and the inspector both want to walk the same transcript
// (action_log + the synthesized opening message + ephemeral client
// notes), but for *different* purposes: the feed renders chronologically,
// the inspector wants to search and jump. Keeping the row derivation in
// one place means the two surfaces can never disagree about what the
// transcript "is" — and the search rule itself stays unit-testable
// without a DOM.
//
// Rules baked into the derivation, mirroring `ChatFeed.svelte`:
//   1. Oracle events are NOT first-class rows. They fold into the
//      receipt under the narrative event that references them by
//      `oracle_outcome_id`. Including them as separate rows here would
//      leak the chat's deduplication logic into search results.
//   2. Narrative events render as DM rows and join their oracle outcome
//      summary so a search for "ambush" or "scar" matches both prose
//      and the deterministic receipt.
//   3. Player events render as player rows.
//   4. System events render as system rows (campaign init / chaos
//      changes / scene transitions / regenerate audits).
//   5. If no narrative events exist yet, synthesize an opening DM row
//      from `current_scene + setting_notes` so the very first beat is
//      searchable / scrollable just like any other moment.
//   6. Client notes (slash help, slash error toasts) get a row each,
//      flagged as ephemeral so callers can decide whether to include
//      them in search.
//
// The synthesized opening row carries a stable id (`opening_<state-id>`)
// matching the one ChatFeed renders, so a "scroll to this row" command
// from the inspector can target it via the same DOM anchor.

import type { ClientNote } from "./store.svelte";
import type {
  GameEvent,
  GameState,
  OracleKind,
  OracleOutcome,
} from "./types";

export type TranscriptRowKind = "dm" | "player" | "system";

export interface TranscriptRow {
  id: string;
  kind: TranscriptRowKind;
  text: string;
  // Outcome summary text, surfaced for DM rows so a search query can
  // match either the prose or the receipt without the caller having to
  // join the data themselves. Non-DM rows always have null here.
  outcomeSummary: string | null;
  timestamp: string;
  // Synthesized opening DM row (no canonical event behind it). Useful
  // for callers that want to gate "jump to chat" on whether a real
  // event id exists.
  isOpening: boolean;
  // Client-side ephemeral note (slash help/error). Cannot be jumped to
  // reliably because the next refresh / resubmit drops it from `notes`.
  isNote: boolean;
}

export interface SearchMatch {
  rowId: string;
  kind: TranscriptRowKind;
  // Pre-rendered snippet with ~60 chars of context around the match,
  // ellipsis-trimmed at boundaries so it reads as prose. We render
  // snippets in the inspector list rather than the full row text so a
  // 300-word DM message doesn't blow up the panel.
  snippet: string;
  // Source field the match came from. `text` = primary row text;
  // `outcome` = receipt summary tagged onto a DM row. Surfaced so the
  // inspector list can label "matched in receipt" vs "matched in
  // narration", which has been useful in playtesting because the
  // player often remembers the dice context but not the prose.
  source: "text" | "outcome";
  // Char offsets within `snippet` so the inspector can wrap the
  // matched substring in a <mark>. End is exclusive. We compute these
  // here so the renderer doesn't have to re-do a case-insensitive
  // search to find the highlight position.
  highlightStart: number;
  highlightEnd: number;
  timestamp: string;
}

export interface SearchOptions {
  // Cap the result list. Default 50 — enough that a real search like
  // "ghoul" or "abbey" surfaces every relevant beat in a multi-hour
  // campaign, but not so large that the inspector list scrolls
  // forever before the player notices it has run.
  limit?: number;
  // Include client-note rows in the result set. Default false because
  // notes are ephemeral feedback (slash help, error toasts) and
  // jumping into them would teleport the player to a row that no
  // longer exists after the next composer submit.
  includeNotes?: boolean;
}

export interface OracleHistoryFilters {
  // Free-text query. Matched against the oracle outcome's `summary`
  // and `cairn.action_summary` plus the event-flavor strings
  // (`event_focus`, `event_subject`, `event_action`, `event_tone`).
  // Empty string = no text filter.
  query: string;
  // Whitelist of kinds to keep. Empty set = no kind filter (all
  // kinds pass). We use a Set instead of an array so callers can
  // build it once per render and check membership in O(1).
  kinds: ReadonlySet<OracleKind>;
}

const SNIPPET_RADIUS = 48;

/**
 * Build the synthesized opening row id. Mirrors the id ChatFeed uses
 * so a "scroll to" request from the inspector can target the same
 * DOM anchor without a separate lookup table.
 */
function openingRowId(state: GameState): string {
  return `opening_${state.id}`;
}

function fromEvent(
  event: GameEvent,
  outcomesById: ReadonlyMap<string, OracleOutcome>,
): TranscriptRow | null {
  switch (event.event_type) {
    case "narrative": {
      const outcome =
        event.oracle_outcome_id !== null
          ? outcomesById.get(event.oracle_outcome_id) ?? null
          : null;
      return {
        id: event.id,
        kind: "dm",
        text: event.content,
        outcomeSummary: outcome?.summary ?? null,
        timestamp: event.created_at,
        isOpening: false,
        isNote: false,
      };
    }
    case "player":
      return {
        id: event.id,
        kind: "player",
        text: event.content,
        outcomeSummary: null,
        timestamp: event.created_at,
        isOpening: false,
        isNote: false,
      };
    case "system":
      return {
        id: event.id,
        kind: "system",
        text: event.content,
        outcomeSummary: null,
        timestamp: event.created_at,
        isOpening: false,
        isNote: false,
      };
    case "oracle":
      // Folded into the receipt under the matching narrative row.
      // Matching ChatFeed's behavior — see the file header comment.
      return null;
  }
}

function fromNote(note: ClientNote): TranscriptRow {
  // F-10: OOC explanation notes carry the player's question alongside
  // the answer. We fold both into the searchable text so a query like
  // "atk" finds the question even when the answer phrased it
  // differently (and vice versa). Keeping the row kind as `system`
  // avoids widening `TranscriptRowKind` for an ephemeral surface that
  // the inspector treats uniformly with other client notes; the OOC
  // visual treatment lives in the chat feed, not the inspector list.
  if ((note.kind === "explanation" || note.kind === "oracle_preview") && note.question) {
    return {
      id: note.id,
      kind: "system",
      text: `Q: ${note.question}\n\nA: ${note.text}`,
      outcomeSummary: null,
      timestamp: note.created_at,
      isOpening: false,
      isNote: true,
    };
  }
  return {
    id: note.id,
    kind: "system",
    text: note.text,
    outcomeSummary: null,
    timestamp: note.created_at,
    isOpening: false,
    isNote: true,
  };
}

function openingRow(state: GameState): TranscriptRow | null {
  const hasNarrative = state.action_log.some(
    (event) => event.event_type === "narrative",
  );
  if (hasNarrative) return null;
  // We render the same `current_scene + "\n\n" + setting_notes`
  // composite ChatFeed uses so search hits in the opening beat
  // surface a snippet that reads identically to what the player
  // sees in the chat.
  return {
    id: openingRowId(state),
    kind: "dm",
    text: `${state.current_scene}\n\n${state.setting_notes}`,
    outcomeSummary: null,
    timestamp: state.created_at,
    isOpening: true,
    isNote: false,
  };
}

/**
 * Derive the searchable transcript rows from canonical state and the
 * current ephemeral client-note buffer. Rows are returned in
 * chronological order so callers can render a search result list
 * without re-sorting.
 */
export function deriveTranscriptRows(
  state: GameState,
  notes: readonly ClientNote[] = [],
): readonly TranscriptRow[] {
  // Index outcomes once so `O(action_log * oracle_history)` collapses
  // to `O(action_log)` for long campaigns.
  const outcomesById = new Map<string, OracleOutcome>();
  for (const outcome of state.oracle_history) {
    outcomesById.set(outcome.id, outcome);
  }

  const rows: TranscriptRow[] = [];
  const opening = openingRow(state);
  if (opening !== null) rows.push(opening);

  for (const event of state.action_log) {
    const row = fromEvent(event, outcomesById);
    if (row !== null) rows.push(row);
  }

  for (const note of notes) {
    rows.push(fromNote(note));
  }

  rows.sort((a, b) => a.timestamp.localeCompare(b.timestamp));
  return rows;
}

/**
 * Find the narrative event id (chat anchor) that surfaces a given
 * oracle outcome. Returns null when no narrative event has been
 * committed yet against that outcome — happens transiently while a
 * stream is mid-flight, and persistently for outcomes whose narrative
 * was discarded by a cancel-before-commit.
 *
 * Iteration order matches `action_log` order; in practice every
 * outcome maps to at most one narrative event, but we walk the log
 * (rather than reversing) so the regenerate audit chain — which
 * produces a *new* narrative event with the same `oracle_outcome_id`
 * — also lands at the most recent good prose.
 */
export function findNarrativeEventForOracle(
  state: GameState,
  oracleOutcomeId: string,
): string | null {
  let latest: string | null = null;
  for (const event of state.action_log) {
    if (
      event.event_type === "narrative"
      && event.oracle_outcome_id === oracleOutcomeId
    ) {
      latest = event.id;
    }
  }
  return latest;
}

/**
 * Tokenize a search query into lowercase tokens. We split on
 * whitespace because most player searches are 1-2 words ("ghoul",
 * "abbey gate"); a phrase mode could be added later but every
 * playtest so far has wanted token-AND, not phrase-exact.
 */
function tokenize(query: string): string[] {
  return query
    .toLowerCase()
    .split(/\s+/)
    .filter((token) => token.length > 0);
}

/**
 * Substring-match every token against a haystack. Each token must
 * appear at least once (token-AND). Returns the position of the
 * *first* token's first occurrence so the snippet can center on it —
 * playtest feedback was that snippets centered on the rarer token
 * read better, but rarity scoring would require corpus knowledge we
 * don't have at search time, so leftmost-of-leftmost is the simplest
 * rule that produces stable results.
 */
function matchPosition(haystack: string, tokens: readonly string[]): number {
  if (tokens.length === 0) return -1;
  const lowered = haystack.toLowerCase();
  let firstHitStart = -1;
  for (const token of tokens) {
    const idx = lowered.indexOf(token);
    if (idx === -1) return -1;
    if (firstHitStart === -1) firstHitStart = idx;
  }
  return firstHitStart;
}

/**
 * Build the snippet shown in the inspector list. We pull a window
 * around the first match position and add ellipses at the trimmed
 * boundaries. Highlight offsets are recomputed against the snippet
 * so the renderer can wrap the match without re-searching.
 */
function buildMatch(
  row: TranscriptRow,
  source: SearchMatch["source"],
  haystack: string,
  tokens: readonly string[],
  position: number,
): SearchMatch {
  const tokenLength = tokens[0]?.length ?? 0;
  const start = Math.max(0, position - SNIPPET_RADIUS);
  const end = Math.min(haystack.length, position + tokenLength + SNIPPET_RADIUS);
  const prefix = start > 0 ? "…" : "";
  const suffix = end < haystack.length ? "…" : "";
  const slice = haystack.slice(start, end);
  const snippet = `${prefix}${slice}${suffix}`;
  const highlightStart = (position - start) + prefix.length;
  const highlightEnd = highlightStart + tokenLength;
  return {
    rowId: row.id,
    kind: row.kind,
    snippet,
    source,
    highlightStart,
    highlightEnd,
    timestamp: row.timestamp,
  };
}

/**
 * Search the transcript for a query. Returns chronologically ordered
 * matches (oldest → newest) so the inspector list reads as a timeline
 * rather than a relevance ranking. Relevance ranking is deliberately
 * out of scope: in a single-character campaign there's no corpus to
 * tf-idf against, and "first match in time" is the order the player
 * usually wants anyway when looking for "where did the abbot show up
 * the first time?".
 */
export function searchTranscript(
  rows: readonly TranscriptRow[],
  query: string,
  options: SearchOptions = {},
): readonly SearchMatch[] {
  const tokens = tokenize(query);
  if (tokens.length === 0) return [];

  const limit = options.limit ?? 50;
  const includeNotes = options.includeNotes ?? false;
  const matches: SearchMatch[] = [];

  for (const row of rows) {
    if (!includeNotes && row.isNote) continue;

    const textPos = matchPosition(row.text, tokens);
    if (textPos !== -1) {
      matches.push(buildMatch(row, "text", row.text, tokens, textPos));
      if (matches.length >= limit) break;
      continue;
    }

    if (row.outcomeSummary !== null) {
      const outcomePos = matchPosition(row.outcomeSummary, tokens);
      if (outcomePos !== -1) {
        matches.push(
          buildMatch(row, "outcome", row.outcomeSummary, tokens, outcomePos),
        );
        if (matches.length >= limit) break;
      }
    }
  }

  return matches;
}

/**
 * Aggregate every searchable string on an oracle outcome into a
 * single haystack. Centralized here (rather than inlined in
 * `filterOracleHistory`) so the unit tests can pin which fields are
 * matchable without depending on the filter's loop.
 *
 * Cairn fields included are the ones a player would actually use to
 * remember a beat: `target_name` ("the lead leper"), `weapon_name`
 * ("notched cudgel"), `scar_result` ("white scar across the brow"),
 * and the enemy-damage source narration. Numerics like HP/STR
 * deltas are deliberately excluded because querying for "4" would
 * produce noisy hits across every roll that landed on that value.
 */
function oracleHaystack(outcome: OracleOutcome): string {
  const parts: string[] = [outcome.summary];
  if (outcome.event_focus !== null) parts.push(outcome.event_focus);
  if (outcome.event_subject !== null) parts.push(outcome.event_subject);
  if (outcome.event_action !== null) parts.push(outcome.event_action);
  if (outcome.event_tone !== null) parts.push(outcome.event_tone);
  if (outcome.scene_status !== null) parts.push(outcome.scene_status);
  if (outcome.answer !== null) parts.push(outcome.answer);
  if (outcome.cairn !== null) {
    if (outcome.cairn.target_name !== null) parts.push(outcome.cairn.target_name);
    if (outcome.cairn.weapon_name !== null) parts.push(outcome.cairn.weapon_name);
    if (outcome.cairn.scar_result !== null) parts.push(outcome.cairn.scar_result);
    const enemySource = outcome.cairn.enemy_damage_source;
    if (enemySource !== undefined && enemySource !== null && enemySource !== "") {
      parts.push(enemySource);
    }
  }
  return parts.join(" \u2022 ");
}

/**
 * Filter an oracle-history list by free-text query and/or kind set.
 * Order is preserved (newest-last on the wire, callers may reverse).
 * An empty filter (no query, no kinds) returns the input array
 * unchanged — useful so the inspector can pass the same predicate
 * regardless of whether the player has typed anything.
 */
export function filterOracleHistory(
  history: readonly OracleOutcome[],
  filters: OracleHistoryFilters,
): readonly OracleOutcome[] {
  const tokens = tokenize(filters.query);
  const kindFilter = filters.kinds.size > 0 ? filters.kinds : null;
  if (tokens.length === 0 && kindFilter === null) return history;

  const result: OracleOutcome[] = [];
  for (const outcome of history) {
    if (kindFilter !== null && !kindFilter.has(outcome.kind)) continue;
    if (tokens.length > 0) {
      const haystack = oracleHaystack(outcome);
      if (matchPosition(haystack, tokens) === -1) continue;
    }
    result.push(outcome);
  }
  return result;
}
