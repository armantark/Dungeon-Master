from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

type JSONValue = None | bool | int | float | str | list[JSONValue] | dict[str, JSONValue]


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False, validate_assignment=True)


class Likelihood(StrEnum):
    IMPOSSIBLE = "Impossible"
    VERY_UNLIKELY = "Very unlikely"
    UNLIKELY = "Unlikely"
    EVEN = "Even odds"
    LIKELY = "Likely"
    VERY_LIKELY = "Very likely"
    NEARLY_CERTAIN = "Nearly certain"


class OracleKind(StrEnum):
    YES_NO = "yes_no"
    RANDOM_EVENT = "random_event"
    SCENE_CHECK = "scene_check"
    PLAYER_ACTION = "player_action"
    SAVE = "save"
    ATTACK = "attack"
    HARM = "harm"
    RECOVERY = "recovery"
    RETREAT = "retreat"


class EventType(StrEnum):
    ORACLE = "oracle"
    NARRATIVE = "narrative"
    PLAYER = "player"
    SYSTEM = "system"


class StageStatus(StrEnum):
    """Persisted mirror of `narrative.StreamStageStatus`.

    Lives in `models.py` because `GameEvent.stage_timings` carries it
    onto disk, and the persistence-mirror file is the source of truth
    for what we serialize. The wire enum in `narrative.py` stays
    decoupled so streaming code can move independently of the schema.
    """

    PENDING = "pending"
    ACTIVE = "active"
    DONE = "done"
    SKIPPED = "skipped"


class ThreadStatus(StrEnum):
    ACTIVE = "active"
    RESOLVED = "resolved"


class NPCStatus(StrEnum):
    ACTIVE = "active"
    RETIRED = "retired"


class NPCPlayerLabelKind(StrEnum):
    PROPER_NAME = "proper_name"
    DESCRIPTOR = "descriptor"


class PartyMemberKind(StrEnum):
    COMPANION = "companion"
    HIRELING = "hireling"
    ANIMAL = "animal"


class SceneStatus(StrEnum):
    EXPECTED = "expected"
    ALTERED = "altered"
    INTERRUPTED = "interrupted"


class CampaignStatus(StrEnum):
    CHARACTER_CREATION = "character_creation"
    READY_TO_START = "ready_to_start"
    ACTIVE = "active"
    ENDED = "ended"


class CairnMechanicsSource(StrEnum):
    UNSET = "unset"
    NARRATIVE_BACKFILL = "narrative_backfill"
    EXPLICIT = "explicit"


class CairnAbility(StrEnum):
    STR = "STR"
    DEX = "DEX"
    WIL = "WIL"


class AttackStance(StrEnum):
    NORMAL = "normal"
    IMPAIRED = "impaired"
    ENHANCED = "enhanced"


class CairnRestKind(StrEnum):
    BREATHER = "breather"
    FULL_REST = "full_rest"
    WEEK_RECOVERY = "week_recovery"


class EncounterEndReason(StrEnum):
    VICTORY = "victory"
    ENEMY_ROUT = "enemy_rout"
    PLAYER_ESCAPED = "player_escaped"


class EncounterInitiator(StrEnum):
    PLAYER = "player"
    ENEMY = "enemy"


class CampaignEndReason(StrEnum):
    DEATH = "death"
    RETIREMENT = "retirement"
    VICTORY = "victory"


class RetreatOutcome(StrEnum):
    CAUGHT = "caught"
    DISENGAGED = "disengaged"
    ESCAPED = "escaped"


class CairnItemTag(StrEnum):
    PETTY = "petty"
    BULKY = "bulky"
    WEAPON = "weapon"
    RANGED = "ranged"
    ARMOR = "armor"
    SHIELD = "shield"
    TOOL = "tool"
    LIGHT = "light"
    RELIC = "relic"
    HOLY = "holy"
    HEALING = "healing"
    CONSUMABLE = "consumable"
    SUPPLIES = "supplies"
    MAGIC = "magic"
    UTILITY = "utility"


class CairnItemPowerKind(StrEnum):
    NONE = "none"
    SPELLBOOK = "spellbook"
    SCROLL = "scroll"
    RELIC = "relic"
    HOLY_RELIC = "holy_relic"


