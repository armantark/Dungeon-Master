from __future__ import annotations

from collections.abc import Generator, Mapping
from concurrent.futures import ThreadPoolExecutor

from dungeon_master.application.continuity import NarratedTurn
from dungeon_master.application.service_models import (
    CLARIFICATION_EVENT_TITLE,
    ClarificationPrompt,
    ExecutedTurn,
)
from dungeon_master.application.service_ports import ExplainerPort, NarrativePort
from dungeon_master.application.stage_timing import (
    TURN_STREAM_STAGE_LABELS,
    TURN_STREAM_STAGE_ORDER,
    StageTimingTracker,
)
from dungeon_master.application.state_management import ApplicationState
from dungeon_master.application.turn_commit import TurnCommitter
from dungeon_master.application.turn_plan_execution import TurnPlanExecutor
from dungeon_master.cancel import CancellationToken
from dungeon_master.explainer import ExplanationResult
from dungeon_master.memory import (
    CommittedTurnMemory,
    ConversationMessage,
    MemoryManager,
    MemoryState,
    active_encounter_line_for_state,
)
from dungeon_master.models import (
    CharacterSheet,
    EventType,
    GameEvent,
    GameState,
    OracleKind,
    OracleOutcome,
    SceneStatus,
)
from dungeon_master.narrative import (
    CompletionDelta,
    NarrativeResult,
    StreamStageStatus,
    StreamStageUpdate,
)
from dungeon_master.state_store import StateStore, TurnCheckpointRecord
from dungeon_master.turn_router import TurnPlan, TurnRouter


