"""Integration tests for the FastAPI surface.

These tests don't go to the network: a `FakeNarrative` and
`FakeCampaignGenerator` replace LiteLLM, so we exercise the routing,
serialization, and state-mutation contracts without spending tokens.
"""

from __future__ import annotations

from collections.abc import Generator
from threading import Event
from typing import TYPE_CHECKING

from dungeon_master.campaign import (
    CampaignWorldResult,
    CharacterDraftMode,
    CharacterDraftResult,
    CharacterQuizResult,
    CharacterTemplatesResult,
)
from dungeon_master.cancel import CancellationToken
from dungeon_master.explainer import ExplanationResult
from dungeon_master.models import (
    CampaignSeed,
    CharacterQuiz,
    CharacterQuizAnswer,
    CharacterQuizOption,
    CharacterQuizQuestion,
    CharacterSheet,
    GameState,
    OracleOutcome,
)
from dungeon_master.narrative import (
    CompletionDelta,
    CompletionRequest,
    NarrativeConfig,
    NarrativeResult,
)
from tests.factories import sample_state

if TYPE_CHECKING:
    from litellm.types.utils import ModelResponse


class FakeNarrative:
    _config = NarrativeConfig(model="", api_key=None, base_url=None)

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
        del cancel_token
        suffix = f" / ctx {execution_context}" if execution_context else ""
        memory_suffix = " / mem yes" if memory_context else ""
        scene_suffix = " / scene yes" if scene_messages else ""
        return (
            f"FAKE: {outcome.summary} / {player_input} / chaos {state.chaos_factor}"
            f"{suffix}{memory_suffix}{scene_suffix}"
        )


