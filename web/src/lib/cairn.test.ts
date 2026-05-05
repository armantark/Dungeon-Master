import { describe, expect, it } from "vitest";

import {
  activeStatuses,
  cairnHeadline,
  defaultCairnCharacterState,
  defaultCairnItemState,
  formatAbility,
  formatBurden,
  formatRestKind,
  formatStance,
  hasCairnMechanics,
  itemTagLabel,
  itemTagLabels,
} from "./cairn";
import type {
  CairnItemTag,
  CairnResolution,
  CairnRestKind,
  OracleOutcome,
} from "./types";
import { CAIRN_ABILITIES, CAIRN_ITEM_TAGS } from "./types";

// We build outcomes via a helper because a partial OracleOutcome would
// drift from the real wire shape. Tests should rehearse the full shape
// the API returns, since cairnHeadline branches on `kind` and `cairn`
// fields that *must* line up with the backend's CairnResolution.
function makeOutcome(
  kind: OracleOutcome["kind"],
  cairn: CairnResolution | null = null,
): OracleOutcome {
  return {
    id: "oracle_test",
    created_at: "2024-01-01T00:00:00Z",
    kind,
    summary: "test outcome",
    rolls: [],
    question: null,
    likelihood: null,
    answer: null,
    probability: null,
    chaos_factor: 5,
    event_focus: null,
    event_action: null,
    event_tone: null,
    event_subject: null,
    referenced_thread_id: null,
    referenced_npc_id: null,
    scene_status: null,
    cairn,
  };
}

function emptyCairnResolution(): CairnResolution {
  return {
    ability: null,
    target: null,
    success: null,
    rest_kind: null,
    attack_stance: null,
    weapon_item_id: null,
    weapon_name: null,
    target_name: null,
    target_armor: null,
    base_damage: null,
    damage_after_armor: null,
    hp_before: null,
    hp_after: null,
    str_before: null,
    str_after: null,
    fatigue_before: null,
    fatigue_after: null,
    scar_result: null,
    overloaded: null,
  };
}

describe("default factories", () => {
  it("defaultCairnCharacterState mirrors the unset Pydantic defaults", () => {
    const state = defaultCairnCharacterState();
    expect(state.source).toBe("unset");
    expect(state.skills).toEqual([]);
    expect(state.abilities).toEqual([]);
    expect(state.slots_total).toBe(10);
    expect(state.backpack_slots).toBe(6);
    expect(state.comfortable_slots).toBe(5);
    expect(state.slots_used).toBe(0);
    expect(state.overloaded).toBe(false);
    expect(state.hp).toBe(1);
    expect(state.max_hp).toBe(1);
    expect(state.str_score).toBe(10);
    expect(state.dex_score).toBe(10);
    expect(state.wil_score).toBe(10);
  });

  it("defaultCairnItemState mirrors the unset Pydantic defaults", () => {
    const item = defaultCairnItemState();
    expect(item.source).toBe("unset");
    expect(item.tags).toEqual([]);
    expect(item.slots).toBe(1);
    expect(item.weapon_damage_die).toBeNull();
    expect(item.armor_bonus).toBe(0);
    expect(item.uses).toBeNull();
    expect(item.equipped).toBe(false);
  });
});

describe("hasCairnMechanics", () => {
  it("treats unset as not yet derived", () => {
    expect(hasCairnMechanics("unset")).toBe(false);
  });
  it("treats narrative_backfill and explicit as derived", () => {
    expect(hasCairnMechanics("narrative_backfill")).toBe(true);
    expect(hasCairnMechanics("explicit")).toBe(true);
  });
});

