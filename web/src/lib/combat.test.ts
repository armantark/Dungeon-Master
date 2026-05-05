import { describe, expect, it } from "vitest";

import {
  combatFromState,
  combatantHpTier,
  combatantStatusLabel,
  encounterHeadline,
  firstRoundActionGated,
  sortCombatants,
  type CombatantState,
  type CombatantStatus,
  type CombatEncounterState,
} from "./combat";

// We intentionally test the helpers as pure functions; there's no
// rendering test here because the Svelte component is structural and
// the logic worth pinning lives in these helpers. Tests that *also*
// run the component would just rehearse Svelte's own template engine.

function makeFoe(overrides: Partial<CombatantState> = {}): CombatantState {
  return {
    id: "foe_1",
    name: "Halfwit Marauder",
    tags: [],
    hp: 6,
    max_hp: 6,
    str_score: 10,
    max_str_score: 10,
    dex_score: 10,
    wil_score: 8,
    armor: 1,
    weapon_damage_die: 6,
    morale: null,
    morale_broken: false,
    status: "active",
    ...overrides,
  };
}

function makeEncounter(
  overrides: Partial<CombatEncounterState> = {},
): CombatEncounterState {
  return {
    active: true,
    round: 1,
    player_ready: false,
    morale_triggered: false,
    combatants: [],
    summary: null,
    ...overrides,
  };
}

describe("combatantHpTier", () => {
  it("returns 'fresh' at full HP", () => {
    expect(combatantHpTier(makeFoe({ hp: 6, max_hp: 6 }))).toBe("fresh");
  });

  it("returns 'wounded' once below max but above one-third", () => {
    // 4/6 ≈ 0.67 — wounded tier.
    expect(combatantHpTier(makeFoe({ hp: 4, max_hp: 6 }))).toBe("wounded");
  });

  it("returns 'critical' at one-third or below", () => {
    expect(combatantHpTier(makeFoe({ hp: 2, max_hp: 6 }))).toBe("critical");
    // Boundary: exactly one-third counts as critical (≤ 0.34 in the impl).
    expect(combatantHpTier(makeFoe({ hp: 1, max_hp: 3 }))).toBe("critical");
  });

  it("returns 'down' at zero or negative HP", () => {
    expect(combatantHpTier(makeFoe({ hp: 0, max_hp: 6 }))).toBe("down");
    expect(combatantHpTier(makeFoe({ hp: -2, max_hp: 6 }))).toBe("down");
  });

  it("returns 'fresh' when max_hp is zero (avoids division by zero)", () => {
    // A combatant with max_hp 0 is degenerate; we default to fresh
    // rather than crashing the tier calc.
    expect(combatantHpTier(makeFoe({ hp: 0, max_hp: 0 }))).toBe("down");
    expect(combatantHpTier(makeFoe({ hp: 1, max_hp: 0 }))).toBe("fresh");
  });
});

describe("combatantStatusLabel", () => {
  const cases: ReadonlyArray<[CombatantStatus, string | null]> = [
    ["dead", "Dead"],
    ["fled", "Fled"],
    ["incapacitated", "Down"],
    ["active", null],
  ];
  for (const [status, label] of cases) {
    it(`labels '${status}' as ${JSON.stringify(label)}`, () => {
      expect(combatantStatusLabel(status)).toBe(label);
    });
  }
});

describe("encounterHeadline", () => {
  it("returns null for a null encounter", () => {
    expect(encounterHeadline(null)).toBeNull();
  });

  it("returns the cleared summary when active is false and a summary is present", () => {
    expect(
      encounterHeadline(
        makeEncounter({ active: false, summary: "The marauders broke and fled." }),
      ),
    ).toBe("The marauders broke and fled.");
  });

  it("returns 'Encounter cleared' when active is false without a summary", () => {
    expect(encounterHeadline(makeEncounter({ active: false }))).toBe("Encounter cleared");
  });

  it("flags the first-round DEX gate when the player isn't ready", () => {
    expect(
      encounterHeadline(makeEncounter({ round: 1, player_ready: false })),
    ).toBe("Round 1 · DEX save to act");
  });

  it("drops the DEX gate label after the first round or once the player is ready", () => {
    expect(encounterHeadline(makeEncounter({ round: 1, player_ready: true }))).toBe("Round 1");
    expect(encounterHeadline(makeEncounter({ round: 2, player_ready: false }))).toBe("Round 2");
  });

  it("returns 'Encounter brewing' for round zero", () => {
    expect(encounterHeadline(makeEncounter({ round: 0 }))).toBe("Encounter brewing");
  });
});

describe("firstRoundActionGated", () => {
  it("is true only on round 1 when active and not ready", () => {
    expect(firstRoundActionGated(makeEncounter({ round: 1, player_ready: false }))).toBe(true);
    expect(firstRoundActionGated(makeEncounter({ round: 1, player_ready: true }))).toBe(false);
    expect(firstRoundActionGated(makeEncounter({ round: 2, player_ready: false }))).toBe(false);
    expect(firstRoundActionGated(makeEncounter({ active: false, round: 1 }))).toBe(false);
    expect(firstRoundActionGated(null)).toBe(false);
  });
});

