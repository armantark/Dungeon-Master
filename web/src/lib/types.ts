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

// NPC continuity. `retired` mirrors the backend's `NPCStatus.RETIRED`:
// the NPC has left the active cast (died, departed, became irrelevant)
// but is preserved in canon so memory can still reference them and so
// they can be reactivated by a future `update` op without inventing a
// new identity. The frontend treats `retired` as a sink-and-mute state
// — visible in the panel, but never highlighted as if they were still
// driving play. See F-04 in memory-bank/featureKanban.md.
export type NPCStatus = "active" | "retired";

// H-01 mirrors the backend split between a canonical true name and the
// player-facing label the fiction has actually granted. `proper_name`
// means the player may know the figure's real name; `descriptor` means
// the roster should render the safer "known by sign" label instead.
export type NPCPlayerLabelKind = "proper_name" | "descriptor";

export type SceneStatus = "expected" | "altered" | "interrupted";

// `ended` is the F-06 terminal state. Once the campaign reaches it, the
// frontend renders chat as a read-only archive (no Composer, no slash
// commands that mutate state) and the only canonical control is
// "Begin a new campaign" which calls `/state/reset`. We intentionally
// keep the active-state union intact instead of routing every screen
// through a "is play allowed?" boolean — switching on
// `campaign_status` keeps the App-level layout split mechanical and
// exhaustive at the type level.
export type CampaignStatus =
  | "character_creation"
  | "ready_to_start"
  | "active"
  | "ended";

// Mirrors backend `CampaignEndReason`. `death` is the auto-end the
// service triggers when a turn drops STR / HP to a fatal Cairn state;
// `retirement` is the explicit "I walk away" close; `victory` is the
// explicit "the campaign is won" close. The frontend uses this to
// pick the End-Banner kicker / glyph / tone — never to gate behavior
// (the gate is `campaign_status === "ended"`).
export type CampaignEndReason = "death" | "retirement" | "victory";

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

// Mirrors backend `EncounterInitiator`. Tells the UI who started the
// fight so the combat tracker / receipt can label an enemy-opened fight
// as an ambush instead of a normal player-initiated swing. F-05 only
// publishes this when an encounter exists; resolutions outside combat
// (e.g. trap damage, environmental harm) leave it null.
export type EncounterInitiator = "player" | "enemy";

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

export type CairnItemPowerKind =
  | "none"
  | "spellbook"
  | "scroll"
  | "relic"
  | "holy_relic";

export type CairnItemEffectKind =
  | "none"
  | "restore_hp"
  | "restore_attribute"
  | "clear_condition"
  | "enhance_attack"
  | "impair_target"
  | "force_save"
  | "reveal_sign"
  | "create_safe_passage"
  | "ward_or_pacify"
  | "extraordinary_aid"
  | "resurrect";

export type CairnConditionKey =
  | "deprived"
  | "critically_wounded"
  | "doomed"
  | "paralyzed"
  | "delirious";

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
  player_label: string;
  player_label_kind: NPCPlayerLabelKind;
  role: string;
  disposition: string;
  // F-04: dynamic NPC updates can retire an NPC instead of deleting it.
  // Older state blobs that pre-date the field still deserialize cleanly
  // because the backend defaults retired-less NPCs to `active`, so the
  // wire never sends `undefined`. We keep it required here to force any
  // new TS code path to think about which bucket it's rendering.
  status: NPCStatus;
}

export interface CairnItemPower {
  kind: CairnItemPowerKind;
  name: string;
  summary: string;
  effect: CairnItemEffectKind;
  effect_amount: number;
  effect_ability: CairnAbility | null;
  clears_condition: CairnConditionKey | null;
  recharge_condition: string;
  requires_wil_save_in_danger: boolean;
  adds_fatigue: boolean;
  consumed_on_use: boolean;
}