describe("formatBurden", () => {
  it("returns the comfortable tier for low burden", () => {
    const summary = formatBurden({
      ...defaultCairnCharacterState(),
      slots_used: 3,
    });
    expect(summary.tier).toBe("comfortable");
    expect(summary.used).toBe(3);
    expect(summary.total).toBe(10);
    expect(summary.comfortable).toBe(5);
    expect(summary.backpack).toBe(6);
    expect(summary.overloaded).toBe(false);
  });

  it("returns the backpack tier between comfortable and backpack", () => {
    const summary = formatBurden({
      ...defaultCairnCharacterState(),
      slots_used: 6,
    });
    expect(summary.tier).toBe("backpack");
    expect(summary.overloaded).toBe(false);
  });

  it("returns the overloaded tier when slots exceed backpack arithmetic", () => {
    const summary = formatBurden({
      ...defaultCairnCharacterState(),
      slots_used: 8,
    });
    expect(summary.tier).toBe("overloaded");
    expect(summary.overloaded).toBe(true);
  });

  it("trusts the backend overloaded flag even when arithmetic would not flag it", () => {
    const summary = formatBurden({
      ...defaultCairnCharacterState(),
      slots_used: 2,
      overloaded: true,
    });
    expect(summary.tier).toBe("overloaded");
    expect(summary.overloaded).toBe(true);
  });

  it("widens total when slots_used exceeds slots_total to avoid impossible bars", () => {
    const summary = formatBurden({
      ...defaultCairnCharacterState(),
      slots_used: 12,
      slots_total: 10,
    });
    expect(summary.total).toBe(12);
    expect(summary.tier).toBe("overloaded");
  });

  it("clamps negative slot counts to zero", () => {
    const summary = formatBurden({
      ...defaultCairnCharacterState(),
      slots_used: -3,
    });
    expect(summary.used).toBe(0);
  });
});

describe("activeStatuses", () => {
  it("returns an empty array when no flags are set", () => {
    expect(activeStatuses(defaultCairnCharacterState())).toEqual([]);
  });

  it("returns badges in priority order, never alphabetical", () => {
    const badges = activeStatuses({
      ...defaultCairnCharacterState(),
      deprived: true,
      doomed: true,
      dead: true,
      overloaded: true,
      paralyzed: true,
      delirious: true,
      critically_wounded: true,
    });
    expect(badges.map((b) => b.key)).toEqual([
      "dead",
      "doomed",
      "critically_wounded",
      "paralyzed",
      "delirious",
      "deprived",
      "overloaded",
    ]);
  });

  it("returns each individual flag in isolation", () => {
    const flags = [
      "dead",
      "doomed",
      "critically_wounded",
      "paralyzed",
      "delirious",
      "deprived",
      "overloaded",
    ] as const;
    for (const flag of flags) {
      const badges = activeStatuses({
        ...defaultCairnCharacterState(),
        [flag]: true,
      });
      expect(badges).toHaveLength(1);
      expect(badges[0]?.key).toBe(flag);
      expect(badges[0]?.label.length).toBeGreaterThan(0);
    }
  });
});

describe("itemTagLabel / itemTagLabels", () => {
  it("provides a human label for every CairnItemTag enum variant", () => {
    for (const tag of CAIRN_ITEM_TAGS) {
      const label = itemTagLabel(tag);
      expect(label.length).toBeGreaterThan(0);
      // Labels are title-cased, never empty, never the raw enum slug.
      expect(label).not.toBe(tag.toUpperCase());
    }
  });

  it("preserves the order in which tags appear on the item", () => {
    const tags: CairnItemTag[] = ["weapon", "ranged", "bulky"];
    const item = { ...defaultCairnItemState(), tags };
    expect(itemTagLabels(item)).toEqual(["Weapon", "Ranged", "Bulky"]);
  });

  it("returns an empty list for an item without tags", () => {
    expect(itemTagLabels(defaultCairnItemState())).toEqual([]);
  });
});

