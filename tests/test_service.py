from collections.abc import Callable, Generator
from pathlib import Path
from threading import Event
from typing import cast

import pytest

from dungeon_master.cairn import CairnEngine, SurvivalUpdate
from dungeon_master.campaign import (
    CampaignWorldResult,
    CharacterDraftMode,
    CharacterDraftResult,
    CharacterQuizResult,
    CharacterTemplatesResult,
)
from dungeon_master.cancel import CancellationRegistry, CancellationToken, RequestCancelledError
from dungeon_master.continuity_classifier import ContinuityUpdateScope
from dungeon_master.memory import LocationMemory, MemoryState
from dungeon_master.models import (
    NPC,
    AttackStance,
    CairnAbility,
    CairnCharacterState,
    CairnDayPhase,
    CairnItemEffectKind,
    CairnItemPower,
    CairnItemPowerKind,
    CairnItemState,
    CairnItemTag,
    CairnMechanicsSource,
    CairnResolution,
    CairnRestKind,
    CairnSurvivalAction,
    CairnTimeAdvance,
    CampaignEndReason,
    CampaignStatus,
    CharacterQuiz,
    CharacterQuizAnswer,
    CharacterQuizOption,
    CharacterQuizQuestion,
    CharacterSheet,
    EncounterInitiator,
    EncounterState,
    EnemyCombatant,
    EventType,
    GameState,
    GameThread,
    InventoryItem,
    Likelihood,
    NPCPlayerLabelKind,
    NPCStatus,
    OracleKind,
    OracleOutcome,
    PartyMember,
    RetreatOutcome,
    StageStatus,
    ThreadStatus,
)
from dungeon_master.narrative import CompletionDelta, NarrativeConfig
from dungeon_master.npc_updater import (
    GeneratedNPCUpdateBatch,
    LegacyNPCRosterRepairResult,
    NPCUpdateResult,
)
from dungeon_master.oracle import OracleEngine
from dungeon_master.service import TURN_STREAM_STAGE_ORDER, GameService
from dungeon_master.state_store import StateStore
from dungeon_master.thread_updater import GeneratedThreadUpdateBatch, ThreadUpdateResult
from dungeon_master.turn_router import (
    PlannedTurnOp,
    PlannedTurnOpKind,
    RoutedTurn,
    TurnPlan,
    TurnRoute,
    TurnRouter,
)
from tests.factories import sample_state


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
    def generate(self, character: CharacterSheet) -> GameState:
        state = sample_state()
        state.character = character
        state.player_notes = character.backstory
        return state

    def generate_result(self, character: CharacterSheet) -> CampaignWorldResult:
        return CampaignWorldResult(state=self.generate(character))

    def iter_generate(
        self,
        character: CharacterSheet,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, CampaignWorldResult]:
        del cancel_token
        result = self.generate_result(character)
        yield CompletionDelta(content=result.state.model_dump_json())
        return result


class FakeCharacterGenerator:
    def setup_state(self) -> GameState:
        return sample_state()

    def generate_templates(self) -> list[CharacterSheet]:
        return [sample_state().character]

    def generate_templates_result(self) -> CharacterTemplatesResult:
        return CharacterTemplatesResult(templates=self.generate_templates())

    def iter_generate_templates(
        self,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, CharacterTemplatesResult]:
        del cancel_token
        result = self.generate_templates_result()
        yield CompletionDelta(content=result.templates[0].model_dump_json())
        return result

    def generate_draft(
        self,
        *,
        mode: CharacterDraftMode,
        prompt: str | None,
        template: CharacterSheet | None,
    ) -> CharacterSheet:
        del mode, prompt, template
        return sample_state().character

    def generate_draft_result(
        self,
        *,
        mode: CharacterDraftMode,
        prompt: str | None,
        template: CharacterSheet | None,
    ) -> CharacterDraftResult:
        return CharacterDraftResult(
            draft=self.generate_draft(mode=mode, prompt=prompt, template=template),
        )

    def iter_generate_draft(
        self,
        *,
        mode: CharacterDraftMode,
        prompt: str | None,
        template: CharacterSheet | None,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, CharacterDraftResult]:
        del cancel_token
        result = self.generate_draft_result(mode=mode, prompt=prompt, template=template)
        yield CompletionDelta(content=result.draft.model_dump_json())
        return result

    def generate_quiz(self, concept: str) -> CharacterQuiz:
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

    def generate_quiz_result(self, concept: str) -> CharacterQuizResult:
        return CharacterQuizResult(quiz=self.generate_quiz(concept))

    def iter_generate_quiz(
        self,
        concept: str,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, CharacterQuizResult]:
        del cancel_token
        result = self.generate_quiz_result(concept)
        yield CompletionDelta(content=result.quiz.model_dump_json())
        return result

    def generate_quizzed_draft(
        self,
        *,
        concept: str,
        answers: list[CharacterQuizAnswer],
        final_note: str | None,
    ) -> CharacterSheet:
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
    ) -> CharacterDraftResult:
        return CharacterDraftResult(
            draft=self.generate_quizzed_draft(
                concept=concept,
                answers=answers,
                final_note=final_note,
            ),
        )

    def iter_generate_quizzed_draft(
        self,
        *,
        concept: str,
        answers: list[CharacterQuizAnswer],
        final_note: str | None,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, CharacterDraftResult]:
        del cancel_token
        result = self.generate_quizzed_draft_result(
            concept=concept,
            answers=answers,
            final_note=final_note,
        )
        yield CompletionDelta(content=result.draft.model_dump_json())
        return result


class SetupCharacterGenerator(FakeCharacterGenerator):
    def setup_state(self) -> GameState:
        state = sample_state()
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
        del state, execution_context, memory_context, cancel_token
        if narrative_text is None:
            self.calls.append((player_input, outcome.summary))
        else:
            self.post_calls.append((player_input, outcome.summary, narrative_text))
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
        del state, execution_context, memory_context, cancel_token
        if narrative_text is None:
            self.calls.append((player_input, outcome.summary))
        else:
            self.post_calls.append((player_input, outcome.summary, narrative_text))
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


