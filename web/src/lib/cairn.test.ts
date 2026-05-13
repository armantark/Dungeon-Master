import { describe, expect, it } from "vitest";

import {
  activeStatuses,
  cairnHeadline,
  defaultCairnCharacterState,
  defaultCairnItemState,
  defaultCairnSurvivalClock,
  FOOD_DEPRIVED_WATCHES,
  FOOD_WARNING_WATCHES,
  foodPressureMeter,
  foodPressureTier,
  formatDayPhase,
  formatSurvivalLine,
  formatTimeAdvance,
  formatTurnTimeAdvance,
  hasItemPower,
  itemEffectLabel,
  itemPowerKindLabel,
  itemPowerSummary,
  itemPowerTitle,
  formatAbility,
  formatBurden,
  formatCombatInitiator,
  formatRestKind,
  formatResourceCost,
  formatResourceDelta,
  formatResourcePool,
  formatStance,
  hasCairnMechanics,
  isAmbushOpener,
  itemTagLabel,
  itemTagLabels,
  SLEEP_DEPRIVED_WATCHES,
  SLEEP_WARNING_WATCHES,
  sleepPressureMeter,
  sleepPressureTier,
  survivalChanged,
  WATCHES_PER_DAY,
} from "./cairn";
import type {
  CairnDayPhase,
  CairnItemTag,
  CairnResolution,
  CairnRestKind,
  CairnSurvivalClock,
  CairnTimeAdvance,
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
    referenced_thread_ids: [],
    referenced_npc_id: null,
    referenced_npc_ids: [],
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
    time_advance: null,
    day_number_before: null,
    day_number_after: null,
    watch_index_before: null,
    watch_index_after: null,
    day_phase_before: null,
    day_phase_after: null,
    watches_since_meal_before: null,
    watches_since_meal_after: null,
    watches_since_sleep_before: null,
    watches_since_sleep_after: null,
    food_deprived_before: null,
    food_deprived_after: null,
    sleep_deprived_before: null,
    sleep_deprived_after: null,
    deprived_before: null,
    deprived_after: null,
    ration_item_id: null,
    ration_item_name: null,
    ration_uses_before: null,
    ration_uses_after: null,
    actor_id: null,
    actor_name: null,
    item_id: null,
    item_name: null,
    item_power_kind: null,
    item_effect_kind: null,
    effect_summary: null,
    uses_before: null,
    uses_after: null,
    recharge_condition: null,
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
    dex_before: null,
    dex_after: null,
    wil_before: null,
    wil_after: null,
    fatigue_before: null,
    fatigue_after: null,
    combat_round: null,
    combat_started: null,
    combat_active: null,
    combat_initiator: null,
    player_acted: null,
    initiative_target: null,
    scar_result: null,
    target_combatant_id: null,
    target_hp_before: null,
    target_hp_after: null,
    target_str_before: null,
    target_str_after: null,
    target_defeated: null,
    target_fled: null,
    enemy_damage: null,
    enemy_damage_source: null,
    morale_target: null,
    morale_success: null,
    coordinated_attack: false,
    coordinated_participants: [],
    defeated_combatant_ids: [],
    fled_combatant_ids: [],
    retreat_outcome: null,
    player_disengaged: null,
    pursuit_active: null,
    encounter_end_reason: null,
    resource_deltas: [],
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
    // Survival clock is mirrored at its resting state — Day 1, dawn,
    // no pressure, no flags. The whole-state factory must include it
    // by construction so freshly drafted sheets round-trip through
    // the wire shape without TypeScript pruning the field.
    expect(state.survival).toEqual(defaultCairnSurvivalClock());
  });

  it("defaultCairnSurvivalClock mirrors the resting Pydantic defaults", () => {
    const survival = defaultCairnSurvivalClock();
    expect(survival.day_number).toBe(1);
    expect(survival.watch_index).toBe(0);
    expect(survival.day_phase).toBe("dawn");
    expect(survival.watches_since_meal).toBe(0);
    expect(survival.watches_since_sleep).toBe(0);
    expect(survival.food_deprived).toBe(false);
    expect(survival.sleep_deprived).toBe(false);
    expect(survival.other_deprived).toBe(false);
  });

  it("defaultCairnItemState mirrors the unset Pydantic defaults", () => {
    const item = defaultCairnItemState();
    expect(item.source).toBe("unset");
    expect(item.tags).toEqual([]);
    expect(item.slots).toBe(1);
    expect(item.weapon_damage_die).toBeNull();
    expect(item.armor_bonus).toBe(0);
    expect(item.uses).toBeNull();
    expect(item.resources).toEqual([]);
    expect(item.attack_costs).toEqual([]);
    expect(item.use_costs).toEqual([]);
    expect(item.equipped).toBe(false);
    expect(item.power).toEqual({
      kind: "none",
      name: "",
      summary: "",
      effect: "none",
      effect_amount: 1,
      effect_ability: null,
      clears_condition: null,
      recharge_condition: "",
      requires_wil_save_in_danger: false,
      adds_fatigue: false,
      consumed_on_use: false,
    });
  });
});

