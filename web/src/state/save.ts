import type { SaveSummary } from "../lib/types";
import type { ClientNote } from "./play";

export type LibraryStatus = "loading" | "empty" | "selecting" | "ready";

export function createdSaveId(
  beforeIds: ReadonlySet<string>,
  saves: readonly SaveSummary[],
): string | null {
  return saves.find((entry) => !beforeIds.has(entry.save_id))?.save_id ?? null;
}

export function mergePersistedNotes(
  current: readonly ClientNote[],
  persisted: readonly ClientNote[],
): ClientNote[] {
  if (persisted.length === 0) return [...current];
  const seen = new Set(current.map((note) => note.id));
  const merged = [...persisted.filter((note) => !seen.has(note.id)), ...current];
  merged.sort((a, b) => a.created_at.localeCompare(b.created_at));
  return merged;
}
