from __future__ import annotations

from typing import Protocol

from dungeon_master.campaign import CampaignGenerator, CharacterDraftMode, CharacterGenerator
from dungeon_master.models import (
    CampaignStatus,
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
from dungeon_master.narrative import NarrativeEngine
from dungeon_master.oracle import OracleEngine
from dungeon_master.state_store import StateStore
from dungeon_master.turn_router import TurnRoute, TurnRouter


class NarrativePort(Protocol):
    def generate(self, state: GameState, outcome: OracleOutcome, player_input: str) -> str:
        raise NotImplementedError


class CampaignPort(Protocol):
    def generate(self, character: CharacterSheet) -> GameState:
        raise NotImplementedError


class CharacterPort(Protocol):
    def setup_state(self) -> GameState:
        raise NotImplementedError

    def generate_templates(self) -> list[CharacterSheet]:
        raise NotImplementedError

    def generate_draft(
        self,
        *,
        mode: CharacterDraftMode,
        prompt: str | None,
        template: CharacterSheet | None,
    ) -> CharacterSheet:
        raise NotImplementedError

    def generate_quiz(self, concept: str) -> CharacterQuiz:
        raise NotImplementedError

    def generate_quizzed_draft(
        self,
        *,
        concept: str,
        answers: list[CharacterQuizAnswer],
        final_note: str | None,
    ) -> CharacterSheet:
        raise NotImplementedError


class GameService:
    def __init__(  # noqa: PLR0913
        self,
        store: StateStore,
        oracle: OracleEngine | None = None,
        narrative: NarrativePort | None = None,
        campaign_generator: CampaignPort | None = None,
        character_generator: CharacterPort | None = None,
        turn_router: TurnRouter | None = None,
    ) -> None:
        self._store = store
        self._oracle = oracle or OracleEngine()
        self._narrative = narrative or NarrativeEngine()
        self._campaign_generator = campaign_generator or CampaignGenerator.from_env()
        self._character_generator = character_generator or CharacterGenerator.from_env()
        self._turn_router = turn_router or TurnRouter()

    def load_state(self) -> GameState:
        return self._store.load_or_create(self._new_setup_state)

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
        self._store.save(state, create_checkpoint=True)
        return state

    def _new_setup_state(self) -> GameState:
        return self._character_generator.setup_state()

    def list_character_templates(self) -> list[CharacterSheet]:
        return self._character_generator.generate_templates()

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

    def generate_character_quiz(self, concept: str) -> CharacterQuiz:
        return self._character_generator.generate_quiz(concept)

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

    def finalize_character(self, character: CharacterSheet) -> GameState:
        state = self.load_state()
        state.character = character
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
        self._store.save(state, create_checkpoint=True)
        return state

    def start_campaign(self) -> GameState:
        state = self.load_state()
        if state.campaign_status == CampaignStatus.ACTIVE:
            return state
        if state.campaign_status != CampaignStatus.READY_TO_START:
            message = "Finalize a character before starting the campaign."
            raise ValueError(message)

        next_state = self._campaign_generator.generate(state.character)
        self._record_event(
            next_state,
            GameEvent(
                event_type=EventType.SYSTEM,
                title="Campaign initialized",
                content="Opening state and oracle tables were generated for this campaign.",
            ),
        )
        self._store.save(next_state, create_checkpoint=True)
        return next_state

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
        self._store.save(state, create_checkpoint=True)
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
        self._store.save(state, create_checkpoint=True)
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
            state.scene_status = outcome.scene_status
            state.scene_number += 1
            state.current_scene = self._scene_text(expected_scene, outcome.scene_status)

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
        state.oracle_history.append(outcome)
        self._store.write_turn_checkpoint(
            turn_id=outcome.id,
            oracle_outcome_id=outcome.id,
            player_input=action,
            state=state,
        )
        narration = self._narrative.generate(state, outcome, action)
        self._record_event(
            state,
            GameEvent(
                event_type=EventType.NARRATIVE,
                title="Narrative response",
                content=narration,
                oracle_outcome_id=outcome.id,
            ),
        )
        self._store.save(state, create_checkpoint=True)
        return state

    def submit_player_turn(self, text: str) -> GameState:
        """Route natural player chat through the right deterministic operation.

        Slash commands remain a frontend affordance. This method is the
        human-DM path: player writes naturally, the backend conservatively
        decides whether a roll is required, and the LLM still only narrates
        after Python has produced the mechanical outcome.
        """
        routed = self._turn_router.route(text)
        state = self.load_state()
        self._ensure_active(state)
        self._record_event(
            state,
            GameEvent(event_type=EventType.PLAYER, title="Player action", content=text),
        )

        if routed.route == TurnRoute.YES_NO:
            likelihood = routed.likelihood or Likelihood.EVEN
            outcome = self._oracle.ask_yes_no(state, routed.text, likelihood)
            self._commit_oracle_turn(
                state=state,
                player_input=f"Player asked: {routed.text}",
                outcome=outcome,
                oracle_title="Oracle answer",
            )
            return state

        if routed.route == TurnRoute.RANDOM_EVENT:
            outcome = self._oracle.generate_random_event(state)
            self._commit_oracle_turn(
                state=state,
                player_input=f"Player invited a complication: {routed.text}",
                outcome=outcome,
                oracle_title="Random event",
            )
            return state

        if routed.route == TurnRoute.SCENE_CHECK:
            outcome = self._oracle.check_scene(state, routed.text)
            if outcome.scene_status is not None:
                state.scene_status = outcome.scene_status
                state.scene_number += 1
                state.current_scene = self._scene_text(routed.text, outcome.scene_status)
            self._commit_oracle_turn(
                state=state,
                player_input=f"Player pushes into a new scene: {routed.text}",
                outcome=outcome,
                oracle_title="Scene check",
            )
            return state

        outcome = OracleOutcome(
            kind=OracleKind.PLAYER_ACTION,
            summary="Narrative continuation requested without an oracle roll.",
            chaos_factor=state.chaos_factor,
        )
        state.oracle_history.append(outcome)
        self._store.write_turn_checkpoint(
            turn_id=outcome.id,
            oracle_outcome_id=outcome.id,
            player_input=routed.text,
            state=state,
        )
        narration = self._narrative.generate(state, outcome, routed.text)
        self._record_event(
            state,
            GameEvent(
                event_type=EventType.NARRATIVE,
                title="Narrative response",
                content=narration,
                oracle_outcome_id=outcome.id,
            ),
        )
        self._store.save(state, create_checkpoint=True)
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
        narration = self._narrative.generate(restored_state, outcome, checkpoint.player_input)
        self._record_event(
            restored_state,
            GameEvent(
                event_type=EventType.NARRATIVE,
                title="Narrative response",
                content=narration,
                oracle_outcome_id=outcome.id,
            ),
        )
        self._store.save(restored_state, create_checkpoint=True)
        return restored_state

    def _commit_oracle_turn(
        self,
        *,
        state: GameState,
        player_input: str,
        outcome: OracleOutcome,
        oracle_title: str,
    ) -> None:
        state.oracle_history.append(outcome)
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
            state=state,
        )
        narration = self._narrative.generate(state, outcome, player_input)
        self._record_event(
            state,
            GameEvent(
                event_type=EventType.NARRATIVE,
                title="Narrative response",
                content=narration,
                oracle_outcome_id=outcome.id,
            ),
        )
        self._store.save(state, create_checkpoint=True)

    def _record_event(self, state: GameState, event: GameEvent) -> None:
        state.action_log.append(event)
        self._store.append_event(event)

    def _ensure_active(self, state: GameState) -> None:
        if state.campaign_status != CampaignStatus.ACTIVE:
            message = "Campaign has not started. Finalize a character and start the campaign."
            raise ValueError(message)

    def _scene_text(self, expected_scene: str, status: SceneStatus) -> str:
        if status == SceneStatus.EXPECTED:
            return expected_scene
        if status == SceneStatus.ALTERED:
            return f"Altered: {expected_scene}"
        return f"Interrupted before: {expected_scene}"
