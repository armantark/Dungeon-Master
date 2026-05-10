import { describe, expect, it } from "vitest";

import {
  applyCommonAction,
  deriveCommonActions,
  type CommonAction,
} from "./common-actions";
import type { CombatEncounterState } from "./combat";
import type { GameState } from "./types";

// `deriveCommonActions` only reads whether `state` is non-null and
// uses the passed-in combat slot to decide which actions to surface.
// We therefore stub a GameState rather than building a faithful one
// — the test's contract is "given some state and a combat slot, what
// actions appear in what order?", not "is this GameState valid?".
const STUB_STATE = { id: "test" } as unknown as GameState;

function makeEncounter(
  overrides: Partial<CombatEncounterState> = {},
): CombatEncounterState {
  return {
    active: true,
    round: 1,
    player_ready: false,
    morale_triggered: false,
    initiator: null,
    combatants: [],
    pending_advantages: [],
    summary: null,
    ...overrides,
  };
}

describe("deriveCommonActions visibility", () => {
  it("returns no actions when state is null", () => {
    expect(deriveCommonActions(null, null)).toEqual([]);
    expect(deriveCommonActions(null, makeEncounter())).toEqual([]);
  });

  it("surfaces only the baseline actions when no encounter is active", () => {
    const ids = deriveCommonActions(STUB_STATE, null).map((a) => a.id);
    // Order is contractual — the player learns left-to-right and
    // the kanban entry pins this ordering. Don't sort before
    // comparing.
    expect(ids).toEqual([
      "ask-oracle",
      "random-event",
      "scene-check",
      "check-gear",
    ]);
  });

  it("treats an inactive encounter the same as no encounter", () => {
    // Inactive encounter = "encounter cleared but the slot lingers".
    // Combat-only actions must not leak into this state, otherwise
    // the player sees an Attack pill after their last foe just
    // dropped — which would be a small but real cue-confusion bug.
    const cleared = makeEncounter({ active: false });
    const ids = deriveCommonActions(STUB_STATE, cleared).map((a) => a.id);
    expect(ids).toEqual([
      "ask-oracle",
      "random-event",
      "scene-check",
      "check-gear",
    ]);
  });

  it("appends combat actions when an encounter is active", () => {
    const fight = makeEncounter({ active: true });
    const ids = deriveCommonActions(STUB_STATE, fight).map((a) => a.id);
    // Combat actions tail the row so existing pills don't reshuffle
    // under the player's cursor when combat begins.
    expect(ids).toEqual([
      "ask-oracle",
      "random-event",
      "scene-check",
      "check-gear",
      "attack",
      "recover",
      "retreat",
    ]);
  });

  it("returns prefill intents for every action (no auto-submit)", () => {
    // Hard guarantee: the tray never auto-submits. If a future
    // action ever needed a different intent kind, the helper's
    // type would force a deliberate change here.
    const fight = makeEncounter({ active: true });
    const actions = deriveCommonActions(STUB_STATE, fight);
    for (const action of actions) {
      expect(action.intent.kind).toBe("prefill");
      // Non-empty prefill text is contractually meaningful — an
      // empty prefill would clear the buffer silently on click.
      expect(action.intent.text.length).toBeGreaterThan(0);
    }
  });

  it("uses slash commands for routes that already have a parser entry", () => {
    // ask / event / scene / retreat must round-trip through the
    // slash parser; bypassing it would risk drift between tray
    // wording and parser expectations.
    const fight = makeEncounter({ active: true });
    const byId = new Map(
      deriveCommonActions(STUB_STATE, fight).map((a) => [a.id, a] as const),
    );
    expect(byId.get("ask-oracle")!.intent.text).toBe("/ask ");
    expect(byId.get("random-event")!.intent.text).toBe("/event");
    expect(byId.get("scene-check")!.intent.text).toBe("/scene ");
    expect(byId.get("retreat")!.intent.text).toBe("/retreat ");
  });

  it("uses prose (planner-classified) for actions without slash routes", () => {
    // attack / recover / check-gear are routed through the planner
    // because there's intentionally no /attack /recover /gear slash
    // today — F-11 tracks that work. F-07 stays a discoverability
    // layer over existing routes; it must not invent vocabulary
    // the parser doesn't recognize.
    const fight = makeEncounter({ active: true });
    const byId = new Map(
      deriveCommonActions(STUB_STATE, fight).map((a) => [a.id, a] as const),
    );
    expect(byId.get("attack")!.intent.text).not.toMatch(/^\//);
    expect(byId.get("recover")!.intent.text).not.toMatch(/^\//);
    expect(byId.get("check-gear")!.intent.text).not.toMatch(/^\//);
  });
});

describe("applyCommonAction replacement rule", () => {
  function action(text: string): CommonAction {
    return {
      id: "stub",
      label: "stub",
      summary: "stub",
      intent: { kind: "prefill", text },
    };
  }

  it("replaces an empty buffer wholesale with the prefill", () => {
    const result = applyCommonAction("", action("/ask "));
    expect(result.text).toBe("/ask ");
    expect(result.caret).toBe("/ask ".length);
  });

  it("treats whitespace-only buffers as empty", () => {
    // Trailing newlines from auto-grow + paste artefacts shouldn't
    // count as "the player typed something we must preserve".
    const result = applyCommonAction("   \n\t ", action("/event"));
    expect(result.text).toBe("/event");
    expect(result.caret).toBe("/event".length);
  });

  it("appends on a new line when there's typed prose to preserve", () => {
    // Player typed "Then I" and then clicked Attack — the typed
    // fragment is preserved and the prefill lands on its own line
    // so the player can decide whether to combine, edit, or
    // backspace it.
    const result = applyCommonAction("Then I", action("I attack "));
    expect(result.text).toBe("Then I\nI attack ");
    expect(result.caret).toBe(result.text.length);
  });

  it("trims trailing whitespace before appending so we don't double-blank-line", () => {
    // Composer often carries a trailing newline from a previous
    // edit; collapsing it before the join keeps the visual gap
    // tight.
    const result = applyCommonAction("Look around. \n", action("/event"));
    expect(result.text).toBe("Look around.\n/event");
    expect(result.caret).toBe(result.text.length);
  });

  it("places caret at end of inserted text in both branches", () => {
    // For `/ask ` end-of-inserted-text == end-of-buffer because the
    // tray always pastes at the end. This invariant is the reason
    // we collapsed the caret-placement enum in the helper.
    const slashOnEmpty = applyCommonAction("", action("/ask "));
    expect(slashOnEmpty.caret).toBe(slashOnEmpty.text.length);

    const slashAppended = applyCommonAction("Then I", action("/ask "));
    expect(slashAppended.caret).toBe(slashAppended.text.length);
  });
});
