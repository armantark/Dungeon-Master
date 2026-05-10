// Pure presentation helpers + presets for the F-15 campaign seed.
//
// This module is strictly presentational. It owns the dictionaries that
// translate the backend's lowercase enum values into player-facing
// labels and short descriptions, plus a small set of curated presets
// the seed editor offers as "starting points". It never mutates state
// and never talks to the network.
//
// Keeping the labels here (rather than inline in the .svelte) means
// the inspector, the save library badge, and the editor all read from
// the same dictionary. When the backend grows a new enum variant the
// missing key shows up as a TS error here, not a silent "missing
// label" in the UI.

import type {
  CampaignDangerProfile,
  CampaignGenre,
  CampaignMagicLevel,
  CampaignSeed,
  CampaignStakesScale,
  CampaignTechLevel,
  CampaignTimePeriod,
  CampaignToneDarkBright,
  CampaignToneGrimNoble,
  EncounterAdvantagePayoff,
  EncounterThreatLevel,
} from "./types";

export const TIME_PERIOD_LABEL: Record<CampaignTimePeriod, string> = {
  bronze_age: "Bronze Age",
  classical_antiquity: "Classical antiquity",
  early_medieval: "Early medieval",
  high_medieval: "High medieval",
  renaissance: "Renaissance",
  early_modern: "Early modern",
  industrial: "Industrial",
  modern: "Modern",
  near_future: "Near future",
  far_future: "Far future",
  post_apocalyptic: "Post-apocalyptic",
  mythic_timeless: "Mythic / timeless",
};

export const TONE_GRIM_NOBLE_LABEL: Record<CampaignToneGrimNoble, string> = {
  grim: "Grim",
  mixed: "Mixed",
  noble: "Noble",
};

export const TONE_DARK_BRIGHT_LABEL: Record<CampaignToneDarkBright, string> = {
  dark: "Dark",
  mixed: "Mixed",
  bright: "Bright",
};

// F-15 + F-19 difficulty surface. We keep both a label and a short
// blurb that mirrors the backend's `render_danger_guidance` so the
// editor can show players what each profile actually means.
export const DANGER_PROFILE_LABEL: Record<CampaignDangerProfile, string> = {
  story: "Story",
  standard: "Standard",
  harsh: "Harsh",
  lethal: "Lethal",
};

export const DANGER_PROFILE_BLURB: Record<CampaignDangerProfile, string> = {
  story:
    "Survivable fights: ordinary foes, low counts, quick morale, strong telegraphing.",
  standard:
    "Default Cairn 2e scale: ~3 HP common foes, ~6 HP veterans, serious threats only when telegraphed.",
  harsh:
    "Hardier foes and more resource pressure, but retreat and preparation still pay off.",
  lethal:
    "Serious threats and punishing abilities allowed when telegraphed; poor preparation can be fatal.",
};

export const GENRE_LABEL: Record<CampaignGenre, string> = {
  high_fantasy: "High fantasy",
  low_fantasy: "Low fantasy",
  sword_and_sorcery: "Sword & sorcery",
  dark_fantasy: "Dark fantasy",
  gothic_horror: "Gothic horror",
  cosmic_horror: "Cosmic horror",
  weird_fiction: "Weird fiction",
  fairy_tale: "Fairy tale",
  mythic: "Mythic",
  post_apocalyptic: "Post-apocalyptic",
  science_fantasy: "Science fantasy",
  historical_fantasy: "Historical fantasy",
  urban_fantasy: "Urban fantasy",
  hearth_and_homestead: "Hearth & homestead",
};

export const MAGIC_LEVEL_LABEL: Record<CampaignMagicLevel, string> = {
  none: "No magic",
  rare_numinous: "Rare & numinous",
  common: "Common",
  ubiquitous: "Ubiquitous",
};

export const TECH_LEVEL_LABEL: Record<CampaignTechLevel, string> = {
  stone: "Stone",
  iron: "Iron",
  medieval: "Medieval",
  renaissance: "Renaissance",
  industrial: "Industrial",
  modern: "Modern",
  spacefaring: "Spacefaring",
};