class CairnItemEffectKind(StrEnum):
    NONE = "none"
    RESTORE_HP = "restore_hp"
    RESTORE_ATTRIBUTE = "restore_attribute"
    CLEAR_CONDITION = "clear_condition"
    ENHANCE_ATTACK = "enhance_attack"
    IMPAIR_TARGET = "impair_target"
    FORCE_SAVE = "force_save"
    REVEAL_SIGN = "reveal_sign"
    CREATE_SAFE_PASSAGE = "create_safe_passage"
    WARD_OR_PACIFY = "ward_or_pacify"
    EXTRAORDINARY_AID = "extraordinary_aid"
    RESURRECT = "resurrect"


class CairnConditionKey(StrEnum):
    DEPRIVED = "deprived"
    CRITICALLY_WOUNDED = "critically_wounded"
    DOOMED = "doomed"
    PARALYZED = "paralyzed"
    DELIRIOUS = "delirious"


class Roll(StrictModel):
    sides: int = Field(ge=2)
    result: int = Field(ge=1)
    label: str


class GameThread(StrictModel):
    id: str = Field(default_factory=lambda: new_id("thread"))
    title: str = Field(min_length=1)
    status: ThreadStatus = ThreadStatus.ACTIVE
    stakes: str = ""


class NPC(StrictModel):
    id: str = Field(default_factory=lambda: new_id("npc"))
    name: str = Field(min_length=1)
    role: str = ""
    disposition: str = "unknown"
    status: NPCStatus = NPCStatus.ACTIVE
    player_label: str | None = None
    player_label_kind: NPCPlayerLabelKind = NPCPlayerLabelKind.PROPER_NAME

    @model_validator(mode="after")
    def normalize_player_label(self) -> NPC:
        cleaned_label = (self.player_label or "").strip()
        if cleaned_label == "":
            if self.player_label_kind == NPCPlayerLabelKind.DESCRIPTOR:
                message = "Descriptor-visible NPCs must provide a player label."
                raise ValueError(message)
            cleaned_label = self.name
        object.__setattr__(self, "player_label", cleaned_label)
        return self

    def display_label(self) -> str:
        label = (self.player_label or "").strip()
        return label or self.name

    def player_knows_proper_name(self) -> bool:
        return self.player_label_kind == NPCPlayerLabelKind.PROPER_NAME


class EnemyCombatant(StrictModel):
    id: str = Field(default_factory=lambda: new_id("foe"))
    name: str = Field(min_length=1)
    description: str = ""
    hp: int = Field(default=1, ge=0)
    max_hp: int = Field(default=1, ge=0)
    str_score: int = Field(default=10, ge=0)
    dex_score: int = Field(default=10, ge=0)
    wil_score: int = Field(default=10, ge=0)
    armor: int = Field(default=0, ge=0, le=3)
    weapon_name: str = "Weapon"
    weapon_damage_die: int = Field(default=6, ge=4, le=12)
    leader: bool = False
    critically_wounded: bool = False
    defeated: bool = False
    fled: bool = False
    notes: str = ""

    @model_validator(mode="after")
    def normalize_current_values(self) -> EnemyCombatant:
        object.__setattr__(self, "hp", min(self.hp, self.max_hp))
        return self


class EncounterState(StrictModel):
    active: bool = False
    round_number: int = Field(default=0, ge=0)
    first_round_dex_gate_pending: bool = False
    initiator: EncounterInitiator | None = None
    casualty_morale_checked: bool = False
    half_force_morale_checked: bool = False
    player_disengaged: bool = False
    pursuit_active: bool = False
    end_reason: EncounterEndReason | None = None
    combatants: list[EnemyCombatant] = Field(default_factory=list)
    notes: str = ""


class CairnItemPower(StrictModel):
    kind: CairnItemPowerKind = CairnItemPowerKind.NONE
    name: str = ""
    summary: str = ""
    effect: CairnItemEffectKind = CairnItemEffectKind.NONE
    effect_amount: int = Field(default=1, ge=0)
    effect_ability: CairnAbility | None = None
    clears_condition: CairnConditionKey | None = None
    recharge_condition: str = ""
    requires_wil_save_in_danger: bool = False
    adds_fatigue: bool = False
    consumed_on_use: bool = False


