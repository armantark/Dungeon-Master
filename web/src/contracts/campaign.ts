// Campaign identity, continuity, lifecycle, and world-seed wire contracts.

export type ThreadStatus = "active" | "resolved";

// NPC continuity. `retired` mirrors the backend's `NPCStatus.RETIRED`:
// the NPC has left the active cast (died, departed, became irrelevant)
// but is preserved in canon so memory can still reference them and so
// they can be reactivated by a future `update` op without inventing a
// new identity. The frontend treats `retired` as a sink-and-mute state
// — visible in the panel, but never highlighted as if they were still
// driving play. See F-04 in memory-bank/featureKanban.md.
export type NPCStatus = "active" | "retired";

// H-01 mirrors the backend split between a canonical true name and the
// player-facing label the fiction has actually granted. `proper_name`
// means the player may know the figure's real name; `descriptor` means
// the roster should render the safer "known by sign" label instead.
export type NPCPlayerLabelKind = "proper_name" | "descriptor";

// `ended` is the F-06 terminal state. Once the campaign reaches it, the
// frontend renders chat as a read-only archive (no Composer, no slash
// commands that mutate state) and the only canonical control is
// "Begin a new campaign" which calls `/state/reset`. We intentionally
// keep the active-state union intact instead of routing every screen
// through a "is play allowed?" boolean — switching on
// `campaign_status` keeps the App-level layout split mechanical and
// exhaustive at the type level.
export type CampaignStatus =
  | "character_creation"
  | "ready_to_start"
  | "active"
  | "ended";

// Mirrors backend `CampaignEndReason`. `death` is the auto-end the
// service triggers when a turn drops STR / HP to a fatal Cairn state;
// `retirement` is the explicit "I walk away" close; `victory` is the
// explicit "the campaign is won" close. The frontend uses this to
// pick the End-Banner kicker / glyph / tone — never to gate behavior
// (the gate is `campaign_status === "ended"`).
export type CampaignEndReason = "death" | "retirement" | "victory";

export interface GameThread {
  id: string;
  title: string;
  status: ThreadStatus;
  stakes: string;
}

export interface NPC {
  id: string;
  name: string;
  player_label: string;
  player_label_kind: NPCPlayerLabelKind;
  role: string;
  disposition: string;
  // F-04: dynamic NPC updates can retire an NPC instead of deleting it.
  // Older state blobs that pre-date the field still deserialize cleanly
  // because the backend defaults retired-less NPCs to `active`, so the
  // wire never sends `undefined`. We keep it required here to force any
  // new TS code path to think about which bucket it's rendering.
  status: NPCStatus;
}

// F-15 Campaign seed enums. Hand-mirrored from the backend StrEnums in
// `dungeon_master/models.py`. The setup UI renders friendly labels via
// the dictionaries in `lib/campaign-seed.ts`; the wire format is always
// the lowercase enum value.
export type CampaignTimePeriod =
  | "bronze_age"
  | "classical_antiquity"
  | "early_medieval"
  | "high_medieval"
  | "renaissance"
  | "early_modern"
  | "industrial"
  | "modern"
  | "near_future"
  | "far_future"
  | "post_apocalyptic"
  | "mythic_timeless";

export type CampaignToneGrimNoble = "grim" | "mixed" | "noble";
export type CampaignToneDarkBright = "dark" | "mixed" | "bright";

// F-15 + F-19: difficulty surface. The backend's
// `EncounterScalingPolicy.for_danger` translates this into the HP /
// armor / damage caps that govern generated encounters.
export type CampaignDangerProfile = "story" | "standard" | "harsh" | "lethal";

export type CampaignGenre =
  | "high_fantasy"
  | "low_fantasy"
  | "sword_and_sorcery"
  | "dark_fantasy"
  | "gothic_horror"
  | "cosmic_horror"
  | "weird_fiction"
  | "fairy_tale"
  | "mythic"
  | "post_apocalyptic"
  | "science_fantasy"
  | "historical_fantasy"
  | "urban_fantasy"
  | "hearth_and_homestead";

export type CampaignMagicLevel = "none" | "rare_numinous" | "common" | "ubiquitous";

export type CampaignTechLevel =
  | "stone"
  | "iron"
  | "medieval"
  | "renaissance"
  | "industrial"
  | "modern"
  | "spacefaring";

export type CampaignStakesScale =
  | "personal_local"
  | "regional"
  | "civilizational"
  | "cosmic";

// Mirrors backend `CampaignSeed`. Lives on `GameState.campaign_seed`
// once a seed has been authored; the backend defaults every new state
// to a "Oppressive Dark Fantasy" preset so this field is never
// undefined on the wire. The setup screen lets the player tweak the
// seed before campaign generation runs; the inspector lets them read
// (but not mutate) the seed mid-campaign.
export interface CampaignSeed {
  preset: string;
  time_period: CampaignTimePeriod;
  tone_grim_noble: CampaignToneGrimNoble;
  tone_dark_bright: CampaignToneDarkBright;
  danger_profile: CampaignDangerProfile;
  // The backend caps this list at 3 entries (`max_length=3`) and
  // guarantees at least one — we mirror it as a plain array and let
  // the seed editor enforce the cap on the input side.
  genres: CampaignGenre[];
  magic_level: CampaignMagicLevel;
  tech_level: CampaignTechLevel;
  stakes_scale: CampaignStakesScale;
  inspirations: string;
  restrictions: string;
}

// B-02 Campaign directives — the persistent OOC steering surface.
//
// We deliberately keep this separate from `setting_notes` /
// `player_notes`. Those two fields are *canonical campaign material*
// (world bible, character backstory) authored at generation time and
// fed into prose. Directives are something different: a small,
// player-authored OOC dial like "the hierophant cannot speak first"
// or "keep miracles subtle" that the system should remember but
// never narrate. Sharing one editor for both meanings was the bug —
// once the surface is meaningfully scoped, the player stops feeling
// nudged into freeform journaling and the model gets a cleaner
// channel for stable steering.
//
// Both fields are `string` (not optional) because the backend
// always emits them; an empty string means "no guidance set", which
// the editor renders as a neutral hint rather than as an error
// state.
export interface CampaignDirectives {
  world_guidance: string;
  play_guidance: string;
}