class FakeContinuityClassifier:
    def __init__(self, scope: ContinuityUpdateScope) -> None:
        self._scope = scope
        self.calls: list[tuple[str, str, str | None]] = []

    def classify_update_scope(  # noqa: PLR0913
        self,
        state: GameState,
        *,
        player_input: str,
        outcome: OracleOutcome,
        execution_context: str | None = None,
        narrative_text: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> ContinuityUpdateScope:
        del state, execution_context, cancel_token
        self.calls.append((player_input, outcome.summary, narrative_text))
        return self._scope


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


class FakeCairnEngine:
    def ensure_character_state(
        self,
        state: GameState,
        *,
        allow_backfill: bool,
        cancel_token: CancellationToken | None = None,
    ) -> bool:
        del cancel_token
        if state.character.cairn.source != CairnMechanicsSource.UNSET:
            return False
        if not allow_backfill:
            return False
        state.character.cairn = CairnCharacterState(
            source=CairnMechanicsSource.NARRATIVE_BACKFILL,
            backfill_version=3,
            skills=["Shrine lore"],
            abilities=["Condemn sorcery"],
            str_score=14,
            dex_score=12,
            wil_score=15,
            max_str_score=14,
            max_dex_score=12,
            max_wil_score=15,
            hp=4,
            max_hp=4,
            primary_weapon_item_id=state.character.inventory[0].id,
        )
        for item in state.character.inventory:
            item.cairn = CairnItemState(
                source=CairnMechanicsSource.NARRATIVE_BACKFILL,
                backfill_version=3,
                tags=[CairnItemTag.WEAPON] if item == state.character.inventory[0] else [],
                weapon_damage_die=6 if item == state.character.inventory[0] else None,
                equipped=item == state.character.inventory[0],
            )
        state.character.cairn.slots_used = len(state.character.inventory)
        return True

    def resolve_save(
        self,
        state: GameState,
        ability: CairnAbility,
        reason: str,
        *,
        actor_id: str | None = None,
    ) -> OracleOutcome:
        del actor_id
        return OracleOutcome(
            kind=OracleKind.SAVE,
            summary=f"{ability.value} save passed: {reason}",
            chaos_factor=state.chaos_factor,
            cairn=CairnResolution(ability=ability, target=12, success=True),
        )

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
        del actor_id, cancel_token
        return OracleOutcome(
            kind=OracleKind.ATTACK,
            summary=f"Attack against {target_name}.",
            chaos_factor=state.chaos_factor,
            cairn=CairnResolution(
                weapon_item_id=weapon_item_id,
                target_name=target_name,
                target_armor=target_armor,
                attack_stance=stance,
                base_damage=5,
                damage_after_armor=max(0, 5 - target_armor),
            ),
        )

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
        del actor_id, in_combat, armor_applies
        state.character.cairn.hp = max(0, state.character.cairn.hp - amount)
        state.character.cairn.str_score = min(
            state.character.cairn.str_score,
            state.character.cairn.max_str_score,
        )
        return OracleOutcome(
            kind=OracleKind.HARM,
            summary=f"Harm from {source}.",
            chaos_factor=state.chaos_factor,
            cairn=CairnResolution(
                target_name=source,
                base_damage=amount,
                damage_after_armor=amount,
                hp_before=4,
                hp_after=state.character.cairn.hp,
                str_before=state.character.cairn.max_str_score,
                str_after=state.character.cairn.str_score,
            ),
        )

    def resolve_enemy_opener(
        self,
        state: GameState,
        *,
        source: str,
        text: str,
        cancel_token: CancellationToken | None = None,
    ) -> OracleOutcome:
        del cancel_token
        state.encounter = EncounterState(
            active=True,
            round_number=2,
            first_round_dex_gate_pending=False,
            initiator=EncounterInitiator.ENEMY,
            combatants=[EnemyCombatant(name=source, hp=4, max_hp=4)],
            notes="A hostile foe seized the initiative.",
        )
        state.character.cairn.hp = max(0, state.character.cairn.hp - 1)
        return OracleOutcome(
            kind=OracleKind.HARM,
            summary=f"{source} struck first: {text}",
            chaos_factor=state.chaos_factor,
            cairn=CairnResolution(
                combat_round=1,
                combat_started=True,
                combat_active=True,
                combat_initiator=EncounterInitiator.ENEMY,
                player_acted=False,
                target_name=source,
                damage_after_armor=1,
                hp_before=4,
                hp_after=state.character.cairn.hp,
                str_before=state.character.cairn.max_str_score,
                str_after=state.character.cairn.str_score,
                enemy_damage=1,
                enemy_damage_source=source,
            ),
        )

    def recover(
        self,
        state: GameState,
        kind: CairnRestKind,
        *,
        actor_id: str | None = None,
    ) -> OracleOutcome:
        del actor_id
        state.character.cairn.hp = state.character.cairn.max_hp
        return OracleOutcome(
            kind=OracleKind.RECOVERY,
            summary=f"Recovery: {kind.value}",
            chaos_factor=state.chaos_factor,
            cairn=CairnResolution(rest_kind=kind, hp_before=0, hp_after=state.character.cairn.hp),
        )

    def advance_survival_clock(
        self,
        state: GameState,
        *,
        time_advance: CairnTimeAdvance,
        actions: tuple[CairnSurvivalAction, ...] = (),
        actor_id: str | None = None,
        extra_days: int = 0,
    ) -> SurvivalUpdate:
        del actor_id
        survival = state.character.cairn.survival
        before_day = survival.day_number
        before_phase = survival.day_phase
        before_meal = survival.watches_since_meal
        before_sleep = survival.watches_since_sleep
        if time_advance == CairnTimeAdvance.WATCH:
            survival.watch_index = (survival.watch_index + 1) % 6
        elif time_advance == CairnTimeAdvance.DAY:
            survival.watch_index = (survival.watch_index + 3) % 6
        elif time_advance == CairnTimeAdvance.OVERNIGHT:
            survival.day_number += 1
            survival.watch_index = 0
        survival.day_number += extra_days
        if CairnSurvivalAction.EAT in actions:
            survival.watches_since_meal = 0
        if CairnSurvivalAction.SLEEP in actions:
            survival.watches_since_sleep = 0
        phase_after = CairnDayPhase.DAWN if survival.watch_index == 0 else before_phase
        return SurvivalUpdate(
            summary="Survival clock updated in fake engine.",
            resolution=CairnResolution(
                time_advance=time_advance,
                day_number_before=before_day,
                day_number_after=survival.day_number,
                day_phase_before=before_phase,
                day_phase_after=phase_after,
                watches_since_meal_before=before_meal,
                watches_since_meal_after=survival.watches_since_meal,
                watches_since_sleep_before=before_sleep,
                watches_since_sleep_after=survival.watches_since_sleep,
                deprived_before=False,
                deprived_after=False,
            ),
        )

    def resolve_retreat(self, state: GameState, reason: str) -> OracleOutcome:
        state.encounter.active = False
        state.encounter.notes = "You escaped the encounter."
        return OracleOutcome(
            kind=OracleKind.RETREAT,
            summary=f"Retreat resolved: {reason}",
            chaos_factor=state.chaos_factor,
            cairn=CairnResolution(
                ability=CairnAbility.DEX,
                target=12,
                success=True,
                retreat_outcome=RetreatOutcome.ESCAPED,
                combat_active=False,
            ),
        )

    def set_item_equipped(
        self,
        state: GameState,
        *,
        item_id: str,
        equipped: bool,
        actor_id: str | None = None,
    ) -> None:
        del actor_id
        for item in state.character.inventory:
            item.cairn.equipped = item.id == item_id if equipped else False
        if equipped:
            state.character.cairn.primary_weapon_item_id = item_id

    def acquire_items(
        self,
        state: GameState,
        *,
        text: str,
        actor_id: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> str:
        del actor_id, cancel_token
        lantern = InventoryItem(
            name="Pilgrim lantern",
            details="Taken during play.",
            cairn=CairnItemState(
                source=CairnMechanicsSource.EXPLICIT,
                tags=[CairnItemTag.LIGHT, CairnItemTag.UTILITY],
                slots=1,
                uses=3,
                equipped="ready" in text.lower(),
            ),
        )
        purse = InventoryItem(
            name="Purse of old silver",
            details="A small bundle of spendable coin.",
            cairn=CairnItemState(
                source=CairnMechanicsSource.EXPLICIT,
                tags=[CairnItemTag.PETTY, CairnItemTag.UTILITY],
                slots=0,
            ),
        )
        state.character.inventory.extend([lantern, purse])
        state.character.cairn.slots_used = sum(
            item.cairn.slots for item in state.character.inventory
        )
        return "Acquired Pilgrim lantern, Purse of old silver."

    def use_item(
        self,
        state: GameState,
        *,
        item_id: str,
        intent: str,
        actor_id: str | None = None,
    ) -> OracleOutcome:
        del actor_id
        for item in list(state.character.inventory):
            if item.id != item_id:
                continue
            if item.cairn.uses is None:
                summary = f"Used {item.name}: {intent}. No limited uses were consumed."
                return OracleOutcome(
                    kind=OracleKind.PLAYER_ACTION,
                    summary=summary,
                    chaos_factor=state.chaos_factor,
                    cairn=CairnResolution(item_id=item.id, item_name=item.name),
                )
            remaining = item.cairn.uses - 1
            if remaining <= 0:
                state.character.inventory = [
                    candidate for candidate in state.character.inventory if candidate.id != item_id
                ]
                summary = f"Used {item.name}: final use spent, item exhausted and removed."
                return OracleOutcome(
                    kind=OracleKind.PLAYER_ACTION,
                    summary=summary,
                    chaos_factor=state.chaos_factor,
                    cairn=CairnResolution(
                        item_id=item.id,
                        item_name=item.name,
                        uses_before=item.cairn.uses,
                        uses_after=None,
                    ),
                )
            item.cairn.uses = remaining
            summary = f"Used {item.name}: {remaining} uses remain."
            return OracleOutcome(
                kind=OracleKind.PLAYER_ACTION,
                summary=summary,
                chaos_factor=state.chaos_factor,
                cairn=CairnResolution(
                    item_id=item.id,
                    item_name=item.name,
                    uses_before=remaining + 1,
                    uses_after=remaining,
                ),
            )
        message = f"Unknown inventory item: {item_id}"
        raise ValueError(message)

    def drop_item(
        self,
        state: GameState,
        *,
        item_id: str,
        actor_id: str | None = None,
    ) -> str:
        del actor_id
        for item in list(state.character.inventory):
            if item.id != item_id:
                continue
            state.character.inventory = [
                candidate for candidate in state.character.inventory if candidate.id != item_id
            ]
            return f"Dropped {item.name}."
        message = f"Unknown inventory item: {item_id}"
        raise ValueError(message)

    def backfill_companion_sheet(
        self,
        state: GameState,
        authored: CharacterSheet,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> CharacterSheet:
        del state, cancel_token
        authored.cairn = CairnCharacterState(
            source=CairnMechanicsSource.EXPLICIT,
            hp=3,
            max_hp=3,
            str_score=10,
            dex_score=11,
            wil_score=12,
            max_str_score=10,
            max_dex_score=11,
            max_wil_score=12,
        )
        authored.inventory = [
            InventoryItem(
                name=f"{authored.name}'s walking stick",
                details="A companion's practical weapon.",
                cairn=CairnItemState(
                    source=CairnMechanicsSource.EXPLICIT,
                    tags=[CairnItemTag.WEAPON],
                    weapon_damage_die=6,
                    equipped=True,
                ),
            ),
        ]
        return authored


class FatalFakeCairnEngine(FakeCairnEngine):
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
        del actor_id, in_combat, armor_applies
        state.character.cairn.hp = 0
        state.character.cairn.str_score = 0
        state.character.cairn.dead = True
        return OracleOutcome(
            kind=OracleKind.HARM,
            summary=f"Fatal harm from {source}.",
            chaos_factor=state.chaos_factor,
            cairn=CairnResolution(
                target_name=source,
                base_damage=amount,
                damage_after_armor=amount,
                hp_before=1,
                hp_after=0,
                str_before=1,
                str_after=0,
            ),
        )


def scripted_classifier(text: str, likelihood: Likelihood | None) -> RoutedTurn:  # noqa: PLR0911
    if text == "Is the abbey gate watched?":
        return RoutedTurn(
            route=TurnRoute.YES_NO,
            text=text,
            likelihood=likelihood or Likelihood.LIKELY,
        )
    if text == "I cross the bone bridge before dawn.":
        return RoutedTurn(route=TurnRoute.SCENE_CHECK, text=text)
    if text == "I balance across the abbey beam.":
        return RoutedTurn(route=TurnRoute.SAVE, text=text, ability=CairnAbility.DEX)
    if text == "I swing my cudgel at the abbey ghoul.":
        return RoutedTurn(
            route=TurnRoute.ATTACK,
            text=text,
            target_name="Abbey ghoul",
            stance=AttackStance.NORMAL,
        )
    if text == "I catch my breath and drink water.":
        return RoutedTurn(
            route=TurnRoute.RECOVERY,
            text=text,
            rest_kind=CairnRestKind.BREATHER,
        )
    if text == "I draw the test knife.":
        return RoutedTurn(
            route=TurnRoute.EQUIP,
            text=text,
            item_name="Test knife",
            equipped=True,
        )
    if text == "I fall back through the chapel arch.":
        return RoutedTurn(route=TurnRoute.RETREAT, text=text)
    return RoutedTurn(route=TurnRoute.PLAYER_ACTION, text=text)


def test_service_commits_oracle_turn_with_narration(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    state = service.ask_oracle("Is the abbey gate watched?", Likelihood.LIKELY)

    assert len(state.oracle_history) == 1
    assert len(state.action_log) == 2
    assert state.action_log[-1].content.startswith("FAKE:")


def test_service_persists_memory_sidecar_after_committed_turn(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    service.ask_oracle("Is the abbey gate watched?", Likelihood.LIKELY)
    memory = store.load_memory()

    assert memory.turn_count == 1
    assert memory.recent_turn_summaries[-1].oracle_kind == OracleKind.YES_NO
    assert memory.current_scene_summary


def test_narrator_context_rebuilds_from_checkpoints_not_stale_sidecar(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "game_state.json")
    narrative = CapturingNarrative()
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=narrative,
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    first = service.submit_player_action("I leave the chapel behind.")
    stale = store.load_memory()
    stale.location_memory = [
        LocationMemory(
            location_key=stale.current_scene_key,
            label=first.current_scene,
            summary="Player asked: We need to find a quest in the chapel.",
            last_touched_turn=1,
            recent_developments=["We need to find a quest in the chapel."],
        ),
    ]
    store.save_memory(stale)

    service.submit_player_action("I ask Kaelen whether he can hold the rear wall.")
    latest_call = narrative.calls[-1]
    memory_context = cast("str", latest_call["memory_context"])
    scene_messages = cast("list[dict[str, str]]", latest_call["scene_messages"])

    assert "We need to find a quest" not in memory_context
    assert "I leave the chapel behind." in memory_context
    assert scene_messages == [
        {
            "role": "user",
            "content": "I leave the chapel behind.",
        },
        {
            "role": "assistant",
            "content": "CAPTURED: I leave the chapel behind.",
        },
    ]


def test_streamed_narrator_context_uses_deferred_checkpoint_override(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "game_state.json")
    narrative = CapturingStreamingNarrative()
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=narrative,
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    service.submit_player_action("I leave the chapel behind.")
    stale = store.load_memory()
    stale.location_memory = [
        LocationMemory(
            location_key=stale.current_scene_key,
            label=stale.active_location_key,
            summary="Player asked: We need to find a quest in the chapel.",
            last_touched_turn=1,
            recent_developments=["We need to find a quest in the chapel."],
        ),
    ]
    store.save_memory(stale)

    stream = service.stream_submit_player_action(
        "I ask Kaelen whether he can hold the rear wall.",
    )
    for _ in stream:
        pass
    latest_call = narrative.calls[-1]
    memory_context = cast("str", latest_call["memory_context"])
    scene_messages = cast("list[dict[str, str]]", latest_call["scene_messages"])

    assert "We need to find a quest" not in memory_context
    assert "I ask Kaelen whether he can hold the rear wall." in memory_context
    assert scene_messages == [
        {
            "role": "user",
            "content": "I leave the chapel behind.",
        },
        {
            "role": "assistant",
            "content": "CAPTURED: I leave the chapel behind.",
        },
    ]


def test_service_scene_check_updates_current_scene(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    state = service.check_scene("I arrive before midnight.")

    assert state.scene_number == 2
    assert state.current_scene == "Interrupted before: I arrive before midnight."
    assert len(state.oracle_history) == 1


def test_service_player_action_does_not_require_oracle_roll(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    state = service.submit_player_action("I listen at the abbey door.")

    assert state.oracle_history[0].rolls == []
    assert state.action_log[0].title == "Player action"
    assert state.action_log[1].title == "Narrative response"


def test_service_player_turn_routes_question_through_oracle(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        turn_router=TurnRouter(classifier=scripted_classifier),
    )

    state = service.submit_player_turn("Is the abbey gate watched? [likely]")

    assert state.action_log[0].title == "Player action"
    assert state.action_log[1].title == "Oracle answer"
    assert state.action_log[2].title == "Narrative response"
    assert state.oracle_history[0].kind == "yes_no"
    assert state.oracle_history[0].likelihood == Likelihood.LIKELY


def test_service_player_turn_routes_scene_transition(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        turn_router=TurnRouter(classifier=scripted_classifier),
    )

    state = service.submit_player_turn("I cross the bone bridge before dawn.")

    assert state.action_log[0].title == "Player action"
    assert state.action_log[1].title == "Scene check"
    assert state.scene_number == 2
    assert state.oracle_history[0].kind == "scene_check"


def test_service_player_turn_routes_obvious_save(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        turn_router=TurnRouter(classifier=scripted_classifier),
    )

    state = service.submit_player_turn("I balance across the abbey beam.")

    assert state.action_log[0].title == "Player action"
    assert state.action_log[1].title == "Cairn save"
    assert state.oracle_history[0].kind == "save"
    assert state.oracle_history[0].cairn is not None
    assert state.oracle_history[0].cairn.ability == CairnAbility.DEX


def test_service_player_turn_routes_attack(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        turn_router=TurnRouter(classifier=scripted_classifier),
    )

    state = service.submit_player_turn("I swing my cudgel at the abbey ghoul.")

    assert state.action_log[0].title == "Player action"
    assert state.action_log[1].title == "Attack resolution"
    assert state.oracle_history[0].kind == "attack"
    assert state.oracle_history[0].cairn is not None
    assert state.oracle_history[0].cairn.target_name == "Abbey ghoul"


def test_service_player_turn_routes_enemy_opener_into_tracked_combat(tmp_path: Path) -> None:
    def ambush_classifier(text: str, likelihood: Likelihood | None) -> TurnPlan:
        del likelihood
        return TurnPlan(
            route=TurnRoute.HARM,
            text=text,
            ops=(
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.ENEMY_OPENER,
                    text=text,
                    harm_source="Abbey ghoul",
                ),
            ),
        )

    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        turn_router=TurnRouter(classifier=ambush_classifier),
    )

    state = service.submit_player_turn(
        "The abbey ghoul drops from the choir loft and claws me before I can raise my cudgel.",
    )

    assert state.action_log[0].title == "Player action"
    assert state.action_log[1].title == "Ambush resolution"
    assert state.oracle_history[0].kind == "harm"
    assert state.oracle_history[0].cairn is not None
    assert state.oracle_history[0].cairn.combat_initiator == EncounterInitiator.ENEMY
    assert state.oracle_history[0].cairn.combat_started is True
    assert state.encounter.active is True
    assert state.encounter.initiator == EncounterInitiator.ENEMY


def test_service_player_turn_routes_recovery(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        turn_router=TurnRouter(classifier=scripted_classifier),
    )

    state = service.submit_player_turn("I catch my breath and drink water.")

    assert state.action_log[0].title == "Player action"
    assert state.action_log[1].title == "Recovery"
    assert state.oracle_history[0].kind == "recovery"
    assert state.oracle_history[0].cairn is not None
    assert state.oracle_history[0].cairn.rest_kind == CairnRestKind.BREATHER


def test_service_player_turn_commits_survival_clock_advance(tmp_path: Path) -> None:
    def waiting_classifier(text: str, _likelihood: Likelihood | None) -> TurnPlan:
        return TurnPlan(
            route=TurnRoute.PLAYER_ACTION,
            text=text,
            time_advance=CairnTimeAdvance.WATCH,
            ops=(PlannedTurnOp(kind=PlannedTurnOpKind.NARRATE, text=text),),
        )

    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=CairnEngine(
            seed=1,
            config=NarrativeConfig(model="", api_key=None, base_url=None),
        ),
        turn_router=TurnRouter(classifier=waiting_classifier),
    )
    seeded = sample_state()
    seeded.character.cairn = CairnCharacterState(
        source=CairnMechanicsSource.EXPLICIT,
        str_score=12,
        dex_score=12,
        wil_score=10,
        max_str_score=12,
        max_dex_score=12,
        max_wil_score=10,
        hp=4,
        max_hp=4,
        primary_weapon_item_id=seeded.character.inventory[0].id,
    )
    seeded.character.inventory[0].cairn = CairnItemState(
        source=CairnMechanicsSource.EXPLICIT,
        tags=[CairnItemTag.WEAPON],
        weapon_damage_die=6,
        equipped=True,
    )
    service._store.save(seeded, create_checkpoint=False)  # noqa: SLF001

    state = service.submit_player_turn("I keep watch by the thorn hedge until dusk.")

    assert state.character.cairn.survival.watch_index == 1
    assert state.oracle_history[-1].cairn is not None
    assert state.oracle_history[-1].cairn.time_advance == CairnTimeAdvance.WATCH


def test_service_full_rest_eats_and_sleeps_before_recovery(tmp_path: Path) -> None:
    def full_rest_classifier(text: str, _likelihood: Likelihood | None) -> TurnPlan:
        return TurnPlan(
            route=TurnRoute.RECOVERY,
            text=text,
            time_advance=CairnTimeAdvance.OVERNIGHT,
            survival_actions=(CairnSurvivalAction.EAT, CairnSurvivalAction.SLEEP),
            ops=(
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.RECOVERY,
                    text=text,
                    rest_kind=CairnRestKind.FULL_REST,
                ),
            ),
        )

    store = StateStore(tmp_path / "game_state.json")
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=CairnEngine(
            seed=1,
            config=NarrativeConfig(model="", api_key=None, base_url=None),
        ),
        turn_router=TurnRouter(classifier=full_rest_classifier),
    )
    state = sample_state()
    state.character.cairn = CairnCharacterState(
        source=CairnMechanicsSource.EXPLICIT,
        str_score=12,
        dex_score=12,
        wil_score=10,
        max_str_score=12,
        max_dex_score=12,
        max_wil_score=10,
        hp=4,
        max_hp=4,
        primary_weapon_item_id=state.character.inventory[0].id,
    )
    state.character.inventory[0].cairn = CairnItemState(
        source=CairnMechanicsSource.EXPLICIT,
        tags=[CairnItemTag.WEAPON],
        weapon_damage_die=6,
        equipped=True,
    )
    state.character.cairn.hp = 1
    state.character.cairn.survival.watches_since_meal = 3
    state.character.cairn.survival.food_deprived = True
    state.character.cairn.deprived = True
    state.character.inventory.append(
        InventoryItem(
            name="Trail rations",
            details="Hard bread and salt fish.",
            cairn=CairnItemState(
                source=CairnMechanicsSource.EXPLICIT,
                tags=[CairnItemTag.SUPPLIES],
                slots=1,
                uses=None,
            ),
        ),
    )
    store.save(state, create_checkpoint=False)

    rested = service.submit_player_turn("I eat my trail rations and sleep by the fire.")

    assert rested.character.cairn.hp == rested.character.cairn.max_hp
    assert rested.character.cairn.deprived is False
    assert rested.character.cairn.survival.watches_since_meal == 0
    assert rested.character.cairn.survival.watches_since_sleep == 0
    assert rested.oracle_history[-1].cairn is not None
    assert rested.oracle_history[-1].cairn.ration_uses_before == 3
    assert rested.oracle_history[-1].cairn.ration_uses_after == 2


def test_service_player_turn_routes_retreat(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        turn_router=TurnRouter(classifier=scripted_classifier),
    )
    state = service.load_state()
    state.encounter = EncounterState(
        active=True,
        round_number=2,
        combatants=[EnemyCombatant(name="Abbey ghoul", hp=4, max_hp=4)],
    )
    store.save(state, create_checkpoint=False)

    retreated = service.submit_player_turn("I fall back through the chapel arch.")

    assert retreated.action_log[0].title == "Player action"
    assert retreated.action_log[1].title == "Retreat resolution"
    assert retreated.oracle_history[0].kind == "retreat"
    assert retreated.oracle_history[0].cairn is not None
    assert retreated.oracle_history[0].cairn.retreat_outcome == RetreatOutcome.ESCAPED


def test_service_player_turn_routes_equip(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        turn_router=TurnRouter(classifier=scripted_classifier),
    )

    state = service.submit_player_turn("I draw the test knife.")

    assert state.action_log[0].title == "Player action"
    assert state.action_log[1].title == "Narrative response"
    assert state.oracle_history[0].summary == "Equipment updated: Test knife equipped."


def test_service_player_turn_executes_compound_inventory_plan(tmp_path: Path) -> None:
    def compound_classifier(text: str, likelihood: Likelihood | None) -> TurnPlan:
        del likelihood
        return TurnPlan(
            route=TurnRoute.PLAYER_ACTION,
            text=text,
            ops=(
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.INSPECT_INVENTORY,
                    text="I check my supplies.",
                ),
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.DROP_ITEM,
                    text="I drop the test map.",
                    item_name="Test map",
                ),
            ),
        )

    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        turn_router=TurnRouter(classifier=compound_classifier),
    )

    state = service.submit_player_turn("I check my supplies and drop the map.")

    assert state.action_log[0].title == "Player action"
    assert state.action_log[1].title == "Narrative response"
    assert state.oracle_history[0].kind == OracleKind.PLAYER_ACTION
    assert [item.name for item in state.character.inventory] == ["Test knife"]
    assert "Dropped Test map." in state.action_log[1].content