class CairnItemState(StrictModel):
    source: CairnMechanicsSource = CairnMechanicsSource.UNSET
    backfill_version: int = Field(default=0, ge=0)
    tags: list[CairnItemTag] = Field(default_factory=list)
    slots: int = Field(default=1, ge=0, le=10)
    weapon_damage_die: int | None = Field(default=None, ge=4, le=12)
    armor_bonus: int = Field(default=0, ge=0, le=3)
    uses: int | None = Field(default=None, ge=0)
    equipped: bool = False
    power: CairnItemPower = Field(default_factory=CairnItemPower)


class InventoryItem(StrictModel):
    id: str = Field(default_factory=lambda: new_id("item"))
    name: str = Field(min_length=1)
    details: str = ""
    cairn: CairnItemState = Field(default_factory=CairnItemState)


class CairnCharacterState(StrictModel):
    source: CairnMechanicsSource = CairnMechanicsSource.UNSET
    backfill_version: int = Field(default=0, ge=0)
    skills: list[str] = Field(default_factory=list)
    abilities: list[str] = Field(default_factory=list)
    str_score: int = Field(default=10, ge=0)
    dex_score: int = Field(default=10, ge=0)
    wil_score: int = Field(default=10, ge=0)
    max_str_score: int = Field(default=10, ge=0)
    max_dex_score: int = Field(default=10, ge=0)
    max_wil_score: int = Field(default=10, ge=0)
    hp: int = Field(default=1, ge=0)
    max_hp: int = Field(default=1, ge=0)
    armor: int = Field(default=0, ge=0, le=3)
    fatigue: int = Field(default=0, ge=0)
    deprived: bool = False
    critically_wounded: bool = False
    doomed: bool = False
    paralyzed: bool = False
    delirious: bool = False
    dead: bool = False
    slots_total: int = Field(default=10, ge=1)
    backpack_slots: int = Field(default=6, ge=0)
    comfortable_slots: int = Field(default=5, ge=0)
    slots_used: int = Field(default=0, ge=0)
    overloaded: bool = False
    primary_weapon_item_id: str | None = None
    notes: str = ""

    @model_validator(mode="after")
    def normalize_current_values(self) -> CairnCharacterState:
        object.__setattr__(self, "str_score", min(self.str_score, self.max_str_score))
        object.__setattr__(self, "dex_score", min(self.dex_score, self.max_dex_score))
        object.__setattr__(self, "wil_score", min(self.wil_score, self.max_wil_score))
        object.__setattr__(self, "hp", min(self.hp, self.max_hp))
        return self


class CairnResolution(StrictModel):
    ability: CairnAbility | None = None
    target: int | None = Field(default=None, ge=1, le=20)
    success: bool | None = None
    rest_kind: CairnRestKind | None = None
    actor_id: str | None = None
    actor_name: str | None = None
    item_id: str | None = None
    item_name: str | None = None
    item_power_kind: CairnItemPowerKind | None = None
    item_effect_kind: CairnItemEffectKind | None = None
    effect_summary: str | None = None
    uses_before: int | None = Field(default=None, ge=0)
    uses_after: int | None = Field(default=None, ge=0)
    recharge_condition: str | None = None
    combat_round: int | None = Field(default=None, ge=0)
    combat_started: bool | None = None
    combat_active: bool | None = None
    combat_initiator: EncounterInitiator | None = None
    player_acted: bool | None = None
    initiative_target: int | None = Field(default=None, ge=1, le=20)
    attack_stance: AttackStance | None = None
    weapon_item_id: str | None = None
    weapon_name: str | None = None
    target_combatant_id: str | None = None
    target_name: str | None = None
    target_armor: int | None = Field(default=None, ge=0, le=3)
    base_damage: int | None = Field(default=None, ge=0)
    damage_after_armor: int | None = Field(default=None, ge=0)
    hp_before: int | None = Field(default=None, ge=0)
    hp_after: int | None = Field(default=None, ge=0)
    str_before: int | None = Field(default=None, ge=0)
    str_after: int | None = Field(default=None, ge=0)
    dex_before: int | None = Field(default=None, ge=0)
    dex_after: int | None = Field(default=None, ge=0)
    wil_before: int | None = Field(default=None, ge=0)
    wil_after: int | None = Field(default=None, ge=0)
    fatigue_before: int | None = Field(default=None, ge=0)
    fatigue_after: int | None = Field(default=None, ge=0)
    target_hp_before: int | None = Field(default=None, ge=0)
    target_hp_after: int | None = Field(default=None, ge=0)
    target_str_before: int | None = Field(default=None, ge=0)
    target_str_after: int | None = Field(default=None, ge=0)
    target_defeated: bool | None = None
    target_fled: bool | None = None
    enemy_damage: int | None = Field(default=None, ge=0)
    enemy_damage_source: str | None = None
    morale_target: int | None = Field(default=None, ge=1, le=20)
    morale_success: bool | None = None
    defeated_combatant_ids: list[str] = Field(default_factory=list)
    fled_combatant_ids: list[str] = Field(default_factory=list)
    retreat_outcome: RetreatOutcome | None = None
    player_disengaged: bool | None = None
    pursuit_active: bool | None = None
    encounter_end_reason: EncounterEndReason | None = None
    scar_result: str | None = None
    overloaded: bool | None = None


