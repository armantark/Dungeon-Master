import { describe, expect, it } from "vitest";

import {
  ADVANTAGE_PAYOFF_BLURB,
  ADVANTAGE_PAYOFF_LABEL,
  CAMPAIGN_SEED_PRESETS,
  DANGER_PROFILE_BLURB,
  DANGER_PROFILE_LABEL,
  defaultCampaignSeed,
  GENRE_LABEL,
  MAGIC_LEVEL_LABEL,
  STAKES_SCALE_LABEL,
  TECH_LEVEL_LABEL,
  THREAT_LEVEL_LABEL,
  TIME_PERIOD_LABEL,
  TONE_DARK_BRIGHT_LABEL,
  TONE_GRIM_NOBLE_LABEL,
  seedBadgeLabel,
  seedsEqual,
} from "./campaign-seed";
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

// --- Default seed --------------------------------------------------------

describe("defaultCampaignSeed", () => {
  it("mirrors the backend's CampaignSeed() defaults exactly", () => {
    // The first registered preset is "Oppressive Dark Fantasy" which
    // by design matches the backend's default field values. Pinning
    // this here means any drift between the backend default and the
    // frontend default surfaces as a test failure rather than an
    // invisible UX divergence.
    const seed = defaultCampaignSeed();
    expect(seed.preset).toBe("Oppressive Dark Fantasy");
    expect(seed.time_period).toBe("high_medieval");
    expect(seed.tone_grim_noble).toBe("grim");
    expect(seed.tone_dark_bright).toBe("dark");
    expect(seed.danger_profile).toBe("standard");
    expect(seed.genres).toEqual(["dark_fantasy"]);
    expect(seed.magic_level).toBe("rare_numinous");
    expect(seed.tech_level).toBe("medieval");
    expect(seed.stakes_scale).toBe("regional");
    expect(seed.inspirations).toContain("Berserk");
  });

  it("returns a fresh object each call so callers can mutate without crosstalk", () => {
    const a = defaultCampaignSeed();
    const b = defaultCampaignSeed();
    a.genres.push("gothic_horror");
    expect(b.genres).toEqual(["dark_fantasy"]);
  });
});

// --- Label dictionaries --------------------------------------------------

describe("label dictionaries cover every enum variant", () => {
  // We don't import the const lists from types.ts because the unions
  // are pure type-level. Instead we keep an explicit list here so
  // adding a new variant on the backend forces a TS error in this
  // file when the corresponding label is missing.
  it("labels every CampaignTimePeriod", () => {
    const keys: CampaignTimePeriod[] = [
      "bronze_age",
      "classical_antiquity",
      "early_medieval",
      "high_medieval",
      "renaissance",
      "early_modern",
      "industrial",
      "modern",
      "near_future",
      "far_future",
      "post_apocalyptic",
      "mythic_timeless",
    ];
    for (const k of keys) expect(TIME_PERIOD_LABEL[k]).toBeDefined();
  });

  it("labels every tone variant", () => {
    const grim: CampaignToneGrimNoble[] = ["grim", "mixed", "noble"];
    const dark: CampaignToneDarkBright[] = ["dark", "mixed", "bright"];
    for (const g of grim) expect(TONE_GRIM_NOBLE_LABEL[g]).toBeDefined();
    for (const d of dark) expect(TONE_DARK_BRIGHT_LABEL[d]).toBeDefined();
  });

  it("labels every danger profile and supplies a non-empty blurb", () => {
    const dangers: CampaignDangerProfile[] = ["story", "standard", "harsh", "lethal"];
    for (const d of dangers) {
      expect(DANGER_PROFILE_LABEL[d]).toBeDefined();
      expect(DANGER_PROFILE_BLURB[d].length).toBeGreaterThan(10);
    }
  });

  it("labels every genre", () => {
    const genres: CampaignGenre[] = [
      "high_fantasy",
      "low_fantasy",
      "sword_and_sorcery",
      "dark_fantasy",
      "gothic_horror",
      "cosmic_horror",
      "weird_fiction",
      "fairy_tale",
      "mythic",
      "post_apocalyptic",
      "science_fantasy",
      "historical_fantasy",
      "urban_fantasy",
      "hearth_and_homestead",
    ];
    for (const g of genres) expect(GENRE_LABEL[g]).toBeDefined();
  });

  it("labels every magic / tech / stakes variant", () => {
    const magic: CampaignMagicLevel[] = ["none", "rare_numinous", "common", "ubiquitous"];
    const tech: CampaignTechLevel[] = [
      "stone",
      "iron",
      "medieval",
      "renaissance",
      "industrial",
      "modern",
      "spacefaring",
    ];
    const stakes: CampaignStakesScale[] = [
      "personal_local",
      "regional",
      "civilizational",
      "cosmic",
    ];
    for (const m of magic) expect(MAGIC_LEVEL_LABEL[m]).toBeDefined();
    for (const t of tech) expect(TECH_LEVEL_LABEL[t]).toBeDefined();
    for (const s of stakes) expect(STAKES_SCALE_LABEL[s]).toBeDefined();
  });

  it("labels every threat level", () => {
    const tiers: EncounterThreatLevel[] = ["ordinary", "hardier", "serious"];
    for (const t of tiers) expect(THREAT_LEVEL_LABEL[t]).toBeDefined();
  });

  it("labels every advantage payoff and supplies a non-empty blurb", () => {
    // The dictionary is the single source of truth for receipts and
    // tracker pills — if a new payoff lands on the backend we want
    // the test to fail until both the label and the blurb are
    // populated.
    const payoffs: EncounterAdvantagePayoff[] = [
      "enhanced_attack",
      "direct_str_damage",
      "skip_dex_gate",
      "deny_enemy_action",
      "impair_enemy",
      "force_morale",
      "expose_weakness",
    ];
    for (const p of payoffs) {
      expect(ADVANTAGE_PAYOFF_LABEL[p]).toBeDefined();
      expect(ADVANTAGE_PAYOFF_BLURB[p].length).toBeGreaterThan(10);
    }
  });
});

