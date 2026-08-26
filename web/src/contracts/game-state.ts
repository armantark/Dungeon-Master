// Canonical whole-state wire contract returned by state-changing endpoints.

import type { CharacterSheet, PartyMember } from "./cairn";
import type {
  CampaignDirectives,
  CampaignEndReason,
  CampaignSeed,
  CampaignStatus,
  GameThread,
  NPC,
} from "./campaign";
import type { EncounterState } from "./encounter";
import type {
  GameEvent,
  OracleOutcome,
  OracleTables,
  SceneStatus,
} from "./oracle";

export interface GameState {
  id: string;
  created_at: string;
  updated_at: string;
  chaos_factor: number;
  scene_number: number;
  current_scene: string;
  scene_status: SceneStatus;
  campaign_status: CampaignStatus;
  // F-06 terminal-state metadata. All three are null while the
  // campaign is alive (any non-`ended` status) and populated when the
  // service marks the campaign ended. `campaign_end_summary` is
  // canon-grade prose — either authored by the player on
  // `/retire`/`/victory`, or a deterministic default written by the
  // service for auto-deaths so the archive always has something to
  // read in the End-Banner.
  campaign_end_reason: CampaignEndReason | null;
  campaign_ended_at: string | null;
  campaign_end_summary: string | null;
  character?: CharacterSheet;
  // Party harness v1. Active companions/hirelings/animals wrap full
  // CharacterSheets so the folio can render their Cairn stats and
  // inventory through the same read-only components as the protagonist.
  party_members: PartyMember[];
  // F-16: monotonic version of the visible/hidden NPC roster split.
  // The backend stamps `2` on any save it has migrated into the
  // hidden-cast contract; older saves load as `1` and are reseeded
  // exactly once. The frontend doesn't branch on this field today —
  // it exists so future UI behavior (e.g. "your roster was just
  // reorganized" pip) can detect a version bump without re-walking
  // canon.
  npc_roster_version: number;
  setting_notes: string;
  player_notes: string;
  // B-02: persistent OOC steering, distinct from the canonical
  // setting/player notes. The Inspector edits this surface; the
  // backend never appends it to the action log because it is
  // durable prompt guidance, not transcript canon.
  directives: CampaignDirectives;
  threads: GameThread[];
  // F-16: introduced cast only. The opener-seeded recurring figures
  // start in `hidden_npcs` and are moved here once committed
  // narration explicitly names them, so the panel never spoils a
  // character the player hasn't actually met.
  npcs: NPC[];
  // F-16: backend-only cast continuity. Hidden NPCs are tracked
  // canonically so the system can reference them in prompts and
  // promote them on first introduction, but the player UI deliberately
  // never reads from this list. We mirror it on the wire because the
  // backend always sends it, and not modeling it would force every
  // call site to coerce `unknown` — but no component should display
  // it.
  hidden_npcs: NPC[];
  // Canonical backend encounter payload. Combat components adapt this
  // wire shape into a presentation-only view model in `combat.ts`.
  encounter: EncounterState;
  oracle_tables: OracleTables;
  oracle_history: OracleOutcome[];
  action_log: GameEvent[];
  // F-15: persistent campaign-setup record. Mutable while the campaign
  // is still in `character_creation`; locked once the campaign starts.
  // The backend always emits this field — older saves are migrated to
  // a default seed at load time so the wire never carries `undefined`.
  campaign_seed: CampaignSeed;
}