class CharacterSheet(StrictModel):
    name: str = Field(default="Unnamed wanderer", min_length=1)
    archetype: str = "Unknown wanderer"
    epithet: str = ""
    backstory: str = ""
    drive: str = ""
    flaw: str = ""
    condition: str = "Uninjured, for now."
    inventory: list[InventoryItem] = Field(default_factory=list)
    cairn: CairnCharacterState = Field(default_factory=CairnCharacterState)


class PartyMember(StrictModel):
    id: str = Field(default_factory=lambda: new_id("party"))
    kind: PartyMemberKind = PartyMemberKind.COMPANION
    sheet: CharacterSheet = Field(default_factory=CharacterSheet)
    npc_id: str | None = None
    active: bool = True
    loyalty: str = ""
    notes: str = ""

    def display_label(self) -> str:
        name = self.sheet.name.strip()
        if name:
            return name
        return self.sheet.epithet.strip() or self.kind.value


class CampaignDirectives(StrictModel):
    """Persistent OOC guidance for this campaign.

    These are intentionally distinct from `setting_notes` and
    `player_notes`. Those older fields still carry campaign/world seed
    prose and character-facing backstory context, while directives are a
    durable steering layer for future model work ("this NPC cannot speak
    first", "keep miracles subtle", "avoid modern slang").
    """

    world_guidance: str = ""
    play_guidance: str = ""

    def has_content(self) -> bool:
        return bool(self.world_guidance.strip() or self.play_guidance.strip())


class CharacterQuizOption(StrictModel):
    """A single multiple-choice answer for the assist-mode interview.

    The "Other (write your own)" path is a frontend affordance and is
    NOT part of the model — the LLM should never invent it as a choice
    because the entire point of Other is that the player escapes the
    set the LLM proposed.
    """

    label: str = Field(min_length=1)


class CharacterQuizQuestion(StrictModel):
    id: str = Field(default_factory=lambda: new_id("q"))
    prompt: str = Field(min_length=1)
    options: list[CharacterQuizOption] = Field(min_length=2, max_length=6)


class CharacterQuiz(StrictModel):
    concept: str = Field(min_length=1)
    questions: list[CharacterQuizQuestion] = Field(min_length=3, max_length=6)


class CharacterQuizAnswer(StrictModel):
    """A single answer the player committed to during the interview.

    `value` always carries the literal answer text we'll feed to the LLM,
    whether the player picked an option or wrote their own. We keep
    `is_other` as a small audit signal so future debugging can distinguish
    "the player reached past the list" from "the player accepted the list".
    """

    question_id: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    value: str = Field(min_length=1)
    is_other: bool = False


class OracleTables(StrictModel):
    event_focus: list[str] = Field(min_length=6)
    event_actions: list[str] = Field(min_length=8)
    event_tones: list[str] = Field(min_length=8)
    event_subjects: list[str] = Field(min_length=8)


class OracleOutcome(StrictModel):
    id: str = Field(default_factory=lambda: new_id("oracle"))
    created_at: datetime = Field(default_factory=utc_now)
    kind: OracleKind
    summary: str
    rolls: list[Roll] = Field(default_factory=list)
    question: str | None = None
    likelihood: Likelihood | None = None
    answer: str | None = None
    probability: int | None = Field(default=None, ge=1, le=99)
    chaos_factor: int = Field(ge=1, le=9)
    event_focus: str | None = None
    event_action: str | None = None
    event_tone: str | None = None
    event_subject: str | None = None
    referenced_thread_id: str | None = None
    referenced_thread_ids: list[str] = Field(default_factory=list)
    referenced_npc_id: str | None = None
    referenced_npc_ids: list[str] = Field(default_factory=list)
    scene_status: SceneStatus | None = None
    scene_number_snapshot: int | None = Field(default=None, ge=1)
    scene_label_snapshot: str | None = None
    scene_status_snapshot: SceneStatus | None = None
    cairn: CairnResolution | None = None