def test_service_player_turn_executes_inventory_acquisition_plan(tmp_path: Path) -> None:
    def acquire_classifier(text: str, likelihood: Likelihood | None) -> TurnPlan:
        del likelihood
        return TurnPlan(
            route=TurnRoute.PLAYER_ACTION,
            text=text,
            ops=(
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.ACQUIRE_ITEM,
                    text="I loot the abbey ghoul for a lantern and a purse of coins.",
                ),
            ),
        )

    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        turn_router=TurnRouter(classifier=acquire_classifier),
    )

    state = service.submit_player_turn("I loot the abbey ghoul for a lantern and a purse of coins.")

    assert state.oracle_history[0].kind == OracleKind.PLAYER_ACTION
    assert [item.name for item in state.character.inventory] == [
        "Test knife",
        "Test map",
        "Pilgrim lantern",
        "Purse of old silver",
    ]
    assert "Acquired Pilgrim lantern, Purse of old silver." in state.action_log[1].content


def test_service_player_turn_transfers_inventory_to_companion(tmp_path: Path) -> None:
    def transfer_classifier(text: str, likelihood: Likelihood | None) -> TurnPlan:
        del likelihood
        return TurnPlan(
            route=TurnRoute.PLAYER_ACTION,
            text=text,
            ops=(
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.TRANSFER_ITEM,
                    text=text,
                    item_name="Test map",
                    source_actor_name="player",
                    target_actor_name="Brother Sava",
                ),
            ),
        )

    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        turn_router=TurnRouter(classifier=transfer_classifier),
    )
    state = service.load_state()
    state.character.cairn.source = CairnMechanicsSource.EXPLICIT
    state.character.inventory[1].cairn = CairnItemState(
        source=CairnMechanicsSource.EXPLICIT,
        slots=1,
    )
    state.character.cairn.slots_used = 2
    state.party_members.append(
        PartyMember(
            sheet=CharacterSheet(
                name="Brother Sava",
                cairn=CairnCharacterState(
                    source=CairnMechanicsSource.EXPLICIT,
                    hp=3,
                    max_hp=3,
                ),
            ),
        ),
    )
    service._save_state_commit(state, create_checkpoint=True)  # noqa: SLF001

    next_state = service.submit_player_turn("I hand the test map to Brother Sava.")

    assert [item.name for item in next_state.character.inventory] == ["Test knife"]
    assert [item.name for item in next_state.party_members[0].sheet.inventory] == ["Test map"]
    assert next_state.character.cairn.slots_used == 1
    assert next_state.party_members[0].sheet.cairn.slots_used == 1
    assert (
        "Transferred Test map from Test Wanderer to Brother Sava."
        in next_state.action_log[1].content
    )


