from collections.abc import Callable, Generator
from threading import Event

from dungeon_master.campaign import (
    CampaignWorldResult,
    CharacterDraftMode,
    CharacterDraftResult,
    CharacterQuizResult,
    CharacterTemplatesResult,
)
from dungeon_master.cancel import CancellationToken
from dungeon_master.capability_oracle_guard import CapabilityOracleGuardResult
from dungeon_master.character_effect_updater import CharacterEffectUpdateResult
from dungeon_master.config import LLMConfig, LLMRuntimeBundle, single_llm_runtime
from dungeon_master.inventory_updater import InventoryUpdateResult
from dungeon_master.models import (
    CampaignSeed,
    CampaignStatus,
    CharacterQuiz,
    CharacterQuizAnswer,
    CharacterQuizOption,
    CharacterQuizQuestion,
    CharacterSheet,
    GameState,
    Likelihood,
    OracleOutcome,
)
from dungeon_master.narrative import CompletionDelta, NarrativeConfig
from dungeon_master.npc_updater import (
    GeneratedNPCUpdateBatch,
    LegacyNPCRosterRepairResult,
    NPCUpdateResult,
)
from dungeon_master.thread_updater import GeneratedThreadUpdateBatch, ThreadUpdateResult
from tests.factories import sample_state
from tests.service.cairn_fakes import FakeCairnEngine

__all__ = ["FakeCairnEngine"]


def single_test_runtime() -> LLMRuntimeBundle:
    return single_llm_runtime(
        LLMConfig(model="test-model", api_key="test-key", base_url=None),
    )


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


