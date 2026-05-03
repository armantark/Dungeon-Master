// Mirrors src/dungeon_master/models.py.
//
// We keep the frontend types hand-written instead of generated from the
// OpenAPI schema because the surface is small and the indirection of a
// codegen step doesn't earn its weight for a personal project. If the API
// surface starts to drift, we'll revisit.

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

export type OracleKind =
  | "yes_no"
  | "random_event"
  | "scene_check"
  | "player_action";

export type EventType = "oracle" | "narrative" | "player" | "system";

export type ThreadStatus = "active" | "resolved";

export type SceneStatus = "expected" | "altered" | "interrupted";

export type CampaignStatus = "character_creation" | "ready_to_start" | "active";

export interface Roll {
  sides: number;
  result: number;
  label: string;
}

export interface GameThread {
  id: string;
  title: string;
  status: ThreadStatus;
  stakes: string;
}

export interface NPC {
  id: string;
  name: string;
  role: string;
  disposition: string;
}

export interface InventoryItem {
  id: string;
  name: string;
  details: string;
}

export interface CharacterSheet {
  name: string;
  archetype: string;
  epithet: string;
  backstory: string;
  drive: string;
  flaw: string;
  condition: string;
  inventory: InventoryItem[];
}

export interface CharacterTemplatesResponse {
  templates: CharacterSheet[];
}

export interface CharacterDraftResponse {
  draft: CharacterSheet;
}

export interface CharacterQuizOption {
  label: string;
}

export interface CharacterQuizQuestion {
  id: string;
  prompt: string;
  options: CharacterQuizOption[];
}

export interface CharacterQuiz {
  concept: string;
  questions: CharacterQuizQuestion[];
}

export interface CharacterQuizAnswer {
  question_id: string;
  prompt: string;
  value: string;
  is_other: boolean;
}

export interface CharacterQuizResponse {
  quiz: CharacterQuiz;
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
  referenced_thread_id: string | null;
  referenced_npc_id: string | null;
  scene_status: SceneStatus | null;
}

export interface GameEvent {
  id: string;
  created_at: string;
  event_type: EventType;
  title: string;
  content: string;
  oracle_outcome_id: string | null;
}

export interface GameState {
  id: string;
  created_at: string;
  updated_at: string;
  chaos_factor: number;
  scene_number: number;
  current_scene: string;
  scene_status: SceneStatus;
  campaign_status: CampaignStatus;
  character?: CharacterSheet;
  setting_notes: string;
  player_notes: string;
  threads: GameThread[];
  npcs: NPC[];
  oracle_tables: OracleTables;
  oracle_history: OracleOutcome[];
  action_log: GameEvent[];
}