def test_service_player_turn_recruits_visible_npc_to_party(tmp_path: Path) -> None:
    def recruit_classifier(text: str, likelihood: Likelihood | None) -> TurnPlan:
        del likelihood
        return TurnPlan(
            route=TurnRoute.PLAYER_ACTION,
            text=text,
            ops=(
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.RECRUIT_NPC,
                    text=text,
                    npc_name="Brother Sava",
                ),
            ),
        )

    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        turn_router=TurnRouter(classifier=recruit_classifier),
    )
    state = service.load_state()
    recruitable = NPC(
        name="Brother Sava",
        role="Lantern bearer",
        disposition="wary but willing",
    )
    state.npcs.append(recruitable)
    service._save_state_commit(state, create_checkpoint=True)  # noqa: SLF001

    next_state = service.submit_player_turn("I ask Brother Sava to join us.")

    assert len(next_state.party_members) == 1
    member = next_state.party_members[0]
    assert member.npc_id == recruitable.id
    assert member.display_label() == "Brother Sava"
    assert member.sheet.cairn.source == CairnMechanicsSource.EXPLICIT
    assert member.sheet.inventory[0].name == "Brother Sava's walking stick"
    assert next_state.npcs[-1].status == NPCStatus.RETIRED
    assert "Recruited Brother Sava into the party." in next_state.action_log[1].content


def test_service_player_turn_uses_holy_relic_as_structured_outcome(tmp_path: Path) -> None:
    def relic_classifier(text: str, likelihood: Likelihood | None) -> TurnPlan:
        del likelihood
        return TurnPlan(
            route=TurnRoute.PLAYER_ACTION,
            text=text,
            ops=(
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.USE_ITEM,
                    text=text,
                    item_name="leaden icon",
                ),
            ),
        )

    store = StateStore(tmp_path / "game_state.json")
    seeded = sample_state()
    seeded.character.cairn = CairnCharacterState(
        source=CairnMechanicsSource.EXPLICIT,
        wil_score=7,
        max_wil_score=10,
        hp=4,
        max_hp=4,
    )
    seeded.character.inventory.append(
        InventoryItem(
            name="Leaden icon",
            details="A cold icon of a nameless patriarch.",
            cairn=CairnItemState(
                source=CairnMechanicsSource.EXPLICIT,
                tags=[CairnItemTag.HOLY, CairnItemTag.RELIC, CairnItemTag.PETTY],
                slots=0,
                uses=1,
                power=CairnItemPower(
                    kind=CairnItemPowerKind.HOLY_RELIC,
                    name="Intercession of the Nameless Patriarch",
                    effect=CairnItemEffectKind.RESTORE_ATTRIBUTE,
                    effect_amount=1,
                    recharge_condition="Confess a true failing at a consecrated threshold.",
                ),
            ),
        ),
    )
    store.save(seeded, create_checkpoint=False)
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=CairnEngine(
            seed=1,
            config=NarrativeConfig(model="", api_key=None, base_url=None),
        ),
        turn_router=TurnRouter(classifier=relic_classifier),
    )

    state = service.submit_player_turn("I kiss the leaden icon and ask for intercession.")

    outcome = state.oracle_history[-1]
    assert outcome.kind == OracleKind.PLAYER_ACTION
    assert outcome.cairn is not None
    assert outcome.cairn.item_name == "Leaden icon"
    assert outcome.cairn.item_power_kind == CairnItemPowerKind.HOLY_RELIC
    assert outcome.cairn.wil_before == 7
    assert outcome.cairn.wil_after == 8
    assert state.character.cairn.wil_score == 8
    assert state.action_log[1].title == "Item use"
    assert "WIL restored 7->8" in state.action_log[-1].content


def test_service_explicit_inventory_acquire_records_system_and_narrative(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        turn_router=TurnRouter(classifier=scripted_classifier),
    )

    state = service.acquire_inventory("I buy a lantern and a purse of old silver.")

    assert state.action_log[0].title == "Inventory acquired"
    assert state.action_log[1].title == "Narrative response"
    assert state.oracle_history[0].summary == "Acquired Pilgrim lantern, Purse of old silver."
    assert [item.name for item in state.character.inventory][-2:] == [
        "Pilgrim lantern",
        "Purse of old silver",
    ]