// Mirrors `CairnItemState` in models.py. `weapon_damage_die` is the d-side
// for the item's weapon roll (4–12 in models.py); `armor_bonus` adds to
// the wearer's armor pool (0–3); `uses` is null for unlimited consumables
// (e.g. lanterns aren't consumed per scene), or a positive count for
// charge-tracked items. `power` is the backend's typed Cairn item-power
// contract for spellbooks, scrolls, relics, and holy relics; renderers
// must use it as data, never infer powers from item prose.
export interface CairnItemState {
  source: CairnMechanicsSource;
  backfill_version: number;
  tags: CairnItemTag[];
  slots: number;
  weapon_damage_die: number | null;
  armor_bonus: number;
  uses: number | null;
  equipped: boolean;
  power: CairnItemPower;
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
  actor_id: string | null;
  actor_name: string | null;
  item_id: string | null;
  item_name: string | null;
  item_power_kind: CairnItemPowerKind | null;
  item_effect_kind: CairnItemEffectKind | null;
  effect_summary: string | null;
  uses_before: number | null;
  uses_after: number | null;
  recharge_condition: string | null;
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
  dex_before: number | null;
  dex_after: number | null;
  wil_before: number | null;
  wil_after: number | null;
  fatigue_before: number | null;
  fatigue_after: number | null;
  // Combat-context fields published when the resolution belongs to an
  // active encounter (F-05). All optional because most non-combat
  // outcomes (yes/no oracle, scene check, recovery outside the fight)
  // simply omit them. We don't promote them into the required side of
  // the union because that would force the rest of the codebase — and
  // every existing test factory — to provide them everywhere.
  combat_round?: number | null;
  combat_started?: boolean | null;
  combat_active?: boolean | null;
  // Tells the receipt / tracker who started the fight when this
  // outcome opened or escalated combat. `enemy` is the F-05 ambush
  // path; `player` is the normal attack path. Null for resolutions
  // that didn't seed an encounter (e.g. trap harm).
  combat_initiator?: EncounterInitiator | null;
  // False for the F-05 enemy-opener path because the player didn't
  // get to act yet — the foe seized initiative. We use this on the
  // receipt to render "(no player action)" / "Initiative · enemy".
  player_acted?: boolean | null;
  // Damage the foe applied to the player on this very resolution.
  // F-05 enemy openers always populate this (the opener strike is
  // the whole point); player attacks may also set it when the
  // counterattack landed in the same turn.
  enemy_damage?: number | null;
  enemy_damage_source?: string | null;
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

export type PartyMemberKind = "companion" | "hireling" | "animal";

export interface PartyMember {
  id: string;
  kind: PartyMemberKind;
  sheet: CharacterSheet;
  npc_id: string | null;
  active: boolean;
  loyalty: string;
  notes: string;
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

// F-12 Save library. Mirrors `SaveSummary` in `save_library.py`.
//
// `identifying_line` is the short backstory blurb the backend chose for
// the card body (it falls back to archetype / current scene if the
// backstory is empty). `state_summary` is the hover/expand reveal —
// scene number plus combat / archive context. We keep both as plain
// strings rather than richer structures so the card UI never has to
// re-derive them and the wire stays trivially diff-friendly.
export type SaveCampaignStatus = CampaignStatus;
export interface SaveSummary {
  save_id: string;
  state_id: string;
  character_name: string;
  character_epithet: string;
  identifying_line: string;
  state_summary: string;
  campaign_status: SaveCampaignStatus;
  campaign_end_reason: CampaignEndReason | null;
  updated_at: string;
  created_at: string;
}

export interface SaveLibraryBootstrapResponse {
  active_save_id: string | null;
  saves: SaveSummary[];
}

// F-10 OOC rules explainer. Mirrors the backend `ExplanationResponse`.
// `thinking` is a non-empty string when the model surfaced a reasoning
// trace; `""` when the model produced none. We don't render it as an
// independent surface — the streaming `thinking_delta` events animate
// the trace inside the chat's collapsed-thinking block. The unary
// shape exists primarily so tests can assert no-mutation against the
// fallback path.
export interface ExplanationResponse {
  answer: string;
  thinking: string;
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

// Persisted mirror of `dungeon_master.models.StageStatus`. Identical
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

// B-02 Campaign directives — the persistent OOC steering surface.
//
// We deliberately keep this separate from `setting_notes` /
// `player_notes`. Those two fields are *canonical campaign material*
// (world bible, character backstory) authored at generation time and
// fed into prose. Directives are something different: a small,
// player-authored OOC dial like "the hierophant cannot speak first"
// or "keep miracles subtle" that the system should remember but
// never narrate. Sharing one editor for both meanings was the bug —
// once the surface is meaningfully scoped, the player stops feeling
// nudged into freeform journaling and the model gets a cleaner
// channel for stable steering.
//
// Both fields are `string` (not optional) because the backend
// always emits them; an empty string means "no guidance set", which
// the editor renders as a neutral hint rather than as an error
// state.
export interface CampaignDirectives {
  world_guidance: string;
  play_guidance: string;
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
  oracle_tables: OracleTables;
  oracle_history: OracleOutcome[];
  action_log: GameEvent[];
}
