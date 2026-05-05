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

export type ThreadStatus = "active" | "resolved";

export type SceneStatus = "expected" | "altered" | "interrupted";

export type CampaignStatus = "character_creation" | "ready_to_start" | "active";

// `unset` means the backend has not yet derived Cairn mechanics for this
// record. The frontend uses it as a gate: never render the mechanics
// block while a sheet/item is still in `unset`, even if other fields
// happen to look populated.
export type CairnMechanicsSource = "unset" | "narrative_backfill" | "explicit";

export type CairnAbility = "STR" | "DEX" | "WIL";

export const CAIRN_ABILITIES: readonly CairnAbility[] = ["STR", "DEX", "WIL"] as const;

export type AttackStance = "normal" | "impaired" | "enhanced";

export type CairnRestKind = "breather" | "full_rest" | "week_recovery";

export type EncounterEndReason =
  | "victory"
  | "enemy_rout"
  | "player_escaped";

export type RetreatOutcome = "caught" | "disengaged" | "escaped";

export type CairnItemTag =
  | "petty"
  | "bulky"
  | "weapon"
  | "ranged"
  | "armor"
  | "shield"
  | "tool"
  | "light"
  | "relic"
  | "holy"
  | "healing"
  | "consumable"
  | "supplies"
  | "magic"
  | "utility";

export const CAIRN_ITEM_TAGS: readonly CairnItemTag[] = [
  "petty",
  "bulky",
  "weapon",
  "ranged",
  "armor",
  "shield",
  "tool",
  "light",
  "relic",
  "holy",
  "healing",
  "consumable",
  "supplies",
  "magic",
  "utility",
] as const;

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

// Mirrors `CairnItemState` in models.py. `weapon_damage_die` is the d-side
// for the item's weapon roll (4–12 in models.py); `armor_bonus` adds to
// the wearer's armor pool (0–3); `uses` is null for unlimited consumables
// (e.g. lanterns aren't consumed per scene), or a positive count for
// charge-tracked items.
export interface CairnItemState {
  source: CairnMechanicsSource;
  backfill_version: number;
  tags: CairnItemTag[];
  slots: number;
  weapon_damage_die: number | null;
  armor_bonus: number;
  uses: number | null;
  equipped: boolean;
}

export interface InventoryItem {
  id: string;
  name: string;
  details: string;
  cairn: CairnItemState;
}

// Mirrors `CairnCharacterState`. We keep the field names identical to
// the Pydantic model so the JSON wire format is the source of truth and
// no transformation layer hides drift. `*_before` / `*_after` snapshots
// live on `CairnResolution`, not here — this struct is the live state.
export interface CairnCharacterState {
  source: CairnMechanicsSource;
  backfill_version: number;
  skills: string[];
  abilities: string[];
  str_score: number;
  dex_score: number;
  wil_score: number;
  max_str_score: number;
  max_dex_score: number;
  max_wil_score: number;
  hp: number;
  max_hp: number;
  armor: number;
  fatigue: number;
  deprived: boolean;
  critically_wounded: boolean;
  doomed: boolean;
  paralyzed: boolean;
  delirious: boolean;
  dead: boolean;
  slots_total: number;
  backpack_slots: number;
  comfortable_slots: number;
  slots_used: number;
  overloaded: boolean;
  primary_weapon_item_id: string | null;
  notes: string;
}

// Mirrors `CairnResolution`. Every field is nullable because a single
// resolution only fills the slots relevant to its kind: a save uses
// `ability/target/success`; an attack uses `weapon_*`/`base_damage`/
// `damage_after_armor`; harm uses `hp_before`/`hp_after` and possibly
// `str_*`/`scar_result`; recovery uses `rest_kind`/`hp_*`/`fatigue_*`.
export interface CairnResolution {
  ability: CairnAbility | null;
  target: number | null;
  success: boolean | null;
  rest_kind: CairnRestKind | null;
  attack_stance: AttackStance | null;
  weapon_item_id: string | null;
  weapon_name: string | null;
  target_name: string | null;
  target_armor: number | null;
  base_damage: number | null;
  damage_after_armor: number | null;
  hp_before: number | null;
  hp_after: number | null;
  str_before: number | null;
  str_after: number | null;
  fatigue_before: number | null;
  fatigue_after: number | null;
  retreat_outcome?: RetreatOutcome | null;
  player_disengaged?: boolean | null;
  pursuit_active?: boolean | null;
  encounter_end_reason?: EncounterEndReason | null;
  scar_result: string | null;
  overloaded: boolean | null;
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
  cairn: CairnCharacterState;
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
  cairn: CairnResolution | null;
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
