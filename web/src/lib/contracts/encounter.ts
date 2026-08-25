// Canonical frontend mirror of the backend encounter wire contract.
//
// Keep this file aligned with `src/dungeon_master/models.py`:
// `EnemyCombatant`, `PendingEncounterAdvantage`, and `EncounterState`.
// Combat UI code may derive richer presentation models from these
// interfaces, but must not redeclare the backend payload shape.

export type EncounterEndReason =
  | "victory"
  | "enemy_rout"
  | "player_escaped";

export type EncounterThreatLevel = "ordinary" | "hardier" | "serious";

export type EncounterAdvantagePayoff =
  | "enhanced_attack"
  | "direct_str_damage"
  | "skip_dex_gate"
  | "deny_enemy_action"
  | "impair_enemy"
  | "force_morale"
  | "expose_weakness";

export type EncounterInitiator = "player" | "enemy";

export interface PendingEncounterAdvantage {
  id: string;
  actor_id: string | null;
  actor_name: string | null;
  target_combatant_id: string | null;
  target_name: string;
  setup: string;
  payoff: EncounterAdvantagePayoff;
  weakness: string;
}

export interface EnemyCombatant {
  id: string;
  name: string;
  description: string;
  hp: number;
  max_hp: number;
  str_score: number;
  dex_score: number;
  wil_score: number;
  armor: number;
  weapon_name: string;
  weapon_damage_die: number;
  // Optional only for compatibility with saves created before F-19.
  // The current backend always publishes all three values.
  threat_level?: EncounterThreatLevel;
  weakness?: string;
  tactics?: string;
  leader: boolean;
  critically_wounded: boolean;
  defeated: boolean;
  fled: boolean;
  notes: string;
}

export interface EncounterState {
  active: boolean;
  round_number: number;
  first_round_dex_gate_pending: boolean;
  // Optional only for compatibility with saves created before F-05.
  // The current backend publishes either an initiator or null.
  initiator?: EncounterInitiator | null;
  casualty_morale_checked: boolean;
  half_force_morale_checked: boolean;
  player_disengaged: boolean;
  pursuit_active: boolean;
  end_reason: EncounterEndReason | null;
  combatants: EnemyCombatant[];
  // Optional only for compatibility with saves created before F-18.
  pending_advantages?: PendingEncounterAdvantage[];
  notes: string;
}
