# mypy: disable-error-code="misc"
from __future__ import annotations

from collections.abc import Generator
from typing import TYPE_CHECKING

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
from dungeon_master.narrative import (
    CompletionDelta,
)

if TYPE_CHECKING:
    from dungeon_master.service import GameService


class CampaignLifecycleMixin:
    def update_campaign_seed(self: GameService, seed: CampaignSeed) -> GameState:
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

    def list_character_templates(self: GameService) -> list[CharacterSheet]:
        state = self.load_state()
        return self._character_generator.generate_templates(seed=state.campaign_seed)

    def list_character_templates_result(self: GameService) -> CharacterTemplatesResult:
        state = self.load_state()
        return self._character_generator.generate_templates_result(seed=state.campaign_seed)

    def stream_character_templates(
        self: GameService,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, CharacterTemplatesResult]:
        return self._character_generator.iter_generate_templates(
            seed=self.load_state(cancel_token=cancel_token).campaign_seed,
            cancel_token=cancel_token,
        )

    def generate_character_draft(
        self: GameService,
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
        self: GameService,
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

    def generate_character_quiz(self: GameService, concept: str) -> CharacterQuiz:
        state = self.load_state()
        return self._character_generator.generate_quiz(concept, seed=state.campaign_seed)

    def generate_character_quiz_result(self: GameService, concept: str) -> CharacterQuizResult:
        state = self.load_state()
        return self._character_generator.generate_quiz_result(
            concept,
            seed=state.campaign_seed,
        )

    def stream_character_quiz(
        self: GameService,
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
        self: GameService,
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
        self: GameService,
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
        self: GameService,
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
        self: GameService,
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

    def finalize_character(self: GameService, character: CharacterSheet) -> GameState:
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

    def start_campaign(self: GameService) -> GameState:
        return self.start_campaign_result().state

    def start_campaign_result(self: GameService) -> CampaignWorldResult:
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
        self: GameService,
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
        self: GameService,
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
