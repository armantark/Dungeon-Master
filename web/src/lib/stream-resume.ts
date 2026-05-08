// Client-side persistence for the "resume an in-flight stream after a
// reload" contract.
//
// Why this exists:
//   The backend now keeps stream sessions alive past a subscriber
//   disconnect (see src/dungeon_master/stream_session.py and
//   GET /api/requests/{request_id}/stream). The browser-side half of
//   that contract is "remember which request_id was in flight when the
//   tab last saw it" so the next bootstrap can call back and tail the
//   buffered output. Without that descriptor we'd have no way to
//   re-discover the request after navigation drops the in-memory store
//   state.
//
// Why per-save scoping:
//   The backend rejects a reattach against a different active save
//   with a 409 ("Request belongs to a different active save."). Even
//   without that guard, surfacing one save's resumed turn against
//   another save's chat would be confusing. Keying by save_id keeps
//   the descriptor scoped to the campaign that produced it.
//
// Why a TTL:
//   localStorage entries can outlive the backend's session retention
//   window — the backend GC's finished sessions after ~120s. A stale
//   descriptor would 404 on every reload. A 10-minute window is well
//   past the longest plausible turn (Kimi K2.6 caps at ~5min combat)
//   and keeps the failure mode "we tried, server already cleaned it
//   up" cheap and silent.

const STORAGE_PREFIX = "dm.stream-resume";
const RESUME_TTL_MS = 10 * 60 * 1000;

// The descriptor we hand back to bootstrap. We keep this minimal on
// purpose: anything we add here has to be honored across versions of
// the app, and the only thing the reattach path actually needs is the
// request_id. `route` is for telemetry / labeling the resumed bubble;
// `started_at` lets us TTL-fence stale entries; `save_id` is the
// scope guard and matches the bucket key.
// Serializable stage snapshot mirroring `StageProgress` from the store.
// We duplicate the shape (instead of importing) so the stream-resume
// module stays self-contained and doesn't pull Svelte runes code into
// a plain-TS validation path.
export interface PersistedStage {
  stageId: string;
  label: string;
  status: string;
  order: number;
  startedAt: number | null;
  completedAt: number | null;
}

export interface StreamResumeDescriptor {
  request_id: string;
  save_id: string;
  route: string;
  started_at: string;
  /** Snapshot of the pipeline stages at the time of the last persist. */
  stages?: PersistedStage[];
}

function storageKey(saveId: string): string {
  return `${STORAGE_PREFIX}.${saveId}`;
}

function safeStorage(): Storage | null {
  // Guard for SSR / disabled storage / restrictive iframes. We never
  // throw out of this module — a missing storage just means resume
  // is a no-op for this session, which matches the legacy behavior
  // before reattach existed.
  try {
    if (typeof window === "undefined") return null;
    return window.localStorage;
  } catch {
    return null;
  }
}

function isValidDescriptor(value: unknown): value is StreamResumeDescriptor {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  if (typeof candidate.request_id !== "string" || candidate.request_id === "") return false;
  if (typeof candidate.save_id !== "string" || candidate.save_id === "") return false;
  if (typeof candidate.route !== "string") return false;
  if (typeof candidate.started_at !== "string") return false;
  return true;
}

function isFresh(descriptor: StreamResumeDescriptor, now: number = Date.now()): boolean {
  const startedAt = Date.parse(descriptor.started_at);
  if (Number.isNaN(startedAt)) return false;
  return now - startedAt < RESUME_TTL_MS;
}

/**
 * Persist the in-flight request's descriptor so the next page load can
 * find it. Call this once per stream when the `meta` event arrives —
 * that's the first moment we know the backend's request_id, which is
 * also the only id the reattach endpoint accepts.
 *
 * Calling this with `saveId === null` is a no-op (no save bound, no
 * place to scope the descriptor).
 */
export function saveStreamResume(
  saveId: string | null,
  descriptor: Omit<StreamResumeDescriptor, "save_id">,
): void {
  if (saveId === null) return;
  const storage = safeStorage();
  if (storage === null) return;
  const payload: StreamResumeDescriptor = { ...descriptor, save_id: saveId };
  try {
    storage.setItem(storageKey(saveId), JSON.stringify(payload));
  } catch {
    // Quota or disabled storage: the next reload simply won't try to
    // resume. The current session's stream still works because that
    // path runs entirely off in-memory store state.
  }
}

/**
 * Persist the current stage snapshot onto the existing descriptor for
 * `saveId`. No-op when no descriptor exists (the meta event hasn't
 * landed yet) or storage is unavailable. Called on every backend
 * `stage` event so a mid-stream reload restores the checklist.
 */
export function updateStreamResumeStages(
  saveId: string | null,
  stages: PersistedStage[],
): void {
  if (saveId === null) return;
  const storage = safeStorage();
  if (storage === null) return;
  let raw: string | null;
  try {
    raw = storage.getItem(storageKey(saveId));
  } catch {
    return;
  }
  if (raw === null) return;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return;
  }
  if (!isValidDescriptor(parsed)) return;
  const updated: StreamResumeDescriptor = { ...parsed, stages };
  try {
    storage.setItem(storageKey(saveId), JSON.stringify(updated));
  } catch {
    // Quota — best effort.
  }
}

/**
 * Read the descriptor the previous page wrote. Returns null when:
 *   - no descriptor exists for this save,
 *   - the descriptor is malformed (hand-edited / schema drift),
 *   - the descriptor is older than the TTL.
 *
 * Stale descriptors are evicted as a side-effect so the next call
 * doesn't keep paying the parse cost. Corrupt entries are also
 * evicted so a single bad write can't permanently disable resume.
 */
export function loadStreamResume(saveId: string | null): StreamResumeDescriptor | null {
  if (saveId === null) return null;
  const storage = safeStorage();
  if (storage === null) return null;
  let raw: string | null;
  try {
    raw = storage.getItem(storageKey(saveId));
  } catch {
    return null;
  }
  if (raw === null) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    clearStreamResume(saveId);
    return null;
  }
  if (!isValidDescriptor(parsed)) {
    clearStreamResume(saveId);
    return null;
  }
  if (parsed.save_id !== saveId) {
    // Defensive: the bucket key is per-save, but if a previous bug
    // wrote the wrong save_id we'd silently mis-resume. Treat as
    // corrupt and evict.
    clearStreamResume(saveId);
    return null;
  }
  if (!isFresh(parsed)) {
    clearStreamResume(saveId);
    return null;
  }
  return parsed;
}

/**
 * Forget the descriptor for `saveId`. Call this on every terminal
 * event we observe (final_state, backend-authored error, explicit
 * cancel) and on a 404 from the reattach endpoint. Anything else
 * leaves the descriptor in place so a refresh-during-stream can
 * still find it.
 */
export function clearStreamResume(saveId: string | null): void {
  if (saveId === null) return;
  const storage = safeStorage();
  if (storage === null) return;
  try {
    storage.removeItem(storageKey(saveId));
  } catch {
    // Best-effort. If we can't remove now, the TTL will catch it on
    // the next read.
  }
}

// Exported only so tests can anchor the constant; the runtime never
// needs to read the literal value because it's already baked into
// `isFresh`.
export const STREAM_RESUME_TTL_MS = RESUME_TTL_MS;