class FakeCampaignGenerator:
    def generate(self, character: CharacterSheet, seed: CampaignSeed | None = None) -> GameState:
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
    def __init__(self) -> None:
        self.quiz_seeds: list[CampaignSeed | None] = []

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
        *,
        seed: CampaignSeed | None = None,
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
        self.quiz_seeds.append(seed.model_copy(deep=True) if seed is not None else None)
        return CharacterQuiz(
            concept=concept or "Test concept",
            questions=[
                CharacterQuizQuestion(
                    prompt="Test question one?",
                    options=[
                        CharacterQuizOption(label="Test option A"),
                        CharacterQuizOption(label="Test option B"),
                        CharacterQuizOption(label="Test option C"),
                    ],
                ),
                CharacterQuizQuestion(
                    prompt="Test question two?",
                    options=[
                        CharacterQuizOption(label="Test option D"),
                        CharacterQuizOption(label="Test option E"),
                        CharacterQuizOption(label="Test option F"),
                    ],
                ),
                CharacterQuizQuestion(
                    prompt="Test question three?",
                    options=[
                        CharacterQuizOption(label="Test option G"),
                        CharacterQuizOption(label="Test option H"),
                        CharacterQuizOption(label="Test option I"),
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
        # Make the test sheet visibly reflect inputs so we can assert plumbing.
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


class SetupCharacterGenerator(FakeCharacterGenerator):
    def setup_state(self, seed: CampaignSeed | None = None) -> GameState:
        state = sample_state()
        if seed is not None:
            state.campaign_seed = seed
        state.campaign_status = CampaignStatus.CHARACTER_CREATION
        state.threads = []
        state.npcs = []
        state.action_log = []
        state.oracle_history = []
        return state


class FakeThreadUpdater:
    def __init__(
        self,
        mutate: Callable[[GameState, OracleOutcome], tuple[str, ...]] | None = None,
    ) -> None:
        self._mutate = mutate
        self.calls: list[tuple[str, str]] = []
        self.post_calls: list[tuple[str, str, str]] = []
        self.post_memory_contexts: list[str | None] = []

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
        generated = self.generate_thread_updates(
            state,
            player_input=player_input,
            outcome=outcome,
            execution_context=execution_context,
            narrative_text=narrative_text,
            memory_context=memory_context,
            cancel_token=cancel_token,
        )
        if generated is None:
            return ThreadUpdateResult()
        return self.apply_generated_updates(state, generated)

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
        del state, execution_context, cancel_token
        if narrative_text is None:
            self.calls.append((player_input, outcome.summary))
        else:
            self.post_calls.append((player_input, outcome.summary, narrative_text))
            self.post_memory_contexts.append(memory_context)
        return GeneratedThreadUpdateBatch()

    def apply_generated_updates(
        self,
        state: GameState,
        generated: GeneratedThreadUpdateBatch,
    ) -> ThreadUpdateResult:
        del generated
        latest_outcome = state.oracle_history[-1]
        if self._mutate is None:
            return ThreadUpdateResult()
        return ThreadUpdateResult(touched_thread_ids=self._mutate(state, latest_outcome))


class FakeNpcUpdater:
    def __init__(
        self,
        mutate: Callable[[GameState, OracleOutcome], tuple[str, ...]] | None = None,
        repair: LegacyNPCRosterRepairResult | None = None,
    ) -> None:
        self._mutate = mutate
        self._repair = repair
        self.calls: list[tuple[str, str]] = []
        self.post_calls: list[tuple[str, str, str]] = []
        self.post_memory_contexts: list[str | None] = []

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
        generated = self.generate_npc_updates(
            state,
            player_input=player_input,
            outcome=outcome,
            execution_context=execution_context,
            narrative_text=narrative_text,
            memory_context=memory_context,
            cancel_token=cancel_token,
        )
        if generated is None:
            return NPCUpdateResult()
        return self.apply_generated_updates(state, generated)

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
        del state, execution_context, cancel_token
        if narrative_text is None:
            self.calls.append((player_input, outcome.summary))
        else:
            self.post_calls.append((player_input, outcome.summary, narrative_text))
            self.post_memory_contexts.append(memory_context)
        return GeneratedNPCUpdateBatch()

    def apply_generated_updates(
        self,
        state: GameState,
        generated: GeneratedNPCUpdateBatch,
    ) -> NPCUpdateResult:
        del generated
        latest_outcome = state.oracle_history[-1]
        if self._mutate is None:
            return NPCUpdateResult()
        return NPCUpdateResult(touched_npc_ids=self._mutate(state, latest_outcome))

    def reseed_legacy_roster(
        self,
        state: GameState,
        *,
        memory_context: str | None = None,
        cancel_token: CancellationToken | None = None,
        use_model: bool = False,
    ) -> LegacyNPCRosterRepairResult:
        del state, memory_context, cancel_token, use_model
        return self._repair or LegacyNPCRosterRepairResult()


class FakeInventoryUpdater:
    def __init__(
        self,
        mutate: Callable[[GameState, OracleOutcome], tuple[str, ...]] | None = None,
    ) -> None:
        self._mutate = mutate
        self.calls: list[tuple[str, str, str]] = []

    def update_inventory(  # noqa: PLR0913
        self,
        state: GameState,
        *,
        player_input: str,
        outcome: OracleOutcome,
        execution_context: str | None,
        narrative_text: str,
        cancel_token: CancellationToken | None = None,
    ) -> InventoryUpdateResult:
        del execution_context, cancel_token
        self.calls.append((player_input, outcome.summary, narrative_text))
        if self._mutate is None:
            return InventoryUpdateResult()
        summaries = self._mutate(state, outcome)
        return InventoryUpdateResult(changed=bool(summaries), summaries=summaries)


class ParallelThreadUpdater(FakeThreadUpdater):
    def __init__(
        self,
        *,
        started: Event,
        other_started: Event,
        mutate: Callable[[GameState, OracleOutcome], tuple[str, ...]] | None = None,
    ) -> None:
        super().__init__(mutate=mutate)
        self._started = started
        self._other_started = other_started

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
        generated = super().generate_thread_updates(
            state,
            player_input=player_input,
            outcome=outcome,
            execution_context=execution_context,
            narrative_text=narrative_text,
            memory_context=memory_context,
            cancel_token=cancel_token,
        )
        self._started.set()
        assert self._other_started.wait(0.5)
        return generated


class ParallelNpcUpdater(FakeNpcUpdater):
    def __init__(
        self,
        *,
        started: Event,
        other_started: Event,
        mutate: Callable[[GameState, OracleOutcome], tuple[str, ...]] | None = None,
        repair: LegacyNPCRosterRepairResult | None = None,
    ) -> None:
        super().__init__(mutate=mutate, repair=repair)
        self._started = started
        self._other_started = other_started

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
        generated = super().generate_npc_updates(
            state,
            player_input=player_input,
            outcome=outcome,
            execution_context=execution_context,
            narrative_text=narrative_text,
            memory_context=memory_context,
            cancel_token=cancel_token,
        )
        self._started.set()
        assert self._other_started.wait(0.5)
        return generated


class FakeCapabilityOracleGuard:
    def __init__(
        self,
        result: CapabilityOracleGuardResult | None = None,
    ) -> None:
        self._result = result or CapabilityOracleGuardResult()
        self.calls: list[tuple[str, Likelihood]] = []

    def guard_yes_no(
        self,
        state: GameState,
        *,
        question: str,
        requested_likelihood: Likelihood,
        cancel_token: CancellationToken | None = None,
    ) -> CapabilityOracleGuardResult:
        del state, cancel_token
        self.calls.append((question, requested_likelihood))
        return self._result


class FakeCharacterEffectUpdater:
    def __init__(
        self,
        mutate: Callable[[GameState, str], tuple[str, ...]] | None = None,
    ) -> None:
        self._mutate = mutate
        self.calls: list[tuple[str, str, str]] = []

    def update_character_effects(  # noqa: PLR0913
        self,
        state: GameState,
        *,
        player_input: str,
        outcome: OracleOutcome,
        execution_context: str | None,
        narrative_text: str,
        cancel_token: CancellationToken | None = None,
    ) -> CharacterEffectUpdateResult:
        del execution_context, cancel_token
        self.calls.append((player_input, outcome.summary, narrative_text))
        if self._mutate is None:
            return CharacterEffectUpdateResult()
        summaries = self._mutate(state, narrative_text)
        return CharacterEffectUpdateResult(changed=bool(summaries), summaries=summaries)


class CountingNarrative:
    _config = NarrativeConfig(model="", api_key=None, base_url=None)

    def __init__(self) -> None:
        self.calls = 0

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
        del cancel_token, execution_context, memory_context, scene_messages
        self.calls += 1
        return f"GEN {self.calls}: {outcome.summary} / {player_input} / chaos {state.chaos_factor}"


class SequencedNarrative:
    _config = NarrativeConfig(model="", api_key=None, base_url=None)

    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self.calls = 0

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
        del (
            state,
            outcome,
            player_input,
            execution_context,
            memory_context,
            scene_messages,
            cancel_token,
        )
        response = self._responses[min(self.calls, len(self._responses) - 1)]
        self.calls += 1
        return response


class CapturingNarrative:
    _config = NarrativeConfig(model="", api_key=None, base_url=None)

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

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
        del state, outcome, cancel_token
        self.calls.append(
            {
                "player_input": player_input,
                "execution_context": execution_context,
                "memory_context": memory_context,
                "scene_messages": [] if scene_messages is None else list(scene_messages),
            },
        )
        return f"CAPTURED: {player_input}"


class CapturingStreamingNarrative(CapturingNarrative):
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
    ) -> Generator[CompletionDelta, None, str]:
        del state, outcome, cancel_token
        self.calls.append(
            {
                "player_input": player_input,
                "execution_context": execution_context,
                "memory_context": memory_context,
                "scene_messages": [] if scene_messages is None else list(scene_messages),
            },
        )
        yield CompletionDelta(content=f"STREAMED: {player_input}")
        return f"STREAMED: {player_input}"


class SlowStreamingNarrative(FakeNarrative):
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
    ) -> Generator[CompletionDelta, None, str]:
        del state, outcome, player_input, execution_context, memory_context, scene_messages
        yield CompletionDelta(thinking="Working...")
        while True:
            if cancel_token is not None:
                cancel_token.raise_if_cancelled()
            yield CompletionDelta(content="...")