def test_finalize_character_sets_ready_to_start(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=SetupCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    character = sample_state().character
    state = service.finalize_character(character)

    assert state.campaign_status == CampaignStatus.READY_TO_START
    assert state.character.name == character.name


def test_start_campaign_uses_finalized_character(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=SetupCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    character = sample_state().character.model_copy(deep=True)
    character.name = "Sable"
    service.finalize_character(character)
    state = service.start_campaign()

    assert state.campaign_status == CampaignStatus.ACTIVE
    assert state.character.name == "Sable"
    assert state.character.cairn.source == CairnMechanicsSource.NARRATIVE_BACKFILL
    assert state.character.cairn.slots_used >= 1
    assert state.character.cairn.primary_weapon_item_id is not None


def test_load_state_backfills_active_character_once(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    state = service.load_state()

    assert state.character.cairn.source == CairnMechanicsSource.NARRATIVE_BACKFILL
    assert state.character.cairn.max_hp >= 1
    assert any(
        item.cairn.source == CairnMechanicsSource.NARRATIVE_BACKFILL
        for item in state.character.inventory
    )


def test_load_state_syncs_dead_active_campaign_into_terminal_death_state(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")
    seeded = sample_state()
    seeded.character.cairn = CairnCharacterState(
        source=CairnMechanicsSource.EXPLICIT,
        str_score=0,
        dex_score=10,
        wil_score=10,
        max_str_score=10,
        max_dex_score=10,
        max_wil_score=10,
        hp=0,
        max_hp=4,
        dead=True,
    )
    store.save(seeded, create_checkpoint=False)

    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    loaded = service.load_state()
    persisted = store.load()

    assert loaded.campaign_status == CampaignStatus.ENDED
    assert loaded.campaign_end_reason == CampaignEndReason.DEATH
    assert loaded.campaign_end_summary == "Test Wanderer's campaign ended in death."
    assert persisted.campaign_status == CampaignStatus.ENDED
    assert persisted.campaign_end_reason == CampaignEndReason.DEATH


def test_end_campaign_marks_retirement_and_blocks_further_play(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    ended = service.end_campaign(
        reason=CampaignEndReason.RETIREMENT,
        summary="Vrtanes lays down the cudgel and leaves the chapel road behind.",
    )

    assert ended.campaign_status == CampaignStatus.ENDED
    assert ended.campaign_end_reason == CampaignEndReason.RETIREMENT
    assert (
        ended.campaign_end_summary
        == "Vrtanes lays down the cudgel and leaves the chapel road behind."
    )
    assert ended.action_log[-1].title == "Campaign ended"

    with pytest.raises(ValueError, match="retirement"):
        service.submit_player_turn("I keep walking down the ash-dark road.")


def test_end_campaign_marks_victory_with_default_summary(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    ended = service.end_campaign(reason=CampaignEndReason.VICTORY)

    assert ended.campaign_status == CampaignStatus.ENDED
    assert ended.campaign_end_reason == CampaignEndReason.VICTORY
    assert ended.campaign_end_summary == "Test Wanderer achieved a final victory."


def test_service_resolve_save_records_deterministic_outcome(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    state = service.resolve_cairn_save(CairnAbility.WIL, "Resist the bell's whisper.")

    assert state.oracle_history[-1].kind == "save"
    assert state.oracle_history[-1].cairn is not None
    assert state.oracle_history[-1].cairn.ability == CairnAbility.WIL


def test_service_attack_uses_primary_weapon(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    state = service.load_state()
    primary_weapon_id = state.character.cairn.primary_weapon_item_id
    assert primary_weapon_id is not None

    attacked = service.attack_target(
        target_name="Abbey ghoul",
        target_armor=1,
        weapon_item_id=primary_weapon_id,
        stance=AttackStance.NORMAL,
    )

    assert attacked.oracle_history[-1].kind == "attack"
    assert attacked.oracle_history[-1].cairn is not None
    assert attacked.oracle_history[-1].cairn.weapon_item_id == primary_weapon_id


def test_service_harm_can_trigger_str_loss(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    state = service.load_state()
    state.character.cairn.hp = 1
    store.save(state, create_checkpoint=False)

    harmed = service.suffer_harm(
        amount=5,
        source="Falling masonry",
        in_combat=True,
        armor_applies=False,
    )

    assert harmed.oracle_history[-1].kind == "harm"
    assert harmed.character.cairn.hp == 0
    assert harmed.character.cairn.str_score <= harmed.character.cairn.max_str_score


def test_service_fatal_harm_ends_campaign_in_death(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FatalFakeCairnEngine(),
    )

    state = service.load_state()
    state.character.cairn.hp = 1
    state.character.cairn.str_score = 1
    store.save(state, create_checkpoint=False)

    harmed = service.suffer_harm(
        amount=5,
        source="Falling masonry",
        in_combat=True,
        armor_applies=False,
    )

    assert harmed.campaign_status == CampaignStatus.ENDED
    assert harmed.campaign_end_reason == CampaignEndReason.DEATH
    assert harmed.campaign_end_summary is not None
    assert "Final turn: Fatal harm from Falling masonry." in harmed.campaign_end_summary
    assert harmed.action_log[-1].title == "Campaign ended"


def test_service_recovery_restores_hp(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    state = service.load_state()
    state.character.cairn.hp = 0
    store.save(state, create_checkpoint=False)

    recovered = service.recover_character(CairnRestKind.BREATHER)

    assert recovered.oracle_history[-1].kind == "recovery"
    assert recovered.character.cairn.hp == recovered.character.cairn.max_hp


def test_service_explicit_retreat_records_deterministic_outcome(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )
    state = service.load_state()
    state.encounter = EncounterState(
        active=True,
        round_number=2,
        combatants=[EnemyCombatant(name="Abbey ghoul", hp=4, max_hp=4)],
    )
    store.save(state, create_checkpoint=False)

    retreated = service.retreat_from_encounter("Break contact and reach the chapel arch.")

    assert retreated.oracle_history[-1].kind == "retreat"
    assert retreated.oracle_history[-1].cairn is not None
    assert retreated.oracle_history[-1].cairn.retreat_outcome == RetreatOutcome.ESCAPED


def test_generate_character_quiz_uses_concept(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=SetupCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    quiz = service.generate_character_quiz("An Armenian Apostolic paladin.")

    assert quiz.concept == "An Armenian Apostolic paladin."
    assert len(quiz.questions) >= 3


def test_generate_quizzed_draft_threads_answers_through(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=SetupCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    quiz = service.generate_character_quiz("A scarred deserter.")
    answers = [
        CharacterQuizAnswer(
            question_id=quiz.questions[0].id,
            prompt=quiz.questions[0].prompt,
            value="Wounded but standing.",
        ),
        CharacterQuizAnswer(
            question_id=quiz.questions[1].id,
            prompt=quiz.questions[1].prompt,
            value="A name I cannot say.",
        ),
        CharacterQuizAnswer(
            question_id=quiz.questions[2].id,
            prompt=quiz.questions[2].prompt,
            value="My old company.",
            is_other=True,
        ),
    ]

    draft = service.generate_quizzed_character_draft(
        concept="A scarred deserter.",
        answers=answers,
        final_note="One scar shaped like a sigil.",
    )

    assert draft.epithet == "A scarred deserter."
    assert "Wounded but standing." in draft.backstory
    assert "A name I cannot say." in draft.backstory
    assert "My old company." in draft.backstory
    assert draft.condition == "One scar shaped like a sigil."


def test_regenerate_response_preserves_oracle_outcome(tmp_path: Path) -> None:
    narrative = CountingNarrative()
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=narrative,
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    first = service.ask_oracle("Is the abbey gate watched?", Likelihood.LIKELY)
    first_event_id = first.action_log[-1].id
    first_outcome = first.oracle_history[-1]

    repaired = service.regenerate_response(first_event_id)
    latest_outcome = repaired.oracle_history[-1]

    assert latest_outcome.id == first_outcome.id
    assert latest_outcome.answer == first_outcome.answer
    assert repaired.action_log[-2].title == "Narrative regenerated"
    assert repaired.action_log[-1].title == "Narrative response"
    assert repaired.action_log[-1].content.startswith("GEN 2:")


def test_streamed_regenerate_does_not_duplicate_prior_narrative(tmp_path: Path) -> None:
    narrative = CountingNarrative()
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=narrative,
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        turn_router=TurnRouter(classifier=scripted_classifier),
    )

    stream = service.stream_submit_player_turn("Is the abbey gate watched? [likely]")
    for _ in stream:
        pass
    state = service.load_state()
    first_event_id = state.action_log[-1].id

    repaired = service.regenerate_response(first_event_id)
    narrative_events = [
        event for event in repaired.action_log if event.event_type == EventType.NARRATIVE
    ]

    assert len(narrative_events) == 1
    assert repaired.action_log[-2].title == "Narrative regenerated"
    assert repaired.action_log[-1].title == "Narrative response"


def test_regenerate_response_reapplies_post_narration_npc_disclosure(tmp_path: Path) -> None:
    narrative = SequencedNarrative(
        [
            "A nameless patriarch watches from the icon's cold lead face.",
            "The Hierophant watches from the icon's cold lead face.",
        ],
    )
    store = StateStore(tmp_path / "game_state.json")
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=narrative,
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )
    seeded = service.load_state()
    seeded.hidden_npcs.append(
        NPC(
            name="The Hierophant",
            role="Face-thief patriarch",
            disposition="patient malice",
        ),
    )
    store.save(seeded, create_checkpoint=True)

    first = service.ask_oracle("Is the abbey gate watched?", Likelihood.LIKELY)
    assert all(npc.name != "The Hierophant" for npc in first.npcs)
    first_event_id = first.action_log[-1].id

    repaired = service.regenerate_response(first_event_id)

    revealed = next(npc for npc in repaired.npcs if npc.name == "The Hierophant")
    assert revealed.player_knows_proper_name() is True
    assert repaired.oracle_history[-1].referenced_npc_ids == [revealed.id]
    assert all(npc.name != "The Hierophant" for npc in repaired.hidden_npcs)


def test_regenerate_response_rebuilds_scene_history_from_checkpoint(tmp_path: Path) -> None:
    narrative = CapturingNarrative()
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=narrative,
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    first = service.ask_oracle("Is the abbey gate watched?", Likelihood.LIKELY)
    first_event_id = first.action_log[-1].id

    repaired = service.regenerate_response(first_event_id)
    scene_messages = cast("list[dict[str, str]]", narrative.calls[-1]["scene_messages"])

    assert repaired.action_log[-1].content == (
        "CAPTURED: Oracle question: Is the abbey gate watched?"
    )
    assert scene_messages == []


def test_regenerate_response_preserves_later_directive_edits(tmp_path: Path) -> None:
    narrative = CountingNarrative()
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=narrative,
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    first = service.ask_oracle("Is the abbey gate watched?", Likelihood.LIKELY)
    first_event_id = first.action_log[-1].id
    service.update_directives(
        world_guidance="Keep miracles subtle and costly.",
        play_guidance="The hierophant cannot speak first.",
    )

    repaired = service.regenerate_response(first_event_id)

    assert repaired.directives.world_guidance == "Keep miracles subtle and costly."
    assert repaired.directives.play_guidance == "The hierophant cannot speak first."


def test_memory_sidecar_preserves_explicit_input_and_execution_context(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        turn_router=TurnRouter(classifier=scripted_classifier),
    )

    service.ask_oracle("Is the abbey gate watched?", Likelihood.LIKELY)
    service.submit_player_turn("I draw the test knife.")
    memory = store.load_memory()

    assert (
        memory.recent_turn_summaries[0].player_input
        == "Oracle question: Is the abbey gate watched?"
    )
    assert memory.recent_turn_summaries[-1].execution_context
    assert "Equipment updated" in memory.recent_turn_summaries[-1].execution_context


def test_service_thread_updater_creates_thread_and_persists_memory(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")

    def mutate(state: GameState, outcome: OracleOutcome) -> tuple[str, ...]:
        del outcome
        created = GameThread(
            title="The hierophant's unfinished demand",
            stakes="If ignored, the abbey's claim hardens into open pursuit.",
        )
        state.threads.append(created)
        return (created.id,)

    updater = FakeThreadUpdater(mutate=mutate)
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        thread_updater=updater,
    )

    state = service.submit_player_action("I accept the charge, but not the leash.")
    memory = store.load_memory()

    created = next(
        thread for thread in state.threads if thread.title == "The hierophant's unfinished demand"
    )
    assert updater.calls == []
    assert updater.post_calls == [
        (
            "I accept the charge, but not the leash.",
            state.oracle_history[-1].summary,
            state.action_log[-1].content,
        ),
    ]
    assert state.oracle_history[-1].referenced_thread_id == created.id
    assert state.oracle_history[-1].referenced_thread_ids == [created.id]
    assert any(
        loop.text.startswith("The hierophant's unfinished demand")
        for loop in memory.open_loops
    )


def test_service_continuity_classifier_can_skip_both_updaters(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")
    thread_updater = FakeThreadUpdater()
    npc_updater = FakeNpcUpdater()
    classifier = FakeContinuityClassifier(ContinuityUpdateScope.NONE)
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        thread_updater=thread_updater,
        npc_updater=npc_updater,
        continuity_classifier=classifier,
    )

    updated = service.submit_player_action("I keep moving and say nothing.")

    assert classifier.calls == [
        (
            "I keep moving and say nothing.",
            updated.oracle_history[-1].summary,
            updated.action_log[-1].content,
        ),
    ]
    assert thread_updater.calls == []
    assert npc_updater.calls == []
    assert thread_updater.post_calls == []
    assert npc_updater.post_calls == []
    assert updated.oracle_history[-1].referenced_thread_ids == []
    assert updated.oracle_history[-1].referenced_npc_ids == []


def test_service_skips_pre_narration_continuity_for_pure_narrate_turn(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "game_state.json")
    thread_updater = FakeThreadUpdater()
    npc_updater = FakeNpcUpdater()
    classifier = FakeContinuityClassifier(ContinuityUpdateScope.BOTH)
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        thread_updater=thread_updater,
        npc_updater=npc_updater,
        continuity_classifier=classifier,
        turn_router=TurnRouter(classifier=scripted_classifier),
    )

    updated = service.submit_player_turn("I study the icon and pray for intercession.")

    assert classifier.calls == [
        (
            "I study the icon and pray for intercession.",
            updated.oracle_history[-1].summary,
            updated.action_log[-1].content,
        ),
    ]
    assert thread_updater.calls == []
    assert npc_updater.calls == []
    assert thread_updater.post_calls == [
        (
            "I study the icon and pray for intercession.",
            updated.oracle_history[-1].summary,
            updated.action_log[-1].content,
        ),
    ]
    assert npc_updater.post_calls == [
        (
            "I study the icon and pray for intercession.",
            updated.oracle_history[-1].summary,
            updated.action_log[-1].content,
        ),
    ]
    assert updated.oracle_history[-1].kind == OracleKind.PLAYER_ACTION
    assert updated.oracle_history[-1].referenced_thread_ids == []
    assert updated.oracle_history[-1].referenced_npc_ids == []


def test_service_recon_turn_does_not_advance_scene_or_run_pre_narration_continuity(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "game_state.json")
    thread_updater = FakeThreadUpdater()
    npc_updater = FakeNpcUpdater()
    classifier = FakeContinuityClassifier(ContinuityUpdateScope.BOTH)

    def recon_classifier(text: str, likelihood: Likelihood | None) -> TurnPlan | RoutedTurn:
        if text == "Are there enemies along the goat-path?":
            return TurnPlan(
                route=TurnRoute.PLAYER_ACTION,
                text=text,
                ops=(
                    PlannedTurnOp(
                        kind=PlannedTurnOpKind.SEARCH_SCENE,
                        text=text,
                    ),
                ),
            )
        return scripted_classifier(text, likelihood)

    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        thread_updater=thread_updater,
        npc_updater=npc_updater,
        continuity_classifier=classifier,
        turn_router=TurnRouter(classifier=recon_classifier),
    )
    initial = service.load_state()

    updated = service.submit_player_turn("Are there enemies along the goat-path?")

    assert updated.scene_number == initial.scene_number
    assert updated.current_scene == initial.current_scene
    assert [event.title for event in updated.action_log] == [
        "Player action",
        "Narrative response",
    ]
    assert updated.oracle_history[-1].kind == OracleKind.PLAYER_ACTION
    assert "current vantage without advancing" in updated.action_log[-1].content
    assert classifier.calls == [
        (
            "Are there enemies along the goat-path?",
            updated.oracle_history[-1].summary,
            updated.action_log[-1].content,
        ),
    ]
    assert thread_updater.calls == []
    assert npc_updater.calls == []
    assert thread_updater.post_calls == [
        (
            "Are there enemies along the goat-path?",
            updated.oracle_history[-1].summary,
            updated.action_log[-1].content,
        ),
    ]
    assert npc_updater.post_calls == [
        (
            "Are there enemies along the goat-path?",
            updated.oracle_history[-1].summary,
            updated.action_log[-1].content,
        ),
    ]


def test_service_post_narration_continuity_can_touch_threads_and_npcs(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "game_state.json")

    def mutate_thread(state: GameState, outcome: OracleOutcome) -> tuple[str, ...]:
        del outcome
        created = GameThread(
            title="The patriarch's forgotten name",
            stakes="If pursued, the ruined chapel may reveal who still invokes it.",
        )
        state.threads.append(created)
        return (created.id,)

    def mutate_npc(state: GameState, outcome: OracleOutcome) -> tuple[str, ...]:
        del outcome
        created = NPC(
            name="Saint Vyr",
            role="Patriarch of the ruined chapel",
            disposition="silent in lead",
        )
        state.npcs.append(created)
        return (created.id,)

    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        thread_updater=FakeThreadUpdater(mutate=mutate_thread),
        npc_updater=FakeNpcUpdater(mutate=mutate_npc),
        continuity_classifier=FakeContinuityClassifier(ContinuityUpdateScope.BOTH),
        turn_router=TurnRouter(classifier=scripted_classifier),
    )

    updated = service.submit_player_turn("I study the icon and pray for intercession.")

    assert updated.oracle_history[-1].referenced_thread_ids
    assert updated.oracle_history[-1].referenced_npc_ids


def test_service_post_narration_continuity_can_skip_when_narration_adds_no_lore(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "game_state.json")
    thread_updater = FakeThreadUpdater()
    npc_updater = FakeNpcUpdater()
    classifier = FakeContinuityClassifier(ContinuityUpdateScope.NONE)
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        thread_updater=thread_updater,
        npc_updater=npc_updater,
        continuity_classifier=classifier,
        turn_router=TurnRouter(classifier=scripted_classifier),
    )

    updated = service.submit_player_turn("Do we know the patriarch's name?")

    assert classifier.calls == [
        (
            "Do we know the patriarch's name?",
            updated.oracle_history[-1].summary,
            updated.action_log[-1].content,
        ),
    ]
    assert thread_updater.post_calls == []
    assert npc_updater.post_calls == []
    assert updated.oracle_history[-1].referenced_thread_ids == []
    assert updated.oracle_history[-1].referenced_npc_ids == []


def test_service_continuity_classifier_can_run_only_thread_updater(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")

    def mutate(state: GameState, outcome: OracleOutcome) -> tuple[str, ...]:
        del outcome
        created = GameThread(
            title="The ferryman's warning grows teeth",
            stakes="If ignored, the crossing toll becomes a trap.",
        )
        state.threads.append(created)
        return (created.id,)

    thread_updater = FakeThreadUpdater(mutate=mutate)
    npc_updater = FakeNpcUpdater()
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        thread_updater=thread_updater,
        npc_updater=npc_updater,
        continuity_classifier=FakeContinuityClassifier(ContinuityUpdateScope.THREADS),
    )

    updated = service.submit_player_action("I accept the ferryman's warning.")

    created = next(
        thread for thread in updated.threads if thread.title == "The ferryman's warning grows teeth"
    )
    assert thread_updater.calls == []
    assert npc_updater.calls == []
    assert thread_updater.post_calls == [
        (
            "I accept the ferryman's warning.",
            updated.oracle_history[-1].summary,
            updated.action_log[-1].content,
        ),
    ]
    assert npc_updater.post_calls == []
    assert updated.oracle_history[-1].referenced_thread_ids == [created.id]
    assert updated.oracle_history[-1].referenced_npc_ids == []


def test_service_continuity_classifier_can_run_only_npc_updater(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")

    def mutate(state: GameState, outcome: OracleOutcome) -> tuple[str, ...]:
        del outcome
        created = NPC(
            name="Brother Vahagn",
            role="Bell-ringer hiding a blood debt",
            disposition="guarded",
        )
        state.npcs.append(created)
        return (created.id,)

    thread_updater = FakeThreadUpdater()
    npc_updater = FakeNpcUpdater(mutate=mutate)
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        thread_updater=thread_updater,
        npc_updater=npc_updater,
        continuity_classifier=FakeContinuityClassifier(ContinuityUpdateScope.NPCS),
    )

    updated = service.submit_player_action("I press the bell-ringer for the truth.")

    created = next(npc for npc in updated.npcs if npc.name == "Brother Vahagn")
    assert thread_updater.calls == []
    assert npc_updater.calls == []
    assert thread_updater.post_calls == []
    assert npc_updater.post_calls == [
        (
            "I press the bell-ringer for the truth.",
            updated.oracle_history[-1].summary,
            updated.action_log[-1].content,
        ),
    ]
    assert updated.oracle_history[-1].referenced_thread_ids == []
    assert updated.oracle_history[-1].referenced_npc_ids == [created.id]


def test_service_npc_updater_creates_npc_and_persists_memory(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")

    def mutate(state: GameState, outcome: OracleOutcome) -> tuple[str, ...]:
        del outcome
        created = NPC(
            name="Brother Vahagn",
            role="Bell-ringer hiding a blood debt",
            disposition="guarded",
        )
        state.npcs.append(created)
        return (created.id,)

    updater = FakeNpcUpdater(mutate=mutate)
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        npc_updater=updater,
    )

    state = service.submit_player_action("I ask the bell-ringer why he watches me.")
    memory = store.load_memory()

    created = next(npc for npc in state.npcs if npc.name == "Brother Vahagn")
    assert updater.calls == []
    assert updater.post_calls == [
        (
            "I ask the bell-ringer why he watches me.",
            state.oracle_history[-1].summary,
            state.action_log[-1].content,
        ),
    ]
    assert state.oracle_history[-1].referenced_npc_id == created.id
    assert state.oracle_history[-1].referenced_npc_ids == [created.id]
    assert any(card.npc_id == created.id for card in memory.npc_memory)


def test_service_load_state_repairs_legacy_npc_roster_once(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")
    legacy = sample_state()
    legacy.npc_roster_version = 1
    store.save(legacy, create_checkpoint=False)
    existing_id = legacy.npcs[0].id
    repair = LegacyNPCRosterRepairResult(
        introduced_npcs=(
            NPC(
                id=existing_id,
                name="Generated NPC One",
                role="Witness finally met in person",
                disposition="fearful",
            ),
        ),
        hidden_npcs=(
            NPC(
                name="The Hierophant",
                role="Face-thief patriarch",
                disposition="patient malice",
            ),
        ),
    )
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        npc_updater=FakeNpcUpdater(repair=repair),
    )

    state = service.load_state()
    reloaded = store.load()

    assert state.npc_roster_version == 2
    assert [npc.name for npc in state.npcs] == ["Generated NPC One"]
    assert [npc.name for npc in state.hidden_npcs] == ["The Hierophant"]
    assert state.npcs[0].id == existing_id
    assert reloaded.npc_roster_version == 2


def test_service_reveals_hidden_npc_named_in_narration(tmp_path: Path) -> None:
    class RevealingNarrative(FakeNarrative):
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
            return "The Hierophant steps from the ash-dark arch and finally speaks."

    store = StateStore(tmp_path / "game_state.json")
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=RevealingNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )
    state = service.load_state()
    state.hidden_npcs.append(
        NPC(
            name="The Hierophant",
            role="Face-thief patriarch",
            disposition="patient malice",
        ),
    )
    state.npcs = []
    store.save(state, create_checkpoint=False)

    updated = service.submit_player_action("I wait in terrified silence.")

    assert [npc.name for npc in updated.npcs] == ["The Hierophant"]
    assert updated.hidden_npcs == []
    assert updated.oracle_history[-1].referenced_npc_id == updated.npcs[0].id
    assert updated.oracle_history[-1].referenced_npc_ids == [updated.npcs[0].id]


def test_service_promotes_visible_descriptor_npc_when_true_name_is_narrated(
    tmp_path: Path,
) -> None:
    class NameGrantingNarrative(FakeNarrative):
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
            return "The Hierophant lifts the ash veil and finally offers his true name."

    store = StateStore(tmp_path / "game_state.json")
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=NameGrantingNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )
    state = service.load_state()
    state.npcs = [
        NPC(
            name="The Hierophant",
            role="Face-thief patriarch",
            disposition="patient malice",
            player_label="The ash-veiled bellringer",
            player_label_kind=NPCPlayerLabelKind.DESCRIPTOR,
        ),
    ]
    state.hidden_npcs = []
    store.save(state, create_checkpoint=False)

    updated = service.submit_player_action("I demand the bellringer name himself.")

    assert updated.npcs[0].player_label == "The Hierophant"
    assert updated.npcs[0].player_label_kind == NPCPlayerLabelKind.PROPER_NAME
    assert updated.oracle_history[-1].referenced_npc_ids == [updated.npcs[0].id]


def test_service_syncs_recruited_party_member_when_true_name_is_narrated(
    tmp_path: Path,
) -> None:
    class NameGrantingNarrative(FakeNarrative):
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
            return "The shivering youth lowers his hood. His name is Kaelen."

    store = StateStore(tmp_path / "game_state.json")
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=NameGrantingNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )
    state = service.load_state()
    npc = NPC(
        name="Kaelen",
        role="Fugitive guide from Oakhaven",
        disposition="steady after revealing himself",
        player_label="Shivering Youth",
        player_label_kind=NPCPlayerLabelKind.DESCRIPTOR,
    )
    state.npcs = [npc]
    state.party_members.append(
        PartyMember(
            sheet=CharacterSheet(
                name="Shivering Youth",
                archetype="Fugitive guide",
                epithet="grimly cooperative",
            ),
            npc_id=npc.id,
            loyalty="grimly cooperative",
        ),
    )
    store.save(state, create_checkpoint=False)

    updated = service.submit_player_action("I ask the youth for his name.")

    assert updated.npcs[0].player_label == "Kaelen"
    assert updated.npcs[0].player_label_kind == NPCPlayerLabelKind.PROPER_NAME
    assert updated.party_members[0].sheet.name == "Kaelen"
    assert updated.party_members[0].sheet.archetype == "Fugitive guide from Oakhaven"
    assert updated.party_members[0].sheet.epithet == "steady after revealing himself"
    assert updated.party_members[0].loyalty == "steady after revealing himself"


def test_service_only_persists_visible_npc_ids_on_outcomes(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")

    def mutate(state: GameState, outcome: OracleOutcome) -> tuple[str, ...]:
        del outcome
        hidden = NPC(
            name="The Hierophant",
            role="Face-thief patriarch",
            disposition="patient malice",
            player_label="The ash-veiled bellringer",
            player_label_kind=NPCPlayerLabelKind.DESCRIPTOR,
        )
        state.hidden_npcs.append(hidden)
        return (hidden.id,)

    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        npc_updater=FakeNpcUpdater(mutate=mutate),
    )

    updated = service.submit_player_action("I wait for the watcher to reveal himself.")

    assert [npc.name for npc in updated.hidden_npcs] == ["The Hierophant"]
    assert updated.oracle_history[-1].referenced_npc_id is None
    assert updated.oracle_history[-1].referenced_npc_ids == []


def test_service_update_directives_persists_without_action_log_event(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    state = service.update_directives(
        world_guidance="Keep miracles subtle and costly.",
        play_guidance="The hierophant cannot speak first.",
    )
    reloaded = store.load()

    assert state.directives.world_guidance == "Keep miracles subtle and costly."
    assert reloaded.directives.play_guidance == "The hierophant cannot speak first."
    assert all(event.title != "Campaign directives updated" for event in state.action_log)


def test_streamed_turn_thread_updater_can_resolve_thread(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")

    def mutate(state: GameState, outcome: OracleOutcome) -> tuple[str, ...]:
        del outcome
        state.threads[0].status = ThreadStatus.RESOLVED
        return (state.threads[0].id,)

    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        thread_updater=FakeThreadUpdater(mutate=mutate),
    )

    stream = service.stream_submit_player_action("I burn the old ledger and walk away.")
    for _ in stream:
        pass
    state = store.load()
    memory = store.load_memory()

    assert state.threads[0].status == ThreadStatus.RESOLVED
    assert state.oracle_history[-1].referenced_thread_id == state.threads[0].id
    assert state.oracle_history[-1].referenced_thread_ids == [state.threads[0].id]
    assert all(
        not loop.text.startswith(state.threads[0].title)
        for loop in memory.open_loops
    )
    resolved_card = next(
        card for card in memory.thread_memory if card.thread_id == state.threads[0].id
    )
    assert resolved_card.status == ThreadStatus.RESOLVED


def test_streamed_turn_npc_updater_can_retire_npc(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")

    def mutate(state: GameState, outcome: OracleOutcome) -> tuple[str, ...]:
        del outcome
        state.npcs[0].status = NPCStatus.RETIRED
        state.npcs[0].disposition = "gone to ground"
        return (state.npcs[0].id,)

    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        npc_updater=FakeNpcUpdater(mutate=mutate),
    )

    stream = service.stream_submit_player_action("I pay the witness to disappear before dawn.")
    for _ in stream:
        pass
    state = store.load()
    memory = store.load_memory()

    assert state.npcs[0].status == NPCStatus.RETIRED
    assert state.oracle_history[-1].referenced_npc_id == state.npcs[0].id
    assert state.oracle_history[-1].referenced_npc_ids == [state.npcs[0].id]
    retired_card = next(card for card in memory.npc_memory if card.npc_id == state.npcs[0].id)
    assert retired_card.status == NPCStatus.RETIRED
    assert retired_card.disposition == "gone to ground"


def test_stream_cancel_discards_inflight_turn_state(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=SlowStreamingNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )
    before = service.load_state()
    registry = CancellationRegistry()
    token = registry.register("req_test")

    stream = service.stream_submit_player_action(
        "I wait in silence.",
        cancel_token=token,
    )
    first = next(stream)
    assert first.stage is not None

    thinking_delta = next(delta for delta in stream if delta.thinking)
    assert thinking_delta.thinking == "Working..."

    token.cancel()
    with pytest.raises(RequestCancelledError):
        next(stream)

    after = store.load()
    assert after.updated_at == before.updated_at
    assert after.action_log == before.action_log
    assert after.oracle_history == before.oracle_history
    assert not store.events_path.exists()
    assert not store.turn_checkpoints_dir.exists()


def test_continuity_parallelizes_thread_and_npc_generation_when_scope_is_both(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "game_state.json")
    thread_started = Event()
    npc_started = Event()

    def mutate_thread(state: GameState, outcome: OracleOutcome) -> tuple[str, ...]:
        del outcome
        created = GameThread(
            title="The bellringer marks a debt",
            stakes="If ignored, the abbey's watchers close in.",
        )
        state.threads.append(created)
        return (created.id,)

    def mutate_npc(state: GameState, outcome: OracleOutcome) -> tuple[str, ...]:
        del outcome
        created = NPC(
            name="Brother Sava",
            role="Bellringer",
            disposition="watchful",
        )
        state.npcs.append(created)
        return (created.id,)

    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        continuity_classifier=FakeContinuityClassifier(ContinuityUpdateScope.BOTH),
        thread_updater=ParallelThreadUpdater(
            started=thread_started,
            other_started=npc_started,
            mutate=mutate_thread,
        ),
        npc_updater=ParallelNpcUpdater(
            started=npc_started,
            other_started=thread_started,
            mutate=mutate_npc,
        ),
    )

    state = service.submit_player_action("I ask the bellringer to name his price.")

    assert any(thread.title == "The bellringer marks a debt" for thread in state.threads)
    assert any(npc.name == "Brother Sava" for npc in state.npcs)


def test_streamed_player_action_reuses_memory_sidecar_load_before_narration(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "game_state.json")
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )
    load_calls = 0
    original_load_memory_or_none = store.load_memory_or_none

    def counting_load_memory_or_none() -> MemoryState | None:
        nonlocal load_calls
        load_calls += 1
        return original_load_memory_or_none()

    store.load_memory_or_none = counting_load_memory_or_none  # type: ignore[method-assign]

    stream = service.stream_submit_player_action("I wait in silence.")
    for _ in stream:
        pass

    assert load_calls == 1


# --- StageTiming persistence ----------------------------------------------
#
# These anchor the contract introduced when the pre-narration checklist
# was promoted from a frontend-only ephemeral surface to canonical state.
# Three things matter:
#   1. The narrative GameEvent persists a `stage_timings` snapshot for
#      every stage the tracker observed during the streamed turn.
#   2. Stages skipped by route (e.g. player-action skips planning /
#      mechanics) land as `skipped` rather than `done`, so the UI can
#      render the same channel for the same turn shape across routes.
#   3. The stage timestamps are monotonic in canonical pipeline order:
#      `started_at` of stage N+1 is never earlier than `completed_at`
#      of stage N for stages that actually ran. This guards against a
#      future refactor that accidentally records timestamps off the
#      bootstrap frame instead of the real ACTIVE transition.


def _consume_stream(generator: Generator[CompletionDelta, None, GameState]) -> GameState:
    """Drain a streamed turn and return the final GameState.

    Test helper because the generator protocol returns the final state
    via StopIteration.value, which `for _ in stream` would silently
    discard. Several assertions below want to verify state and timings
    in the same test, so we centralize the pattern here.
    """
    while True:
        try:
            next(generator)
        except StopIteration as stop:
            return cast("GameState", stop.value)


def test_streamed_player_turn_persists_stage_timings(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        turn_router=TurnRouter(classifier=scripted_classifier),
    )

    final = _consume_stream(
        service.stream_submit_player_turn("Is the abbey gate watched? [likely]"),
    )
    narrative_event = final.action_log[-1]
    timings = narrative_event.stage_timings
    by_id = {timing.stage_id: timing for timing in timings}

    # Every canonical pre-narration stage should appear in order. We
    # don't assert exact statuses for continuity stages because the
    # scripted classifier's scope is route-dependent; we *do* assert
    # the planning / mechanics / narration trio is `done` because the
    # full-turn route always runs them.
    assert [t.stage_id for t in timings] == list(TURN_STREAM_STAGE_ORDER)
    for stage_id in (
        "planning_turn",
        "resolving_mechanics",
        "preparing_narration",
        "streaming_narration",
    ):
        timing = by_id[stage_id]
        assert timing.status == StageStatus.DONE
        assert timing.started_at is not None
        assert timing.completed_at is not None
        assert timing.completed_at >= timing.started_at
    assert by_id["reconciling_continuity"].status == StageStatus.SKIPPED
    assert by_id["reconciling_continuity"].started_at is None
    assert by_id["reconciling_continuity"].completed_at is None


def test_streamed_pure_narrate_turn_marks_continuity_stages_skipped(
    tmp_path: Path,
) -> None:
    classifier = FakeContinuityClassifier(ContinuityUpdateScope.BOTH)
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        continuity_classifier=classifier,
        turn_router=TurnRouter(classifier=scripted_classifier),
    )

    final = _consume_stream(
        service.stream_submit_player_turn("I study the icon and pray for intercession."),
    )
    by_id = {timing.stage_id: timing for timing in final.action_log[-1].stage_timings}

    assert classifier.calls == [
        (
            "I study the icon and pray for intercession.",
            final.oracle_history[-1].summary,
            final.action_log[-1].content,
        ),
    ]
    for skipped_id in ("classifying_continuity", "updating_threads", "updating_npcs"):
        timing = by_id[skipped_id]
        assert timing.status == StageStatus.SKIPPED
        assert timing.started_at is None
        assert timing.completed_at is None
    assert by_id["streaming_narration"].status == StageStatus.DONE
    assert by_id["reconciling_continuity"].status == StageStatus.DONE
    assert by_id["reconciling_continuity"].started_at is not None
    assert by_id["reconciling_continuity"].completed_at is not None


def test_streamed_recon_turn_marks_pre_narration_continuity_stages_skipped(
    tmp_path: Path,
) -> None:
    classifier = FakeContinuityClassifier(ContinuityUpdateScope.BOTH)

    def recon_classifier(text: str, likelihood: Likelihood | None) -> TurnPlan | RoutedTurn:
        if text == "Are there enemies along the goat-path?":
            return TurnPlan(
                route=TurnRoute.PLAYER_ACTION,
                text=text,
                ops=(
                    PlannedTurnOp(
                        kind=PlannedTurnOpKind.SEARCH_SCENE,
                        text=text,
                    ),
                ),
            )
        return scripted_classifier(text, likelihood)

    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        continuity_classifier=classifier,
        turn_router=TurnRouter(classifier=recon_classifier),
    )

    final = _consume_stream(
        service.stream_submit_player_turn("Are there enemies along the goat-path?"),
    )
    by_id = {timing.stage_id: timing for timing in final.action_log[-1].stage_timings}

    assert classifier.calls == [
        (
            "Are there enemies along the goat-path?",
            final.oracle_history[-1].summary,
            final.action_log[-1].content,
        ),
    ]
    for skipped_id in ("classifying_continuity", "updating_threads", "updating_npcs"):
        timing = by_id[skipped_id]
        assert timing.status == StageStatus.SKIPPED
        assert timing.started_at is None
        assert timing.completed_at is None
    assert by_id["streaming_narration"].status == StageStatus.DONE
    assert by_id["reconciling_continuity"].status == StageStatus.DONE
    assert by_id["reconciling_continuity"].started_at is not None
    assert by_id["reconciling_continuity"].completed_at is not None