class StageTiming(StrictModel):
    """Persisted timing for one pre-narration pipeline stage.

    The status is recorded as the *terminal* status reached during the
    turn (`done` / `skipped`), or `active` when the stream cancelled
    mid-stage. `started_at` is None for stages that were skipped before
    they ran; `completed_at` is None for stages that were still active
    at termination.
    """

    stage_id: str
    label: str
    status: StageStatus
    started_at: datetime | None = None
    completed_at: datetime | None = None


class GameEvent(StrictModel):
    id: str = Field(default_factory=lambda: new_id("event"))
    created_at: datetime = Field(default_factory=utc_now)
    event_type: EventType
    title: str
    content: str
    thinking: str = ""
    oracle_outcome_id: str | None = None
    # Pre-narration pipeline timings recorded by `StageTimingTracker`
    # while the turn streamed. Empty for non-narrative events and for
    # legacy saves that predate the field. Default `[]` keeps the
    # JSON-on-disk contract backwards-compatible without a migration.
    stage_timings: list[StageTiming] = Field(default_factory=list)


class GameState(StrictModel):
    id: str = Field(default_factory=lambda: new_id("state"))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    chaos_factor: int = Field(default=5, ge=1, le=9)
    scene_number: int = Field(default=1, ge=1)
    current_scene: str = Field(min_length=1)
    scene_status: SceneStatus = SceneStatus.EXPECTED
    campaign_status: CampaignStatus = CampaignStatus.ACTIVE
    campaign_end_reason: CampaignEndReason | None = None
    campaign_ended_at: datetime | None = None
    campaign_end_summary: str | None = None
    npc_roster_version: int = Field(default=2, ge=0)
    character: CharacterSheet = Field(default_factory=CharacterSheet)
    setting_notes: str = Field(min_length=1)
    player_notes: str = Field(min_length=1)
    directives: CampaignDirectives = Field(default_factory=CampaignDirectives)
    threads: list[GameThread] = Field(default_factory=list)
    npcs: list[NPC] = Field(default_factory=list)
    hidden_npcs: list[NPC] = Field(default_factory=list)
    party_members: list[PartyMember] = Field(default_factory=list)
    encounter: EncounterState = Field(default_factory=EncounterState)
    oracle_tables: OracleTables
    oracle_history: list[OracleOutcome] = Field(default_factory=list)
    action_log: list[GameEvent] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def mark_legacy_npc_roster_version(cls, data: object) -> object:
        """Mark missing-roster-version payloads as legacy saves."""
        if not isinstance(data, dict):
            return data
        if "npc_roster_version" in data:
            return data
        migrated = dict(data)
        migrated["npc_roster_version"] = 1
        return migrated

    def touch(self) -> None:
        self.updated_at = utc_now()

    def all_npcs(self) -> list[NPC]:
        return [*self.npcs, *self.hidden_npcs]

    def party_sheets(self) -> list[CharacterSheet]:
        return [self.character, *(member.sheet for member in self.party_members if member.active)]

    @model_validator(mode="after")
    def seed_character_from_legacy_notes(self) -> GameState:
        """Keep pre-character-sheet save files immediately playable.

        Older campaigns only have `player_notes`. The left folio still
        needs something useful, so seed a conservative sheet from those
        notes without pretending we parsed a full RPG inventory system.
        New campaigns provide structured character data directly.
        """
        if (
            self.character.inventory
            or self.character.epithet != ""
            or self.character.backstory != ""
        ):
            return self

        self.character.archetype = "Unknown wanderer"
        self.character.epithet = self.player_notes
        self.character.backstory = self.player_notes
        self.character.drive = "Survive the next turning of the wheel."
        self.character.flaw = "Carries too much of the old life forward."
        lowered = self.player_notes.lower()
        if "skewer" in lowered:
            self.character.inventory.append(
                InventoryItem(name="Rusted skewer", details="A poor weapon, but yours."),
            )
        if "map" in lowered:
            self.character.inventory.append(
                InventoryItem(name="Damp unreadable map", details="Burns cold against the ribs."),
            )
        return self