// --- Presets -------------------------------------------------------------

describe("CAMPAIGN_SEED_PRESETS", () => {
  it("has at least one preset and each preset's seed round-trips through seedsEqual", () => {
    expect(CAMPAIGN_SEED_PRESETS.length).toBeGreaterThan(0);
    for (const preset of CAMPAIGN_SEED_PRESETS) {
      // `seedsEqual` is the contract the editor uses to detect
      // "this is a known preset". A preset that doesn't match
      // itself would mean the editor never highlights it.
      expect(seedsEqual(preset.seed, preset.seed)).toBe(true);
    }
  });

  it("uses unique preset ids", () => {
    const ids = new Set(CAMPAIGN_SEED_PRESETS.map((p) => p.id));
    expect(ids.size).toBe(CAMPAIGN_SEED_PRESETS.length);
  });
});

// --- seedsEqual ----------------------------------------------------------

describe("seedsEqual", () => {
  function customSeed(): CampaignSeed {
    return defaultCampaignSeed();
  }

  it("treats deeply equal seeds as equal", () => {
    expect(seedsEqual(customSeed(), customSeed())).toBe(true);
  });

  it("returns false when the danger profile differs", () => {
    const a = customSeed();
    const b = { ...customSeed(), danger_profile: "lethal" as const };
    expect(seedsEqual(a, b)).toBe(false);
  });

  it("returns false when genres differ in length or order", () => {
    const base = customSeed();
    const extra = { ...base, genres: [...base.genres, "gothic_horror" as const] };
    expect(seedsEqual(base, extra)).toBe(false);

    // Order matters for the editor's "active preset" detection — we
    // want the player to see "this matches the preset" only when the
    // saved seed exactly mirrors the preset, including ordering. A
    // preset reordered by hand reads as a custom seed.
    const reordered: CampaignSeed = {
      ...base,
      genres: ["gothic_horror", "dark_fantasy"],
    };
    const ordered: CampaignSeed = {
      ...base,
      genres: ["dark_fantasy", "gothic_horror"],
    };
    expect(seedsEqual(reordered, ordered)).toBe(false);
  });

  it("returns false when free-text fields drift", () => {
    const a = customSeed();
    const b = { ...customSeed(), inspirations: "Different" };
    expect(seedsEqual(a, b)).toBe(false);
  });
});

// --- seedBadgeLabel ------------------------------------------------------

describe("seedBadgeLabel", () => {
  it("renders 'Preset · Danger' when both are present", () => {
    const label = seedBadgeLabel({
      preset: "Bone Grinders' War",
      danger_profile: "lethal",
    });
    expect(label).toBe("Bone Grinders' War · Lethal");
  });

  it("falls back to the danger label alone when the preset string is empty", () => {
    // A custom save with no preset text shouldn't render as
    // "  · Standard" — the editor allows the player to clear the
    // preset name, and the badge should still feel deliberate.
    const label = seedBadgeLabel({
      preset: "   ",
      danger_profile: "standard",
    });
    expect(label).toBe("Standard");
  });
});