def test_streamed_player_action_marks_skipped_stages(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    final = _consume_stream(
        service.stream_submit_player_action("I wait in silence."),
    )
    timings = final.action_log[-1].stage_timings
    by_id = {timing.stage_id: timing for timing in timings}

    # The action route bypasses planning + mechanics by design; their
    # entries must still appear in the persisted record (so the UI
    # never has to decide whether a stage "would have been there"),
    # but they're flagged skipped and have no timestamps.
    for skipped_id in (
        "planning_turn",
        "resolving_mechanics",
        "classifying_continuity",
        "updating_threads",
        "updating_npcs",
    ):
        assert by_id[skipped_id].status == StageStatus.SKIPPED
        assert by_id[skipped_id].started_at is None
        assert by_id[skipped_id].completed_at is None

    # And the narration + post-narration continuity stages recorded real
    # wall-clock entries.
    for done_id in ("streaming_narration", "reconciling_continuity"):
        assert by_id[done_id].status == StageStatus.DONE
        assert by_id[done_id].started_at is not None
        assert by_id[done_id].completed_at is not None


def test_streamed_regenerate_persists_stage_timings(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        turn_router=TurnRouter(classifier=scripted_classifier),
    )

    initial = _consume_stream(
        service.stream_submit_player_turn("Is the abbey gate watched? [likely]"),
    )
    target_event_id = initial.action_log[-1].id

    repaired = _consume_stream(service.stream_regenerate_response(target_event_id))
    timings = repaired.action_log[-1].stage_timings
    by_id = {timing.stage_id: timing for timing in timings}

    # Regenerate path is a focused repair: planner/mechanics/pre-narration
    # continuity are skipped because the original outcome is reused, while
    # narration + post-narration continuity still run against the new prose.
    for skipped_id in (
        "planning_turn",
        "resolving_mechanics",
        "classifying_continuity",
        "updating_threads",
        "updating_npcs",
    ):
        assert by_id[skipped_id].status == StageStatus.SKIPPED
    for done_id in ("preparing_narration", "streaming_narration", "reconciling_continuity"):
        timing = by_id[done_id]
        assert timing.status == StageStatus.DONE
        assert timing.started_at is not None
        assert timing.completed_at is not None


def test_stage_timings_round_trip_through_persistence(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    _consume_stream(service.stream_submit_player_action("I wait in silence."))
    # Reload from disk specifically (rather than the in-memory final
    # state) to assert the StageTiming list survives serialization.
    reloaded = store.load()
    timings = reloaded.action_log[-1].stage_timings

    assert len(timings) == len(TURN_STREAM_STAGE_ORDER)
    assert any(t.status == StageStatus.SKIPPED for t in timings)
    assert any(t.status == StageStatus.DONE and t.started_at is not None for t in timings)