describe("sortCombatants", () => {
  it("orders standing foes first, then incapacitated, then fled, then dead", () => {
    const sorted = sortCombatants([
      makeFoe({ id: "a", status: "dead", hp: 0 }),
      makeFoe({ id: "b", status: "active", hp: 5 }),
      makeFoe({ id: "c", status: "fled", hp: 3 }),
      makeFoe({ id: "d", status: "incapacitated", hp: 0 }),
    ]);
    expect(sorted.map((f) => f.id)).toEqual(["b", "d", "c", "a"]);
  });

  it("breaks ties on lower HP first, then id", () => {
    const sorted = sortCombatants([
      makeFoe({ id: "z", status: "active", hp: 6 }),
      makeFoe({ id: "y", status: "active", hp: 2 }),
      makeFoe({ id: "x", status: "active", hp: 6 }),
    ]);
    // y has the lowest HP, then x and z tie on HP and sort by id.
    expect(sorted.map((f) => f.id)).toEqual(["y", "x", "z"]);
  });
});

describe("combatFromState", () => {
  // We test against the backend's actual `EncounterState` wire shape
  // (mirrors `src/dungeon_master/models.py::EncounterState`). The
  // adapter is the contract surface — these tests pin both the
  // mapping and the "no encounter tracked" recognition.

  function backendEncounter(
    overrides: Partial<{
      active: boolean;
      round_number: number;
      first_round_dex_gate_pending: boolean;
      casualty_morale_checked: boolean;
      half_force_morale_checked: boolean;
      combatants: object[];
      notes: string;
    }> = {},
  ): object {
    return {
      active: false,
      round_number: 0,
      first_round_dex_gate_pending: false,
      casualty_morale_checked: false,
      half_force_morale_checked: false,
      combatants: [],
      notes: "",
      ...overrides,
    };
  }

  function backendFoe(overrides: Partial<Record<string, unknown>> = {}): object {
    return {
      id: "foe_1",
      name: "Halfwit Marauder",
      description: "ragged conscript",
      hp: 6,
      max_hp: 6,
      str_score: 10,
      dex_score: 10,
      wil_score: 8,
      armor: 1,
      weapon_name: "Cleaver",
      weapon_damage_die: 6,
      leader: false,
      critically_wounded: false,
      defeated: false,
      fled: false,
      notes: "",
      ...overrides,
    };
  }

  it("returns null when state has no encounter field", () => {
    expect(combatFromState({})).toBeNull();
    expect(combatFromState({ id: "g" })).toBeNull();
  });

  it("returns null when encounter is explicitly null", () => {
    expect(combatFromState({ encounter: null })).toBeNull();
  });

  it("returns null for a default-empty encounter (no foes, inactive, no notes)", () => {
    expect(combatFromState({ encounter: backendEncounter() })).toBeNull();
  });

  it("adapts an active encounter into the tracker shape", () => {
    const encounter = backendEncounter({
      active: true,
      round_number: 1,
      first_round_dex_gate_pending: true,
      combatants: [backendFoe()],
    });
    const adapted = combatFromState({ encounter });
    expect(adapted).not.toBeNull();
    expect(adapted?.active).toBe(true);
    expect(adapted?.round).toBe(1);
    // first_round_dex_gate_pending=true means player is NOT yet ready.
    expect(adapted?.player_ready).toBe(false);
    expect(adapted?.combatants).toHaveLength(1);
    const foe = adapted?.combatants[0]!;
    expect(foe.status).toBe("active");
    expect(foe.tags).toEqual(["ragged conscript"]);
    expect(foe.weapon_damage_die).toBe(6);
    expect(foe.max_str_score).toBe(foe.str_score);
  });

  it("flags morale_triggered when either casualty or half-force flag is set", () => {
    const a = combatFromState({
      encounter: backendEncounter({
        active: true,
        casualty_morale_checked: true,
        combatants: [backendFoe()],
      }),
    });
    expect(a?.morale_triggered).toBe(true);

    const b = combatFromState({
      encounter: backendEncounter({
        active: true,
        half_force_morale_checked: true,
        combatants: [backendFoe()],
      }),
    });
    expect(b?.morale_triggered).toBe(true);
  });

  it("derives status from defeated > fled > critically_wounded > active", () => {
    const encounter = backendEncounter({
      active: true,
      combatants: [
        backendFoe({ id: "a", defeated: true }),
        backendFoe({ id: "b", fled: true }),
        backendFoe({ id: "c", critically_wounded: true }),
        backendFoe({ id: "d" }),
      ],
    });
    const adapted = combatFromState({ encounter });
    const byId = Object.fromEntries(
      (adapted?.combatants ?? []).map((c) => [c.id, c.status]),
    );
    expect(byId["a"]).toBe("dead");
    expect(byId["b"]).toBe("fled");
    expect(byId["c"]).toBe("incapacitated");
    expect(byId["d"]).toBe("active");
  });

  it("surfaces backend notes as the cleared-encounter summary", () => {
    const encounter = backendEncounter({
      active: false,
      notes: "The marauders broke and fled.",
    });
    const adapted = combatFromState({ encounter });
    expect(adapted?.summary).toBe("The marauders broke and fled.");
  });
});
