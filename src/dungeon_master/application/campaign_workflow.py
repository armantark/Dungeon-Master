from __future__ import annotations

from collections.abc import Generator

from dungeon_master.application.service_ports import CairnPort, CampaignPort, CharacterPort
from dungeon_master.application.state_management import ApplicationState
from dungeon_master.campaign import (
    CampaignWorldResult,
    CharacterDraftMode,
    CharacterDraftResult,
    CharacterQuizResult,
    CharacterTemplatesResult,
)
from dungeon_master.cancel import CancellationToken
from dungeon_master.models import (
    CampaignEndReason,
    CampaignSeed,
    CampaignStatus,
    CharacterQuiz,
    CharacterQuizAnswer,
    CharacterSheet,
    EventType,
    GameEvent,
    GameState,
)
from dungeon_master.narrative import CompletionDelta


class CampaignWorkflow:
    """Own setup, generation, and campaign lifecycle orchestration."""

    def __init__(
        self,
        *,
        state: ApplicationState,
        campaign_generator: CampaignPort,
        character_generator: CharacterPort,
        cairn: CairnPort,
    ) -> None:
        self._state = state
        self._campaign_generator = campaign_generator
        self._character_generator = character_generator
        self._cairn = cairn

    def load_state(self, *, cancel_token: CancellationToken | None = None) -> GameState:
        return self._state.load_state(cancel_token=cancel_token)

    def new_setup_state(self) -> GameState:
        return self._state.new_setup_state()

    def record_event(self, state: GameState, event: GameEvent) -> None:
        self._state.record_event(state, event)

    def queue_event(self, state: GameState, queue: list[GameEvent], event: GameEvent) -> None:
        self._state.queue_event(state, queue, event)

    def save_state_commit(self, state: GameState, *, create_checkpoint: bool) -> None:
        self._state.save_state_commit(state, create_checkpoint=create_checkpoint)

    def persist_streamed_state(
        self,
        state: GameState,
        events: list[GameEvent],
        *,
        cancel_token: CancellationToken | None = None,
    ) -> None:
        self._state.persist_streamed_state(
            state,
            events,
            cancel_token=cancel_token,
        )

    def ensure_active(self, state: GameState) -> None:
        self._state.ensure_active(state)

    def campaign_end_conflict_message(self, state: GameState) -> str:
        return self._state.campaign_end_conflict_message(state)

    def mark_campaign_ended(
        self,
        state: GameState,
        *,
        reason: CampaignEndReason,
        summary: str | None = None,
    ) -> bool:
        return self._state.mark_campaign_ended(state, reason=reason, summary=summary)

    def campaign_end_event(self, state: GameState) -> GameEvent:
        return self._state.campaign_end_event(state)

    def raise_if_cancelled(self, cancel_token: CancellationToken | None) -> None:
        self._state.raise_if_cancelled(cancel_token)

    def reset(self) -> GameState:
        state = self.new_setup_state()
        self.record_event(
            state,
            GameEvent(
                event_type=EventType.SYSTEM,
                title="Setup reset",
                content="Returned to character creation.",
            ),
        )
        self.save_state_commit(state, create_checkpoint=True)
        return state

    def update_campaign_seed(self, seed: CampaignSeed) -> GameState:
        state = self.load_state()
        if state.campaign_status == CampaignStatus.ACTIVE:
            message = "Campaign seed is locked after the campaign starts."
            raise ValueError(message)
        if state.campaign_status == CampaignStatus.ENDED:
            message = self.campaign_end_conflict_message(state)
            raise ValueError(message)
        state.campaign_seed = seed.model_copy(deep=True)
        self.save_state_commit(state, create_checkpoint=True)
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
            message = self.campaign_end_conflict_message(state)
            raise ValueError(message)
        state.character = character.model_copy(deep=True)
        self._cairn.ensure_character_state(state, allow_backfill=False)
        state.player_notes = character.backstory
        state.campaign_status = CampaignStatus.READY_TO_START
        self.record_event(
            state,
            GameEvent(
                event_type=EventType.SYSTEM,
                title="Character finalized",
                content=f"{character.name} is ready to enter the world.",
            ),
        )
        self.save_state_commit(state, create_checkpoint=True)
        return state

    def start_campaign(self) -> GameState:
        return self.start_campaign_result().state

    def start_campaign_result(self) -> CampaignWorldResult:
        state = self.load_state()
        if state.campaign_status == CampaignStatus.ACTIVE:
            return CampaignWorldResult(state=state)
        if state.campaign_status == CampaignStatus.ENDED:
            message = self.campaign_end_conflict_message(state)
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
        self.record_event(
            next_state,
            GameEvent(
                event_type=EventType.SYSTEM,
                title="Campaign initialized",
                content="Opening state and oracle tables were generated for this campaign.",
                thinking=generated.thinking,
            ),
        )
        self.save_state_commit(next_state, create_checkpoint=True)
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
            message = self.campaign_end_conflict_message(state)
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
            self.raise_if_cancelled(cancel_token)
            self._cairn.ensure_character_state(
                next_state,
                allow_backfill=True,
                cancel_token=cancel_token,
            )
            self.raise_if_cancelled(cancel_token)
            queued_events: list[GameEvent] = []
            self.queue_event(
                next_state,
                queued_events,
                GameEvent(
                    event_type=EventType.SYSTEM,
                    title="Campaign initialized",
                    content="Opening state and oracle tables were generated for this campaign.",
                    thinking=generated.thinking,
                ),
            )
            self.persist_streamed_state(
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
        self.ensure_active(state)
        if reason == CampaignEndReason.DEATH and not state.character.cairn.dead:
            message = "Cannot end the campaign as death while the character is still alive."
            raise ValueError(message)
        if reason != CampaignEndReason.DEATH and state.encounter.active:
            message = "Cannot retire or declare victory while an encounter is still active."
            raise ValueError(message)

        self.mark_campaign_ended(state, reason=reason, summary=summary)
        self.record_event(
            state,
            self.campaign_end_event(state),
        )
        self.save_state_commit(state, create_checkpoint=True)
        return state
