// Stream event union mirroring the backend's NDJSON contract.
//
// This file is the *contract*. It deliberately lives next to the
// streaming transport rather than in types.ts because:
//   1. types.ts is a hand-mirror of `src/dungeon_master/models.py`
//      (Pydantic state shapes). The streaming envelope is wire-only —
//      it doesn't persist, doesn't show up in GameState, and shouldn't
//      pollute the persistence-mirror file.
//   2. Backend can match this shape without renaming Pydantic models.
//      The backend pass should publish `pydantic.RootModel`-style event
//      classes (or a `Literal["..."]` discriminated union) that produce
//      JSON identical to these TypeScript shapes.
//
// Recommended event names from the plan, in lifecycle order:
//   meta            once, first frame, request id and routing intent
//   mechanics_ready zero or one, deterministic Cairn/oracle resolution
//                   resolved before any prose token streams
//   oracle_outcome  alias of mechanics_ready when the resolution comes
//                   from the oracle path rather than the Cairn engine
//   thinking_delta  zero or many, model reasoning tokens (raw)
//   content_delta   zero or many, narrative tokens (raw)
//   final_state     for endpoints that mutate `GameState` (turn, action,
//                   regenerate, campaign/start, character/finalize)
//   final_payload   for non-state endpoints (quiz, draft) — payload
//                   shape is endpoint-specific
//   error           backend-authored failure; the stream may still emit
//                   trailing events but the client should treat the
//                   stream as failed.

import type { GameState, OracleOutcome } from "./types";

// `request_id` is a stable opaque identifier the backend generates per
// stream. We surface it in errors and in the chat receipt so a player
// asking "why did this go sideways?" can tag a specific run when they
// open an issue. `route` is the conservative classification the router
// settled on, so the UI can label provisional bubbles ("composing a
// scene check…") before any tokens stream.
export interface StreamMeta {
  type: "meta";
  request_id: string;
  route: StreamRoute;
}

// Mirror of the backend `OracleKind` plus extra route names that aren't
// outcome kinds (campaign generation, character drafting). Keep this in
// sync with the backend router; new routes appear here first so the
// frontend can render a labeled provisional bubble while the backend
// catches up.
export type StreamRoute =
  | "yes_no"
  | "random_event"
  | "scene_check"
  | "player_action"
  | "save"
  | "attack"
  | "harm"
  | "recovery"
  | "equip"
  | "retreat"
  | "campaign_start"
  | "character_quiz"
  | "character_draft"
  | "regenerate";

// `mechanics_ready` is the deterministic resolution. It carries the
// final OracleOutcome shape so the UI can pin the dice / damage /
// success state before any prose streams. Both `oracle_outcome` and
// `mechanics_ready` carry the same payload — they're separate event
// types so the backend can distinguish "this came from the oracle
// engine" (history-tracked) from "this came from the Cairn engine"
// (mechanically authoritative). The frontend treats them identically.
export interface StreamMechanicsReady {
  type: "mechanics_ready";
  outcome: OracleOutcome;
}

export interface StreamOracleOutcome {
  type: "oracle_outcome";
  outcome: OracleOutcome;
}

// `text` is *cumulative-friendly*: it's the next slice to append. The
// frontend store concatenates these into a provisional buffer until
// the final event arrives. We do not promise idempotency on retries —
// if the backend re-streams, the frontend resets its provisional buffer
// on the next `meta` frame.
export interface StreamThinkingDelta {
  type: "thinking_delta";
  text: string;
}

export interface StreamContentDelta {
  type: "content_delta";
  text: string;
}

// Final state for endpoints that mutate GameState. `thinking` is the
// persisted, complete reasoning trace. The plan says thinking is
// persisted alongside the narrative event, so the backend stores it on
// the `GameEvent` row; this field is a convenience for UIs that want
// to show the complete trace immediately rather than re-reading from
// state.action_log[-1].thinking.
export interface StreamFinalState {
  type: "final_state";
  state: GameState;
  thinking: string | null;
}

// Final payload for non-state endpoints. `kind` lets the frontend
// dispatch to the right typed handler (quiz vs draft vs regenerate),
// and `payload` carries the endpoint-specific JSON.
export interface StreamFinalPayload {
  type: "final_payload";
  kind: "character_quiz" | "character_draft";
  payload: unknown;
  thinking: string | null;
}

export interface StreamError {
  type: "error";
  message: string;
  code: string | null;
  // The backend may include the partial state at the time of failure
  // so the frontend can decide whether to roll back the chat to the
  // pre-stream snapshot or keep what was produced. Optional because
  // not every error has a meaningful state to surface.
  state: GameState | null;
}

export type StreamEvent =
  | StreamMeta
  | StreamMechanicsReady
  | StreamOracleOutcome
  | StreamThinkingDelta
  | StreamContentDelta
  | StreamFinalState
  | StreamFinalPayload
  | StreamError;
