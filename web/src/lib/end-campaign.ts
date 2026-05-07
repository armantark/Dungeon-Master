// Pure presentation helpers for F-06 ended-campaign state.
//
// We keep these out of the .svelte component so the kicker/glyph/tone
// rules are testable without spinning up a Vitest DOM. The component
// only does layout and event wiring; everything that has a "what does
// this *say* for reason X?" answer lives here.
//
// Why three derived strings instead of one big "describe the end"
// helper: the End-Banner uses them in different visual slots
// (kicker on top, headline in the middle, prose underneath), and the
// archive-mode StatusStrip reuses the kicker independently. Splitting
// keeps each call site responsible for its own slot.

import type { CampaignEndReason, GameState } from "./types";

const REASON_KICKER: Record<CampaignEndReason, string> = {
  death: "Cairn marker",
  retirement: "Hearth & quiet",
  victory: "Triumph",
};

const REASON_HEADLINE: Record<CampaignEndReason, string> = {
  death: "The wanderer fell.",
  retirement: "The wanderer walked away.",
  victory: "The wanderer prevailed.",
};

// Default closing prose used when the backend hasn't written a
// summary yet (e.g. a stale legacy save migrated by
// `_sync_terminal_state_on_load` without backfilling) or when the
// frontend renders an Ended state that pre-dates the F-06 backend
// fields entirely. Keeping these here (rather than in the component)
// means the test suite can assert the deterministic fallbacks without
// rendering Svelte. The backend-authored summary always wins; this
// is only the safety net.
const REASON_FALLBACK_SUMMARY: Record<CampaignEndReason, string> = {
  death:
    "The character's wounds proved final. The campaign closes here, with this archive preserved.",
  retirement:
    "The character set the road aside. The campaign closes here, with this archive preserved.",
  victory:
    "The campaign reached its endgame. The archive preserves the path that led here.",
};

export function endKicker(reason: CampaignEndReason): string {
  return REASON_KICKER[reason];
}

export function endHeadline(reason: CampaignEndReason): string {
  return REASON_HEADLINE[reason];
}

/**
 * Resolve the prose that the End-Banner shows underneath the
 * headline. The backend-authored `campaign_end_summary` is canonical;
 * we only fall back to a deterministic per-reason default when the
 * server didn't author one (older saves, future migrations). An empty
 * string from the wire counts as "no summary" and falls back too.
 */
export function endSummary(state: GameState): string {
  const reason = state.campaign_end_reason;
  if (reason === null) return "";
  const authored = state.campaign_end_summary;
  if (authored !== null && authored.trim() !== "") return authored;
  return REASON_FALLBACK_SUMMARY[reason];
}

/**
 * True when the GameState is in the F-06 terminal state and the
 * banner / read-only archive should render. Hoisted so callers don't
 * have to duplicate the literal `"ended"` check (a typo there would
 * silently leave Composer mounted on a closed campaign).
 */
export function isCampaignEnded(state: GameState | null): boolean {
  return state !== null && state.campaign_status === "ended";
}

/**
 * Optional ISO timestamp formatter. We render the close timestamp
 * as a localized short date so the End-Banner says *when* the
 * campaign closed without leaning on Date.toString()'s noisy default.
 * Returns null when the backend hasn't populated the timestamp yet.
 */
export function formatEndedAt(value: string | null): string | null {
  if (value === null || value === "") return null;
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return null;
  return dt.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
