# mypy: disable-error-code="misc"
from __future__ import annotations

from collections.abc import Generator
from typing import TYPE_CHECKING

from dungeon_master.application.continuity import (
    NarratedTurn,
)
from dungeon_master.application.service_models import (
    CLARIFICATION_EVENT_TITLE,
)
from dungeon_master.application.stage_timing import (
    StageTimingTracker,
)
from dungeon_master.cancel import CancellationToken
from dungeon_master.models import (
    EventType,
    GameEvent,
    GameState,
    OracleKind,
    OracleOutcome,
)
from dungeon_master.narrative import (
    CompletionDelta,
    StreamStageStatus,
)

if TYPE_CHECKING:
    from dungeon_master.service import GameService


class TurnSubmissionMixin:
    def submit_player_action(self: GameService, action: str) -> GameState:
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

    def submit_player_turn(self: GameService, text: str) -> GameState:
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

    def regenerate_response(self: GameService, narrative_event_id: str) -> GameState:
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
        self: GameService,
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
        self: GameService,
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
        self: GameService,
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
