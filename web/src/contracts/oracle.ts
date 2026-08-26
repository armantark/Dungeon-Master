// Oracle, event-log, and stage-timing wire contracts.

import type { CairnResolution } from "./cairn";

export type Likelihood =
  | "Impossible"
  | "Very unlikely"
  | "Unlikely"
  | "Even odds"
  | "Likely"
  | "Very likely"
  | "Nearly certain";

export const LIKELIHOOD_VALUES: readonly Likelihood[] = [
  "Impossible",
  "Very unlikely",
  "Unlikely",
  "Even odds",
  "Likely",
  "Very likely",
  "Nearly certain",
] as const;

// `save | attack | harm | recovery` were added when the deterministic
// Cairn engine started producing outcomes alongside the oracle. Keep this
// union exhaustive — the receipt switch in MechanicalReceipt relies on it
// to fail at type-check time when the backend grows a new kind.
export type OracleKind =
  | "yes_no"
  | "random_event"
  | "scene_check"
  | "player_action"
  | "save"
  | "attack"
  | "harm"
  | "recovery"
  | "retreat";

export type EventType = "oracle" | "narrative" | "player" | "system";

export type SceneStatus = "expected" | "altered" | "interrupted";

export interface Roll {
  sides: number;
  result: number;
  label: string;
}

export interface OracleTables {
  event_focus: string[];
  event_actions: string[];
  event_tones: string[];
  event_subjects: string[];
}

export interface OracleOutcome {
  id: string;
  created_at: string;
  kind: OracleKind;
  summary: string;
  rolls: Roll[];
  question: string | null;
  likelihood: Likelihood | null;
  answer: string | null;
  probability: number | null;
  chaos_factor: number;
  event_focus: string | null;
  event_action: string | null;
  event_tone: string | null;
  event_subject: string | null;
  // The legacy primary thread reference. Kept for backward-compatible
  // surfaces (e.g. older oracle history rows). New code should prefer
  // the plural `referenced_thread_ids` because a single turn can now
  // touch several threads via the dynamic thread updater (F-03).
  referenced_thread_id: string | null;
  // All thread ids the resolved turn touched — created, updated, or
  // resolved. Always includes `referenced_thread_id` when present, plus
  // any threads the post-outcome updater advanced. We use this for the
  // "recently advanced" surface in the Threads panel.
  referenced_thread_ids: string[];
  // The legacy primary NPC reference, still emitted by older oracle
  // outcomes (e.g. random-event picks). New code should prefer the
  // plural `referenced_npc_ids` because the post-outcome NPC updater
  // can create / update / retire several NPCs in a single turn.
  referenced_npc_id: string | null;
  // All NPC ids the resolved turn touched — created, updated, or
  // retired (F-04). Always includes `referenced_npc_id` when present,
  // plus anyone the post-outcome updater advanced. Used for the
  // "recently advanced" surface in the NPCs panel.
  referenced_npc_ids: string[];
  scene_status: SceneStatus | null;
  scene_number_snapshot?: number | null;
  scene_label_snapshot?: string | null;
  scene_status_snapshot?: SceneStatus | null;
  cairn: CairnResolution | null;
}

// Persisted mirror of `dungeon_master.domain.models.StageStatus`. Identical
// string set to `streaming-types.ts:StreamStageStatus` — the wire and
// disk enums are kept structurally equal so the in-trace checklist and
// the live checklist can share the same renderer without a mapping.
export type StageStatus = "pending" | "active" | "done" | "skipped";

// Persisted timing for one backend pipeline stage. The backend records
// it on the narrative `GameEvent` so the player can see the per-stage
// and total roundtrip time even after a reload — the live
// `streaming.stages` buffer goes away with the stream.
//
// Both timestamps are nullable on purpose:
//   - `started_at === null` for stages that were skipped before they
//     ran (e.g. action route bypasses planner / mechanics).
//   - `completed_at === null` for stages that were still active when
//     the stream cancelled.
// "Both present" is the only shape that yields a real elapsed duration;
// the renderer treats anything else as "no duration to show".
export interface StageTiming {
  stage_id: string;
  label: string;
  status: StageStatus;
  started_at: string | null;
  completed_at: string | null;
}

export interface GameEvent {
  id: string;
  created_at: string;
  event_type: EventType;
  title: string;
  content: string;
  oracle_outcome_id: string | null;
  // F-11 stage-timing surface. Only narrative events carry non-empty
  // arrays; legacy saves and player/oracle/system events default to
  // empty. Optional in TS because older client builds don't know the
  // field exists, but the wire payload always supplies a list.
  stage_timings?: StageTiming[];
  // Backend persists model reasoning alongside narrative events. We
  // surfaced this in `ChatFeed.thinkingFor` via a defensive cast for a
  // long time; typing it directly removes that hack.
  thinking?: string;
}
