// Pure derivation for the F-07 Common Actions Tray.
//
// This module is intentionally separate from the .svelte component so
// the visibility + labelling rules are testable without a DOM and so
// the tray can never drift out of sync with the chat-first routing
// rules in `slash.ts` / `store.svelte.ts`. The component owns input
// state and focus; this module owns "which actions are available
// right now, and what does each click *intend* to do?"
//
// Design rules baked into the helper:
//   1. The tray never auto-submits. Every action that maps onto a
//      typed turn returns a `prefill` intent that the Composer pastes
//      into its textarea, so the player still consciously hits Send.
//      The user explicitly chose this in the F-07 plan because
//      auto-fire would feel like a button-driven game while the
//      product invariant is chat-first.
//   2. Combat-only actions (Attack / Recover / Retreat) are hidden
//      outside an active encounter rather than greyed out. A button
//      that grey-flickers per turn reads as state churn; structural
//      hide-on-context is the same pattern used by the existing
//      slash hint in the composer footer.
//   3. The action vocabulary is deliberately narrow. F-11 is where
//      explicit Cairn controls (deterministic /attack, /harm,
//      /recover endpoints) live; F-07 stays a discoverability /
//      ergonomics layer over the existing planner + slash routes.
//
// `Check gear` deliberately maps to a planner-classified prose
// turn ("I take stock of what I'm carrying.") rather than to a
// direct open-inspector action. The folio rail already shows raw
// inventory at all times, so the *useful* shape of "check gear" is
// the planner-emitted `inspect_inventory` op with narration, not a
// duplicate of what the rail already displays.

import type { CombatStateSlot } from "./combat";
import type { GameState } from "./types";

export interface CommonActionIntent {
  kind: "prefill";
  text: string;
}

export interface CommonAction {
  id: string;
  label: string;
  // Screen-reader / tooltip text. Single string because we want the
  // sighted hover hint and the aria description to never drift.
  summary: string;
  intent: CommonActionIntent;
}

const ASK_ORACLE: CommonAction = {
  id: "ask-oracle",
  label: "Ask oracle",
  summary: "Pose a yes/no question to the oracle.",
  intent: { kind: "prefill", text: "/ask " },
};

const RANDOM_EVENT: CommonAction = {
  id: "random-event",
  label: "Random event",
  summary: "Roll a campaign event.",
  intent: { kind: "prefill", text: "/event" },
};

const SCENE_CHECK: CommonAction = {
  id: "scene-check",
  label: "Scene check",
  summary: "Test whether the next scene plays out as expected.",
  intent: { kind: "prefill", text: "/scene " },
};

// Open-ended prose so the planner classifies it as `inspect_inventory`
// and narrates the gear in voice. The folio rail already shows the
// raw list; the value of this tray button is the narration, not a
// duplicate readout.
const CHECK_GEAR: CommonAction = {
  id: "check-gear",
  label: "Check gear",
  summary: "Have the GM describe what you carry.",
  intent: { kind: "prefill", text: "I take stock of what I'm carrying." },
};

// We deliberately don't pre-pick a foe even when the encounter has
// exactly one combatant — the "name your target" beat is part of
// how Cairn turns are written, and the prefill should preserve it.
const ATTACK: CommonAction = {
  id: "attack",
  label: "Attack",
  summary: "Strike a foe.",
  intent: { kind: "prefill", text: "I attack " },
};

// `breather` is the lightest of the three Cairn rest kinds; the
// planner can still upgrade it to a full rest from edited prose. We
// avoid a `/recover` slash because there isn't one today (F-11) and
// we don't want F-07 to invent vocabulary the parser doesn't know.
const RECOVER: CommonAction = {
  id: "recover",
  label: "Recover",
  summary: "Catch your breath and recover.",
  intent: { kind: "prefill", text: "I take a short breather to recover." },
};

// Routed through the existing /retreat slash handler. Trailing space
// invites an optional direction ("down the chapel stair") without
// losing the verb.
const RETREAT: CommonAction = {
  id: "retreat",
  label: "Retreat",
  summary: "Attempt to disengage from the encounter.",
  intent: { kind: "prefill", text: "/retreat " },
};

/**
 * Derive the visible tray for the current state. Returns an empty
 * list when there's no live game state — the Composer is unmounted
 * in setup / ended layouts anyway, but returning [] (rather than
 * throwing) keeps this helper safe to call from a Svelte $derived.
 *
 * The `combat` slot is passed in instead of recomputed so the
 * Composer and the tray share exactly one combat reading per render
 * — the alternative was double-adapting `state.encounter`, which
 * permitted a transient mismatch if the adapter ever gained side
 * effects.
 */
export function deriveCommonActions(
  state: GameState | null,
  combat: CombatStateSlot,
): readonly CommonAction[] {
  if (state === null) return [];

  // Order is intentional. We lead with oracle/event/scene/gear
  // because those are the always-available baseline and the
  // player's eye settles on the leftmost pill first. Combat-only
  // actions tail the row so they appear *after* the baseline when
  // an encounter begins, rather than reshuffling existing pills
  // under the player's cursor.
  const actions: CommonAction[] = [ASK_ORACLE, RANDOM_EVENT, SCENE_CHECK, CHECK_GEAR];

  const inActiveCombat = combat !== null && combat.active;
  if (inActiveCombat) {
    actions.push(ATTACK, RECOVER, RETREAT);
  }

  return actions;
}

export interface TrayApplyResult {
  text: string;
  caret: number;
}

/**
 * Apply a tray click to a current composer buffer. Returns the new
 * buffer plus the caret position to set on the textarea after the
 * paste. The Composer keeps the imperative focus / selection-range
 * plumbing; the *replacement rule itself* lives here so it stays
 * unit-testable.
 *
 * Replacement rule: a non-empty buffer is preserved — we never
 * silently clobber typed prose. Instead, the prefill is appended
 * on a fresh line so the player can see what was added and either
 * edit or backspace it. Empty / whitespace-only buffers are
 * replaced wholesale because there's nothing meaningful to keep.
 *
 * Caret always lands at the end of the inserted text. For prose
 * prefills (`I attack `) that's where the player wants to type the
 * target; for slash prefills (`/ask `) it's right after the
 * trailing space, ready for the question body.
 */
export function applyCommonAction(
  current: string,
  action: CommonAction,
): TrayApplyResult {
  const prefill = action.intent.text;
  const trimmed = current.trim();
  if (trimmed === "") {
    return { text: prefill, caret: prefill.length };
  }
  const stripped = current.replace(/\s+$/, "");
  const next = `${stripped}\n${prefill}`;
  return { text: next, caret: next.length };
}