class TurnWorkflow:
    """Own planning, narration, regeneration, and ordered turn commits."""

    def __init__(  # noqa: PLR0913
        self,
        *,
        state: ApplicationState,
        narrative: NarrativePort,
        explainer: ExplainerPort,
        turn_router: TurnRouter,
        memory_manager: MemoryManager,
        turn_committer: TurnCommitter,
        turn_plan_executor: TurnPlanExecutor,
    ) -> None:
        self._state = state
        self._narrative = narrative
        self._explainer = explainer
        self._turn_router = turn_router
        self._memory = memory_manager
        self._turn_committer = turn_committer
        self._turn_plan_executor = turn_plan_executor

    @property
    def _store(self) -> StateStore:
        return self._state.store

    def load_state(self, *, cancel_token: CancellationToken | None = None) -> GameState:
        return self._state.load_state(cancel_token=cancel_token)

    def load_state_readonly(
        self,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> GameState:
        return self._state.load_state_readonly(cancel_token=cancel_token)

    def record_event(self, state: GameState, event: GameEvent) -> None:
        self._state.record_event(state, event)

    def queue_event(self, state: GameState, queue: list[GameEvent], event: GameEvent) -> None:
        self._state.queue_event(state, queue, event)

    def persist_streamed_state(
        self,
        state: GameState,
        events: list[GameEvent],
        *,
        turn_checkpoint: TurnCheckpointRecord | None = None,
        committed_turn: CommittedTurnMemory | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> None:
        self._state.persist_streamed_state(
            state,
            events,
            turn_checkpoint=turn_checkpoint,
            committed_turn=committed_turn,
            cancel_token=cancel_token,
        )

    def save_state_commit(
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

    def ensure_active(self, state: GameState) -> None:
        self._state.ensure_active(state)

    def auto_end_campaign_if_needed(
        self,
        state: GameState,
        *,
        outcome: OracleOutcome,
    ) -> GameEvent | None:
        return self._state.auto_end_campaign_if_needed(state, outcome=outcome)

    def memory_for_state(
        self,
        state: GameState,
        *,
        existing_memory: MemoryState | None = None,
        force_rebuild: bool = False,
        checkpoint_overrides: Mapping[str, TurnCheckpointRecord] | None = None,
    ) -> MemoryState:
        return self._state.memory_for_state(
            state,
            existing_memory=existing_memory,
            force_rebuild=force_rebuild,
            checkpoint_overrides=checkpoint_overrides,
        )

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

    def submit_player_action(self, action: str) -> GameState:
        state = self.load_state()
        self.ensure_active(state)
        outcome = OracleOutcome(
            kind=OracleKind.PLAYER_ACTION,
            summary="Narrative continuation requested without an oracle roll.",
            chaos_factor=state.chaos_factor,
        )
        self.record_event(
            state,
            GameEvent(event_type=EventType.PLAYER, title="Player action", content=action),
        )
        self.commit_oracle_turn(
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
        self.ensure_active(state)
        self.record_event(
            state,
            GameEvent(event_type=EventType.PLAYER, title="Player action", content=text),
        )
        clarification = self._clarification_prompt_for_plan(plan)
        if clarification is not None:
            self.record_event(
                state,
                GameEvent(
                    event_type=EventType.NARRATIVE,
                    title=CLARIFICATION_EVENT_TITLE,
                    content=clarification.question,
                ),
            )
            self.save_state_commit(state, create_checkpoint=True)
            return state
        executed = self._execute_turn_plan(state, plan)
        self.commit_oracle_turn(
            state=state,
            player_input=text,
            outcome=executed.outcome,
            oracle_title=executed.oracle_title,
            execution_context=executed.execution_context,
        )
        return state

    def regenerate_response(self, narrative_event_id: str) -> GameState:
        state = self.load_state()
        self.ensure_active(state)

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

        self.record_event(
            restored_state,
            GameEvent(
                event_type=EventType.SYSTEM,
                title="Narrative regenerated",
                content="Repaired the latest DM response after a retry request.",
            ),
        )
        working_memory = self.memory_for_state(restored_state, force_rebuild=True)
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
        self.record_event(
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
        self.save_state_commit(
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
        self.ensure_active(state)
        outcome = OracleOutcome(
            kind=OracleKind.PLAYER_ACTION,
            summary="Narrative continuation requested without an oracle roll.",
            chaos_factor=state.chaos_factor,
        )
        queued_events: list[GameEvent] = []
        self.queue_event(
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
        self.ensure_active(state)
        queued_events: list[GameEvent] = []
        self.queue_event(
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
            self.queue_event(
                state,
                queued_events,
                GameEvent(
                    event_type=EventType.NARRATIVE,
                    title=CLARIFICATION_EVENT_TITLE,
                    content=clarification.question,
                    stage_timings=tracker.snapshot(),
                ),
            )
            self.persist_streamed_state(
                state,
                queued_events,
                cancel_token=cancel_token,
                committed_turn=None,
            )
            return state
        self.raise_if_cancelled(cancel_token)
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
        self.ensure_active(state)
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

        self.queue_event(
            restored_state,
            queued_events,
            GameEvent(
                event_type=EventType.SYSTEM,
                title="Narrative regenerated",
                content="Repaired the latest DM response after a retry request.",
            ),
        )
        self.raise_if_cancelled(cancel_token)
        yield self._stage_delta("preparing_narration", StreamStageStatus.ACTIVE, tracker=tracker)
        working_memory = self.memory_for_state(restored_state, force_rebuild=True)
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
        self.queue_event(
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
        self.persist_streamed_state(
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

    def commit_oracle_turn(
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
        terminal_event = self.auto_end_campaign_if_needed(state, outcome=outcome)
        if oracle_title is not None:
            self.record_event(
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
        self.record_event(
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
            self.record_event(state, terminal_event)
        self.save_state_commit(
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
        terminal_event = self.auto_end_campaign_if_needed(state, outcome=outcome)
        if oracle_title is not None:
            self.queue_event(
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
        self.raise_if_cancelled(cancel_token)
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
        self.queue_event(
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
            self.queue_event(state, queued_events, terminal_event)
        self.persist_streamed_state(
            state,
            queued_events,
            turn_checkpoint=turn_checkpoint,
            cancel_token=cancel_token,
            committed_turn=committed_turn,
        )
        return state

    def apply_scene_transition(
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
        planner_memory = self.memory_for_state(state, existing_memory=existing_memory)
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
        self.raise_if_cancelled(cancel_token)
        return plan, state

    def _load_state_and_memory_context_for_explainer(
        self,
        question: str,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> tuple[GameState, str | None]:
        with ThreadPoolExecutor(max_workers=2) as executor:
            memory_future = executor.submit(self._store.load_memory_or_none)
            state = self.load_state_readonly(cancel_token=cancel_token)
            existing_memory = memory_future.result()
        memory = self.memory_for_state(state, existing_memory=existing_memory)
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
        self.raise_if_cancelled(cancel_token)
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
            memory = self.memory_for_state(
                state,
                force_rebuild=True,
                checkpoint_overrides=checkpoint_overrides,
            )
        else:
            memory = self.contextmemory_for_state(state, working_memory)
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
        return self.memory_for_state(
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

    def contextmemory_for_state(
        self,
        state: GameState,
        working_memory: MemoryState | None,
    ) -> MemoryState:
        if working_memory is None:
            return self.memory_for_state(state)
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

    def raise_if_cancelled(self, cancel_token: CancellationToken | None) -> None:
        if cancel_token is not None:
            cancel_token.raise_if_cancelled()

    def _item_id_from_name(self, character: CharacterSheet, item_name: str | None) -> str | None:
        return self._turn_plan_executor.item_id_from_name(character, item_name)

    def _require_item_id_from_name(self, character: CharacterSheet, item_name: str) -> str:
        return self._turn_plan_executor.require_item_id_from_name(character, item_name)
