from __future__ import annotations

import json
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Protocol

from dungeon_master.cairn import CairnEngine
from dungeon_master.campaign import (
    CampaignGenerator,
    CampaignWorldResult,
    CharacterDraftMode,
    CharacterDraftResult,
    CharacterGenerator,
    CharacterQuizResult,
    CharacterTemplatesResult,
)
from dungeon_master.cancel import CancellationToken
from dungeon_master.continuity_classifier import ContinuityClassifier, ContinuityUpdateScope
from dungeon_master.explainer import ExplainerEngine, ExplanationResult
from dungeon_master.memory import (
    CURRENT_MEMORY_SCHEMA_VERSION,
    CommittedTurnMemory,
    ConversationMessage,
    MemoryManager,
    MemoryState,
)
from dungeon_master.models import (
    NPC,
    AttackStance,
    CairnAbility,
    CairnRestKind,
    CampaignDirectives,
    CampaignEndReason,
    CampaignStatus,
    CharacterQuiz,
    CharacterQuizAnswer,
    CharacterSheet,
    EventType,
    GameEvent,
    GameState,
    JSONValue,
    Likelihood,
    NPCPlayerLabelKind,
    NPCStatus,
    OracleKind,
    OracleOutcome,
    PartyMember,
    SceneStatus,
    StageStatus,
    StageTiming,
    utc_now,
)
from dungeon_master.narrative import (
    CompletionDelta,
    NarrativeConfig,
    NarrativeEngine,
    NarrativeResult,
    StreamStageStatus,
    StreamStageUpdate,
)
from dungeon_master.npc_updater import (
    GeneratedNPCUpdateBatch,
    LegacyNPCRosterRepairResult,
    NPCUpdater,
    NPCUpdateResult,
)
from dungeon_master.oracle import OracleEngine
from dungeon_master.state_store import StateStore, TurnCheckpointRecord
from dungeon_master.thread_updater import (
    GeneratedThreadUpdateBatch,
    ThreadUpdater,
    ThreadUpdateResult,
)
from dungeon_master.turn_router import PlannedTurnOpKind, TurnPlan, TurnRouter

CURRENT_NPC_ROSTER_VERSION = 2
CURRENT_SAVE_SCHEMA_VERSION = 4
TURN_STREAM_STAGE_LABELS: dict[str, str] = {
    "planning_turn": "Planning turn",
    "resolving_mechanics": "Resolving mechanics",
    "classifying_continuity": "Classifying continuity",
    "updating_threads": "Updating threads",
    "updating_npcs": "Updating NPCs",
    "preparing_narration": "Preparing narration",
    "streaming_narration": "Streaming narration",
    "reconciling_continuity": "Reconciling continuity",
}
TURN_STREAM_STAGE_ORDER: tuple[str, ...] = tuple(TURN_STREAM_STAGE_LABELS)
PLAYER_ACTOR_ALIASES = {"player", "me", "myself", "you", "main character", "wanderer"}


@dataclass(frozen=True)
class ServiceActor:
    id: str
    name: str
    sheet: CharacterSheet
    is_player: bool

# Map between the wire-stream enum (`narrative.StreamStageStatus`) and
# the persisted enum (`models.StageStatus`). The two are intentionally
# separate types — wire vs. persistence — so the streaming protocol can
# evolve without forcing a save migration. The mapping is total and
# direct; we keep it as a module-level constant rather than a method so
# the lookup can be re-used inside `StageTimingTracker.record`.
_STAGE_STATUS_FROM_STREAM: dict[StreamStageStatus, StageStatus] = {
    StreamStageStatus.PENDING: StageStatus.PENDING,
    StreamStageStatus.ACTIVE: StageStatus.ACTIVE,
    StreamStageStatus.DONE: StageStatus.DONE,
    StreamStageStatus.SKIPPED: StageStatus.SKIPPED,
}


class StageTimingTracker:
    """Records per-stage start / end timestamps for one streamed turn.

    The tracker is the canonical owner of stage timings while a turn
    streams. It updates on every status transition emitted via
    ``_stage_delta``: ``ACTIVE`` writes ``started_at`` (idempotent —
    we keep the first-seen timestamp so a repeated ACTIVE doesn't
    reset the clock), and ``DONE`` / ``SKIPPED`` write ``completed_at``.
    The tracker preserves bootstrap order so ``snapshot()`` returns the
    stages in the same sequence the frontend renders the checklist.

    The tracker deliberately does not read or yield ``CompletionDelta``
    values. It is invoked alongside the existing ``_stage_delta`` so
    the streaming generator's shape stays unchanged; callers thread one
    tracker through the entire turn and attach its snapshot to the
    persisted ``GameEvent`` once the narrator finishes.
    """

    def __init__(self) -> None:
        # Insertion-ordered map keyed by stage_id. We snapshot by
        # iterating insertion order rather than re-sorting, because the
        # bootstrap pass that primes the tracker already emits stages
        # in canonical pipeline order.
        self._records: dict[str, StageTiming] = {}

    def record(self, stage_id: str, label: str, status: StreamStageStatus) -> None:
        persisted_status = _STAGE_STATUS_FROM_STREAM[status]
        existing = self._records.get(stage_id)
        now = utc_now()
        # `started_at` is set on the first ACTIVE transition.
        # `completed_at` is set on a DONE that follows a started stage —
        # a SKIPPED stage never started, so leaving completed_at None
        # keeps the simple "duration = completed_at - started_at" math
        # well-defined: present + present ⇒ duration; either missing ⇒
        # no duration. Encoding the skipped intent in `status` alone
        # avoids the ambiguity of "completed without running".
        started = existing.started_at if existing is not None else None
        completed = existing.completed_at if existing is not None else None
        if status == StreamStageStatus.ACTIVE and started is None:
            started = now
        if status == StreamStageStatus.DONE and completed is None:
            completed = now
        self._records[stage_id] = StageTiming(
            stage_id=stage_id,
            label=label,
            status=persisted_status,
            started_at=started,
            completed_at=completed,
        )

    def snapshot(self) -> list[StageTiming]:
        return list(self._records.values())


@dataclass(frozen=True)
class ExecutedTurn:
    outcome: OracleOutcome
    oracle_title: str | None
    execution_context: str | None = None
    pre_narration_continuity: bool = True


@dataclass(frozen=True)
class SaveBackfillReport:
    applied: bool
    state_changed: bool
    character_backfilled: bool
    npc_roster_repaired: bool
    terminal_state_synced: bool
    memory_rebuilt: bool
    checkpoint_written: bool
    campaign_status_before: CampaignStatus
    campaign_status_after: CampaignStatus
    visible_npc_count_before: int
    visible_npc_count_after: int
    hidden_npc_count_before: int
    hidden_npc_count_after: int
    visible_name_warnings: tuple[str, ...] = ()


