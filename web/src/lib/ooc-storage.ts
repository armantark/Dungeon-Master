// Client-side persistence for OOC ("Archivist") explainer exchanges.
//
// Why client-side, and not the server's action_log:
//   The OOC channel is non-canonical by contract — see service.py and
//   store.svelte.ts on `#explanationNote`. Round-tripping these
//   exchanges through `memory.json` would slowly poison the in-fiction
//   voice (the LLM would start quoting its own out-of-character
//   answers back to itself). Putting them in localStorage instead
//   keeps the "ephemeral to the game state" contract intact while
//   still letting the player see their previous explainer Q+As after
//   a reload — which is what reload-to-keep-reading expects in any
//   other chat surface.
//
// Why per-save scoping:
//   OOC questions are usually about the *current* campaign's mechanics
//   ("does this counter as combat?", "what happens if I retreat into
//   the same ambush?"). Showing another save's OOC log would be
//   confusing at best and a memory leak at worst. We key by save_id
//   so each campaign has its own scrollback that follows it across
//   reloads but stays out of every other save's chat surface.
//
// Why we don't persist help/error/info notes:
//   Those are transient feedback ("you typed /loot wrong"). The user
//   already saw and reacted; persisting them would just clutter the
//   feed forever after a reload.

import type { ClientNote } from "./store.svelte";

const STORAGE_PREFIX = "dm.ooc";
// Hard cap on persisted entries per save so a long campaign with a
// chatty player can't bloat localStorage past the browser's per-origin
// quota (typically 5MB). 200 entries x ~2KB each ~= 400KB worst case,
// well under any reasonable quota and far past anything a normal
// session will accumulate.
const MAX_NOTES_PER_SAVE = 200;

function storageKey(saveId: string): string {
  return `${STORAGE_PREFIX}.${saveId}`;
}

// Defensive read: any localStorage payload could have been hand-edited
// or written by a previous schema version. We validate the shape and
// drop anything that doesn't look like a `ClientNote` so a single
// corrupt entry can't crash the chat feed on hydration.
function isValidNote(value: unknown): value is ClientNote {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  if (typeof candidate.id !== "string") return false;
  if (typeof candidate.text !== "string") return false;
  if (typeof candidate.created_at !== "string") return false;
  if (candidate.kind !== "explanation") return false;
  if (
    candidate.question !== undefined
    && typeof candidate.question !== "string"
  ) {
    return false;
  }
  return true;
}

function safeStorage(): Storage | null {
  // Guard for SSR / tests / browsers with storage disabled. We never
  // throw out of this module — a missing storage just means OOC notes
  // are session-scoped, which is the legacy behavior.
  try {
    if (typeof window === "undefined") return null;
    return window.localStorage;
  } catch {
    return null;
  }
}

export function loadOocNotes(saveId: string | null): ClientNote[] {
  if (saveId === null) return [];
  const storage = safeStorage();
  if (storage === null) return [];
  let raw: string | null;
  try {
    raw = storage.getItem(storageKey(saveId));
  } catch {
    return [];
  }
  if (raw === null) return [];
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return [];
  }
  if (!Array.isArray(parsed)) return [];
  return parsed.filter(isValidNote);
}

export function saveOocNotes(
  saveId: string | null,
  notes: readonly ClientNote[],
): void {
  if (saveId === null) return;
  const storage = safeStorage();
  if (storage === null) return;
  const explanationOnly = notes
    .filter((n): n is ClientNote => n.kind === "explanation")
    .slice(-MAX_NOTES_PER_SAVE);
  try {
    if (explanationOnly.length === 0) {
      storage.removeItem(storageKey(saveId));
      return;
    }
    storage.setItem(storageKey(saveId), JSON.stringify(explanationOnly));
  } catch {
    // Quota or disabled storage: we silently drop persistence. The
    // in-memory notes still render correctly for this session; only
    // the reload-survival promise breaks, and the alternative
    // (throwing) would yank the user out of an active turn.
  }
}

export function clearOocNotes(saveId: string | null): void {
  if (saveId === null) return;
  const storage = safeStorage();
  if (storage === null) return;
  try {
    storage.removeItem(storageKey(saveId));
  } catch {
    // See `saveOocNotes` — best-effort.
  }
}