describe("formatAbility / formatStance / formatRestKind", () => {
  it("handles every CairnAbility variant", () => {
    for (const ability of CAIRN_ABILITIES) {
      expect(formatAbility(ability)).toBe(ability);
    }
    expect(formatAbility(null)).toBeNull();
  });

  it("handles every AttackStance variant", () => {
    expect(formatStance("normal")).toBe("Normal");
    expect(formatStance("impaired")).toBe("Impaired");
    expect(formatStance("enhanced")).toBe("Enhanced");
    expect(formatStance(null)).toBeNull();
  });

  it("handles every CairnRestKind variant", () => {
    const kinds: CairnRestKind[] = ["breather", "full_rest", "week_recovery"];
    for (const kind of kinds) {
      const formatted = formatRestKind(kind);
      expect(formatted).not.toBeNull();
      expect((formatted as string).length).toBeGreaterThan(0);
    }
    expect(formatRestKind(null)).toBeNull();
  });
});

describe("cairnHeadline", () => {
  it("returns null for non-Cairn outcome kinds", () => {
    const oracleKinds: OracleOutcome["kind"][] = [
      "yes_no",
      "random_event",
      "scene_check",
      "player_action",
    ];
    for (const kind of oracleKinds) {
      expect(cairnHeadline(makeOutcome(kind))).toBeNull();
    }
  });

  it("returns null-safe headlines when cairn is missing for a Cairn kind", () => {
    expect(cairnHeadline(makeOutcome("save"))).toBe("Save");
    expect(cairnHeadline(makeOutcome("attack"))).toBe("Attack");
    expect(cairnHeadline(makeOutcome("harm"))).toBe("Harm");
    expect(cairnHeadline(makeOutcome("recovery"))).toBe("Recovery");
  });

  it("formats save headlines for each ability and outcome", () => {
    for (const ability of CAIRN_ABILITIES) {
      const passed = makeOutcome("save", {
        ...emptyCairnResolution(),
        ability,
        success: true,
      });
      const failed = makeOutcome("save", {
        ...emptyCairnResolution(),
        ability,
        success: false,
      });
      const unresolved = makeOutcome("save", {
        ...emptyCairnResolution(),
        ability,
      });
      expect(cairnHeadline(passed)).toBe(`Save · ${ability} · passed`);
      expect(cairnHeadline(failed)).toBe(`Save · ${ability} · failed`);
      expect(cairnHeadline(unresolved)).toBe(`Save · ${ability} · rolled`);
    }
  });

  it("formats attack headlines with target and damage", () => {
    const dealt = makeOutcome("attack", {
      ...emptyCairnResolution(),
      target_name: "Roadside brigand",
      damage_after_armor: 4,
    });
    expect(cairnHeadline(dealt)).toBe("Attack · Roadside brigand · 4 dmg");

    const noDamage = makeOutcome("attack", {
      ...emptyCairnResolution(),
      target_name: "Plague-ox",
    });
    expect(cairnHeadline(noDamage)).toBe("Attack · Plague-ox");
  });

  it("formats harm headlines with damage, hp tracking, and optional scar", () => {
    const survived = makeOutcome("harm", {
      ...emptyCairnResolution(),
      damage_after_armor: 3,
      hp_after: 2,
    });
    expect(cairnHeadline(survived)).toBe("Harm · 3 · HP 2");

    const scarred = makeOutcome("harm", {
      ...emptyCairnResolution(),
      damage_after_armor: 5,
      hp_after: 0,
      scar_result: "Lasting Scar (Eye)",
    });
    expect(cairnHeadline(scarred)).toBe("Harm · 5 · HP 0 · Lasting Scar (Eye)");

    const minimal = makeOutcome("harm", { ...emptyCairnResolution() });
    expect(cairnHeadline(minimal)).toBe("Harm");
  });

  it("formats recovery headlines for each rest kind", () => {
    const rests: CairnRestKind[] = ["breather", "full_rest", "week_recovery"];
    for (const rest_kind of rests) {
      const outcome = makeOutcome("recovery", {
        ...emptyCairnResolution(),
        rest_kind,
      });
      const headline = cairnHeadline(outcome);
      expect(headline?.startsWith("Recovery · ")).toBe(true);
    }
  });
});
