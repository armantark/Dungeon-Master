from __future__ import annotations

from collections.abc import Generator

from dungeon_master.application import turn_commit
from dungeon_master.application.campaign_workflow import CampaignWorkflow
from dungeon_master.application.cancellation import CancellationToken
from dungeon_master.application.capability_guard import CapabilityOracleGuard
from dungeon_master.application.continuity import ContinuityReconciler
from dungeon_master.application.continuity import ThreadUpdater as ThreadUpdaterPort
from dungeon_master.application.service_models import GuardedYesNoOutcome, SaveBackfillReport
from dungeon_master.application.service_ports import (
    CairnPort,
    CampaignPort,
    CapabilityOracleGuardPort,
    CharacterPort,
    ExplainerPort,
    NarrativePort,
    NPCUpdaterPort,
)
from dungeon_master.application.stage_timing import TURN_STREAM_STAGE_ORDER
from dungeon_master.application.state_management import ApplicationState
from dungeon_master.application.turn_plan_execution import TurnPlanExecutor
from dungeon_master.application.turn_workflow import TurnWorkflow
from dungeon_master.application.updates.character_effects import CharacterEffectUpdater
from dungeon_master.application.updates.inventory import InventoryUpdater
from dungeon_master.application.updates.npcs import NPCUpdater
from dungeon_master.application.updates.threads import ThreadUpdater
from dungeon_master.config import LLMRuntimeBundle, build_llm_runtime, single_llm_runtime
from dungeon_master.domain.models import (
    AttackStance,
    CairnAbility,
    CairnRestKind,
    CampaignDirectives,
    CampaignEndReason,
    CampaignSeed,
    CharacterQuiz,
    CharacterQuizAnswer,
    CharacterSheet,
    EventType,
    GameEvent,
    GameState,
    Likelihood,
    OracleKind,
    OracleOutcome,
    SceneStatus,
)
from dungeon_master.generation import (
    CampaignGenerator,
    CampaignWorldResult,
    CharacterDraftMode,
    CharacterDraftResult,
    CharacterGenerator,
    CharacterQuizResult,
    CharacterTemplatesResult,
)
from dungeon_master.llm.explanation import ExplainerEngine, ExplanationResult
from dungeon_master.llm.narration import CompletionDelta, NarrativeConfig, NarrativeEngine
from dungeon_master.llm.planning import TurnRouter
from dungeon_master.mechanics.engine import CairnEngine
from dungeon_master.mechanics.oracle import OracleEngine
from dungeon_master.memory import CommittedTurnMemory, MemoryManager
from dungeon_master.persistence.state_store import StateStore

__all__ = ["TURN_STREAM_STAGE_ORDER", "GameService", "NPCUpdaterPort", "SaveBackfillReport"]