class NarrativePort(Protocol):
    def generate(  # noqa: PLR0913
        self,
        state: GameState,
        outcome: OracleOutcome,
        player_input: str,
        *,
        execution_context: str | None = None,
        memory_context: str | None = None,
        scene_messages: list[dict[str, str]] | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> str:
        raise NotImplementedError


class CampaignPort(Protocol):
    def generate(self, character: CharacterSheet) -> GameState:
        raise NotImplementedError

    def generate_result(self, character: CharacterSheet) -> CampaignWorldResult:
        raise NotImplementedError

    def iter_generate(
        self,
        character: CharacterSheet,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, CampaignWorldResult]:
        raise NotImplementedError


class CairnPort(Protocol):
    def ensure_character_state(
        self,
        state: GameState,
        *,
        allow_backfill: bool,
        cancel_token: CancellationToken | None = None,
    ) -> bool:
        raise NotImplementedError

    def resolve_save(
        self,
        state: GameState,
        ability: CairnAbility,
        reason: str,
        *,
        actor_id: str | None = None,
    ) -> OracleOutcome:
        raise NotImplementedError

    def resolve_attack(  # noqa: PLR0913
        self,
        state: GameState,
        *,
        target_name: str,
        target_armor: int,
        weapon_item_id: str | None,
        stance: AttackStance,
        actor_id: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> OracleOutcome:
        raise NotImplementedError

    def suffer_harm(  # noqa: PLR0913
        self,
        state: GameState,
        *,
        amount: int,
        source: str,
        in_combat: bool,
        armor_applies: bool,
        actor_id: str | None = None,
    ) -> OracleOutcome:
        raise NotImplementedError

    def resolve_enemy_opener(
        self,
        state: GameState,
        *,
        source: str,
        text: str,
        cancel_token: CancellationToken | None = None,
    ) -> OracleOutcome:
        raise NotImplementedError

    def recover(
        self,
        state: GameState,
        kind: CairnRestKind,
        *,
        actor_id: str | None = None,
    ) -> OracleOutcome:
        raise NotImplementedError

    def resolve_retreat(self, state: GameState, reason: str) -> OracleOutcome:
        raise NotImplementedError

    def set_item_equipped(
        self,
        state: GameState,
        *,
        item_id: str,
        equipped: bool,
        actor_id: str | None = None,
    ) -> None:
        raise NotImplementedError

    def acquire_items(
        self,
        state: GameState,
        *,
        text: str,
        actor_id: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> str:
        raise NotImplementedError

    def use_item(
        self,
        state: GameState,
        *,
        item_id: str,
        intent: str,
        actor_id: str | None = None,
    ) -> OracleOutcome:
        raise NotImplementedError

    def drop_item(
        self,
        state: GameState,
        *,
        item_id: str,
        actor_id: str | None = None,
    ) -> str:
        raise NotImplementedError

    def backfill_companion_sheet(
        self,
        state: GameState,
        authored: CharacterSheet,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> CharacterSheet:
        raise NotImplementedError


class CharacterPort(Protocol):
    def setup_state(self) -> GameState:
        raise NotImplementedError

    def generate_templates(self) -> list[CharacterSheet]:
        raise NotImplementedError

    def generate_templates_result(self) -> CharacterTemplatesResult:
        raise NotImplementedError

    def iter_generate_templates(
        self,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, CharacterTemplatesResult]:
        raise NotImplementedError

    def generate_draft(
        self,
        *,
        mode: CharacterDraftMode,
        prompt: str | None,
        template: CharacterSheet | None,
    ) -> CharacterSheet:
        raise NotImplementedError

    def generate_draft_result(
        self,
        *,
        mode: CharacterDraftMode,
        prompt: str | None,
        template: CharacterSheet | None,
    ) -> CharacterDraftResult:
        raise NotImplementedError

    def iter_generate_draft(
        self,
        *,
        mode: CharacterDraftMode,
        prompt: str | None,
        template: CharacterSheet | None,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, CharacterDraftResult]:
        raise NotImplementedError

    def generate_quiz(self, concept: str) -> CharacterQuiz:
        raise NotImplementedError

    def generate_quiz_result(self, concept: str) -> CharacterQuizResult:
        raise NotImplementedError

    def iter_generate_quiz(
        self,
        concept: str,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, CharacterQuizResult]:
        raise NotImplementedError

    def generate_quizzed_draft(
        self,
        *,
        concept: str,
        answers: list[CharacterQuizAnswer],
        final_note: str | None,
    ) -> CharacterSheet:
        raise NotImplementedError

    def generate_quizzed_draft_result(
        self,
        *,
        concept: str,
        answers: list[CharacterQuizAnswer],
        final_note: str | None,
    ) -> CharacterDraftResult:
        raise NotImplementedError

    def iter_generate_quizzed_draft(
        self,
        *,
        concept: str,
        answers: list[CharacterQuizAnswer],
        final_note: str | None,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, CharacterDraftResult]:
        raise NotImplementedError


class ExplainerPort(Protocol):
    def generate_result(
        self,
        state: GameState,
        question: str,
        *,
        memory_context: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> ExplanationResult:
        raise NotImplementedError

    def iter_stream(
        self,
        state: GameState,
        question: str,
        *,
        memory_context: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, ExplanationResult]:
        raise NotImplementedError


class ThreadUpdaterPort(Protocol):
    def update_threads(  # noqa: PLR0913
        self,
        state: GameState,
        *,
        player_input: str,
        outcome: OracleOutcome,
        execution_context: str | None = None,
        narrative_text: str | None = None,
        memory_context: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> ThreadUpdateResult:
        raise NotImplementedError

    def generate_thread_updates(  # noqa: PLR0913
        self,
        state: GameState,
        *,
        player_input: str,
        outcome: OracleOutcome,
        execution_context: str | None = None,
        narrative_text: str | None = None,
        memory_context: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> GeneratedThreadUpdateBatch | None:
        raise NotImplementedError

    def apply_generated_updates(
        self,
        state: GameState,
        generated: GeneratedThreadUpdateBatch,
    ) -> ThreadUpdateResult:
        raise NotImplementedError


class NPCUpdaterPort(Protocol):
    def update_npcs(  # noqa: PLR0913
        self,
        state: GameState,
        *,
        player_input: str,
        outcome: OracleOutcome,
        execution_context: str | None = None,
        narrative_text: str | None = None,
        memory_context: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> NPCUpdateResult:
        raise NotImplementedError

    def generate_npc_updates(  # noqa: PLR0913
        self,
        state: GameState,
        *,
        player_input: str,
        outcome: OracleOutcome,
        execution_context: str | None = None,
        narrative_text: str | None = None,
        memory_context: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> GeneratedNPCUpdateBatch | None:
        raise NotImplementedError

    def apply_generated_updates(
        self,
        state: GameState,
        generated: GeneratedNPCUpdateBatch,
    ) -> NPCUpdateResult:
        raise NotImplementedError

    def reseed_legacy_roster(
        self,
        state: GameState,
        *,
        memory_context: str | None = None,
        cancel_token: CancellationToken | None = None,
        use_model: bool = False,
    ) -> LegacyNPCRosterRepairResult:
        raise NotImplementedError


class ContinuityClassifierPort(Protocol):
    def classify_update_scope(
        self,
        state: GameState,
        *,
        player_input: str,
        outcome: OracleOutcome,
        execution_context: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> ContinuityUpdateScope:
        raise NotImplementedError


class GameService:
    def __init__(  # noqa: PLR0913
        self,
        store: StateStore,
        oracle: OracleEngine | None = None,
        narrative: NarrativePort | None = None,
        campaign_generator: CampaignPort | None = None,
        character_generator: CharacterPort | None = None,
        explainer: ExplainerPort | None = None,
        cairn_engine: CairnPort | None = None,
        turn_router: TurnRouter | None = None,
        memory_manager: MemoryManager | None = None,
        thread_updater: ThreadUpdaterPort | None = None,
        npc_updater: NPCUpdaterPort | None = None,
        continuity_classifier: ContinuityClassifierPort | None = None,
    ) -> None:
        self._store = store
        self._oracle = oracle or OracleEngine()
        self._narrative = narrative or NarrativeEngine()
        self._campaign_generator = campaign_generator or CampaignGenerator.from_env()
        self._character_generator = character_generator or CharacterGenerator.from_env()
        default_narrative_config = getattr(self._narrative, "_config", None)
        self._explainer = explainer or ExplainerEngine(
            config=(
                default_narrative_config
                if isinstance(default_narrative_config, NarrativeConfig)
                else None
            ),
        )
        self._cairn = cairn_engine or CairnEngine()
        self._turn_router = turn_router or TurnRouter()
        self._memory = memory_manager or MemoryManager()
        self._thread_updater = thread_updater or ThreadUpdater(
            config=(
                default_narrative_config
                if isinstance(default_narrative_config, NarrativeConfig)
                else None
            ),
        )
        self._npc_updater = npc_updater or NPCUpdater(
            config=(
                default_narrative_config
                if isinstance(default_narrative_config, NarrativeConfig)
                else None
            ),
        )
        self._continuity_classifier = continuity_classifier or ContinuityClassifier(
            config=(
                default_narrative_config
                if isinstance(default_narrative_config, NarrativeConfig)
                else None
            ),
        )

    def bind_store(self, store: StateStore) -> None:
        """Rebind the service to a different save slot's StateStore.

        F-12 keeps the gameplay API single-active-save for v1: the FastAPI app
        swaps which local save directory is considered "current" instead of
        threading `save_id` through every gameplay route. Rebinding the store is
        safe because `GameService` caches no state derived from the store beyond
        the `_store` reference itself; canonical state is always reloaded on
        demand per request.
        """
        self._store = store

    def new_setup_state(self) -> GameState:
        """Return a fresh setup-state skeleton for a brand-new save slot."""
        return self._new_setup_state()

    def backfill_current_save(
        self,
        *,
        apply: bool,
        create_checkpoint: bool = True,
        cancel_token: CancellationToken | None = None,
    ) -> SaveBackfillReport:
        """Audit/backfill one existing save against current core features.

        This is intentionally *not* a campaign reseed. The goal is to bring an
        older save forward so it carries the canonical state newer features now
        expect (character Cairn backfill, visible/hidden NPC split, terminal
        status sync, rebuilt `memory.json`) without regenerating the campaign's
        world or rewriting cast canon.

        `apply=False` performs a dry run and reports what would change without
        touching disk. `apply=True` persists canonical state only when the state
        itself changed, and rebuilds/saves the memory sidecar when needed.
        """
        if not self._store.exists():
            message = "No save state exists to backfill."
            raise ValueError(message)

        before_state = self._store.load()
        before_memory = self._store.load_memory_or_none()
        working = before_state.model_copy(deep=True)

        character_backfilled = self._cairn.ensure_character_state(
            working,
            allow_backfill=working.campaign_status == CampaignStatus.ACTIVE,
            cancel_token=cancel_token,
        )
        npc_roster_repaired = self._repair_npc_roster_on_load(
            working,
            cancel_token=cancel_token,
        )
        terminal_state_synced = self._sync_terminal_state_on_load(working)
        schema_defaults_persisted = self._ensure_current_save_schema(working)
        state_changed = (
            character_backfilled
            or npc_roster_repaired
            or terminal_state_synced
            or schema_defaults_persisted
        )

        rebuilt_memory = self._memory_for_state(
            working,
            existing_memory=before_memory,
            force_rebuild=True,
        )
        memory_rebuilt = (
            before_memory is None
            or rebuilt_memory.model_dump(mode="json") != before_memory.model_dump(mode="json")
        )
        visible_name_warnings = self._audit_visible_npc_name_support(working)

        checkpoint_written = False
        if apply:
            if state_changed:
                self._store.save(working, create_checkpoint=create_checkpoint)
                checkpoint_written = create_checkpoint
            if memory_rebuilt:
                self._store.save_memory(rebuilt_memory)

        return SaveBackfillReport(
            applied=apply,
            state_changed=state_changed,
            character_backfilled=character_backfilled,
            npc_roster_repaired=npc_roster_repaired,
            terminal_state_synced=terminal_state_synced,
            memory_rebuilt=memory_rebuilt,
            checkpoint_written=checkpoint_written,
            campaign_status_before=before_state.campaign_status,
            campaign_status_after=working.campaign_status,
            visible_npc_count_before=len(before_state.npcs),
            visible_npc_count_after=len(working.npcs),
            hidden_npc_count_before=len(before_state.hidden_npcs),
            hidden_npc_count_after=len(working.hidden_npcs),
            visible_name_warnings=visible_name_warnings,
        )

    def load_state(self, *, cancel_token: CancellationToken | None = None) -> GameState:
        state = self._store.load_or_create(self._new_setup_state)
        changed = self._cairn.ensure_character_state(
            state,
            allow_backfill=state.campaign_status == CampaignStatus.ACTIVE,
            cancel_token=cancel_token,
        )
        changed = self._repair_npc_roster_on_load(
            state,
            cancel_token=cancel_token,
        ) or changed
        changed = self._sync_terminal_state_on_load(state) or changed
        if changed:
            self._store.save(state, create_checkpoint=False)
            self._store.save_memory(self._memory_for_state(state, force_rebuild=True))
        return state

    def _load_state_readonly(
        self,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> GameState:
        state = self._store.load() if self._store.exists() else self._new_setup_state()
        self._cairn.ensure_character_state(
            state,
            allow_backfill=state.campaign_status == CampaignStatus.ACTIVE,
            cancel_token=cancel_token,
        )
        self._repair_npc_roster_on_load(
            state,
            cancel_token=cancel_token,
        )
        self._sync_terminal_state_on_load(state)
        return state

    def reset(self) -> GameState:
        state = self._new_setup_state()
        self._record_event(
            state,
            GameEvent(
                event_type=EventType.SYSTEM,
                title="Setup reset",
                content="Returned to character creation.",
            ),
        )
        self._save_state_commit(state, create_checkpoint=True)
        return state

    def _new_setup_state(self) -> GameState:
        return self._character_generator.setup_state()

    def list_character_templates(self) -> list[CharacterSheet]:
        return self._character_generator.generate_templates()

    def list_character_templates_result(self) -> CharacterTemplatesResult:
        return self._character_generator.generate_templates_result()

    def stream_character_templates(
        self,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, CharacterTemplatesResult]:
        return self._character_generator.iter_generate_templates(cancel_token=cancel_token)

    def generate_character_draft(
        self,
        *,
        mode: CharacterDraftMode,
        prompt: str | None,
        template: CharacterSheet | None,
    ) -> CharacterSheet:
        return self._character_generator.generate_draft(
            mode=mode,
            prompt=prompt,
            template=template,
        )

    def generate_character_draft_result(
        self,
        *,
        mode: CharacterDraftMode,
        prompt: str | None,
        template: CharacterSheet | None,
    ) -> CharacterDraftResult:
        return self._character_generator.generate_draft_result(
            mode=mode,
            prompt=prompt,
            template=template,
        )

    def generate_character_quiz(self, concept: str) -> CharacterQuiz:
        return self._character_generator.generate_quiz(concept)

    def generate_character_quiz_result(self, concept: str) -> CharacterQuizResult:
        return self._character_generator.generate_quiz_result(concept)

    def stream_character_quiz(
        self,
        concept: str,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, CharacterQuizResult]:
        return self._character_generator.iter_generate_quiz(concept, cancel_token=cancel_token)

    def generate_quizzed_character_draft(
        self,
        *,
        concept: str,
        answers: list[CharacterQuizAnswer],
        final_note: str | None,
    ) -> CharacterSheet:
        return self._character_generator.generate_quizzed_draft(
            concept=concept,
            answers=answers,
            final_note=final_note,
        )

    def generate_quizzed_character_draft_result(
        self,
        *,
        concept: str,
        answers: list[CharacterQuizAnswer],
        final_note: str | None,
    ) -> CharacterDraftResult:
        return self._character_generator.generate_quizzed_draft_result(
            concept=concept,
            answers=answers,
            final_note=final_note,
        )

    def stream_quizzed_character_draft(
        self,
        *,
        concept: str,
        answers: list[CharacterQuizAnswer],
        final_note: str | None,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, CharacterDraftResult]:
        return self._character_generator.iter_generate_quizzed_draft(
            concept=concept,
            answers=answers,
            final_note=final_note,
            cancel_token=cancel_token,
        )

    def stream_character_draft(
        self,
        *,
        mode: CharacterDraftMode,
        prompt: str | None,
        template: CharacterSheet | None,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, CharacterDraftResult]:
        return self._character_generator.iter_generate_draft(
            mode=mode,
            prompt=prompt,
            template=template,
            cancel_token=cancel_token,
        )

    def finalize_character(self, character: CharacterSheet) -> GameState:
        state = self.load_state()
        if state.campaign_status == CampaignStatus.ACTIVE:
            message = "Campaign already started. Reset to create a new character."
            raise ValueError(message)
        if state.campaign_status == CampaignStatus.ENDED:
            message = self._campaign_end_conflict_message(state)
            raise ValueError(message)
        state.character = character.model_copy(deep=True)
        self._cairn.ensure_character_state(state, allow_backfill=False)
        state.player_notes = character.backstory
        state.campaign_status = CampaignStatus.READY_TO_START
        self._record_event(
            state,
            GameEvent(
                event_type=EventType.SYSTEM,
                title="Character finalized",
                content=f"{character.name} is ready to enter the world.",
            ),
        )
        self._save_state_commit(state, create_checkpoint=True)
        return state

    def start_campaign(self) -> GameState:
        return self.start_campaign_result().state

    def start_campaign_result(self) -> CampaignWorldResult:
        state = self.load_state()
        if state.campaign_status == CampaignStatus.ACTIVE:
            return CampaignWorldResult(state=state)
        if state.campaign_status == CampaignStatus.ENDED:
            message = self._campaign_end_conflict_message(state)
            raise ValueError(message)
        if state.campaign_status != CampaignStatus.READY_TO_START:
            message = "Finalize a character before starting the campaign."
            raise ValueError(message)

        generated = self._campaign_generator.generate_result(state.character)
        next_state = generated.state
        self._cairn.ensure_character_state(next_state, allow_backfill=True)
        self._record_event(
            next_state,
            GameEvent(
                event_type=EventType.SYSTEM,
                title="Campaign initialized",
                content="Opening state and oracle tables were generated for this campaign.",
                thinking=generated.thinking,
            ),
        )
        self._save_state_commit(next_state, create_checkpoint=True)
        return CampaignWorldResult(state=next_state, thinking=generated.thinking)

    def stream_start_campaign(
        self,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, CampaignWorldResult]:
        state = self.load_state(cancel_token=cancel_token)
        if state.campaign_status == CampaignStatus.ACTIVE:
            result = CampaignWorldResult(state=state)

            def _active() -> Generator[CompletionDelta, None, CampaignWorldResult]:
                yield CompletionDelta(content=state.model_dump_json())
                return result

            return _active()
        if state.campaign_status == CampaignStatus.ENDED:
            message = self._campaign_end_conflict_message(state)
            raise ValueError(message)
        if state.campaign_status != CampaignStatus.READY_TO_START:
            message = "Finalize a character before starting the campaign."
            raise ValueError(message)

        generator = self._campaign_generator.iter_generate(
            state.character,
            cancel_token=cancel_token,
        )

        def _wrapped() -> Generator[CompletionDelta, None, CampaignWorldResult]:
            generated = yield from generator
            next_state = generated.state
            self._raise_if_cancelled(cancel_token)
            self._cairn.ensure_character_state(
                next_state,
                allow_backfill=True,
                cancel_token=cancel_token,
            )
            self._raise_if_cancelled(cancel_token)
            queued_events: list[GameEvent] = []
            self._queue_event(
                next_state,
                queued_events,
                GameEvent(
                    event_type=EventType.SYSTEM,
                    title="Campaign initialized",
                    content="Opening state and oracle tables were generated for this campaign.",
                    thinking=generated.thinking,
                ),
            )
            self._persist_streamed_state(
                next_state,
                queued_events,
                cancel_token=cancel_token,
            )
            return CampaignWorldResult(state=next_state, thinking=generated.thinking)

        return _wrapped()

    def end_campaign(
        self,
        *,
        reason: CampaignEndReason,
        summary: str | None = None,
    ) -> GameState:
        state = self.load_state()
        self._ensure_active(state)
        if reason == CampaignEndReason.DEATH and not state.character.cairn.dead:
            message = "Cannot end the campaign as death while the character is still alive."
            raise ValueError(message)
        if reason != CampaignEndReason.DEATH and state.encounter.active:
            message = "Cannot retire or declare victory while an encounter is still active."
            raise ValueError(message)

        self._mark_campaign_ended(state, reason=reason, summary=summary)
        self._record_event(
            state,
            self._campaign_end_event(state),
        )
        self._save_state_commit(state, create_checkpoint=True)
        return state

    def explain(self, question: str) -> ExplanationResult:
        state, memory_context = self._load_state_and_memory_context_for_explainer(question)
        return self._explainer.generate_result(
            state,
            question,
            memory_context=memory_context,
        )

    def stream_explain(
        self,
        question: str,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, ExplanationResult]:
        state, memory_context = self._load_state_and_memory_context_for_explainer(
            question,
            cancel_token=cancel_token,
        )
        return self._explainer.iter_stream(
            state,
            question,
            memory_context=memory_context,
            cancel_token=cancel_token,
        )

    def resolve_cairn_save(self, ability: CairnAbility, reason: str) -> GameState:
        state = self.load_state()
        self._ensure_active(state)
        outcome = self._cairn.resolve_save(state, ability, reason)
        self._commit_oracle_turn(
            state=state,
            player_input=f"{ability.value} save: {reason}",
            outcome=outcome,
            oracle_title="Cairn save",
        )
        return state

    def attack_target(
        self,
        *,
        target_name: str,
        target_armor: int,
        weapon_item_id: str | None,
        stance: AttackStance,
    ) -> GameState:
        state = self.load_state()
        self._ensure_active(state)
        outcome = self._cairn.resolve_attack(
            state,
            target_name=target_name,
            target_armor=target_armor,
            weapon_item_id=weapon_item_id,
            stance=stance,
        )
        self._commit_oracle_turn(
            state=state,
            player_input=f"Attack {target_name}",
            outcome=outcome,
            oracle_title="Attack resolution",
        )
        return state

    def suffer_harm(
        self,
        *,
        amount: int,
        source: str,
        in_combat: bool,
        armor_applies: bool,
    ) -> GameState:
        state = self.load_state()
        self._ensure_active(state)
        outcome = self._cairn.suffer_harm(
            state,
            amount=amount,
            source=source,
            in_combat=in_combat,
            armor_applies=armor_applies,
        )
        self._commit_oracle_turn(
            state=state,
            player_input=f"Suffer harm from {source}",
            outcome=outcome,
            oracle_title="Harm resolution",
        )
        return state

    def recover_character(self, kind: CairnRestKind) -> GameState:
        state = self.load_state()
        self._ensure_active(state)
        outcome = self._cairn.recover(state, kind)
        self._commit_oracle_turn(
            state=state,
            player_input=f"Recovery: {kind.value}",
            outcome=outcome,
            oracle_title="Recovery",
        )
        return state

    def retreat_from_encounter(self, reason: str) -> GameState:
        state = self.load_state()
        self._ensure_active(state)
        outcome = self._cairn.resolve_retreat(state, reason)
        self._commit_oracle_turn(
            state=state,
            player_input=f"Retreat: {reason}",
            outcome=outcome,
            oracle_title="Retreat resolution",
        )
        return state

    def set_item_equipped(self, *, item_id: str, equipped: bool) -> GameState:
        state = self.load_state()
        self._ensure_active(state)
        self._cairn.set_item_equipped(state, item_id=item_id, equipped=equipped)
        title = "Equipment updated"
        verb = "equipped" if equipped else "unequipped"
        self._record_event(
            state,
            GameEvent(
                event_type=EventType.SYSTEM,
                title=title,
                content=f"Item {item_id} {verb}.",
            ),
        )
        self._save_state_commit(state, create_checkpoint=True)
        return state

    def acquire_inventory(self, text: str) -> GameState:
        state = self.load_state()
        self._ensure_active(state)
        summary = self._cairn.acquire_items(state, text=text)
        self._record_event(
            state,
            GameEvent(
                event_type=EventType.SYSTEM,
                title="Inventory acquired",
                content=summary,
            ),
        )
        outcome = OracleOutcome(
            kind=OracleKind.PLAYER_ACTION,
            summary=summary,
            question=text,
            chaos_factor=state.chaos_factor,
        )
        execution_context = self._format_execution_context([summary])
        self._commit_oracle_turn(
            state=state,
            player_input=text,
            outcome=outcome,
            oracle_title=None,
            execution_context=execution_context,
        )
        return state

    def set_chaos_factor(self, value: int) -> GameState:
        state = self.load_state()
        self._ensure_active(state)
        state.chaos_factor = max(1, min(9, value))
        self._record_event(
            state,
            GameEvent(
                event_type=EventType.SYSTEM,
                title="Chaos factor changed",
                content=f"Chaos factor set to {state.chaos_factor}.",
            ),
        )
        self._save_state_commit(state, create_checkpoint=True)
        return state

    def update_notes(self, *, setting_notes: str, player_notes: str) -> GameState:
        state = self.load_state()
        self._ensure_active(state)
        state.setting_notes = setting_notes
        state.player_notes = player_notes
        self._record_event(
            state,
            GameEvent(
                event_type=EventType.SYSTEM,
                title="Notes updated",
                content="Setting and player notes were updated.",
            ),
        )
        self._save_state_commit(state, create_checkpoint=True)
        return state

    def update_directives(
        self,
        *,
        world_guidance: str,
        play_guidance: str,
    ) -> GameState:
        state = self.load_state()
        self._ensure_active(state)
        state.directives = CampaignDirectives(
            world_guidance=world_guidance,
            play_guidance=play_guidance,
        )
        # Directives are durable OOC steering, not in-fiction transcript
        # events. Persist the state change, but do not append a visible
        # system message to the action log.
        self._save_state_commit(state, create_checkpoint=True)
        return state

    def ask_oracle(self, question: str, likelihood: Likelihood) -> GameState:
        state = self.load_state()
        self._ensure_active(state)
        outcome = self._oracle.ask_yes_no(state, question, likelihood)
        self._commit_oracle_turn(
            state=state,
            player_input=f"Oracle question: {question}",
            outcome=outcome,
            oracle_title="Oracle answer",
        )
        return state

    def preview_oracle(self, question: str, likelihood: Likelihood) -> OracleOutcome:
        state = self._load_state_readonly()
        self._ensure_active(state)
        return self._oracle.ask_yes_no(state, question, likelihood)

    def generate_random_event(self) -> GameState:
        state = self.load_state()
        self._ensure_active(state)
        outcome = self._oracle.generate_random_event(state)
        self._commit_oracle_turn(
            state=state,
            player_input="Generate a random event.",
            outcome=outcome,
            oracle_title="Random event",
        )
        return state

    def check_scene(self, expected_scene: str) -> GameState:
        state = self.load_state()
        self._ensure_active(state)
        outcome = self._oracle.check_scene(state, expected_scene)
        if outcome.scene_status is not None:
            self._apply_scene_transition(state, expected_scene, outcome.scene_status)

        self._commit_oracle_turn(
            state=state,
            player_input=f"Check scene: {expected_scene}",
            outcome=outcome,
            oracle_title="Scene check",
        )
        return state

    def submit_player_action(self, action: str) -> GameState:
        state = self.load_state()
        self._ensure_active(state)
        outcome = OracleOutcome(
            kind=OracleKind.PLAYER_ACTION,
            summary="Narrative continuation requested without an oracle roll.",
            chaos_factor=state.chaos_factor,
        )
        self._record_event(
            state,
            GameEvent(event_type=EventType.PLAYER, title="Player action", content=action),
        )
        self._commit_oracle_turn(
            state=state,
            player_input=action,
            outcome=outcome,
            oracle_title=None,
            pre_narration_continuity=False,
            post_narration_continuity=True,
        )
        return state

    def submit_player_turn(self, text: str) -> GameState:
        """Route natural player chat through the right deterministic operation.

        Slash commands remain a frontend affordance. This method is the
        human-DM path: player writes naturally, the backend conservatively
        decides whether a roll is required, and the LLM still only narrates
        after Python has produced the mechanical outcome.
        """
        plan, state = self._plan_turn_and_load_state(text)
        self._ensure_active(state)
        self._record_event(
            state,
            GameEvent(event_type=EventType.PLAYER, title="Player action", content=text),
        )
        executed = self._execute_turn_plan(state, plan)
        self._commit_oracle_turn(
            state=state,
            player_input=text,
            outcome=executed.outcome,
            oracle_title=executed.oracle_title,
            execution_context=executed.execution_context,
            pre_narration_continuity=executed.pre_narration_continuity,
            post_narration_continuity=not executed.pre_narration_continuity,
        )
        return state

    def regenerate_response(self, narrative_event_id: str) -> GameState:
        state = self.load_state()
        self._ensure_active(state)

        latest_narrative = next(
            (
                event
                for event in reversed(state.action_log)
                if event.event_type == EventType.NARRATIVE
            ),
            None,
        )
        if latest_narrative is None or latest_narrative.id != narrative_event_id:
            message = "Only the latest DM response can be regenerated."
            raise ValueError(message)
        if latest_narrative.oracle_outcome_id is None:
            message = "This response cannot be regenerated."
            raise ValueError(message)

        checkpoint = self._store.load_turn_checkpoint(latest_narrative.oracle_outcome_id)
        restored_state = checkpoint.state.model_copy(deep=True)

        # Preserve prior repair audit messages for the same turn so repeated
        # regenerate requests leave a visible trace rather than rewriting history.
        prefix_len = len(restored_state.action_log)
        repair_events = [
            event
            for event in state.action_log[prefix_len:-1]
            if event.event_type == EventType.SYSTEM and event.title == "Narrative regenerated"
        ]
        restored_state.action_log.extend(repair_events)

        outcome = next(
            (
                item
                for item in restored_state.oracle_history
                if item.id == checkpoint.oracle_outcome_id
            ),
            None,
        )
        if outcome is None:
            message = "Turn checkpoint is missing the original oracle outcome."
            raise ValueError(message)

        self._record_event(
            restored_state,
            GameEvent(
                event_type=EventType.SYSTEM,
                title="Narrative regenerated",
                content="Repaired the latest DM response after a retry request.",
            ),
        )
        working_memory = self._load_turn_memory_state(restored_state)
        memory_context, scene_messages, _ = self._memory_context_for_narrator(
            restored_state,
            player_input=checkpoint.player_input,
            outcome=outcome,
            working_memory=working_memory,
        )
        narration = self._generate_narrative(
            restored_state,
            outcome,
            checkpoint.player_input,
            execution_context=checkpoint.execution_context,
            memory_context=memory_context,
            scene_messages=scene_messages,
        )
        self._record_event(
            restored_state,
            GameEvent(
                event_type=EventType.NARRATIVE,
                title="Narrative response",
                content=narration.content,
                thinking=narration.thinking,
                oracle_outcome_id=outcome.id,
            ),
        )
        revealed_npc_ids = self._disclose_npcs_from_text(restored_state, narration.content)
        if revealed_npc_ids:
            merged_npcs = self._merged_npc_ids(outcome, revealed_npc_ids)
            outcome.referenced_npc_ids = merged_npcs
            outcome.referenced_npc_id = merged_npcs[0] if merged_npcs else None
        working_memory = self._apply_post_narration_continuity_for_turn(
            restored_state,
            player_input=checkpoint.player_input,
            outcome=outcome,
            execution_context=checkpoint.execution_context,
            narrative_text=narration.content,
            working_memory=working_memory,
        )
        self._save_state_commit(
            restored_state,
            create_checkpoint=True,
            committed_turn=CommittedTurnMemory(
                player_input=checkpoint.player_input,
                outcome=outcome,
                narrative_text=narration.content,
                execution_context=checkpoint.execution_context or "",
            ),
        )
        return restored_state

    def stream_submit_player_action(
        self,
        action: str,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, GameState]:
        tracker = StageTimingTracker()
        yield from self._iter_turn_stage_bootstrap(
            skipped_stage_ids={"planning_turn", "resolving_mechanics"},
            tracker=tracker,
        )
        state = self.load_state(cancel_token=cancel_token)
        self._ensure_active(state)
        outcome = OracleOutcome(
            kind=OracleKind.PLAYER_ACTION,
            summary="Narrative continuation requested without an oracle roll.",
            chaos_factor=state.chaos_factor,
        )
        queued_events: list[GameEvent] = []
        self._queue_event(
            state,
            queued_events,
            GameEvent(event_type=EventType.PLAYER, title="Player action", content=action),
        )
        return (
            yield from self._stream_oracle_turn(
                state=state,
                player_input=action,
                outcome=outcome,
                oracle_title=None,
                queued_events=queued_events,
                pre_narration_continuity=False,
                post_narration_continuity=True,
                cancel_token=cancel_token,
                tracker=tracker,
            )
        )

    def stream_submit_player_turn(
        self,
        text: str,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, GameState]:
        tracker = StageTimingTracker()
        yield from self._iter_turn_stage_bootstrap(tracker=tracker)
        yield self._stage_delta("planning_turn", StreamStageStatus.ACTIVE, tracker=tracker)
        plan, state = self._plan_turn_and_load_state(text, cancel_token=cancel_token)
        yield self._stage_delta("planning_turn", StreamStageStatus.DONE, tracker=tracker)
        self._ensure_active(state)
        queued_events: list[GameEvent] = []
        self._queue_event(
            state,
            queued_events,
            GameEvent(event_type=EventType.PLAYER, title="Player action", content=text),
        )
        self._raise_if_cancelled(cancel_token)
        yield self._stage_delta("resolving_mechanics", StreamStageStatus.ACTIVE, tracker=tracker)
        executed = self._execute_turn_plan(state, plan, cancel_token=cancel_token)
        yield self._stage_delta("resolving_mechanics", StreamStageStatus.DONE, tracker=tracker)
        return (yield from self._stream_oracle_turn(
            state=state,
            player_input=text,
            outcome=executed.outcome,
            oracle_title=executed.oracle_title,
            queued_events=queued_events,
            execution_context=executed.execution_context,
            pre_narration_continuity=executed.pre_narration_continuity,
            post_narration_continuity=not executed.pre_narration_continuity,
            cancel_token=cancel_token,
            tracker=tracker,
        ))

    def stream_regenerate_response(
        self,
        narrative_event_id: str,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, GameState]:
        tracker = StageTimingTracker()
        yield from self._iter_turn_stage_bootstrap(
            skipped_stage_ids={
                "planning_turn",
                "resolving_mechanics",
                "classifying_continuity",
                "updating_threads",
                "updating_npcs",
            },
            tracker=tracker,
        )
        state = self.load_state(cancel_token=cancel_token)
        self._ensure_active(state)
        latest_narrative = next(
            (
                event
                for event in reversed(state.action_log)
                if event.event_type == EventType.NARRATIVE
            ),
            None,
        )
        if latest_narrative is None or latest_narrative.id != narrative_event_id:
            message = "Only the latest DM response can be regenerated."
            raise ValueError(message)
        if latest_narrative.oracle_outcome_id is None:
            message = "This response cannot be regenerated."
            raise ValueError(message)

        checkpoint = self._store.load_turn_checkpoint(latest_narrative.oracle_outcome_id)
        restored_state = checkpoint.state.model_copy(deep=True)
        prefix_len = len(restored_state.action_log)
        repair_events = [
            event
            for event in state.action_log[prefix_len:-1]
            if event.event_type == EventType.SYSTEM and event.title == "Narrative regenerated"
        ]
        restored_state.action_log.extend(repair_events)
        queued_events: list[GameEvent] = []

        outcome = next(
            (
                item
                for item in restored_state.oracle_history
                if item.id == checkpoint.oracle_outcome_id
            ),
            None,
        )
        if outcome is None:
            message = "Turn checkpoint is missing the original oracle outcome."
            raise ValueError(message)

        self._queue_event(
            restored_state,
            queued_events,
            GameEvent(
                event_type=EventType.SYSTEM,
                title="Narrative regenerated",
                content="Repaired the latest DM response after a retry request.",
            ),
        )
        self._raise_if_cancelled(cancel_token)
        yield self._stage_delta("preparing_narration", StreamStageStatus.ACTIVE, tracker=tracker)
        working_memory = self._load_turn_memory_state(restored_state)
        memory_context, scene_messages, _ = self._memory_context_for_narrator(
            restored_state,
            player_input=checkpoint.player_input,
            outcome=outcome,
            working_memory=working_memory,
        )
        yield self._stage_delta("preparing_narration", StreamStageStatus.DONE, tracker=tracker)
        yield self._stage_delta("streaming_narration", StreamStageStatus.ACTIVE, tracker=tracker)
        narration = yield from self._iter_stream_narrative(
            restored_state,
            outcome,
            checkpoint.player_input,
            execution_context=checkpoint.execution_context,
            memory_context=memory_context,
            scene_messages=scene_messages,
            cancel_token=cancel_token,
        )
        yield self._stage_delta("streaming_narration", StreamStageStatus.DONE, tracker=tracker)
        revealed_npc_ids = self._disclose_npcs_from_text(restored_state, narration.content)
        if revealed_npc_ids:
            merged_npcs = self._merged_npc_ids(outcome, revealed_npc_ids)
            outcome.referenced_npc_ids = merged_npcs
            outcome.referenced_npc_id = merged_npcs[0] if merged_npcs else None
        yield self._stage_delta("reconciling_continuity", StreamStageStatus.ACTIVE, tracker=tracker)
        working_memory = self._apply_post_narration_continuity_for_turn(
            restored_state,
            player_input=checkpoint.player_input,
            outcome=outcome,
            execution_context=checkpoint.execution_context,
            narrative_text=narration.content,
            cancel_token=cancel_token,
            working_memory=working_memory,
        )
        yield self._stage_delta("reconciling_continuity", StreamStageStatus.DONE, tracker=tracker)
        self._queue_event(
            restored_state,
            queued_events,
            GameEvent(
                event_type=EventType.NARRATIVE,
                title="Narrative response",
                content=narration.content,
                thinking=narration.thinking,
                oracle_outcome_id=outcome.id,
                stage_timings=tracker.snapshot(),
            ),
        )
        self._persist_streamed_state(
            restored_state,
            queued_events,
            cancel_token=cancel_token,
            committed_turn=CommittedTurnMemory(
                player_input=checkpoint.player_input,
                outcome=outcome,
                narrative_text=narration.content,
                execution_context=checkpoint.execution_context or "",
            ),
        )
        return restored_state

    def _execute_turn_plan(  # noqa: PLR0912, PLR0915, C901
        self,
        state: GameState,
        plan: TurnPlan,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> ExecutedTurn:
        step_summaries: list[str] = []
        primary_outcome: OracleOutcome | None = None
        oracle_title: str | None = None

        for op in plan.ops:
            if op.kind == PlannedTurnOpKind.INSPECT_INVENTORY:
                step_summaries.append(self._inspect_inventory_summary(state))
                continue

            if op.kind == PlannedTurnOpKind.SEARCH_SCENE:
                step_summaries.append(self._search_scene_summary(op.text))
                continue

            if op.kind == PlannedTurnOpKind.ACQUIRE_ITEM:
                actor = self._character_for_actor_name(state, op.actor_name)
                step_summaries.append(
                    self._cairn.acquire_items(
                        state,
                        text=op.text,
                        actor_id=None if actor.is_player else actor.id,
                        cancel_token=cancel_token,
                    ),
                )
                continue

            if op.kind == PlannedTurnOpKind.USE_ITEM and op.item_name is not None:
                actor = self._character_for_actor_name(state, op.actor_name)
                item_id = self._require_item_id_from_name(actor.sheet, op.item_name)
                item_outcome = self._cairn.use_item(
                    state,
                    item_id=item_id,
                    intent=op.text,
                    actor_id=None if actor.is_player else actor.id,
                )
                if primary_outcome is None:
                    primary_outcome = item_outcome
                    oracle_title = "Item use"
                step_summaries.append(item_outcome.summary)
                continue

            if op.kind == PlannedTurnOpKind.DROP_ITEM and op.item_name is not None:
                actor = self._character_for_actor_name(state, op.actor_name)
                item_id = self._require_item_id_from_name(actor.sheet, op.item_name)
                step_summaries.append(
                    self._cairn.drop_item(
                        state,
                        item_id=item_id,
                        actor_id=None if actor.is_player else actor.id,
                    ),
                )
                continue

            if op.kind == PlannedTurnOpKind.TRANSFER_ITEM and op.item_name is not None:
                step_summaries.append(
                    self._transfer_item_between_actors(
                        state,
                        item_name=op.item_name,
                        source_actor_name=op.source_actor_name,
                        target_actor_name=op.target_actor_name,
                    ),
                )
                continue

            if op.kind == PlannedTurnOpKind.RECRUIT_NPC and op.npc_name is not None:
                step_summaries.append(
                    self._recruit_npc_to_party(
                        state,
                        npc_name=op.npc_name,
                        cancel_token=cancel_token,
                    ),
                )
                continue

            if op.kind == PlannedTurnOpKind.EQUIP and op.item_name is not None:
                actor = self._character_for_actor_name(state, op.actor_name)
                item_id = self._require_item_id_from_name(actor.sheet, op.item_name)
                equipped = True if op.equipped is None else op.equipped
                self._cairn.set_item_equipped(
                    state,
                    item_id=item_id,
                    equipped=equipped,
                    actor_id=None if actor.is_player else actor.id,
                )
                actor_context = "" if actor.is_player else f" for {actor.name}"
                step_summaries.append(
                    f"Equipment updated{actor_context}: {op.item_name} "
                    f"{'equipped' if equipped else 'unequipped'}.",
                )
                continue

            if op.kind == PlannedTurnOpKind.YES_NO:
                likelihood = op.likelihood or Likelihood.EVEN
                primary_outcome = self._oracle.ask_yes_no(state, op.text, likelihood)
                oracle_title = "Oracle answer"
                step_summaries.append(f"Oracle resolved: {primary_outcome.summary}")
                continue

            if op.kind == PlannedTurnOpKind.RANDOM_EVENT:
                primary_outcome = self._oracle.generate_random_event(state)
                oracle_title = "Random event"
                step_summaries.append(f"Oracle resolved: {primary_outcome.summary}")
                continue

            if op.kind == PlannedTurnOpKind.SCENE_CHECK:
                primary_outcome = self._oracle.check_scene(state, op.text)
                if primary_outcome.scene_status is not None:
                    self._apply_scene_transition(state, op.text, primary_outcome.scene_status)
                oracle_title = "Scene check"
                step_summaries.append(f"Scene resolved: {primary_outcome.summary}")
                continue

            if op.kind == PlannedTurnOpKind.SAVE and op.ability is not None:
                actor = self._character_for_actor_name(state, op.actor_name)
                primary_outcome = self._cairn.resolve_save(
                    state,
                    op.ability,
                    op.text,
                    actor_id=None if actor.is_player else actor.id,
                )
                oracle_title = "Cairn save"
                step_summaries.append(f"Save resolved: {primary_outcome.summary}")
                continue

            if op.kind == PlannedTurnOpKind.ATTACK and op.target_name is not None:
                actor = self._character_for_actor_name(state, op.actor_name)
                primary_outcome = self._cairn.resolve_attack(
                    state,
                    target_name=op.target_name,
                    target_armor=0,
                    weapon_item_id=self._item_id_from_name(actor.sheet, op.item_name),
                    stance=op.stance or AttackStance.NORMAL,
                    actor_id=None if actor.is_player else actor.id,
                    cancel_token=cancel_token,
                )
                oracle_title = "Attack resolution"
                step_summaries.append(f"Attack resolved: {primary_outcome.summary}")
                continue

            if op.kind == PlannedTurnOpKind.HARM:
                actor = self._character_for_actor_name(state, op.actor_name)
                primary_outcome = self._cairn.suffer_harm(
                    state,
                    amount=op.harm_amount or 1,
                    source=op.harm_source or op.text,
                    in_combat=op.in_combat if op.in_combat is not None else True,
                    armor_applies=(op.armor_applies if op.armor_applies is not None else True),
                    actor_id=None if actor.is_player else actor.id,
                )
                oracle_title = "Harm resolution"
                step_summaries.append(f"Harm resolved: {primary_outcome.summary}")
                continue

            if op.kind == PlannedTurnOpKind.ENEMY_OPENER:
                primary_outcome = self._cairn.resolve_enemy_opener(
                    state,
                    source=op.harm_source or op.target_name or op.text,
                    text=op.text,
                    cancel_token=cancel_token,
                )
                oracle_title = "Ambush resolution"
                step_summaries.append(f"Ambush resolved: {primary_outcome.summary}")
                continue

            if op.kind == PlannedTurnOpKind.RECOVERY and op.rest_kind is not None:
                actor = self._character_for_actor_name(state, op.actor_name)
                primary_outcome = self._cairn.recover(
                    state,
                    op.rest_kind,
                    actor_id=None if actor.is_player else actor.id,
                )
                oracle_title = "Recovery"
                step_summaries.append(f"Recovery resolved: {primary_outcome.summary}")
                continue

            if op.kind == PlannedTurnOpKind.RETREAT:
                primary_outcome = self._cairn.resolve_retreat(state, op.text)
                oracle_title = "Retreat resolution"
                step_summaries.append(f"Retreat resolved: {primary_outcome.summary}")
                continue

        if primary_outcome is None:
            summary = self._player_action_plan_summary(step_summaries)
            primary_outcome = OracleOutcome(
                kind=OracleKind.PLAYER_ACTION,
                summary=summary,
                chaos_factor=state.chaos_factor,
            )
        execution_context = self._format_execution_context(step_summaries)
        return ExecutedTurn(
            outcome=primary_outcome,
            oracle_title=oracle_title,
            execution_context=execution_context,
            pre_narration_continuity=self._plan_needs_pre_narration_continuity(plan),
        )

    def _plan_needs_pre_narration_continuity(self, plan: TurnPlan) -> bool:
        # Pure narration plans have not resolved any durable fact yet. Running
        # the expensive thread/NPC updater before the narrator answers only
        # makes the turn slower; newly narrated canon is captured after prose
        # by the normal committed-turn memory path.
        return any(op.kind is not PlannedTurnOpKind.NARRATE for op in plan.ops)

    def _inspect_inventory_summary(self, state: GameState) -> str:
        inventory = state.character.inventory
        names = ", ".join(item.name for item in inventory) if inventory else "nothing"
        return (
            f"Checked carried gear ({state.character.cairn.slots_used}/"
            f"{state.character.cairn.slots_total} slots): {names}."
        )

    def _transfer_item_between_actors(
        self,
        state: GameState,
        *,
        item_name: str,
        source_actor_name: str | None,
        target_actor_name: str | None,
    ) -> str:
        source = self._character_for_actor_name(state, source_actor_name)
        target = self._character_for_actor_name(state, target_actor_name)
        if source.id == target.id:
            message = "Cannot transfer an item to the same actor."
            raise ValueError(message)
        item_id = self._require_item_id_from_name(source.sheet, item_name)
        item = next(
            (candidate for candidate in source.sheet.inventory if candidate.id == item_id),
            None,
        )
        if item is None:
            message = f"Unknown inventory item: {item_name}"
            raise ValueError(message)
        source.sheet.inventory = [
            candidate for candidate in source.sheet.inventory if candidate.id != item_id
        ]
        if item.cairn.equipped:
            item.cairn.equipped = False
        target.sheet.inventory.append(item)
        self._recompute_party_burden(source.sheet, target.sheet)
        return f"Transferred {item.name} from {source.name} to {target.name}."

    def _recruit_npc_to_party(
        self,
        state: GameState,
        *,
        npc_name: str,
        cancel_token: CancellationToken | None,
    ) -> str:
        npc = self._require_visible_npc_by_name(state, npc_name)
        if any(member.npc_id == npc.id and member.active for member in state.party_members):
            message = f"{npc.display_label()} is already in the party."
            raise ValueError(message)
        authored = CharacterSheet(
            name=npc.display_label(),
            archetype=npc.role or "Companion",
            epithet=npc.disposition,
            backstory=(
                f"{npc.display_label()} was recruited from the current NPC roster. "
                f"Role: {npc.role or 'unknown'}. Disposition: {npc.disposition}."
            ),
            drive="Survive with the party and honor the terms of recruitment.",
            flaw="Has loyalties and limits beyond the player character's control.",
            condition="Able to travel.",
        )
        sheet = self._cairn.backfill_companion_sheet(
            state,
            authored,
            cancel_token=cancel_token,
        )
        member = PartyMember(
            sheet=sheet,
            npc_id=npc.id,
            loyalty=npc.disposition,
            notes=f"Recruited from visible NPC roster entry {npc.id}.",
        )
        state.party_members.append(member)
        npc.status = NPCStatus.RETIRED
        return f"Recruited {member.display_label()} into the party."

    def _require_visible_npc_by_name(self, state: GameState, npc_name: str) -> NPC:
        cleaned = npc_name.strip().lower()
        for npc in state.npcs:
            label = npc.display_label()
            candidates = {npc.id.lower(), npc.name.lower(), label.lower()}
            if cleaned in candidates or cleaned in label.lower() or label.lower() in cleaned:
                if npc.status != NPCStatus.ACTIVE:
                    message = f"NPC is not active: {label}"
                    raise ValueError(message)
                return npc
        message = f"Unknown visible NPC: {npc_name}"
        raise ValueError(message)

    def _character_for_actor_name(
        self,
        state: GameState,
        actor_name: str | None,
    ) -> ServiceActor:
        cleaned = (actor_name or "").strip().lower()
        if (
            not cleaned
            or cleaned in PLAYER_ACTOR_ALIASES
            or cleaned == state.character.name.lower()
        ):
            return ServiceActor(
                id="player",
                name=state.character.name,
                sheet=state.character,
                is_player=True,
            )
        for member in state.party_members:
            label = member.display_label()
            label_lower = label.lower()
            sheet_name = member.sheet.name.lower()
            if cleaned in {member.id.lower(), label_lower, sheet_name}:
                return ServiceActor(
                    id=member.id,
                    name=label,
                    sheet=member.sheet,
                    is_player=False,
                )
            if cleaned in label_lower or label_lower in cleaned:
                return ServiceActor(
                    id=member.id,
                    name=label,
                    sheet=member.sheet,
                    is_player=False,
                )
        message = f"Unknown party actor: {actor_name}"
        raise ValueError(message)

    def _recompute_party_burden(self, *sheets: CharacterSheet) -> None:
        for sheet in sheets:
            cairn = sheet.cairn
            slots_used = cairn.fatigue + sum(item.cairn.slots for item in sheet.inventory)
            cairn.slots_used = slots_used
            cairn.overloaded = slots_used >= cairn.slots_total
            if cairn.overloaded:
                cairn.hp = 0

    def _search_scene_summary(self, step_text: str) -> str:
        return f"Searched the immediate scene carefully: {step_text}."

    def _player_action_plan_summary(self, step_summaries: list[str]) -> str:
        if not step_summaries:
            return "Narrative continuation requested without an oracle roll."
        if len(step_summaries) == 1:
            return step_summaries[0]
        return "Plan executed without an oracle roll: " + " ".join(step_summaries)

    def _format_execution_context(self, step_summaries: list[str]) -> str | None:
        if not step_summaries:
            return None
        return "Executed backend steps:\n" + "\n".join(f"- {summary}" for summary in step_summaries)

    def _commit_oracle_turn(  # noqa: PLR0913
        self,
        *,
        state: GameState,
        player_input: str,
        outcome: OracleOutcome,
        oracle_title: str | None,
        execution_context: str | None = None,
        pre_narration_continuity: bool = True,
        post_narration_continuity: bool = False,
    ) -> None:
        working_memory = self._load_turn_memory_state(state)
        self._stamp_scene_snapshot(state, outcome)
        state.oracle_history.append(outcome)
        working_memory = self._apply_continuity_updates_for_turn(
            state,
            player_input=player_input,
            outcome=outcome,
            execution_context=execution_context,
            pre_narration_continuity=pre_narration_continuity,
        )
        terminal_event = self._auto_end_campaign_if_needed(state, outcome=outcome)
        if oracle_title is not None:
            self._record_event(
                state,
                GameEvent(
                    event_type=EventType.ORACLE,
                    title=oracle_title,
                    content=outcome.summary,
                    oracle_outcome_id=outcome.id,
                ),
            )
        self._store.write_turn_checkpoint(
            turn_id=outcome.id,
            oracle_outcome_id=outcome.id,
            player_input=player_input,
            execution_context=execution_context,
            state=state,
        )
        memory_context, scene_messages, _ = self._memory_context_for_narrator(
            state,
            player_input=player_input,
            outcome=outcome,
            working_memory=working_memory,
        )
        narration = self._generate_narrative(
            state,
            outcome,
            player_input,
            execution_context=execution_context,
            memory_context=memory_context,
            scene_messages=scene_messages,
        )
        self._record_event(
            state,
            GameEvent(
                event_type=EventType.NARRATIVE,
                title="Narrative response",
                content=narration.content,
                thinking=narration.thinking,
                oracle_outcome_id=outcome.id,
            ),
        )
        revealed_npc_ids = self._disclose_npcs_from_text(state, narration.content)
        if revealed_npc_ids:
            merged_npcs = self._merged_npc_ids(outcome, revealed_npc_ids)
            outcome.referenced_npc_ids = merged_npcs
            outcome.referenced_npc_id = merged_npcs[0] if merged_npcs else None
        if post_narration_continuity:
            working_memory = self._apply_post_narration_continuity_for_turn(
                state,
                player_input=player_input,
                outcome=outcome,
                execution_context=execution_context,
                narrative_text=narration.content,
                working_memory=working_memory,
            )
        if terminal_event is not None:
            self._record_event(state, terminal_event)
        self._save_state_commit(
            state,
            create_checkpoint=True,
            committed_turn=CommittedTurnMemory(
                player_input=player_input,
                outcome=outcome,
                narrative_text=narration.content,
                execution_context=execution_context or "",
            ),
        )

    def _stream_oracle_turn(  # noqa: PLR0913
        self,
        *,
        state: GameState,
        player_input: str,
        outcome: OracleOutcome,
        oracle_title: str | None,
        queued_events: list[GameEvent],
        execution_context: str | None = None,
        pre_narration_continuity: bool = True,
        post_narration_continuity: bool = False,
        cancel_token: CancellationToken | None = None,
        tracker: StageTimingTracker | None = None,
    ) -> Generator[CompletionDelta, None, GameState]:
        working_memory = self._load_turn_memory_state(state)
        self._stamp_scene_snapshot(state, outcome)
        state.oracle_history.append(outcome)
        working_memory = yield from self._iter_apply_continuity_updates_for_turn(
            state,
            player_input=player_input,
            outcome=outcome,
            execution_context=execution_context,
            cancel_token=cancel_token,
            working_memory=working_memory,
            tracker=tracker,
            pre_narration_continuity=pre_narration_continuity,
        )
        terminal_event = self._auto_end_campaign_if_needed(state, outcome=outcome)
        if oracle_title is not None:
            self._queue_event(
                state,
                queued_events,
                GameEvent(
                    event_type=EventType.ORACLE,
                    title=oracle_title,
                    content=outcome.summary,
                    oracle_outcome_id=outcome.id,
                ),
            )
        turn_checkpoint = TurnCheckpointRecord(
            turn_id=outcome.id,
            oracle_outcome_id=outcome.id,
            player_input=player_input,
            execution_context=execution_context,
            state=state.model_copy(deep=True),
        )
        self._raise_if_cancelled(cancel_token)
        yield self._stage_delta("preparing_narration", StreamStageStatus.ACTIVE, tracker=tracker)
        memory_context, scene_messages, _ = self._memory_context_for_narrator(
            state,
            player_input=player_input,
            outcome=outcome,
            working_memory=working_memory,
        )
        yield self._stage_delta("preparing_narration", StreamStageStatus.DONE, tracker=tracker)
        yield self._stage_delta("streaming_narration", StreamStageStatus.ACTIVE, tracker=tracker)
        narration = yield from self._iter_stream_narrative(
            state,
            outcome,
            player_input,
            execution_context=execution_context,
            memory_context=memory_context,
            scene_messages=scene_messages,
            cancel_token=cancel_token,
        )
        yield self._stage_delta("streaming_narration", StreamStageStatus.DONE, tracker=tracker)
        revealed_npc_ids = self._disclose_npcs_from_text(state, narration.content)
        if revealed_npc_ids:
            merged_npcs = self._merged_npc_ids(outcome, revealed_npc_ids)
            outcome.referenced_npc_ids = merged_npcs
            outcome.referenced_npc_id = merged_npcs[0] if merged_npcs else None
        if post_narration_continuity:
            yield self._stage_delta(
                "reconciling_continuity",
                StreamStageStatus.ACTIVE,
                tracker=tracker,
            )
            working_memory = self._apply_post_narration_continuity_for_turn(
                state,
                player_input=player_input,
                outcome=outcome,
                execution_context=execution_context,
                narrative_text=narration.content,
                cancel_token=cancel_token,
                working_memory=working_memory,
            )
            yield self._stage_delta(
                "reconciling_continuity",
                StreamStageStatus.DONE,
                tracker=tracker,
            )
        else:
            yield self._stage_delta(
                "reconciling_continuity",
                StreamStageStatus.SKIPPED,
                tracker=tracker,
            )
        # Snapshot after every streamed stage, including post-narration
        # continuity reconciliation, so the persisted narrative event
        # matches the full visible checklist the user saw during the turn.
        timings = tracker.snapshot() if tracker is not None else []
        self._queue_event(
            state,
            queued_events,
            GameEvent(
                event_type=EventType.NARRATIVE,
                title="Narrative response",
                content=narration.content,
                thinking=narration.thinking,
                oracle_outcome_id=outcome.id,
                stage_timings=timings,
            ),
        )
        if terminal_event is not None:
            self._queue_event(state, queued_events, terminal_event)
        self._persist_streamed_state(
            state,
            queued_events,
            turn_checkpoint=turn_checkpoint,
            cancel_token=cancel_token,
            committed_turn=CommittedTurnMemory(
                player_input=player_input,
                outcome=outcome,
                narrative_text=narration.content,
                execution_context=execution_context or "",
            ),
        )
        return state

    def _record_event(self, state: GameState, event: GameEvent) -> None:
        state.action_log.append(event)
        self._store.append_event(event)

    def _queue_event(self, state: GameState, queue: list[GameEvent], event: GameEvent) -> None:
        state.action_log.append(event)
        queue.append(event)

    def _persist_streamed_state(
        self,
        state: GameState,
        events: list[GameEvent],
        *,
        turn_checkpoint: TurnCheckpointRecord | None = None,
        committed_turn: CommittedTurnMemory | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> None:
        self._raise_if_cancelled(cancel_token)
        if turn_checkpoint is not None:
            self._store.write_turn_checkpoint(
                turn_id=turn_checkpoint.turn_id,
                oracle_outcome_id=turn_checkpoint.oracle_outcome_id,
                player_input=turn_checkpoint.player_input,
                execution_context=turn_checkpoint.execution_context,
                state=turn_checkpoint.state,
            )
            self._raise_if_cancelled(cancel_token)
        self._store.append_events(events)
        self._raise_if_cancelled(cancel_token)
        self._save_state_commit(
            state,
            create_checkpoint=True,
            committed_turn=committed_turn,
        )

    def _ensure_active(self, state: GameState) -> None:
        if state.campaign_status == CampaignStatus.ENDED:
            message = self._campaign_end_conflict_message(state)
            raise ValueError(message)
        if state.campaign_status != CampaignStatus.ACTIVE:
            message = "Campaign has not started. Finalize a character and start the campaign."
            raise ValueError(message)

    def _sync_terminal_state_on_load(self, state: GameState) -> bool:
        if (
            state.campaign_status == CampaignStatus.ACTIVE
            and state.character.cairn.dead
        ):
            return self._mark_campaign_ended(state, reason=CampaignEndReason.DEATH)
        return False

    def _audit_visible_npc_name_support(self, state: GameState) -> tuple[str, ...]:
        """Warn when a visible NPC label lacks explicit textual support.

        This is an audit signal for one-time save repair, not an automatic
        demotion rule. The user clarified that backend continuity is allowed to
        know a true name before the player does, and that a name should only be
        player-visible once the fiction explicitly grants it (dialogue, clues,
        divination, etc.). Descriptor-visible figures follow the same rule: the
        player-facing label should be grounded in committed text somewhere. We
        conservatively approximate that by checking whether the visible label
        appears anywhere in the committed current scene or transcript. A miss
        does *not* prove the label is wrong — it may have been granted
        indirectly — so the script reports rather than mutates.
        """
        lowered = self._audit_name_support_text(state).lower()
        return tuple(
            "Visible NPC label lacks explicit text support: "
            f"{npc.display_label()}"
            for npc in state.npcs
            if not self._npc_label_has_text_support(lowered, npc)
        )

    def _audit_name_support_text(self, state: GameState) -> str:
        chunks: list[str] = [
            state.current_scene,
            state.player_notes,
        ]
        if state.campaign_end_summary is not None:
            chunks.append(state.campaign_end_summary)
        chunks.extend(event.content for event in state.action_log)
        chunks.extend(outcome.summary for outcome in state.oracle_history)
        return "\n".join(chunk for chunk in chunks if chunk.strip())

    def _auto_end_campaign_if_needed(
        self,
        state: GameState,
        *,
        outcome: OracleOutcome,
    ) -> GameEvent | None:
        if (
            state.campaign_status != CampaignStatus.ACTIVE
            or not state.character.cairn.dead
        ):
            return None
        summary = (
            self._default_campaign_end_summary(state, reason=CampaignEndReason.DEATH)
            + f" Final turn: {outcome.summary}"
        )
        self._mark_campaign_ended(
            state,
            reason=CampaignEndReason.DEATH,
            summary=summary,
        )
        return self._campaign_end_event(state)

    def _mark_campaign_ended(
        self,
        state: GameState,
        *,
        reason: CampaignEndReason,
        summary: str | None = None,
    ) -> bool:
        normalized_summary = (
            summary.strip()
            if summary is not None and summary.strip() != ""
            else self._default_campaign_end_summary(state, reason=reason)
        )
        changed = False
        if state.campaign_status != CampaignStatus.ENDED:
            state.campaign_status = CampaignStatus.ENDED
            changed = True
        if state.campaign_end_reason != reason:
            state.campaign_end_reason = reason
            changed = True
        if state.campaign_ended_at is None:
            state.campaign_ended_at = utc_now()
            changed = True
        if state.campaign_end_summary != normalized_summary:
            state.campaign_end_summary = normalized_summary
            changed = True
        return changed

    def _default_campaign_end_summary(
        self,
        state: GameState,
        *,
        reason: CampaignEndReason,
    ) -> str:
        name = state.character.name.strip() or "The wanderer"
        if reason == CampaignEndReason.DEATH:
            return f"{name}'s campaign ended in death."
        if reason == CampaignEndReason.RETIREMENT:
            return f"{name} retired from the campaign."
        return f"{name} achieved a final victory."

    def _campaign_end_event(self, state: GameState) -> GameEvent:
        summary = state.campaign_end_summary or "The campaign has ended."
        return GameEvent(
            event_type=EventType.SYSTEM,
            title="Campaign ended",
            content=summary,
        )

    def _campaign_end_conflict_message(self, state: GameState) -> str:
        reason = state.campaign_end_reason
        if reason == CampaignEndReason.DEATH:
            return "Campaign has ended in death. Reset to start a new run."
        if reason == CampaignEndReason.RETIREMENT:
            return "Campaign has ended in retirement. Reset to start a new run."
        if reason == CampaignEndReason.VICTORY:
            return "Campaign has already ended in victory. Reset to start a new run."
        return "Campaign has already ended. Reset to start a new run."

    def _scene_text(self, expected_scene: str, status: SceneStatus) -> str:
        if status == SceneStatus.EXPECTED:
            return expected_scene
        if status == SceneStatus.ALTERED:
            return f"Altered: {expected_scene}"
        return f"Interrupted before: {expected_scene}"

    def _apply_scene_transition(
        self,
        state: GameState,
        expected_scene: str,
        status: SceneStatus,
    ) -> None:
        previous_label = state.current_scene
        previous_status = state.scene_status
        next_label = self._scene_text(expected_scene, status)
        state.scene_status = status
        state.current_scene = next_label
        if (
            _normalize_scene_label(previous_label) != _normalize_scene_label(next_label)
            or previous_status != status
        ):
            state.scene_number += 1

    def _stamp_scene_snapshot(self, state: GameState, outcome: OracleOutcome) -> None:
        outcome.scene_number_snapshot = state.scene_number
        outcome.scene_label_snapshot = state.current_scene
        outcome.scene_status_snapshot = state.scene_status

    def _prompt_scene_messages(
        self,
        scene_messages: list[ConversationMessage],
    ) -> list[dict[str, str]]:
        return [
            {"role": message.role, "content": message.content}
            for message in scene_messages
        ]

    def _generate_narrative(  # noqa: PLR0913
        self,
        state: GameState,
        outcome: OracleOutcome,
        player_input: str,
        *,
        execution_context: str | None = None,
        memory_context: str | None = None,
        scene_messages: list[dict[str, str]] | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> NarrativeResult:
        generate_result = getattr(self._narrative, "generate_result", None)
        if callable(generate_result):
            generated = generate_result(
                state,
                outcome,
                player_input,
                execution_context=execution_context,
                memory_context=memory_context,
                scene_messages=scene_messages,
                cancel_token=cancel_token,
            )
            if isinstance(generated, NarrativeResult):
                return generated
            if isinstance(generated, str):
                return NarrativeResult(content=generated)
        return NarrativeResult(
            content=self._narrative.generate(
                state,
                outcome,
                player_input,
                execution_context=execution_context,
                memory_context=memory_context,
                scene_messages=scene_messages,
                cancel_token=cancel_token,
            ),
        )

    def _iter_stream_narrative(  # noqa: PLR0913
        self,
        state: GameState,
        outcome: OracleOutcome,
        player_input: str,
        *,
        execution_context: str | None = None,
        memory_context: str | None = None,
        scene_messages: list[dict[str, str]] | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, NarrativeResult]:
        iter_stream = getattr(self._narrative, "iter_stream", None)
        if callable(iter_stream):
            streamed = iter_stream(
                state,
                outcome,
                player_input,
                execution_context=execution_context,
                memory_context=memory_context,
                scene_messages=scene_messages,
                cancel_token=cancel_token,
            )
            result = yield from streamed
            if isinstance(result, NarrativeResult):
                return result
            if isinstance(result, str):
                return NarrativeResult(content=result)
        generated = self._generate_narrative(
            state,
            outcome,
            player_input,
            execution_context=execution_context,
            memory_context=memory_context,
            scene_messages=scene_messages,
            cancel_token=cancel_token,
        )
        yield CompletionDelta(content=generated.content, thinking=generated.thinking)
        return generated

    def _plan_turn_and_load_state(
        self,
        text: str,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> tuple[TurnPlan, GameState]:
        with ThreadPoolExecutor(max_workers=2) as executor:
            memory_future = executor.submit(self._store.load_memory_or_none)
            state = self.load_state(cancel_token=cancel_token)
            existing_memory = memory_future.result()
        planner_memory = self._memory_for_state(state, existing_memory=existing_memory)
        planner_context = self._memory.retrieve_for_planner(
            state,
            planner_memory,
            text,
        )
        plan = self._turn_router.plan(
            text,
            memory_context=planner_context.render(),
            scene_messages=self._prompt_scene_messages(planner_context.scene_messages),
            cancel_token=cancel_token,
        )
        self._raise_if_cancelled(cancel_token)
        return plan, state

    def _load_state_and_memory_context_for_explainer(
        self,
        question: str,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> tuple[GameState, str | None]:
        with ThreadPoolExecutor(max_workers=2) as executor:
            memory_future = executor.submit(self._store.load_memory_or_none)
            state = self._load_state_readonly(cancel_token=cancel_token)
            existing_memory = memory_future.result()
        memory = self._memory_for_state(state, existing_memory=existing_memory)
        latest_outcome = state.oracle_history[-1] if state.oracle_history else None
        if latest_outcome is None:
            context = self._memory.retrieve_for_planner(state, memory, question).render()
        else:
            context = self._memory.retrieve_for_narrator(
                state,
                memory,
                question,
                latest_outcome,
            ).render()
        self._raise_if_cancelled(cancel_token)
        return state, (context or None)

    def _memory_context_for_narrator(
        self,
        state: GameState,
        *,
        player_input: str,
        outcome: OracleOutcome,
        working_memory: MemoryState | None = None,
    ) -> tuple[str | None, list[dict[str, str]], MemoryState]:
        memory = self._context_memory_for_state(state, working_memory)
        context = self._memory.retrieve_for_narrator(
            state,
            memory,
            player_input,
            outcome,
        )
        return (
            context.render() or None,
            self._prompt_scene_messages(context.scene_messages),
            memory,
        )

    def _memory_context_for_thread_updater(
        self,
        state: GameState,
        *,
        player_input: str,
        outcome: OracleOutcome,
        working_memory: MemoryState | None = None,
    ) -> tuple[str | None, MemoryState]:
        memory = self._context_memory_for_state(state, working_memory)
        context = self._memory.retrieve_for_thread_updater(
            state,
            memory,
            player_input,
            outcome,
        ).render()
        return (context or None), memory

    def _memory_context_for_npc_updater(
        self,
        state: GameState,
        *,
        player_input: str,
        outcome: OracleOutcome,
        working_memory: MemoryState | None = None,
    ) -> tuple[str | None, MemoryState]:
        memory = self._context_memory_for_state(state, working_memory)
        context = self._memory.retrieve_for_npc_updater(
            state,
            memory,
            player_input,
            outcome,
        ).render()
        return (context or None), memory

    def _load_turn_memory_state(self, state: GameState) -> MemoryState:
        return self._memory_for_state(
            state,
            existing_memory=self._store.load_memory_or_none(),
        )

    def _context_memory_for_state(
        self,
        state: GameState,
        working_memory: MemoryState | None,
    ) -> MemoryState:
        if working_memory is None:
            return self._memory_for_state(state)
        memory = self._memory.sync_from_state(
            state,
            working_memory.model_copy(deep=True),
        )
        if (
            memory.current_scene_turns
            and memory.current_scene_turns[-1].scene_key != memory.current_scene_key
        ):
            memory.current_scene_turns = []
        return memory

    def _apply_continuity_updates_for_turn(  # noqa: PLR0913
        self,
        state: GameState,
        *,
        player_input: str,
        outcome: OracleOutcome,
        execution_context: str | None = None,
        cancel_token: CancellationToken | None = None,
        working_memory: MemoryState | None = None,
        pre_narration_continuity: bool = True,
    ) -> MemoryState:
        if not pre_narration_continuity:
            self._apply_thread_references(outcome, ())
            self._apply_npc_references(state, outcome, ())
            return self._memory_for_state(state, existing_memory=working_memory)
        scope = self._continuity_classifier.classify_update_scope(
            state,
            player_input=player_input,
            outcome=outcome,
            execution_context=execution_context,
            cancel_token=cancel_token,
        )
        memory = self._memory_for_state(state, existing_memory=working_memory)
        touched_thread_ids: tuple[str, ...] = ()
        touched_npc_ids: tuple[str, ...] = ()
        if scope == ContinuityUpdateScope.BOTH:
            thread_context, memory = self._memory_context_for_thread_updater(
                state,
                player_input=player_input,
                outcome=outcome,
                working_memory=memory,
            )
            npc_context, _ = self._memory_context_for_npc_updater(
                state,
                player_input=player_input,
                outcome=outcome,
                working_memory=memory,
            )
            with ThreadPoolExecutor(max_workers=2) as executor:
                thread_future = executor.submit(
                    self._generate_thread_updates_for_turn,
                    state,
                    player_input=player_input,
                    outcome=outcome,
                    execution_context=execution_context,
                    memory_context=thread_context,
                    cancel_token=cancel_token,
                )
                npc_future = executor.submit(
                    self._generate_npc_updates_for_turn,
                    state,
                    player_input=player_input,
                    outcome=outcome,
                    execution_context=execution_context,
                    memory_context=npc_context,
                    cancel_token=cancel_token,
                )
                thread_generated = thread_future.result()
                npc_generated = npc_future.result()
            touched_thread_ids = self._apply_generated_thread_updates(state, thread_generated)
            touched_npc_ids = self._apply_generated_npc_updates(state, npc_generated)
        else:
            if scope.updates_threads():
                thread_context, memory = self._memory_context_for_thread_updater(
                    state,
                    player_input=player_input,
                    outcome=outcome,
                    working_memory=memory,
                )
                touched_thread_ids = self._run_thread_updates_for_turn(
                    state,
                    player_input=player_input,
                    outcome=outcome,
                    execution_context=execution_context,
                    memory_context=thread_context,
                    cancel_token=cancel_token,
                )
                memory = self._memory_for_state(state, existing_memory=memory)
            if scope.updates_npcs():
                npc_context, memory = self._memory_context_for_npc_updater(
                    state,
                    player_input=player_input,
                    outcome=outcome,
                    working_memory=memory,
                )
                touched_npc_ids = self._run_npc_updates_for_turn(
                    state,
                    player_input=player_input,
                    outcome=outcome,
                    execution_context=execution_context,
                    memory_context=npc_context,
                    cancel_token=cancel_token,
                )
                memory = self._memory_for_state(state, existing_memory=memory)
        self._apply_thread_references(outcome, touched_thread_ids)
        self._apply_npc_references(state, outcome, touched_npc_ids)
        return self._memory_for_state(state, existing_memory=memory)

    def _iter_apply_continuity_updates_for_turn(  # noqa: PLR0913
        self,
        state: GameState,
        *,
        player_input: str,
        outcome: OracleOutcome,
        execution_context: str | None = None,
        cancel_token: CancellationToken | None = None,
        working_memory: MemoryState | None = None,
        tracker: StageTimingTracker | None = None,
        pre_narration_continuity: bool = True,
    ) -> Generator[CompletionDelta, None, MemoryState]:
        memory = self._memory_for_state(state, existing_memory=working_memory)
        if not pre_narration_continuity:
            yield self._stage_delta(
                "classifying_continuity",
                StreamStageStatus.SKIPPED,
                tracker=tracker,
            )
            yield self._stage_delta("updating_threads", StreamStageStatus.SKIPPED, tracker=tracker)
            yield self._stage_delta("updating_npcs", StreamStageStatus.SKIPPED, tracker=tracker)
            self._apply_thread_references(outcome, ())
            self._apply_npc_references(state, outcome, ())
            return memory
        yield self._stage_delta("classifying_continuity", StreamStageStatus.ACTIVE, tracker=tracker)
        scope = self._continuity_classifier.classify_update_scope(
            state,
            player_input=player_input,
            outcome=outcome,
            execution_context=execution_context,
            cancel_token=cancel_token,
        )
        yield self._stage_delta("classifying_continuity", StreamStageStatus.DONE, tracker=tracker)
        touched_thread_ids: tuple[str, ...] = ()
        touched_npc_ids: tuple[str, ...] = ()
        if scope == ContinuityUpdateScope.BOTH:
            thread_context, memory = self._memory_context_for_thread_updater(
                state,
                player_input=player_input,
                outcome=outcome,
                working_memory=memory,
            )
            npc_context, _ = self._memory_context_for_npc_updater(
                state,
                player_input=player_input,
                outcome=outcome,
                working_memory=memory,
            )
            yield self._stage_delta("updating_threads", StreamStageStatus.ACTIVE, tracker=tracker)
            yield self._stage_delta("updating_npcs", StreamStageStatus.ACTIVE, tracker=tracker)
            with ThreadPoolExecutor(max_workers=2) as executor:
                thread_future = executor.submit(
                    self._generate_thread_updates_for_turn,
                    state,
                    player_input=player_input,
                    outcome=outcome,
                    execution_context=execution_context,
                    memory_context=thread_context,
                    cancel_token=cancel_token,
                )
                npc_future = executor.submit(
                    self._generate_npc_updates_for_turn,
                    state,
                    player_input=player_input,
                    outcome=outcome,
                    execution_context=execution_context,
                    memory_context=npc_context,
                    cancel_token=cancel_token,
                )
                thread_generated = thread_future.result()
                npc_generated = npc_future.result()
            touched_thread_ids = self._apply_generated_thread_updates(state, thread_generated)
            yield self._stage_delta("updating_threads", StreamStageStatus.DONE, tracker=tracker)
            touched_npc_ids = self._apply_generated_npc_updates(state, npc_generated)
            yield self._stage_delta("updating_npcs", StreamStageStatus.DONE, tracker=tracker)
        else:
            if scope.updates_threads():
                thread_context, memory = self._memory_context_for_thread_updater(
                    state,
                    player_input=player_input,
                    outcome=outcome,
                    working_memory=memory,
                )
                yield self._stage_delta(
                    "updating_threads", StreamStageStatus.ACTIVE, tracker=tracker,
                )
                touched_thread_ids = self._run_thread_updates_for_turn(
                    state,
                    player_input=player_input,
                    outcome=outcome,
                    execution_context=execution_context,
                    memory_context=thread_context,
                    cancel_token=cancel_token,
                )
                yield self._stage_delta(
                    "updating_threads", StreamStageStatus.DONE, tracker=tracker,
                )
                memory = self._memory_for_state(state, existing_memory=memory)
            else:
                yield self._stage_delta(
                    "updating_threads", StreamStageStatus.SKIPPED, tracker=tracker,
                )
            if scope.updates_npcs():
                npc_context, memory = self._memory_context_for_npc_updater(
                    state,
                    player_input=player_input,
                    outcome=outcome,
                    working_memory=memory,
                )
                yield self._stage_delta("updating_npcs", StreamStageStatus.ACTIVE, tracker=tracker)
                touched_npc_ids = self._run_npc_updates_for_turn(
                    state,
                    player_input=player_input,
                    outcome=outcome,
                    execution_context=execution_context,
                    memory_context=npc_context,
                    cancel_token=cancel_token,
                )
                yield self._stage_delta("updating_npcs", StreamStageStatus.DONE, tracker=tracker)
                memory = self._memory_for_state(state, existing_memory=memory)
            else:
                yield self._stage_delta(
                    "updating_npcs", StreamStageStatus.SKIPPED, tracker=tracker,
                )
        self._apply_thread_references(outcome, touched_thread_ids)
        self._apply_npc_references(state, outcome, touched_npc_ids)
        return self._memory_for_state(state, existing_memory=memory)

    def _apply_post_narration_continuity_for_turn(  # noqa: PLR0913
        self,
        state: GameState,
        *,
        player_input: str,
        outcome: OracleOutcome,
        execution_context: str | None,
        narrative_text: str,
        cancel_token: CancellationToken | None = None,
        working_memory: MemoryState | None = None,
    ) -> MemoryState:
        memory = self._memory_for_state(state, existing_memory=working_memory)
        thread_context, memory = self._memory_context_for_thread_updater(
            state,
            player_input=player_input,
            outcome=outcome,
            working_memory=memory,
        )
        npc_context, _ = self._memory_context_for_npc_updater(
            state,
            player_input=player_input,
            outcome=outcome,
            working_memory=memory,
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            thread_future = executor.submit(
                self._generate_thread_updates_for_turn,
                state,
                player_input=player_input,
                outcome=outcome,
                execution_context=execution_context,
                narrative_text=narrative_text,
                memory_context=thread_context,
                cancel_token=cancel_token,
            )
            npc_future = executor.submit(
                self._generate_npc_updates_for_turn,
                state,
                player_input=player_input,
                outcome=outcome,
                execution_context=execution_context,
                narrative_text=narrative_text,
                memory_context=npc_context,
                cancel_token=cancel_token,
            )
            thread_generated = thread_future.result()
            npc_generated = npc_future.result()
        touched_thread_ids = self._apply_generated_thread_updates(state, thread_generated)
        touched_npc_ids = self._apply_generated_npc_updates(state, npc_generated)
        self._apply_thread_references(outcome, touched_thread_ids)
        self._apply_npc_references(state, outcome, touched_npc_ids)
        return self._memory_for_state(state, existing_memory=memory)

    def _run_thread_updates_for_turn(  # noqa: PLR0913
        self,
        state: GameState,
        *,
        player_input: str,
        outcome: OracleOutcome,
        execution_context: str | None = None,
        narrative_text: str | None = None,
        memory_context: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> tuple[str, ...]:
        thread_result = self._thread_updater.update_threads(
            state,
            player_input=player_input,
            outcome=outcome,
            execution_context=execution_context,
            narrative_text=narrative_text,
            memory_context=memory_context,
            cancel_token=cancel_token,
        )
        return thread_result.touched_thread_ids

    def _generate_thread_updates_for_turn(  # noqa: PLR0913
        self,
        state: GameState,
        *,
        player_input: str,
        outcome: OracleOutcome,
        execution_context: str | None = None,
        narrative_text: str | None = None,
        memory_context: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> GeneratedThreadUpdateBatch | None:
        return self._thread_updater.generate_thread_updates(
            state,
            player_input=player_input,
            outcome=outcome,
            execution_context=execution_context,
            narrative_text=narrative_text,
            memory_context=memory_context,
            cancel_token=cancel_token,
        )

    def _apply_generated_thread_updates(
        self,
        state: GameState,
        generated: GeneratedThreadUpdateBatch | None,
    ) -> tuple[str, ...]:
        if generated is None:
            return ()
        result = self._thread_updater.apply_generated_updates(state, generated)
        return result.touched_thread_ids

    def _apply_thread_references(
        self,
        outcome: OracleOutcome,
        touched_thread_ids: tuple[str, ...],
    ) -> None:
        merged = self._merged_thread_ids(outcome, touched_thread_ids)
        outcome.referenced_thread_ids = merged
        outcome.referenced_thread_id = merged[0] if merged else None

    def _run_npc_updates_for_turn(  # noqa: PLR0913
        self,
        state: GameState,
        *,
        player_input: str,
        outcome: OracleOutcome,
        execution_context: str | None = None,
        narrative_text: str | None = None,
        memory_context: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> tuple[str, ...]:
        npc_result = self._npc_updater.update_npcs(
            state,
            player_input=player_input,
            outcome=outcome,
            execution_context=execution_context,
            narrative_text=narrative_text,
            memory_context=memory_context,
            cancel_token=cancel_token,
        )
        return npc_result.touched_npc_ids

    def _generate_npc_updates_for_turn(  # noqa: PLR0913
        self,
        state: GameState,
        *,
        player_input: str,
        outcome: OracleOutcome,
        execution_context: str | None = None,
        narrative_text: str | None = None,
        memory_context: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> GeneratedNPCUpdateBatch | None:
        return self._npc_updater.generate_npc_updates(
            state,
            player_input=player_input,
            outcome=outcome,
            execution_context=execution_context,
            narrative_text=narrative_text,
            memory_context=memory_context,
            cancel_token=cancel_token,
        )

    def _apply_generated_npc_updates(
        self,
        state: GameState,
        generated: GeneratedNPCUpdateBatch | None,
    ) -> tuple[str, ...]:
        if generated is None:
            return ()
        result = self._npc_updater.apply_generated_updates(state, generated)
        return result.touched_npc_ids

    def _apply_npc_references(
        self,
        state: GameState,
        outcome: OracleOutcome,
        touched_npc_ids: tuple[str, ...],
    ) -> None:
        merged = self._visible_npc_ids(
            state,
            self._merged_npc_ids(outcome, touched_npc_ids),
        )
        outcome.referenced_npc_ids = merged
        outcome.referenced_npc_id = merged[0] if merged else None

    def _repair_npc_roster_on_load(
        self,
        state: GameState,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> bool:
        if state.npc_roster_version >= CURRENT_NPC_ROSTER_VERSION:
            return False
        repaired = self._npc_updater.reseed_legacy_roster(
            state,
            memory_context=self._memory_context_for_legacy_npc_repair(state),
            cancel_token=cancel_token,
        )
        state.npcs = [npc.model_copy(deep=True) for npc in repaired.introduced_npcs]
        state.hidden_npcs = [npc.model_copy(deep=True) for npc in repaired.hidden_npcs]
        state.npc_roster_version = CURRENT_NPC_ROSTER_VERSION
        return True

    def _memory_context_for_legacy_npc_repair(self, state: GameState) -> str | None:
        existing_memory = self._store.load_memory_or_none()
        context = self._memory.retrieve_for_planner(
            state,
            self._memory_for_state(state, existing_memory=existing_memory),
            state.current_scene,
        ).render()
        return context or None

    def _disclose_npcs_from_text(
        self,
        state: GameState,
        text: str,
    ) -> tuple[str, ...]:
        lowered = text.lower()
        revealed = [
            npc.id
            for npc in state.npcs
            if self._maybe_promote_visible_npc_label_from_text(npc, lowered)
        ]
        still_hidden = []
        for npc in state.hidden_npcs:
            if self._npc_name_appears_in_text(lowered, npc.name):
                npc.player_label = npc.name
                npc.player_label_kind = NPCPlayerLabelKind.PROPER_NAME
                state.npcs.append(npc)
                revealed.append(npc.id)
            elif (
                npc.player_label_kind == NPCPlayerLabelKind.DESCRIPTOR
                and self._npc_label_appears_in_text(lowered, npc.display_label())
            ):
                state.npcs.append(npc)
                revealed.append(npc.id)
            else:
                still_hidden.append(npc)
        state.hidden_npcs = still_hidden
        return tuple(revealed)

    def _npc_label_has_text_support(self, lowered_text: str, npc: NPC) -> bool:
        return self._npc_label_appears_in_text(lowered_text, npc.display_label())

    def _maybe_promote_visible_npc_label_from_text(
        self,
        npc: NPC,
        lowered_text: str,
    ) -> bool:
        if npc.player_label_kind == NPCPlayerLabelKind.PROPER_NAME:
            return False
        if not self._npc_name_appears_in_text(lowered_text, npc.name):
            return False
        npc.player_label = npc.name
        npc.player_label_kind = NPCPlayerLabelKind.PROPER_NAME
        return True

    def _npc_name_appears_in_text(self, lowered_text: str, npc_name: str) -> bool:
        return self._npc_label_appears_in_text(lowered_text, npc_name)

    def _npc_label_appears_in_text(self, lowered_text: str, label: str) -> bool:
        return " ".join(label.lower().split()) in lowered_text

    def _merged_thread_ids(
        self,
        outcome: OracleOutcome,
        touched_thread_ids: tuple[str, ...],
    ) -> list[str]:
        merged: list[str] = []
        if outcome.referenced_thread_id is not None:
            merged.append(outcome.referenced_thread_id)
        for thread_id in outcome.referenced_thread_ids:
            if thread_id not in merged:
                merged.append(thread_id)
        for thread_id in touched_thread_ids:
            if thread_id not in merged:
                merged.append(thread_id)
        return merged

    def _merged_npc_ids(
        self,
        outcome: OracleOutcome,
        touched_npc_ids: tuple[str, ...],
    ) -> list[str]:
        merged: list[str] = []
        if outcome.referenced_npc_id is not None:
            merged.append(outcome.referenced_npc_id)
        for npc_id in outcome.referenced_npc_ids:
            if npc_id not in merged:
                merged.append(npc_id)
        for npc_id in touched_npc_ids:
            if npc_id not in merged:
                merged.append(npc_id)
        return merged

    def _visible_npc_ids(self, state: GameState, npc_ids: list[str]) -> list[str]:
        visible_ids = {npc.id for npc in state.npcs}
        return [npc_id for npc_id in npc_ids if npc_id in visible_ids]

    def _save_state_commit(
        self,
        state: GameState,
        *,
        create_checkpoint: bool,
        committed_turn: CommittedTurnMemory | None = None,
    ) -> None:
        del committed_turn
        self._store.save(state, create_checkpoint=create_checkpoint)
        self._store.save_memory(self._memory_for_state(state, force_rebuild=True))

    def _ensure_current_save_schema(self, state: GameState) -> bool:
        """Persist newly-added schema defaults during explicit backfill.

        Pydantic fills missing fields (for example item `power` objects and
        `party_members`) while loading old saves, but that alone does not rewrite
        the JSON file. The explicit backfill command should therefore compare the
        original parsed payload to the current model dump and mark the state dirty
        when the on-disk shape lacks fields that now have canonical defaults.
        """
        if not self._store.exists():
            return False

        before: JSONValue = json.loads(self._store.state_path.read_text(encoding="utf-8"))
        after = state.model_dump(mode="json")
        return before != after

    def _memory_for_state(
        self,
        state: GameState,
        *,
        existing_memory: MemoryState | None = None,
        force_rebuild: bool = False,
    ) -> MemoryState:
        memory = self._store.load_memory_or_none() if existing_memory is None else existing_memory
        if force_rebuild or self._memory_needs_rebuild(state, memory):
            return self._memory.bootstrap_from_turns(state, self._committed_turns_for_state(state))
        return self._memory.sync_from_state(state, memory)

    def _memory_needs_rebuild(self, state: GameState, memory: MemoryState | None) -> bool:
        if memory is None:
            return True
        return (
            memory.state_id != state.id
            or memory.turn_count != len(state.oracle_history)
            or memory.schema_version != CURRENT_MEMORY_SCHEMA_VERSION
        )

    def _committed_turns_for_state(self, state: GameState) -> list[CommittedTurnMemory]:
        player_events = [
            event for event in state.action_log if event.event_type == EventType.PLAYER
        ]
        player_event_index = 0
        latest_narrative_by_outcome_id = {
            event.oracle_outcome_id: event
            for event in state.action_log
            if event.event_type == EventType.NARRATIVE and event.oracle_outcome_id is not None
        }
        turns: list[CommittedTurnMemory] = []
        for outcome in state.oracle_history:
            checkpoint = self._store.load_turn_checkpoint_or_none(outcome.id)
            if checkpoint is not None:
                player_input = checkpoint.player_input
                execution_context = checkpoint.execution_context or ""
            else:
                player_input = (
                    player_events[player_event_index].content
                    if player_event_index < len(player_events)
                    else outcome.summary
                )
                execution_context = ""
            if player_event_index < len(player_events):
                player_event = player_events[player_event_index]
                if player_event.content == player_input:
                    player_event_index += 1
            narrative = latest_narrative_by_outcome_id.get(outcome.id)
            turns.append(
                CommittedTurnMemory(
                    player_input=player_input,
                    outcome=outcome,
                    narrative_text="" if narrative is None else narrative.content,
                    execution_context=execution_context,
                ),
            )
        return turns

    def _iter_turn_stage_bootstrap(
        self,
        *,
        skipped_stage_ids: set[str] | None = None,
        tracker: StageTimingTracker | None = None,
    ) -> Generator[CompletionDelta, None, None]:
        skipped = skipped_stage_ids or set()
        for stage_id in TURN_STREAM_STAGE_ORDER:
            status = (
                StreamStageStatus.SKIPPED
                if stage_id in skipped
                else StreamStageStatus.PENDING
            )
            yield self._stage_delta(stage_id, status, tracker=tracker)

    def _stage_delta(
        self,
        stage_id: str,
        status: StreamStageStatus,
        *,
        tracker: StageTimingTracker | None = None,
    ) -> CompletionDelta:
        label = TURN_STREAM_STAGE_LABELS[stage_id]
        if tracker is not None:
            tracker.record(stage_id, label, status)
        return CompletionDelta(
            stage=StreamStageUpdate(
                stage_id=stage_id,
                label=label,
                status=status,
            ),
        )

    def _raise_if_cancelled(self, cancel_token: CancellationToken | None) -> None:
        if cancel_token is not None:
            cancel_token.raise_if_cancelled()

    def _item_id_from_name(self, character: CharacterSheet, item_name: str | None) -> str | None:
        # We tolerate partial item names because the LLM-backed turn router
        # routinely shortens fuller names ("notched cudgel" for "Notched iron
        # cudgel"). Exact match wins; otherwise we score by overlapping word
        # tokens (ignoring tiny stop-token-ish words) and pick the best
        # candidate that shares at least one token.
        if item_name is None:
            return None
        cleaned = item_name.strip().lower()
        if not cleaned:
            return None
        min_token_length = 3
        cleaned_tokens = {token for token in cleaned.split() if len(token) >= min_token_length}
        best_id: str | None = None
        best_score = 0
        for item in character.inventory:
            name = item.name.lower()
            if cleaned == name or cleaned in name or name in cleaned:
                return item.id
            name_tokens = {token for token in name.split() if len(token) >= min_token_length}
            if not cleaned_tokens or not name_tokens:
                continue
            overlap = len(cleaned_tokens & name_tokens)
            if overlap > best_score:
                best_score = overlap
                best_id = item.id
        return best_id

    def _require_item_id_from_name(self, character: CharacterSheet, item_name: str) -> str:
        item_id = self._item_id_from_name(character, item_name)
        if item_id is not None:
            return item_id
        message = f"Unknown inventory item: {item_name}"
        raise ValueError(message)


def _normalize_scene_label(text: str) -> str:
    normalized = text.strip().lower()
    if normalized.startswith("altered:"):
        return normalized.removeprefix("altered:").strip()
    if normalized.startswith("interrupted before:"):
        return normalized.removeprefix("interrupted before:").strip()
    return normalized
