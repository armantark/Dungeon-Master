from __future__ import annotations

import json
from collections.abc import Generator, Mapping
from concurrent.futures import ThreadPoolExecutor

from dungeon_master.application import turn_commit
from dungeon_master.application.continuity import (
    ContinuityReconciler,
    NarratedTurn,
)
from dungeon_master.application.continuity import (
    ThreadUpdater as ThreadUpdaterPort,
)
from dungeon_master.application.service_models import (
    CLARIFICATION_EVENT_TITLE,
    CURRENT_NPC_ROSTER_VERSION,
    ClarificationPrompt,
    ExecutedTurn,
    GuardedYesNoOutcome,
    SaveBackfillReport,
)
from dungeon_master.application.service_ports import (
    CairnPort,
    CampaignPort,
    CapabilityOracleGuardPort,
    CharacterPort,
    ExplainerPort,
    NarrativePort,
    NPCUpdaterPort,
)
from dungeon_master.application.stage_timing import (
    TURN_STREAM_STAGE_LABELS,
    TURN_STREAM_STAGE_ORDER,
    StageTimingTracker,
)
from dungeon_master.application.turn_plan_execution import TurnPlanExecutor
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
from dungeon_master.capability_oracle_guard import (
    CapabilityOracleGuard,
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
    CampaignDirectives,
    CampaignEndReason,
    CampaignSeed,
    CampaignStatus,
    CharacterQuiz,
    CharacterQuizAnswer,
    CharacterSheet,
    EventType,
    GameEvent,
    GameState,
    JSONValue,
    Likelihood,
    OracleKind,
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
from dungeon_master.npc_updater import NPCUpdater
from dungeon_master.oracle import OracleEngine
from dungeon_master.state_store import StateStore, TurnCheckpointRecord
from dungeon_master.thread_updater import ThreadUpdater
from dungeon_master.turn_router import TurnPlan, TurnRouter

__all__ = ["TURN_STREAM_STAGE_ORDER", "GameService", "NPCUpdaterPort", "SaveBackfillReport"]


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
        self._turn_plan_executor = TurnPlanExecutor(
            cairn=self._cairn,
            oracle=self._oracle,
            capability_oracle_guard=self._capability_oracle_guard,
            llm_runtime=self._llm_runtime,
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
        self._turn_plan_executor = TurnPlanExecutor(
            cairn=self._cairn,
            oracle=self._oracle,
            capability_oracle_guard=self._capability_oracle_guard,
            llm_runtime=self._llm_runtime,
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
        party_members_synced = turn_commit.sync_party_members_from_visible_npcs(working)
        schema_defaults_persisted = self._ensure_current_save_schema(working)
        state_changed = (
            character_backfilled
            or npc_roster_repaired
            or terminal_state_synced
            or party_members_synced
            or schema_defaults_persisted
        )

        rebuilt_memory = self._memory_for_state(
            working,
            existing_memory=before_memory,
            force_rebuild=True,
        )
        memory_rebuilt = before_memory is None or rebuilt_memory.model_dump(
            mode="json"
        ) != before_memory.model_dump(mode="json")
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
        changed = (
            self._repair_npc_roster_on_load(
                state,
                cancel_token=cancel_token,
            )
            or changed
        )
        changed = turn_commit.sync_party_members_from_visible_npcs(state) or changed
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
        turn_commit.sync_party_members_from_visible_npcs(state)
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

    def update_campaign_seed(self, seed: CampaignSeed) -> GameState:
        state = self.load_state()
        if state.campaign_status == CampaignStatus.ACTIVE:
            message = "Campaign seed is locked after the campaign starts."
            raise ValueError(message)
        if state.campaign_status == CampaignStatus.ENDED:
            message = self._campaign_end_conflict_message(state)
            raise ValueError(message)
        state.campaign_seed = seed.model_copy(deep=True)
        self._save_state_commit(state, create_checkpoint=True)
        return state

    def list_character_templates(self) -> list[CharacterSheet]:
        state = self.load_state()
        return self._character_generator.generate_templates(seed=state.campaign_seed)

    def list_character_templates_result(self) -> CharacterTemplatesResult:
        state = self.load_state()
        return self._character_generator.generate_templates_result(seed=state.campaign_seed)

    def stream_character_templates(
        self,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, CharacterTemplatesResult]:
        return self._character_generator.iter_generate_templates(
            seed=self.load_state(cancel_token=cancel_token).campaign_seed,
            cancel_token=cancel_token,
        )

    def generate_character_draft(
        self,
        *,
        mode: CharacterDraftMode,
        prompt: str | None,
        template: CharacterSheet | None,
    ) -> CharacterSheet:
        state = self.load_state()
        return self._character_generator.generate_draft(
            mode=mode,
            prompt=prompt,
            template=template,
            seed=state.campaign_seed,
        )

    def generate_character_draft_result(
        self,
        *,
        mode: CharacterDraftMode,
        prompt: str | None,
        template: CharacterSheet | None,
    ) -> CharacterDraftResult:
        state = self.load_state()
        return self._character_generator.generate_draft_result(
            mode=mode,
            prompt=prompt,
            template=template,
            seed=state.campaign_seed,
        )

    def generate_character_quiz(self, concept: str) -> CharacterQuiz:
        state = self.load_state()
        return self._character_generator.generate_quiz(concept, seed=state.campaign_seed)

    def generate_character_quiz_result(self, concept: str) -> CharacterQuizResult:
        state = self.load_state()
        return self._character_generator.generate_quiz_result(
            concept,
            seed=state.campaign_seed,
        )

    def stream_character_quiz(
        self,
        concept: str,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, CharacterQuizResult]:
        state = self.load_state(cancel_token=cancel_token)
        return self._character_generator.iter_generate_quiz(
            concept,
            seed=state.campaign_seed,
            cancel_token=cancel_token,
        )

    def generate_quizzed_character_draft(
        self,
        *,
        concept: str,
        answers: list[CharacterQuizAnswer],
        final_note: str | None,
    ) -> CharacterSheet:
        state = self.load_state()
        return self._character_generator.generate_quizzed_draft(
            concept=concept,
            answers=answers,
            final_note=final_note,
            seed=state.campaign_seed,
        )

    def generate_quizzed_character_draft_result(
        self,
        *,
        concept: str,
        answers: list[CharacterQuizAnswer],
        final_note: str | None,
    ) -> CharacterDraftResult:
        state = self.load_state()
        return self._character_generator.generate_quizzed_draft_result(
            concept=concept,
            answers=answers,
            final_note=final_note,
            seed=state.campaign_seed,
        )

    def stream_quizzed_character_draft(
        self,
        *,
        concept: str,
        answers: list[CharacterQuizAnswer],
        final_note: str | None,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, CharacterDraftResult]:
        state = self.load_state(cancel_token=cancel_token)
        return self._character_generator.iter_generate_quizzed_draft(
            concept=concept,
            answers=answers,
            final_note=final_note,
            seed=state.campaign_seed,
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
        state = self.load_state(cancel_token=cancel_token)
        return self._character_generator.iter_generate_draft(
            mode=mode,
            prompt=prompt,
            template=template,
            seed=state.campaign_seed,
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

        generated = self._campaign_generator.generate_result(
            state.character,
            seed=state.campaign_seed,
        )
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
            seed=state.campaign_seed,
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
        survival_update = self._turn_plan_executor.advance_survival_for_rest(
            state,
            kind=kind,
        )
        outcome = self._cairn.recover(state, kind)
        if survival_update is not None:
            outcome.cairn = self._turn_plan_executor.merge_cairn_resolution(
                outcome.cairn,
                survival_update.resolution,
            )
        self._commit_oracle_turn(
            state=state,
            player_input=f"Recovery: {kind.value}",
            outcome=outcome,
            oracle_title="Recovery",
            execution_context=self._turn_plan_executor.format_execution_context(
                [survival_update.summary] if survival_update is not None else []
            ),
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
        execution_context = self._turn_plan_executor.format_execution_context([summary])
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
        guarded = self._resolve_yes_no_oracle(
            state,
            question=question,
            likelihood=likelihood,
        )
        self._commit_oracle_turn(
            state=state,
            player_input=f"Oracle question: {question}",
            outcome=guarded.outcome,
            oracle_title="Oracle answer",
            execution_context=guarded.execution_context,
        )
        return state

    def preview_oracle(self, question: str, likelihood: Likelihood) -> OracleOutcome:
        state = self._load_state_readonly()
        self._ensure_active(state)
        return self._resolve_yes_no_oracle(
            state,
            question=question,
            likelihood=likelihood,
        ).outcome

    def _resolve_yes_no_oracle(
        self,
        state: GameState,
        *,
        question: str,
        likelihood: Likelihood,
        cancel_token: CancellationToken | None = None,
    ) -> GuardedYesNoOutcome:
        return self._turn_plan_executor.resolve_yes_no(
            state,
            question=question,
            likelihood=likelihood,
            cancel_token=cancel_token,
        )

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
        clarification = self._clarification_prompt_for_plan(plan)
        if clarification is not None:
            self._record_event(
                state,
                GameEvent(
                    event_type=EventType.NARRATIVE,
                    title=CLARIFICATION_EVENT_TITLE,
                    content=clarification.question,
                ),
            )
            self._save_state_commit(state, create_checkpoint=True)
            return state
        executed = self._execute_turn_plan(state, plan)
        self._commit_oracle_turn(
            state=state,
            player_input=text,
            outcome=executed.outcome,
            oracle_title=executed.oracle_title,
            execution_context=executed.execution_context,
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
        self._preserve_out_of_band_state(current_state=state, restored_state=restored_state)

        # Preserve prior repair audit messages for the same turn so repeated
        # regenerate requests leave a visible trace rather than rewriting history.
        prefix_len = len(restored_state.action_log)
        repair_events = [
            event.model_copy(deep=True)
            for event in state.action_log[prefix_len:]
            if event.event_type == EventType.SYSTEM
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
        working_memory = self._memory_for_state(restored_state, force_rebuild=True)
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
        committed_turn = self._turn_committer.apply(
            restored_state,
            NarratedTurn(
                player_input=checkpoint.player_input,
                outcome=outcome,
                execution_context=checkpoint.execution_context,
                narrative_text=narration.content,
            ),
            working_memory=working_memory,
        )
        self._save_state_commit(
            restored_state,
            create_checkpoint=True,
            committed_turn=committed_turn,
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
        clarification = self._clarification_prompt_for_plan(plan)
        if clarification is not None:
            yield self._stage_delta(
                "resolving_mechanics",
                StreamStageStatus.SKIPPED,
                tracker=tracker,
            )
            self._queue_event(
                state,
                queued_events,
                GameEvent(
                    event_type=EventType.NARRATIVE,
                    title=CLARIFICATION_EVENT_TITLE,
                    content=clarification.question,
                    stage_timings=tracker.snapshot(),
                ),
            )
            self._persist_streamed_state(
                state,
                queued_events,
                cancel_token=cancel_token,
                committed_turn=None,
            )
            return state
        self._raise_if_cancelled(cancel_token)
        yield self._stage_delta("resolving_mechanics", StreamStageStatus.ACTIVE, tracker=tracker)
        executed = self._execute_turn_plan(state, plan, cancel_token=cancel_token)
        yield self._stage_delta("resolving_mechanics", StreamStageStatus.DONE, tracker=tracker)
        return (
            yield from self._stream_oracle_turn(
                state=state,
                player_input=text,
                outcome=executed.outcome,
                oracle_title=executed.oracle_title,
                queued_events=queued_events,
                execution_context=executed.execution_context,
                cancel_token=cancel_token,
                tracker=tracker,
            )
        )

    def stream_regenerate_response(
        self,
        narrative_event_id: str,
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
        self._preserve_out_of_band_state(current_state=state, restored_state=restored_state)
        prefix_len = len(restored_state.action_log)
        repair_events = [
            event.model_copy(deep=True)
            for event in state.action_log[prefix_len:]
            if event.event_type == EventType.SYSTEM
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
        working_memory = self._memory_for_state(restored_state, force_rebuild=True)
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
        yield self._stage_delta("reconciling_continuity", StreamStageStatus.ACTIVE, tracker=tracker)
        committed_turn = self._turn_committer.apply(
            restored_state,
            NarratedTurn(
                player_input=checkpoint.player_input,
                outcome=outcome,
                execution_context=checkpoint.execution_context,
                narrative_text=narration.content,
            ),
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
            committed_turn=committed_turn,
        )
        return restored_state

    def _execute_turn_plan(
        self,
        state: GameState,
        plan: TurnPlan,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> ExecutedTurn:
        return self._turn_plan_executor.execute(
            state,
            plan,
            cancel_token=cancel_token,
        )

    def _plan_is_recon_lookup(self, plan: TurnPlan) -> bool:
        return self._turn_plan_executor.is_recon_lookup(plan)

    def _clarification_prompt_for_plan(self, plan: TurnPlan) -> ClarificationPrompt | None:
        return self._turn_plan_executor.clarification_prompt(plan)

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

    def _apply_scene_transition(
        self,
        state: GameState,
        expected_scene: str,
        status: SceneStatus,
    ) -> None:
        self._turn_plan_executor.apply_scene_transition(state, expected_scene, status)

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
        return self._turn_plan_executor.item_id_from_name(character, item_name)

    def _require_item_id_from_name(self, character: CharacterSheet, item_name: str) -> str:
        return self._turn_plan_executor.require_item_id_from_name(character, item_name)