class ThoughtfulNarrative(FakeNarrative):
    def generate_result(  # noqa: PLR0913
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
        del cancel_token
        return NarrativeResult(
            content=self.generate(
                state,
                outcome,
                player_input,
                execution_context=execution_context,
                memory_context=memory_context,
                scene_messages=scene_messages,
            ),
            thinking=f"Thought about {outcome.kind}.",
        )

    def iter_stream(  # noqa: PLR0913
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
        del cancel_token
        yield CompletionDelta(thinking=f"Thought about {outcome.kind}.")
        yield CompletionDelta(
            content=self.generate(
                state,
                outcome,
                player_input,
                execution_context=execution_context,
                memory_context=memory_context,
                scene_messages=scene_messages,
            ),
        )
        return self.generate_result(
            state,
            outcome,
            player_input,
            execution_context=execution_context,
            memory_context=memory_context,
            scene_messages=scene_messages,
        )


class BlockingThoughtfulNarrative(ThoughtfulNarrative):
    def __init__(self) -> None:
        self.started = Event()
        self.release = Event()

    def iter_stream(  # noqa: PLR0913
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
        yield CompletionDelta(thinking=f"Thought about {outcome.kind}.")
        self.started.set()
        while not self.release.wait(timeout=0.01):
            if cancel_token is not None:
                cancel_token.raise_if_cancelled()
        yield CompletionDelta(
            content=self.generate(
                state,
                outcome,
                player_input,
                execution_context=execution_context,
                memory_context=memory_context,
                scene_messages=scene_messages,
            ),
        )
        return self.generate_result(
            state,
            outcome,
            player_input,
            execution_context=execution_context,
            memory_context=memory_context,
            scene_messages=scene_messages,
        )


class FakeExplainer:
    def __init__(self) -> None:
        self.state: GameState | None = None

    def generate_result(
        self,
        state: GameState,
        question: str,
        *,
        memory_context: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> ExplanationResult:
        del cancel_token
        self.state = state
        memory_suffix = " / mem yes" if memory_context else ""
        latest = state.oracle_history[-1].summary if state.oracle_history else "no prior outcome"
        return ExplanationResult(
            answer=(
                f"OOC: {question} / latest {latest} / chaos {state.chaos_factor}{memory_suffix}"
            ),
        )

    def iter_stream(
        self,
        state: GameState,
        question: str,
        *,
        memory_context: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, ExplanationResult]:
        del cancel_token
        self.state = state
        yield CompletionDelta(thinking="Explainer considered the current state.")
        yield CompletionDelta(
            content=self.generate_result(
                state,
                question,
                memory_context=memory_context,
            ).answer,
        )
        return ExplanationResult(
            answer=self.generate_result(
                state,
                question,
                memory_context=memory_context,
            ).answer,
            thinking="Explainer considered the current state.",
        )


class BrokenPlannerCompletion:
    def __call__(self, request: CompletionRequest) -> ModelResponse:
        del request
        return []  # type: ignore[return-value]


class FakeCampaignGenerator:
    def generate(
        self,
        character: CharacterSheet,
        seed: CampaignSeed | None = None,
    ) -> GameState:
        state = sample_state()
        state.character = character
        state.player_notes = character.backstory
        if seed is not None:
            state.campaign_seed = seed
        return state

    def generate_result(
        self,
        character: CharacterSheet,
        seed: CampaignSeed | None = None,
    ) -> CampaignWorldResult:
        return CampaignWorldResult(state=self.generate(character, seed=seed))

    def iter_generate(
        self,
        character: CharacterSheet,
        *,
        seed: CampaignSeed | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, CampaignWorldResult]:
        del cancel_token
        result = self.generate_result(character, seed=seed)
        yield CompletionDelta(content=result.state.model_dump_json())
        return result


class FakeCharacterGenerator:
    def setup_state(self, seed: CampaignSeed | None = None) -> GameState:
        state = sample_state()
        if seed is not None:
            state.campaign_seed = seed
        return state

    def generate_templates(self, seed: CampaignSeed | None = None) -> list[CharacterSheet]:
        del seed
        return [sample_state().character]

    def generate_templates_result(
        self,
        seed: CampaignSeed | None = None,
    ) -> CharacterTemplatesResult:
        return CharacterTemplatesResult(templates=self.generate_templates(seed=seed))

    def iter_generate_templates(
        self,
        seed: CampaignSeed | None = None,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, CharacterTemplatesResult]:
        del cancel_token
        result = self.generate_templates_result(seed=seed)
        yield CompletionDelta(content=result.templates[0].model_dump_json())
        return result

    def generate_draft(
        self,
        *,
        mode: CharacterDraftMode,
        prompt: str | None,
        template: CharacterSheet | None,
        seed: CampaignSeed | None = None,
    ) -> CharacterSheet:
        del mode, prompt, template, seed
        return sample_state().character

    def generate_draft_result(
        self,
        *,
        mode: CharacterDraftMode,
        prompt: str | None,
        template: CharacterSheet | None,
        seed: CampaignSeed | None = None,
    ) -> CharacterDraftResult:
        return CharacterDraftResult(
            draft=self.generate_draft(mode=mode, prompt=prompt, template=template, seed=seed),
        )

    def iter_generate_draft(
        self,
        *,
        mode: CharacterDraftMode,
        prompt: str | None,
        template: CharacterSheet | None,
        seed: CampaignSeed | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, CharacterDraftResult]:
        del cancel_token
        result = self.generate_draft_result(
            mode=mode,
            prompt=prompt,
            template=template,
            seed=seed,
        )
        yield CompletionDelta(content=result.draft.model_dump_json())
        return result

    def generate_quiz(self, concept: str, seed: CampaignSeed | None = None) -> CharacterQuiz:
        del seed
        return CharacterQuiz(
            concept=concept,
            questions=[
                CharacterQuizQuestion(
                    prompt="Where were you when faith asked too much?",
                    options=[
                        CharacterQuizOption(label="At a roadside crucifixion."),
                        CharacterQuizOption(label="In a sacked monastery cellar."),
                        CharacterQuizOption(label="Watching a child you couldn't bury."),
                    ],
                ),
                CharacterQuizQuestion(
                    prompt="What sin do you keep committing?",
                    options=[
                        CharacterQuizOption(label="Mercy for the wrong people."),
                        CharacterQuizOption(label="Keeping a relic you should burn."),
                        CharacterQuizOption(label="Bargains spoken at thresholds."),
                    ],
                ),
                CharacterQuizQuestion(
                    prompt="Who is still hunting you?",
                    options=[
                        CharacterQuizOption(label="The order that ordained you."),
                        CharacterQuizOption(label="A creditor with a writ of teeth."),
                        CharacterQuizOption(label="Your own dead."),
                    ],
                ),
            ],
        )

    def generate_quiz_result(
        self,
        concept: str,
        seed: CampaignSeed | None = None,
    ) -> CharacterQuizResult:
        return CharacterQuizResult(quiz=self.generate_quiz(concept, seed=seed))

    def iter_generate_quiz(
        self,
        concept: str,
        *,
        seed: CampaignSeed | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, CharacterQuizResult]:
        del cancel_token
        result = self.generate_quiz_result(concept, seed=seed)
        yield CompletionDelta(content=result.quiz.model_dump_json())
        return result

    def generate_quizzed_draft(
        self,
        *,
        concept: str,
        answers: list[CharacterQuizAnswer],
        final_note: str | None,
        seed: CampaignSeed | None = None,
    ) -> CharacterSheet:
        del seed
        sheet = sample_state().character.model_copy(deep=True)
        sheet.epithet = concept
        sheet.backstory = "; ".join(answer.value for answer in answers) or "no answers"
        if final_note:
            sheet.condition = final_note
        return sheet

    def generate_quizzed_draft_result(
        self,
        *,
        concept: str,
        answers: list[CharacterQuizAnswer],
        final_note: str | None,
        seed: CampaignSeed | None = None,
    ) -> CharacterDraftResult:
        return CharacterDraftResult(
            draft=self.generate_quizzed_draft(
                concept=concept,
                answers=answers,
                final_note=final_note,
                seed=seed,
            ),
        )

    def iter_generate_quizzed_draft(
        self,
        *,
        concept: str,
        answers: list[CharacterQuizAnswer],
        final_note: str | None,
        seed: CampaignSeed | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, CharacterDraftResult]:
        del cancel_token
        result = self.generate_quizzed_draft_result(
            concept=concept,
            answers=answers,
            final_note=final_note,
            seed=seed,
        )
        yield CompletionDelta(content=result.draft.model_dump_json())
        return result