describe("resource formatting", () => {
  it("formats finite and unbounded resource pools", () => {
    expect(
      formatResourcePool({
        id: "res_arrows",
        label: "Arrows",
        kind: "ammo",
        current: 7,
        max: 12,
        recharge_policy: "none",
        recharge_amount: 1,
        recharge_condition: "",
        notes: "",
      }),
    ).toBe("Arrows 7/12");
    expect(
      formatResourcePool({
        id: "res_stones",
        label: "Soul stones",
        kind: "component",
        current: 2,
        max: null,
        recharge_policy: "none",
        recharge_amount: 1,
        recharge_condition: "",
        notes: "",
      }),
    ).toBe("Soul stones 2");
  });

  it("formats resource costs by draw policy", () => {
    expect(
      formatResourceCost({
        label: "Arrows",
        kind: "ammo",
        amount: 1,
        draw_policy: "actor_inventory",
        resource_id: null,
        linked_item_id: null,
        required: true,
      }),
    ).toBe("Arrows from inventory");
    expect(
      formatResourceCost({
        label: "Charges",
        kind: "charge",
        amount: 2,
        draw_policy: "self",
        resource_id: null,
        linked_item_id: null,
        required: true,
      }),
    ).toBe("2 Charges");
  });

  it("formats resource deltas with actor and item attribution", () => {
    expect(
      formatResourceDelta({
        actor_id: "party_drusus",
        actor_name: "Drusus",
        item_id: "item_quiver",
        item_name: "Drusus' quiver",
        resource_id: "res_arrows",
        resource_label: "Arrows",
        resource_kind: "ammo",
        before: 4,
        after: 3,
        amount: 1,
        reason: "attack",
        note: "",
      }),
    ).toBe("Drusus · Drusus' quiver · Arrows 4 → 3");
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

describe("item power helpers", () => {
  it("suppresses mundane power blocks", () => {
    const power = defaultCairnItemState().power;
    expect(hasItemPower(power)).toBe(false);
    expect(itemPowerTitle(power)).toBeNull();
    expect(itemPowerSummary(power)).toBeNull();
  });

  it("labels known power and effect variants", () => {
    expect(itemPowerKindLabel("holy_relic")).toBe("Holy relic");
    expect(itemPowerKindLabel("spellbook")).toBe("Spellbook");
    expect(itemEffectLabel("restore_attribute")).toBe("Restore attribute");
    expect(itemEffectLabel("ward_or_pacify")).toBe("Ward or pacify");
  });

  it("formats explicit item powers without inferring from prose", () => {
    const power = {
      ...defaultCairnItemState().power,
      kind: "holy_relic" as const,
      name: "Icon of Saint Brindle",
      summary: "Restore WIL by 2 when invoked in honest distress.",
      effect: "restore_attribute" as const,
      effect_amount: 2,
      effect_ability: "WIL" as const,
      requires_wil_save_in_danger: true,
    };

    expect(hasItemPower(power)).toBe(true);
    expect(itemPowerTitle(power)).toBe("Holy relic · Icon of Saint Brindle");
    expect(itemPowerSummary(power)).toBe(
      "Restore WIL by 2 when invoked in honest distress.",
    );
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

  it("formats item-use player actions when the backend supplies Cairn fields", () => {
    const outcome = makeOutcome("player_action", {
      ...emptyCairnResolution(),
      item_name: "Icon of Saint Brindle",
      item_power_kind: "holy_relic",
      item_effect_kind: "restore_attribute",
      uses_before: 2,
      uses_after: 1,
    });

    expect(cairnHeadline(outcome)).toBe(
      "Item · Icon of Saint Brindle · Holy relic · uses 2->1",
    );
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

  it("formats coordinated attack headlines without a new outcome kind", () => {
    const coordinated = makeOutcome("attack", {
      ...emptyCairnResolution(),
      target_name: "Roadside brigand",
      damage_after_armor: 5,
      coordinated_attack: true,
      coordinated_participants: [
        {
          actor_id: null,
          actor_name: "Vrtanes",
          weapon_item_id: "item_cudgel",
          weapon_name: "Notched iron cudgel",
          base_damage: 5,
          damage_after_armor: 5,
          target_hp_before: 6,
          target_hp_after: 1,
          target_str_before: 12,
          target_str_after: 12,
          target_defeated: false,
          target_fled: false,
          acted: true,
        },
      ],
    });

    expect(cairnHeadline(coordinated)).toBe("Coordinated attack · Roadside brigand · 5 dmg");
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

  it("rewrites the harm headline as 'Ambush · …' when the foe opened the fight", () => {
    // F-05: when the backend's CairnResolution carries
    // `combat_started=true` together with `combat_initiator='enemy'`,
    // the receipt strip should read "Ambush · 2 · HP 4" instead of
    // "Harm · 2 · HP 4". Anything weaker than both signals together
    // (e.g. only `combat_started`, or `initiator='player'`) keeps the
    // generic "Harm · …" prefix because the player chose the fight.
    const opener = makeOutcome("harm", {
      ...emptyCairnResolution(),
      damage_after_armor: 2,
      hp_after: 4,
      combat_started: true,
      combat_initiator: "enemy",
    });
    expect(cairnHeadline(opener)).toBe("Ambush · 2 · HP 4");

    const playerStartedFight = makeOutcome("harm", {
      ...emptyCairnResolution(),
      damage_after_armor: 2,
      hp_after: 4,
      combat_started: true,
      combat_initiator: "player",
    });
    expect(cairnHeadline(playerStartedFight)).toBe("Harm · 2 · HP 4");

    const ongoingFight = makeOutcome("harm", {
      ...emptyCairnResolution(),
      damage_after_armor: 2,
      hp_after: 4,
      combat_started: false,
      combat_initiator: "enemy",
    });
    expect(cairnHeadline(ongoingFight)).toBe("Harm · 2 · HP 4");
  });
});

describe("formatCombatInitiator", () => {
  it("labels each known initiator with a player-facing string", () => {
    expect(formatCombatInitiator("player")).toBe("Player opened the fight");
    expect(formatCombatInitiator("enemy")).toBe("Foe seized initiative");
  });

  it("returns null for an absent initiator (out-of-combat harm or legacy outcome)", () => {
    // The receipt uses null as the "skip the row" signal. We test
    // both null and undefined because the wire shape declares the
    // field optional and older outcomes simply omit it.
    expect(formatCombatInitiator(null)).toBeNull();
    expect(formatCombatInitiator(undefined)).toBeNull();
  });
});

describe("isAmbushOpener", () => {
  it("requires both combat_started and an enemy initiator", () => {
    // Both signals are necessary because a player attack that
    // opened combat also flips combat_started=true. Only the
    // enemy-opener path is the "you got jumped" case.
    expect(
      isAmbushOpener(
        makeOutcome("harm", {
          ...emptyCairnResolution(),
          combat_started: true,
          combat_initiator: "enemy",
        }),
      ),
    ).toBe(true);

    expect(
      isAmbushOpener(
        makeOutcome("harm", {
          ...emptyCairnResolution(),
          combat_started: true,
          combat_initiator: "player",
        }),
      ),
    ).toBe(false);

    expect(
      isAmbushOpener(
        makeOutcome("harm", {
          ...emptyCairnResolution(),
          combat_started: false,
          combat_initiator: "enemy",
        }),
      ),
    ).toBe(false);

    // A harm outcome with no Cairn block at all (defensive — the
    // backend always produces one for harm, but the type is
    // nullable) must never read as an ambush.
    expect(isAmbushOpener(makeOutcome("harm"))).toBe(false);

    // Non-harm Cairn kinds also shouldn't latch true even if a
    // future regression fills both fields — initiative carries
    // into the receipt only via `formatCombatInitiator`, never via
    // the ambush flag.
    expect(
      isAmbushOpener(
        makeOutcome("attack", {
          ...emptyCairnResolution(),
          combat_started: true,
          combat_initiator: "enemy",
        }),
      ),
    ).toBe(true);
    // ^ Note: the predicate is structural ("did this outcome open a
    // fight as an ambush?") rather than kind-gated, so an attack
    // outcome with both signals would also count. The receipt
    // component only consults this for harm rows in practice
    // because the strip tag swap is keyed off `outcome.kind === "harm"`
    // implicitly via `formatHarmHeadline`. We still pin the
    // structural behavior here so a future change to the receipt
    // can rely on the predicate consistently.
  });
});

// --- Survival clock helpers -------------------------------------------
//
// These tests pin the *frontend* contract for the watch clock:
// presentation-only translation of backend numeric pressure into
// tier reads + meter shapes, plus the receipt-side
// "did anything actually move?" predicate. The backend owns when
// deprivation flips; the frontend just renders the verdict and the
// approach.

function survivalAt(overrides: Partial<CairnSurvivalClock> = {}): CairnSurvivalClock {
  return { ...defaultCairnSurvivalClock(), ...overrides };
}

describe("formatDayPhase / formatTimeAdvance", () => {
  it("labels every CairnDayPhase variant", () => {
    const phases: CairnDayPhase[] = ["dawn", "day", "dusk", "night", "deep_night"];
    for (const phase of phases) {
      const label = formatDayPhase(phase);
      expect(label.length).toBeGreaterThan(0);
      expect(label[0]).toBe(label[0]?.toUpperCase());
    }
    expect(formatDayPhase("deep_night")).toBe("Deep night");
  });

  it("labels every CairnTimeAdvance variant and skips 'none' on the receipt path", () => {
    const advances: CairnTimeAdvance[] = ["none", "brief", "watch", "day", "overnight"];
    for (const advance of advances) {
      expect(formatTimeAdvance(advance)).not.toBeNull();
    }
    expect(formatTimeAdvance(null)).toBeNull();
    // formatTurnTimeAdvance is the receipt-facing variant: it
    // suppresses `none` because the receipt should not surface
    // "No time passes" as a row of its own.
    expect(formatTurnTimeAdvance("none")).toBeNull();
    expect(formatTurnTimeAdvance(null)).toBeNull();
    expect(formatTurnTimeAdvance("watch")).toBe("A watch");
  });
});

describe("formatSurvivalLine", () => {
  it("1-indexes the watch in the readable line so the player feels the current beat", () => {
    // Backend `watch_index=0, day_phase=dawn` reads as "Watch 1/6"
    // because watches are inclusive of the current beat. The
    // underlying field stays 0-indexed; this is purely presentation.
    expect(formatSurvivalLine(survivalAt({ watch_index: 0, day_phase: "dawn" }))).toBe(
      `Day 1 · Dawn · Watch 1/${WATCHES_PER_DAY}`,
    );
    expect(
      formatSurvivalLine(
        survivalAt({ day_number: 3, watch_index: 4, day_phase: "night" }),
      ),
    ).toBe(`Day 3 · Night · Watch 5/${WATCHES_PER_DAY}`);
  });

  it("clamps the human watch number at WATCHES_PER_DAY for the deep-night beat", () => {
    // watch_index=5 is the deep-night beat; the human watch should
    // read 6/6, never 7/6, even if the backend ever overshoots.
    expect(
      formatSurvivalLine(
        survivalAt({ watch_index: 5, day_phase: "deep_night" }),
      ),
    ).toBe(`Day 1 · Deep night · Watch ${WATCHES_PER_DAY}/${WATCHES_PER_DAY}`);
  });
});

describe("foodPressureTier / sleepPressureTier", () => {
  it("returns 'easy' below the warning watermark", () => {
    expect(foodPressureTier(survivalAt({ watches_since_meal: 0 }))).toBe("easy");
    expect(
      foodPressureTier(survivalAt({ watches_since_meal: FOOD_WARNING_WATCHES - 1 })),
    ).toBe("easy");
    expect(sleepPressureTier(survivalAt({ watches_since_sleep: 0 }))).toBe("easy");
    expect(
      sleepPressureTier(survivalAt({ watches_since_sleep: SLEEP_WARNING_WATCHES - 1 })),
    ).toBe("easy");
  });

  it("returns 'warning' between the warning and deprivation watermarks", () => {
    // The "warning" tier is presentational — the backend has *not*
    // yet flipped the deprived flag, so we must not claim to be
    // authoritative. We pin both edges of the range here.
    expect(
      foodPressureTier(survivalAt({ watches_since_meal: FOOD_WARNING_WATCHES })),
    ).toBe("warning");
    expect(
      sleepPressureTier(survivalAt({ watches_since_sleep: SLEEP_WARNING_WATCHES })),
    ).toBe("warning");
    // Pressure can sit at the deprivation watermark while the
    // backend still hasn't flipped (e.g. an item suppresses it). We
    // honor the backend flag, so without it we still read 'warning'.
    expect(
      foodPressureTier(
        survivalAt({ watches_since_meal: FOOD_DEPRIVED_WATCHES, food_deprived: false }),
      ),
    ).toBe("warning");
  });

  it("returns 'deprived' when the backend has flipped the flag, regardless of pressure", () => {
    // The backend's flag is authoritative. A character whose food
    // pressure is below the warning watermark but who is *flagged*
    // deprived (e.g. by a scar) should still read 'deprived' on the
    // food meter — because that's what is gating HP.
    expect(
      foodPressureTier(survivalAt({ watches_since_meal: 0, food_deprived: true })),
    ).toBe("deprived");
    expect(
      sleepPressureTier(
        survivalAt({ watches_since_sleep: 1, sleep_deprived: true }),
      ),
    ).toBe("deprived");
  });
});

describe("foodPressureMeter / sleepPressureMeter", () => {
  it("shapes a meter the bar can render directly", () => {
    const food = foodPressureMeter(
      survivalAt({ watches_since_meal: FOOD_DEPRIVED_WATCHES, food_deprived: true }),
    );
    expect(food.threshold).toBe(FOOD_DEPRIVED_WATCHES);
    expect(food.warning).toBe(FOOD_WARNING_WATCHES);
    expect(food.value).toBe(FOOD_DEPRIVED_WATCHES);
    expect(food.tier).toBe("deprived");
    expect(food.deprived).toBe(true);

    const sleep = sleepPressureMeter(survivalAt({ watches_since_sleep: 5 }));
    expect(sleep.threshold).toBe(SLEEP_DEPRIVED_WATCHES);
    expect(sleep.warning).toBe(SLEEP_WARNING_WATCHES);
    expect(sleep.value).toBe(5);
    expect(sleep.tier).toBe("warning");
    expect(sleep.deprived).toBe(false);
  });

  it("clamps negative pressure to zero (defensive against weird wire shapes)", () => {
    // Backend `Field(ge=0)` should make this impossible, but we
    // defend the renderer anyway — a negative segment count would
    // crash the meter loop.
    const food = foodPressureMeter(survivalAt({ watches_since_meal: -1 }));
    expect(food.value).toBe(0);
    expect(food.tier).toBe("easy");
  });
});

describe("survivalChanged", () => {
  function emptySurvival(): CairnResolution {
    return emptyCairnResolution();
  }

  it("returns false when no survival fields moved", () => {
    expect(survivalChanged(emptySurvival())).toBe(false);
    // A `none` time advance with no eat is the canonical "this turn
    // didn't bill the clock" shape. Receipt should stay quiet.
    expect(survivalChanged({ ...emptySurvival(), time_advance: "none" })).toBe(false);
  });

  it("returns true when the router billed real time", () => {
    expect(
      survivalChanged({ ...emptySurvival(), time_advance: "watch" }),
    ).toBe(true);
    expect(
      survivalChanged({ ...emptySurvival(), time_advance: "overnight" }),
    ).toBe(true);
  });

  it("returns true when the player ate, even with no time passing", () => {
    // A pure `eat` action (player ate without time advancing) still
    // belongs on the receipt — the ration was consumed.
    expect(
      survivalChanged({
        ...emptySurvival(),
        time_advance: "none",
        ration_item_id: "item_ration_1",
        ration_item_name: "Trail rations",
        ration_uses_before: 3,
        ration_uses_after: 2,
      }),
    ).toBe(true);
  });

  it("returns true when any pressure / deprivation pair shifted", () => {
    // Each axis on its own should flip the predicate, since the
    // receipt should never silently drop a real change.
    expect(
      survivalChanged({
        ...emptySurvival(),
        watches_since_meal_before: 2,
        watches_since_meal_after: 0,
      }),
    ).toBe(true);
    expect(
      survivalChanged({
        ...emptySurvival(),
        watches_since_sleep_before: 0,
        watches_since_sleep_after: 1,
      }),
    ).toBe(true);
    expect(
      survivalChanged({
        ...emptySurvival(),
        food_deprived_before: true,
        food_deprived_after: false,
      }),
    ).toBe(true);
    expect(
      survivalChanged({
        ...emptySurvival(),
        deprived_before: false,
        deprived_after: true,
      }),
    ).toBe(true);
  });

  it("does not flip on equal before/after pairs", () => {
    // A turn where watches_since_meal stayed at 2 (engine snapshot
    // taken but no movement) shouldn't be surfaced as a change.
    expect(
      survivalChanged({
        ...emptySurvival(),
        watches_since_meal_before: 2,
        watches_since_meal_after: 2,
        watches_since_sleep_before: 4,
        watches_since_sleep_after: 4,
        food_deprived_before: false,
        food_deprived_after: false,
        sleep_deprived_before: false,
        sleep_deprived_after: false,
      }),
    ).toBe(false);
  });
});
