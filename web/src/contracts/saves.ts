// Save-library wire contracts.

import type { CampaignDangerProfile, CampaignEndReason, CampaignStatus } from "./campaign";

// F-12 Save library. Mirrors `SaveSummary` in `save_library.py`.
//
// `identifying_line` is the short backstory blurb the backend chose for
// the card body (it falls back to archetype / current scene if the
// backstory is empty). `state_summary` is the hover/expand reveal —
// scene number plus combat / archive context. We keep both as plain
// strings rather than richer structures so the card UI never has to
// re-derive them and the wire stays trivially diff-friendly.
export type SaveCampaignStatus = CampaignStatus;
export interface SaveSummary {
  save_id: string;
  state_id: string;
  character_name: string;
  character_epithet: string;
  identifying_line: string;
  state_summary: string;
  campaign_status: SaveCampaignStatus;
  campaign_end_reason: CampaignEndReason | null;
  // F-15 / F-19: surfaced so the save card can render a "preset · danger"
  // badge without having to load the full GameState. `campaign_preset`
  // is a free-text label set by the seed editor (defaults to the
  // built-in "Oppressive Dark Fantasy"); `danger_profile` is the
  // canonical lowercase enum value (`story | standard | harsh | lethal`).
  campaign_preset: string;
  danger_profile: CampaignDangerProfile;
  updated_at: string;
  created_at: string;
}

export interface SaveLibraryBootstrapResponse {
  active_save_id: string | null;
  saves: SaveSummary[];
}