class GameService:
    """Single application interface used by the HTTP transport."""

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
        self._capability_oracle_guard = capability_oracle_guard or CapabilityOracleGuard(
            config=resolved_runtime.structured,
        )
        self._compose_workflows()

    def _default_llm_runtime(self, narrative: NarrativePort | None) -> LLMRuntimeBundle:
        inherited_config = getattr(narrative, "_config", None)
        if isinstance(inherited_config, NarrativeConfig):
            return single_llm_runtime(inherited_config)
        return build_llm_runtime()

    def _compose_workflows(self) -> None:
        self._state = ApplicationState(
            store=self._store,
            cairn=self._cairn,
            character_generator=self._character_generator,
            npc_updater=self._npc_updater,
            memory_manager=self._memory,
        )
        self._continuity_reconciler = ContinuityReconciler(
            thread_updater=self._thread_updater,
            npc_updater=self._npc_updater,
        )
        self._turn_committer = turn_commit.TurnCommitter(
            memory_manager=self._memory,
            context_memory_for_state=self._state.context_memory_for_state,
            continuity_reconciler=self._continuity_reconciler,
            character_effect_updater=self._character_effect_updater,
            inventory_updater=self._inventory_updater,
        )
        self._turn_plan_executor = TurnPlanExecutor(
            cairn=self._cairn,
            oracle=self._oracle,
            capability_oracle_guard=self._capability_oracle_guard,
            llm_runtime=self._llm_runtime,
        )
        self._campaign_workflow = CampaignWorkflow(
            state=self._state,
            campaign_generator=self._campaign_generator,
            character_generator=self._character_generator,
            cairn=self._cairn,
        )
        self._turn_workflow = TurnWorkflow(
            state=self._state,
            narrative=self._narrative,
            explainer=self._explainer,
            turn_router=self._turn_router,
            memory_manager=self._memory,
            turn_committer=self._turn_committer,
            turn_plan_executor=self._turn_plan_executor,
        )

    def apply_llm_runtime(self, runtime: LLMRuntimeBundle) -> None:
        """Replace model-backed collaborators while preserving store and memory."""
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
        self._capability_oracle_guard = CapabilityOracleGuard(config=runtime.structured)
        self._compose_workflows()

    def bind_store(self, store: StateStore) -> None:
        """Rebind the application to a different active save slot."""
        self._store = store
        self._state.bind_store(store)

    def new_setup_state(self) -> GameState:
        return self._state.new_setup_state()

    def backfill_current_save(
        self,
        *,
        apply: bool,
        create_checkpoint: bool = True,
        cancel_token: CancellationToken | None = None,
    ) -> SaveBackfillReport:
        return self._state.backfill_current_save(
            apply=apply,
            create_checkpoint=create_checkpoint,
            cancel_token=cancel_token,
        )

    def load_state(self, *, cancel_token: CancellationToken | None = None) -> GameState:
        return self._state.load_state(cancel_token=cancel_token)

    def _load_state_readonly(
        self,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> GameState:
        return self._state.load_state_readonly(cancel_token=cancel_token)

    def reset(self) -> GameState:
        return self._campaign_workflow.reset()

    def update_campaign_seed(self, seed: CampaignSeed) -> GameState:
        return self._campaign_workflow.update_campaign_seed(seed)

    def list_character_templates(self) -> list[CharacterSheet]:
        return self._campaign_workflow.list_character_templates()

    def list_character_templates_result(self) -> CharacterTemplatesResult:
        return self._campaign_workflow.list_character_templates_result()

    def stream_character_templates(
        self,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, CharacterTemplatesResult]:
        return self._campaign_workflow.stream_character_templates(cancel_token=cancel_token)

    def generate_character_draft(
        self,
        *,
        mode: CharacterDraftMode,
        prompt: str | None,
        template: CharacterSheet | None,
    ) -> CharacterSheet:
        return self._campaign_workflow.generate_character_draft(
            mode=mode, prompt=prompt, template=template
        )

    def generate_character_draft_result(
        self,
        *,
        mode: CharacterDraftMode,
        prompt: str | None,
        template: CharacterSheet | None,
    ) -> CharacterDraftResult:
        return self._campaign_workflow.generate_character_draft_result(
            mode=mode, prompt=prompt, template=template
        )

    def generate_character_quiz(self, concept: str) -> CharacterQuiz:
        return self._campaign_workflow.generate_character_quiz(concept)

    def generate_character_quiz_result(self, concept: str) -> CharacterQuizResult:
        return self._campaign_workflow.generate_character_quiz_result(concept)

    def stream_character_quiz(
        self,
        concept: str,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, CharacterQuizResult]:
        return self._campaign_workflow.stream_character_quiz(concept, cancel_token=cancel_token)

    def generate_quizzed_character_draft(
        self,
        *,
        concept: str,
        answers: list[CharacterQuizAnswer],
        final_note: str | None,
    ) -> CharacterSheet:
        return self._campaign_workflow.generate_quizzed_character_draft(
            concept=concept, answers=answers, final_note=final_note
        )

    def generate_quizzed_character_draft_result(
        self,
        *,
        concept: str,
        answers: list[CharacterQuizAnswer],
        final_note: str | None,
    ) -> CharacterDraftResult:
        return self._campaign_workflow.generate_quizzed_character_draft_result(
            concept=concept, answers=answers, final_note=final_note
        )

    def stream_quizzed_character_draft(
        self,
        *,
        concept: str,
        answers: list[CharacterQuizAnswer],
        final_note: str | None,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, CharacterDraftResult]:
        return self._campaign_workflow.stream_quizzed_character_draft(
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
        return self._campaign_workflow.stream_character_draft(
            mode=mode,
            prompt=prompt,
            template=template,
            cancel_token=cancel_token,
        )

    def finalize_character(self, character: CharacterSheet) -> GameState:
        return self._campaign_workflow.finalize_character(character)

    def start_campaign(self) -> GameState:
        return self._campaign_workflow.start_campaign()

    def start_campaign_result(self) -> CampaignWorldResult:
        return self._campaign_workflow.start_campaign_result()

    def stream_start_campaign(
        self,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, CampaignWorldResult]:
        return self._campaign_workflow.stream_start_campaign(cancel_token=cancel_token)

    def end_campaign(
        self,
        *,
        reason: CampaignEndReason,
        summary: str | None = None,
    ) -> GameState:
        return self._campaign_workflow.end_campaign(reason=reason, summary=summary)

    def explain(self, question: str) -> ExplanationResult:
        return self._turn_workflow.explain(question)

    def stream_explain(
        self,
        question: str,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, ExplanationResult]:
        return self._turn_workflow.stream_explain(question, cancel_token=cancel_token)

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
        return self._turn_workflow.submit_player_action(action)

    def submit_player_turn(self, text: str) -> GameState:
        return self._turn_workflow.submit_player_turn(text)

    def regenerate_response(self, narrative_event_id: str) -> GameState:
        return self._turn_workflow.regenerate_response(narrative_event_id)

    def stream_submit_player_action(
        self,
        action: str,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, GameState]:
        return (
            yield from self._turn_workflow.stream_submit_player_action(
                action, cancel_token=cancel_token
            )
        )

    def stream_submit_player_turn(
        self,
        text: str,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, GameState]:
        return (
            yield from self._turn_workflow.stream_submit_player_turn(
                text, cancel_token=cancel_token
            )
        )

    def stream_regenerate_response(
        self,
        narrative_event_id: str,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, GameState]:
        return (
            yield from self._turn_workflow.stream_regenerate_response(
                narrative_event_id, cancel_token=cancel_token
            )
        )

    def _commit_oracle_turn(
        self,
        *,
        state: GameState,
        player_input: str,
        outcome: OracleOutcome,
        oracle_title: str | None,
        execution_context: str | None = None,
    ) -> None:
        self._turn_workflow.commit_oracle_turn(
            state=state,
            player_input=player_input,
            outcome=outcome,
            oracle_title=oracle_title,
            execution_context=execution_context,
        )

    def _apply_scene_transition(
        self,
        state: GameState,
        expected_scene: str,
        status: SceneStatus,
    ) -> None:
        self._turn_workflow.apply_scene_transition(state, expected_scene, status)

    def _record_event(self, state: GameState, event: GameEvent) -> None:
        self._state.record_event(state, event)

    def _ensure_active(self, state: GameState) -> None:
        self._state.ensure_active(state)

    def _save_state_commit(
        self,
        state: GameState,
        *,
        create_checkpoint: bool,
        committed_turn: CommittedTurnMemory | None = None,
    ) -> None:
        self._state.save_state_commit(
            state,
            create_checkpoint=create_checkpoint,
            committed_turn=committed_turn,
        )