export const STAKES_SCALE_LABEL: Record<CampaignStakesScale, string> = {
  personal_local: "Personal / local",
  regional: "Regional",
  civilizational: "Civilizational",
  cosmic: "Cosmic",
};

// F-19 threat tier label for the combat tracker. Mirrors backend
// `EncounterThreatLevel`. The tracker also uses these as data-attribute
// keys for CSS coloring — keep the lowercase enum value in one place.
export const THREAT_LEVEL_LABEL: Record<EncounterThreatLevel, string> = {
  ordinary: "Ordinary",
  hardier: "Hardier",
  serious: "Serious",
};

// One-line explanation for the tier. We surface this in the foe
// tooltip / details so the player understands why a "Serious"-tier foe
// is justifying its 10+ HP bar.
export const THREAT_LEVEL_BLURB: Record<EncounterThreatLevel, string> = {
  ordinary: "Average Cairn foe — ~3 HP, quick to break.",
  hardier: "Veteran or hardened threat — ~6 HP, more deliberate.",
  serious: "Set-piece threat — 10+ HP, telegraphed and punishing.",
};

// F-18 advantage payoff labels. The same enum is used by the planner /
// combat-mechanics review on the backend; the label dictionary lives
// here so receipts and the future setup-UI both read from it.
export const ADVANTAGE_PAYOFF_LABEL: Record<EncounterAdvantagePayoff, string> = {
  enhanced_attack: "Enhanced strike",
  direct_str_damage: "Direct STR damage",
  skip_dex_gate: "Skip DEX gate",
  deny_enemy_action: "Deny enemy action",
  impair_enemy: "Impair enemy",
  force_morale: "Force morale check",
  expose_weakness: "Expose weakness",
};

// Short blurbs to clarify what each payoff actually grants when the
// follow-up attack consumes the setup. Used by the receipt body and
// (eventually) the setup-confirmation surface.
export const ADVANTAGE_PAYOFF_BLURB: Record<EncounterAdvantagePayoff, string> = {
  enhanced_attack: "Roll the foe's damage with advantage on your next strike.",
  direct_str_damage: "Bypass HP and shave the foe's STR directly.",
  skip_dex_gate: "Side-step the round-1 DEX save before swinging.",
  deny_enemy_action: "The foe loses its next action.",
  impair_enemy: "The foe's next attack rolls with disadvantage.",
  force_morale: "Force an immediate morale check on this foe / side.",
  expose_weakness: "Reveal the foe's weakness for the next combatant to exploit.",
};

// --- Presets -----------------------------------------------------------

// Curated CampaignSeed presets the editor offers as one-click starts.
// "Oppressive Dark Fantasy" mirrors the backend default exactly (so a
// player who picks it gets the same flavor they would have gotten on
// any pre-F-15 client). The other entries are deliberate excursions —
// they prove the sliders work and give the player a sense of the
// design space without forcing them to build a seed from scratch.
//
// NOTE: presets are pure data — they intentionally don't touch the
// network. Selecting one populates the editor; the player still has
// to confirm before the seed is sent to the backend.
export interface CampaignSeedPreset {
  id: string;
  label: string;
  blurb: string;
  seed: CampaignSeed;
}

