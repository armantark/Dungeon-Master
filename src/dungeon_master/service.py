from __future__ import annotations

import json
from collections.abc import Generator, Mapping
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol

from dungeon_master.application import turn_commit
from dungeon_master.application.campaign_lifecycle import CampaignLifecycleMixin
from dungeon_master.application.continuity import (
    ContinuityReconciler,
    NarratedTurn,
)
from dungeon_master.application.continuity import (
    NPCUpdater as ContinuityNPCUpdaterPort,
)
from dungeon_master.application.continuity import (
    ThreadUpdater as ThreadUpdaterPort,
)
from dungeon_master.application.direct_commands import DirectCommandsMixin
from dungeon_master.application.service_maintenance import ServiceMaintenanceMixin
from dungeon_master.application.service_models import (
    CURRENT_NPC_ROSTER_VERSION,
    SaveBackfillReport,
)
from dungeon_master.application.stage_timing import (
    TURN_STREAM_STAGE_LABELS,
    TURN_STREAM_STAGE_ORDER,
    StageTimingTracker,
)
from dungeon_master.application.turn_plan_execution import TurnPlanExecutionMixin
from dungeon_master.application.turn_submission import TurnSubmissionMixin
from dungeon_master.cairn import AttackActor, CairnEngine, SurvivalUpdate
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
from dungeon_master.capability_oracle_guard import (
    CapabilityOracleGuard,
    CapabilityOracleGuardResult,
)
from dungeon_master.character_effect_updater import CharacterEffectUpdater
from dungeon_master.config import LLMRuntimeBundle, build_llm_runtime, single_llm_runtime
from dungeon_master.explainer import ExplainerEngine, ExplanationResult
from dungeon_master.inventory_updater import InventoryUpdater
from dungeon_master.memory import (
    CURRENT_MEMORY_SCHEMA_VERSION,
    CommittedTurnMemory,
    ConversationMessage,
    MemoryManager,
    MemoryState,
    active_encounter_line_for_state,
)
from dungeon_master.models import (
    NPC,
    AttackStance,
    CairnAbility,
    CairnRestKind,
    CairnSurvivalAction,
    CairnTimeAdvance,
    CampaignEndReason,
    CampaignSeed,
    CampaignStatus,
    CharacterQuiz,
    CharacterQuizAnswer,
    CharacterSheet,
    EncounterAdvantagePayoff,
    EventType,
    GameEvent,
    GameState,
    JSONValue,
    Likelihood,
    OracleOutcome,
    SceneStatus,
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
from dungeon_master.npc_updater import LegacyNPCRosterRepairResult, NPCUpdater
from dungeon_master.oracle import OracleEngine
from dungeon_master.state_store import StateStore, TurnCheckpointRecord
from dungeon_master.thread_updater import ThreadUpdater
from dungeon_master.turn_router import TurnPlan, TurnRouter

__all__ = ["TURN_STREAM_STAGE_ORDER", "GameService", "NPCUpdaterPort", "SaveBackfillReport"]


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
    def generate(self, character: CharacterSheet, seed: CampaignSeed | None = None) -> GameState:
        raise NotImplementedError

    def generate_result(
        self,
        character: CharacterSheet,
        seed: CampaignSeed | None = None,
    ) -> CampaignWorldResult:
        raise NotImplementedError

    def iter_generate(
        self,
        character: CharacterSheet,
        *,
        seed: CampaignSeed | None = None,
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

    def resolve_coordinated_attack(
        self,
        state: GameState,
        *,
        target_name: str,
        target_armor: int,
        participants: tuple[AttackActor, ...],
        cancel_token: CancellationToken | None = None,
    ) -> OracleOutcome:
        del state, target_name, target_armor, participants, cancel_token
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

    def begin_encounter(
        self,
        state: GameState,
        *,
        target_name: str,
        text: str,
        cancel_token: CancellationToken | None = None,
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

    def advance_survival_clock(
        self,
        state: GameState,
        *,
        time_advance: CairnTimeAdvance,
        actions: tuple[CairnSurvivalAction, ...] = (),
        actor_id: str | None = None,
        extra_days: int = 0,
    ) -> SurvivalUpdate:
        raise NotImplementedError

    def resolve_retreat(self, state: GameState, reason: str) -> OracleOutcome:
        raise NotImplementedError

    def setup_advantage(  # noqa: PLR0913
        self,
        state: GameState,
        *,
        target_name: str,
        setup: str,
        payoff: EncounterAdvantagePayoff,
        actor_id: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> OracleOutcome:
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

    def transfer_item(
        self,
        state: GameState,
        *,
        item_id: str,
        source_actor_id: str | None,
        target_actor_id: str | None,
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
    def setup_state(self, seed: CampaignSeed | None = None) -> GameState:
        raise NotImplementedError

    def generate_templates(self, seed: CampaignSeed | None = None) -> list[CharacterSheet]:
        raise NotImplementedError

    def generate_templates_result(
        self,
        seed: CampaignSeed | None = None,
    ) -> CharacterTemplatesResult:
        raise NotImplementedError

    def iter_generate_templates(
        self,
        *,
        seed: CampaignSeed | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, CharacterTemplatesResult]:
        raise NotImplementedError

    def generate_draft(
        self,
        *,
        mode: CharacterDraftMode,
        prompt: str | None,
        template: CharacterSheet | None,
        seed: CampaignSeed | None = None,
    ) -> CharacterSheet:
        raise NotImplementedError

    def generate_draft_result(
        self,
        *,
        mode: CharacterDraftMode,
        prompt: str | None,
        template: CharacterSheet | None,
        seed: CampaignSeed | None = None,
    ) -> CharacterDraftResult:
        raise NotImplementedError

    def iter_generate_draft(
        self,
        *,
        mode: CharacterDraftMode,
        prompt: str | None,
        template: CharacterSheet | None,
        seed: CampaignSeed | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, CharacterDraftResult]:
        raise NotImplementedError

    def generate_quiz(self, concept: str, seed: CampaignSeed | None = None) -> CharacterQuiz:
        raise NotImplementedError

    def generate_quiz_result(
        self,
        concept: str,
        seed: CampaignSeed | None = None,
    ) -> CharacterQuizResult:
        raise NotImplementedError

    def iter_generate_quiz(
        self,
        concept: str,
        *,
        seed: CampaignSeed | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, CharacterQuizResult]:
        raise NotImplementedError

    def generate_quizzed_draft(
        self,
        *,
        concept: str,
        answers: list[CharacterQuizAnswer],
        final_note: str | None,
        seed: CampaignSeed | None = None,
    ) -> CharacterSheet:
        raise NotImplementedError

    def generate_quizzed_draft_result(
        self,
        *,
        concept: str,
        answers: list[CharacterQuizAnswer],
        final_note: str | None,
        seed: CampaignSeed | None = None,
    ) -> CharacterDraftResult:
        raise NotImplementedError

    def iter_generate_quizzed_draft(
        self,
        *,
        concept: str,
        answers: list[CharacterQuizAnswer],
        final_note: str | None,
        seed: CampaignSeed | None = None,
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


class NPCUpdaterPort(ContinuityNPCUpdaterPort, Protocol):
    def reseed_legacy_roster(
        self,
        state: GameState,
        *,
        memory_context: str | None = None,
        cancel_token: CancellationToken | None = None,
        use_model: bool = False,
    ) -> LegacyNPCRosterRepairResult:
        raise NotImplementedError


class CapabilityOracleGuardPort(Protocol):
    def guard_yes_no(
        self,
        state: GameState,
        *,
        question: str,
        requested_likelihood: Likelihood,
        cancel_token: CancellationToken | None = None,
    ) -> CapabilityOracleGuardResult:
        raise NotImplementedError


class GameService(
    ServiceMaintenanceMixin,
    CampaignLifecycleMixin,
    DirectCommandsMixin,
    TurnSubmissionMixin,
    TurnPlanExecutionMixin,
):
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
        character_effect_updater: turn_commit.CharacterEffectUpdater | None = None,
        inventory_updater: turn_commit.InventoryUpdater | None = None,
        capability_oracle_guard: CapabilityOracleGuardPort | None = None,
        llm_runtime: LLMRuntimeBundle | None = None,
    ) -> None:
        self._store = store
        self._oracle = oracle or OracleEngine()
        resolved_runtime = llm_runtime or self._default_llm_runtime(narrative)
        self._llm_runtime = resolved_runtime
        self._narrative = narrative or NarrativeEngine(config=resolved_runtime.narration)
        self._campaign_generator = campaign_generator or CampaignGenerator(
            config=resolved_runtime.reasoning,
        )
        self._character_generator = character_generator or CharacterGenerator(
            config=resolved_runtime.reasoning,
        )
        self._explainer = explainer or ExplainerEngine(config=resolved_runtime.narration)
        self._cairn = cairn_engine or CairnEngine(config=resolved_runtime.reasoning)
        self._turn_router = turn_router or TurnRouter(config=resolved_runtime.structured)
        self._memory = memory_manager or MemoryManager()
        self._thread_updater = thread_updater or ThreadUpdater(config=resolved_runtime.structured)
        self._npc_updater = npc_updater or NPCUpdater(config=resolved_runtime.structured)
        self._character_effect_updater = character_effect_updater or CharacterEffectUpdater(
            config=resolved_runtime.structured,
        )
        self._inventory_updater = inventory_updater or InventoryUpdater(
            cairn=self._cairn,
            config=resolved_runtime.structured,
        )
        self._continuity_reconciler = ContinuityReconciler(
            thread_updater=self._thread_updater,
            npc_updater=self._npc_updater,
        )
        self._turn_committer = turn_commit.TurnCommitter(
            memory_manager=self._memory,
            context_memory_for_state=self._context_memory_for_state,
            continuity_reconciler=self._continuity_reconciler,
            character_effect_updater=self._character_effect_updater,
            inventory_updater=self._inventory_updater,
        )
        self._capability_oracle_guard = capability_oracle_guard or CapabilityOracleGuard(
            config=resolved_runtime.structured,
        )

    def _default_llm_runtime(self, narrative: NarrativePort | None) -> LLMRuntimeBundle:
        inherited_config = getattr(narrative, "_config", None)
        if isinstance(inherited_config, NarrativeConfig):
            return single_llm_runtime(inherited_config)
        return build_llm_runtime()

    def apply_llm_runtime(self, runtime: LLMRuntimeBundle) -> None:
        """Replace the model-backed collaborators for a new runtime preset.

        The store/oracle/memory manager remain stable; only components that talk
        to LiteLLM are rebuilt from the new runtime bundle. This keeps preset
        changes app-global without having to recreate the whole service object or
        disturb the bound save slot.
        """
        self._llm_runtime = runtime
        self._narrative = NarrativeEngine(config=runtime.narration)
        self._campaign_generator = CampaignGenerator(config=runtime.reasoning)
        self._character_generator = CharacterGenerator(config=runtime.reasoning)
        self._explainer = ExplainerEngine(config=runtime.narration)
        self._cairn = CairnEngine(config=runtime.reasoning)
        self._turn_router = TurnRouter(config=runtime.structured)
        self._thread_updater = ThreadUpdater(config=runtime.structured)
        self._npc_updater = NPCUpdater(config=runtime.structured)
        self._character_effect_updater = CharacterEffectUpdater(config=runtime.structured)
        self._inventory_updater = InventoryUpdater(cairn=self._cairn, config=runtime.structured)
        self._continuity_reconciler = ContinuityReconciler(
            thread_updater=self._thread_updater,
            npc_updater=self._npc_updater,
        )
        self._turn_committer = turn_commit.TurnCommitter(
            memory_manager=self._memory,
            context_memory_for_state=self._context_memory_for_state,
            continuity_reconciler=self._continuity_reconciler,
            character_effect_updater=self._character_effect_updater,
            inventory_updater=self._inventory_updater,
        )
        self._capability_oracle_guard = CapabilityOracleGuard(config=runtime.structured)

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

    def _commit_oracle_turn(
        self,
        *,
        state: GameState,
        player_input: str,
        outcome: OracleOutcome,
        oracle_title: str | None,
        execution_context: str | None = None,
    ) -> None:
        working_memory = self._load_turn_memory_state(state)
        self._stamp_scene_snapshot(state, outcome)
        state.oracle_history.append(outcome)
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
            force_rebuild=True,
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
        committed_turn = self._turn_committer.apply(
            state,
            NarratedTurn(
                player_input=player_input,
                outcome=outcome,
                execution_context=execution_context,
                narrative_text=narration.content,
            ),
            working_memory=working_memory,
        )
        if terminal_event is not None:
            self._record_event(state, terminal_event)
        self._save_state_commit(
            state,
            create_checkpoint=True,
            committed_turn=committed_turn,
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
        cancel_token: CancellationToken | None = None,
        tracker: StageTimingTracker | None = None,
    ) -> Generator[CompletionDelta, None, GameState]:
        working_memory = self._load_turn_memory_state(state)
        self._stamp_scene_snapshot(state, outcome)
        state.oracle_history.append(outcome)
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
            checkpoint_overrides={outcome.id: turn_checkpoint},
            force_rebuild=True,
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
        yield self._stage_delta(
            "reconciling_continuity",
            StreamStageStatus.ACTIVE,
            tracker=tracker,
        )
        committed_turn = self._turn_committer.apply(
            state,
            NarratedTurn(
                player_input=player_input,
                outcome=outcome,
                execution_context=execution_context,
                narrative_text=narration.content,
            ),
            cancel_token=cancel_token,
            working_memory=working_memory,
        )
        yield self._stage_delta(
            "reconciling_continuity",
            StreamStageStatus.DONE,
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
            committed_turn=committed_turn,
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
        if state.campaign_status == CampaignStatus.ACTIVE and state.character.cairn.dead:
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
            f"Visible NPC label lacks explicit text support: {npc.display_label()}"
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
        if state.campaign_status != CampaignStatus.ACTIVE or not state.character.cairn.dead:
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
        return [{"role": message.role, "content": message.content} for message in scene_messages]

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
        encounter_hint = active_encounter_line_for_state(state)
        plan = self._turn_router.plan(
            text,
            memory_context=planner_context.render(),
            scene_messages=self._prompt_scene_messages(planner_context.scene_messages),
            combat_encounter_hint=encounter_hint,
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

    def _memory_context_for_narrator(  # noqa: PLR0913
        self,
        state: GameState,
        *,
        player_input: str,
        outcome: OracleOutcome,
        working_memory: MemoryState | None = None,
        checkpoint_overrides: Mapping[str, TurnCheckpointRecord] | None = None,
        force_rebuild: bool = False,
    ) -> tuple[str | None, list[dict[str, str]], MemoryState]:
        if force_rebuild:
            memory = self._memory_for_state(
                state,
                force_rebuild=True,
                checkpoint_overrides=checkpoint_overrides,
            )
        else:
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

    def _load_turn_memory_state(self, state: GameState) -> MemoryState:
        return self._memory_for_state(
            state,
            existing_memory=self._store.load_memory_or_none(),
        )

    def _preserve_out_of_band_state(
        self,
        *,
        current_state: GameState,
        restored_state: GameState,
    ) -> None:
        # Regenerate should repair only the prose for the latest oracle outcome.
        # Durable OOC steering and campaign notes may have changed after the
        # turn checkpoint was written; keep those newer edits instead of
        # silently rolling them back with the restored checkpoint snapshot.
        restored_state.directives = current_state.directives.model_copy(deep=True)
        restored_state.setting_notes = current_state.setting_notes
        restored_state.player_notes = current_state.player_notes

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

    def _npc_label_has_text_support(self, lowered_text: str, npc: NPC) -> bool:
        return self._npc_label_appears_in_text(lowered_text, npc.display_label())

    def _npc_label_appears_in_text(self, lowered_text: str, label: str) -> bool:
        return " ".join(label.lower().split()) in lowered_text

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
        checkpoint_overrides: Mapping[str, TurnCheckpointRecord] | None = None,
    ) -> MemoryState:
        if force_rebuild:
            return self._memory.bootstrap_from_turns(
                state,
                self._committed_turns_for_state(
                    state,
                    checkpoint_overrides=checkpoint_overrides,
                ),
            )
        memory = self._store.load_memory_or_none() if existing_memory is None else existing_memory
        if self._memory_needs_rebuild(state, memory):
            return self._memory.bootstrap_from_turns(
                state,
                self._committed_turns_for_state(state),
            )
        return self._memory.sync_from_state(state, memory)

    def _memory_needs_rebuild(self, state: GameState, memory: MemoryState | None) -> bool:
        if memory is None:
            return True
        return (
            memory.state_id != state.id
            or memory.turn_count != len(state.oracle_history)
            or memory.schema_version != CURRENT_MEMORY_SCHEMA_VERSION
        )

    def _committed_turns_for_state(
        self,
        state: GameState,
        *,
        checkpoint_overrides: Mapping[str, TurnCheckpointRecord] | None = None,
    ) -> list[CommittedTurnMemory]:
        player_events = [
            event for event in state.action_log if event.event_type == EventType.PLAYER
        ]
        overrides = {} if checkpoint_overrides is None else checkpoint_overrides
        player_event_index = 0
        latest_narrative_by_outcome_id = {
            event.oracle_outcome_id: event
            for event in state.action_log
            if event.event_type == EventType.NARRATIVE and event.oracle_outcome_id is not None
        }
        turns: list[CommittedTurnMemory] = []
        for outcome in state.oracle_history:
            checkpoint = overrides.get(outcome.id)
            if checkpoint is None:
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
            status = StreamStageStatus.SKIPPED if stage_id in skipped else StreamStageStatus.PENDING
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