export const CAMPAIGN_SEED_PRESETS: readonly CampaignSeedPreset[] = [
  {
    id: "oppressive_dark_fantasy",
    label: "Oppressive Dark Fantasy",
    blurb:
      "The default flavor: high-medieval, grim, dark, rare-numinous magic, regional stakes.",
    seed: {
      preset: "Oppressive Dark Fantasy",
      time_period: "high_medieval",
      tone_grim_noble: "grim",
      tone_dark_bright: "dark",
      danger_profile: "standard",
      genres: ["dark_fantasy"],
      magic_level: "rare_numinous",
      tech_level: "medieval",
      stakes_scale: "regional",
      inspirations: "Berserk + Dark Souls + Fear & Hunger",
      restrictions:
        "No modern slang. No copied characters, locations, factions, or lore.",
    },
  },
  {
    id: "ashen_pilgrimage",
    label: "Ashen Pilgrimage",
    blurb:
      "Mythic-timeless, mixed grim/noble, rare numinous magic, personal stakes — a quiet, devastating wandering.",
    seed: {
      preset: "Ashen Pilgrimage",
      time_period: "mythic_timeless",
      tone_grim_noble: "mixed",
      tone_dark_bright: "dark",
      danger_profile: "standard",
      genres: ["mythic", "dark_fantasy"],
      magic_level: "rare_numinous",
      tech_level: "iron",
      stakes_scale: "personal_local",
      inspirations: "Princess Mononoke + The Green Knight + Annihilation",
      restrictions:
        "No bombast. No god-tier set pieces. No copied characters or factions.",
    },
  },
  {
    id: "bone_grinders_war",
    label: "Bone Grinders' War",
    blurb:
      "Industrial-grimdark, lethal danger, science-fantasy + post-apocalyptic — the engines speak.",
    seed: {
      preset: "Bone Grinders' War",
      time_period: "industrial",
      tone_grim_noble: "grim",
      tone_dark_bright: "dark",
      danger_profile: "lethal",
      genres: ["dark_fantasy", "post_apocalyptic", "science_fantasy"],
      magic_level: "common",
      tech_level: "industrial",
      stakes_scale: "civilizational",
      inspirations: "Berserk + Bloodborne + 40k traitor regiments",
      restrictions:
        "No copied factions or characters. No clean victories. No modern slang.",
    },
  },
  {
    id: "lantern_road",
    label: "Lantern Road",
    blurb:
      "Hearth-and-homestead drift through gothic horror — softer combat, sharper dread, story-tier difficulty.",
    seed: {
      preset: "Lantern Road",
      time_period: "early_modern",
      tone_grim_noble: "mixed",
      tone_dark_bright: "mixed",
      danger_profile: "story",
      genres: ["gothic_horror", "hearth_and_homestead"],
      magic_level: "rare_numinous",
      tech_level: "renaissance",
      stakes_scale: "personal_local",
      inspirations: "Penny Dreadful + The VVitch + The Witcher novels",
      restrictions:
        "No bright fairy-tale beats. No copied characters or factions.",
    },
  },
] as const;

// True when two seeds are field-by-field equal. Used by the editor to
// label "this is your active preset" without trusting the player's
// preset string (a player who hand-edits any field changes the seed
// even if the preset name still matches).
export function seedsEqual(a: CampaignSeed, b: CampaignSeed): boolean {
  if (a.preset !== b.preset) return false;
  if (a.time_period !== b.time_period) return false;
  if (a.tone_grim_noble !== b.tone_grim_noble) return false;
  if (a.tone_dark_bright !== b.tone_dark_bright) return false;
  if (a.danger_profile !== b.danger_profile) return false;
  if (a.magic_level !== b.magic_level) return false;
  if (a.tech_level !== b.tech_level) return false;
  if (a.stakes_scale !== b.stakes_scale) return false;
  if (a.inspirations !== b.inspirations) return false;
  if (a.restrictions !== b.restrictions) return false;
  if (a.genres.length !== b.genres.length) return false;
  for (let i = 0; i < a.genres.length; i++) {
    if (a.genres[i] !== b.genres[i]) return false;
  }
  return true;
}

export function defaultCampaignSeed(): CampaignSeed {
  // Mirror the backend's `CampaignSeed()` defaults exactly. We surface
  // a fresh object on every call so callers can mutate it without
  // accidentally clobbering a shared baseline.
  return structuredClone(CAMPAIGN_SEED_PRESETS[0]!.seed);
}

// Concise "Preset · danger" label for the save library badge and the
// inspector strip. We keep the danger label in title-case (matching
// `DANGER_PROFILE_LABEL`) and the preset string verbatim because the
// preset can be any free-text label the player saved; a generic
// "campaign · standard" reads worse than the preset they chose.
export function seedBadgeLabel(seed: Pick<CampaignSeed, "preset" | "danger_profile">): string {
  const danger = DANGER_PROFILE_LABEL[seed.danger_profile];
  const preset = seed.preset.trim();
  if (preset === "") return danger;
  return `${preset} · ${danger}`;
}
