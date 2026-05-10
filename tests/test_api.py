"""Integration tests for the FastAPI surface.

These tests don't go to the network: a `FakeNarrative` and
`FakeCampaignGenerator` replace LiteLLM, so we exercise the routing,
serialization, and state-mutation contracts without spending tokens.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Generator
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING, Any, cast

from fastapi.testclient import TestClient
from starlette.requests import Request

from dungeon_master.api import (
    PlayerTurnRequest,
    create_app,
    reattach_request_stream,
    submit_turn_stream,
)
from dungeon_master.cairn import AttackActor, CairnEngine, SurvivalUpdate
from dungeon_master.campaign import (
    CampaignWorldResult,
    CharacterDraftMode,
    CharacterDraftResult,
    CharacterQuizResult,
    CharacterTemplatesResult,
)
from dungeon_master.cancel import CancellationToken
from dungeon_master.config import (
    DEFAULT_GEMINI_FLASH_MODEL,
    DEFAULT_GEMINI_PRO_MODEL,
    DEFAULT_MODEL,
    LLMCredentialsStore,
    LLMPreset,
    LLMProvider,
    RuntimeSettingsStore,
)
from dungeon_master.explainer import ExplanationResult
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
    CampaignSeed,
    CampaignStatus,
    CharacterQuiz,
    CharacterQuizAnswer,
    CharacterQuizOption,
    CharacterQuizQuestion,
    CharacterSheet,
    EncounterAdvantagePayoff,
    EncounterInitiator,
    EncounterState,
    EnemyCombatant,
    GameState,
    GameThread,
    InventoryItem,
    Likelihood,
    NPCStatus,
    OracleKind,
    OracleOutcome,
    PartyMember,
    RetreatOutcome,
    SceneStatus,
)
from dungeon_master.narrative import (
    CompletionDelta,
    CompletionRequest,
    NarrativeConfig,
    NarrativeResult,
)
from dungeon_master.npc_updater import (
    GeneratedNPCUpdateBatch,
    LegacyNPCRosterRepairResult,
    NPCUpdateResult,
)
from dungeon_master.oracle import OracleEngine
from dungeon_master.save_library import SaveLibrary
from dungeon_master.service import GameService, NPCUpdaterPort, ThreadUpdaterPort
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

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    import pytest
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
        return authored

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

    def setup_advantage(  # noqa: PLR0913
        self,
        state: GameState,
        *,
        target_name: str,
        setup: str,
        payoff: EncounterAdvantagePayoff,
        actor_id: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> OracleOutcome:
        del state, actor_id, cancel_token
        return OracleOutcome(
            kind=OracleKind.PLAYER_ACTION,
            summary=f"Setup advantage against {target_name}: {setup}",
            chaos_factor=5,
            cairn=CairnResolution(
                target_name=target_name,
                advantage_setup=setup,
                advantage_payoff=payoff,
                advantage_target_name=target_name,
                advantage_applied=True,
                advantage_consumed=False,
            ),
        )


class FakePlayableCairnEngine(FakeCairnEngine):
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

    def resolve_coordinated_attack(
        self,
        state: GameState,
        *,
        target_name: str,
        target_armor: int,
        participants: tuple[AttackActor, ...],
        cancel_token: CancellationToken | None = None,
    ) -> OracleOutcome:
        del cancel_token
        actor_names = ", ".join(participant.name for participant in participants)
        return OracleOutcome(
            kind=OracleKind.ATTACK,
            summary=f"Coordinated attack against {target_name} by {actor_names}.",
            chaos_factor=state.chaos_factor,
            cairn=CairnResolution(
                target_name=target_name,
                target_armor=target_armor,
                coordinated_attack=True,
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


class FatalPlayableCairnEngine(FakePlayableCairnEngine):
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


class FakeThreadUpdater:
    def __init__(
        self,
        mutate: Callable[[GameState, OracleOutcome], tuple[str, ...]] | None = None,
    ) -> None:
        self._mutate = mutate

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
        del (
            state,
            player_input,
            outcome,
            execution_context,
            narrative_text,
            memory_context,
            cancel_token,
        )
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
        del (
            state,
            player_input,
            outcome,
            execution_context,
            narrative_text,
            memory_context,
            cancel_token,
        )
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


def scripted_classifier(text: str, likelihood: Likelihood | None) -> RoutedTurn:  # noqa: PLR0911
    if text == "Is the abbey gate watched?":
        return RoutedTurn(
            route=TurnRoute.YES_NO,
            text=text,
            likelihood=likelihood or Likelihood.UNLIKELY,
        )
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


def _client(  # noqa: PLR0913
    tmp_path: Path,
    *,
    narrative: FakeNarrative | ThoughtfulNarrative | BlockingThoughtfulNarrative | None = None,
    turn_router: TurnRouter | None = None,
    thread_updater: ThreadUpdaterPort | None = None,
    npc_updater: NPCUpdaterPort | None = None,
    explainer: FakeExplainer | None = None,
) -> TestClient:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=narrative or FakeNarrative(),
        explainer=explainer or FakeExplainer(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakePlayableCairnEngine(),
        turn_router=turn_router or TurnRouter(classifier=scripted_classifier),
        thread_updater=thread_updater,
        npc_updater=npc_updater,
    )
    return TestClient(create_app(service=service))


def _request_for_app(app: object, path: str) -> Request:
    return Request(
        {
            "type": "http",
            "app": app,
            "method": "GET",
            "path": path,
            "headers": [],
            "query_string": b"",
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "scheme": "http",
            "http_version": "1.1",
        },
    )


async def _collect_stream_events(
    iterator: object,
    *,
    limit: int | None = None,
    release: Event | None = None,
    release_on_type: str | None = None,
    until_type: str | None = None,
) -> list[dict[str, Any]]:
    stream = cast("AsyncIterator[str]", iterator)
    events: list[dict[str, Any]] = []
    try:
        async for line in stream:
            if not line:
                continue
            events.append(cast("dict[str, Any]", json.loads(line)))
            latest_type = cast("str | None", events[-1].get("type"))
            if release is not None and (
                (release_on_type is not None and latest_type == release_on_type)
                or (release_on_type is None and len(events) == 2)
            ):
                release.set()
            if until_type is not None and latest_type == until_type:
                break
            if limit is not None and len(events) >= limit:
                break
    finally:
        aclose = getattr(stream, "aclose", None)
        if callable(aclose):
            await aclose()
    return events


def _setup_client(tmp_path: Path) -> TestClient:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        explainer=FakeExplainer(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=SetupCharacterGenerator(),
        cairn_engine=FakePlayableCairnEngine(),
        turn_router=TurnRouter(classifier=scripted_classifier),
    )
    return TestClient(create_app(service=service))


def _thoughtful_client(tmp_path: Path) -> TestClient:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=ThoughtfulNarrative(),
        explainer=FakeExplainer(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakePlayableCairnEngine(),
        turn_router=TurnRouter(classifier=scripted_classifier),
    )
    return TestClient(create_app(service=service))


def _thoughtful_setup_client(tmp_path: Path) -> TestClient:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=ThoughtfulNarrative(),
        explainer=FakeExplainer(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=SetupCharacterGenerator(),
        cairn_engine=FakePlayableCairnEngine(),
        turn_router=TurnRouter(classifier=scripted_classifier),
    )
    return TestClient(create_app(service=service))


def _broken_planner_client(tmp_path: Path) -> TestClient:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        explainer=FakeExplainer(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakePlayableCairnEngine(),
        turn_router=TurnRouter(
            config=NarrativeConfig(
                model="test-model",
                api_key="test-key",
                base_url="https://example.com",
                exclude_reasoning=True,
            ),
            completion_function=BrokenPlannerCompletion(),
        ),
    )
    return TestClient(create_app(service=service))


def _library_service(tmp_path: Path) -> GameService:
    return GameService(
        store=StateStore(tmp_path / "seed_game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        explainer=FakeExplainer(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=SetupCharacterGenerator(),
        cairn_engine=FakePlayableCairnEngine(),
        turn_router=TurnRouter(classifier=scripted_classifier),
    )


def test_health(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_cancel_unknown_request_returns_false(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post("/api/requests/req_missing/cancel")
    assert response.status_code == 200
    assert response.json() == {"cancelled": False}


def test_cancel_live_request_returns_true(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        token = cast("Any", client.app).state.cancellation_registry.register("req_live")
        response = client.post("/api/requests/req_live/cancel")
    assert response.status_code == 200
    assert response.json() == {"cancelled": True}
    assert token.cancelled


def test_library_bootstrap_returns_empty_when_no_saves_exist(tmp_path: Path) -> None:
    service = _library_service(tmp_path)
    library = SaveLibrary(tmp_path / "game_state.json")

    with TestClient(create_app(service=service, save_library=library)) as client:
        response = client.get("/api/library/bootstrap")
        state_response = client.get("/api/state")

    assert response.status_code == 200
    assert response.json() == {"active_save_id": None, "saves": []}
    assert state_response.status_code == 409
    assert state_response.json()["detail"] == "No active save selected."


def test_llm_settings_endpoint_defaults_to_kimi(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-key")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    library = SaveLibrary(tmp_path / "game_state.json")
    settings_store = RuntimeSettingsStore(tmp_path / "runtime_settings.json")

    with TestClient(
        create_app(save_library=library, runtime_settings_store=settings_store),
    ) as client:
        response = client.get("/api/settings/llm")

    assert response.status_code == 200
    payload = response.json()
    assert payload["preset"] == LLMPreset.KIMI.value
    assert payload["structured_model"] == DEFAULT_MODEL
    assert payload["narration_model"] == DEFAULT_MODEL
    assert payload["needs_key"] is False
    assert any(credential["source"] == "env" for credential in payload["provider_credentials"])
    assert any(
        option["id"] == LLMPreset.GEMINI_SPLIT.value
        for option in payload["presets"]
    )


def test_llm_settings_endpoint_reports_first_run_when_no_credentials_exist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    monkeypatch.setenv("LITELLM_API_KEY", "")
    library = SaveLibrary(tmp_path / "game_state.json")
    settings_store = RuntimeSettingsStore(tmp_path / "runtime_settings.json")
    credentials_store = LLMCredentialsStore(tmp_path / "llm_credentials.json")

    with TestClient(
        create_app(
            save_library=library,
            runtime_settings_store=settings_store,
            credentials_store=credentials_store,
        ),
    ) as client:
        response = client.get("/api/settings/llm")

    assert response.status_code == 200
    payload = response.json()
    assert payload["needs_key"] is True
    assert all(not credential["configured"] for credential in payload["provider_credentials"])
    assert any(not option["available"] for option in payload["presets"])


def test_llm_settings_endpoint_updates_to_gemini_split(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-key")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    library = SaveLibrary(tmp_path / "game_state.json")
    settings_store = RuntimeSettingsStore(tmp_path / "runtime_settings.json")

    with TestClient(
        create_app(save_library=library, runtime_settings_store=settings_store),
    ) as client:
        response = client.post(
            "/api/settings/llm",
            json={"preset": LLMPreset.GEMINI_SPLIT.value},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["preset"] == LLMPreset.GEMINI_SPLIT.value
        assert payload["structured_model"] == DEFAULT_GEMINI_FLASH_MODEL
        assert payload["narration_model"] == DEFAULT_GEMINI_PRO_MODEL
        assert settings_store.load().llm_preset == LLMPreset.GEMINI_SPLIT
        app = cast("Any", client.app)
        assert app.state.llm_runtime.structured.model == DEFAULT_GEMINI_FLASH_MODEL
        assert app.state.llm_runtime.narration.model == DEFAULT_GEMINI_PRO_MODEL


def test_llm_credentials_endpoint_persists_masked_gemini_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    monkeypatch.setenv("LITELLM_API_KEY", "")
    library = SaveLibrary(tmp_path / "game_state.json")
    settings_store = RuntimeSettingsStore(tmp_path / "runtime_settings.json")
    credentials_store = LLMCredentialsStore(tmp_path / "llm_credentials.json")

    with TestClient(
        create_app(
            save_library=library,
            runtime_settings_store=settings_store,
            credentials_store=credentials_store,
        ),
    ) as client:
        response = client.post(
            "/api/settings/credentials",
            json={"provider": LLMProvider.GEMINI.value, "api_key": "gemini-secret-1234"},
        )

    assert response.status_code == 200
    payload = response.json()
    gemini = next(
        credential
        for credential in payload["provider_credentials"]
        if credential["id"] == LLMProvider.GEMINI.value
    )
    assert gemini["configured"] is True
    assert gemini["source"] == "stored"
    assert gemini["masked_key"] == "gemi...1234"
    assert credentials_store.load().gemini_api_key == "gemini-secret-1234"
    assert all(
        "gemini-secret-1234" not in json.dumps(credential)
        for credential in payload["provider_credentials"]
    )


def test_llm_settings_endpoint_uses_stored_credentials_for_preset_switch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    monkeypatch.setenv("LITELLM_API_KEY", "")
    library = SaveLibrary(tmp_path / "game_state.json")
    settings_store = RuntimeSettingsStore(tmp_path / "runtime_settings.json")
    credentials_store = LLMCredentialsStore(tmp_path / "llm_credentials.json")

    with TestClient(
        create_app(
            save_library=library,
            runtime_settings_store=settings_store,
            credentials_store=credentials_store,
        ),
    ) as client:
        save_response = client.post(
            "/api/settings/credentials",
            json={"provider": LLMProvider.GEMINI.value, "api_key": "gemini-stored-key"},
        )
        response = client.post(
            "/api/settings/llm",
            json={"preset": LLMPreset.GEMINI_SPLIT.value},
        )
        assert save_response.status_code == 200
        assert response.status_code == 200
        payload = response.json()
        assert payload["preset"] == LLMPreset.GEMINI_SPLIT.value
        assert payload["structured_model"] == DEFAULT_GEMINI_FLASH_MODEL
        app = cast("Any", client.app)
        assert app.state.llm_runtime.structured.api_key == "gemini-stored-key"
        assert app.state.llm_runtime.narration.api_key == "gemini-stored-key"


def test_llm_settings_endpoint_rejects_switch_while_request_is_in_flight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-key")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    library = SaveLibrary(tmp_path / "game_state.json")
    settings_store = RuntimeSettingsStore(tmp_path / "runtime_settings.json")

    with TestClient(
        create_app(save_library=library, runtime_settings_store=settings_store),
    ) as client:
        cast("Any", client.app).state.cancellation_registry.register("req_live")
        response = client.post(
            "/api/settings/llm",
            json={"preset": LLMPreset.GEMINI_SPLIT.value},
        )

    assert response.status_code == 409
    assert (
        response.json()["detail"]
        == "Cannot change LLM settings while a request is still in flight."
    )


def test_create_save_endpoint_selects_new_save_and_exposes_state(tmp_path: Path) -> None:
    service = _library_service(tmp_path)
    library = SaveLibrary(tmp_path / "game_state.json")

    with TestClient(create_app(service=service, save_library=library)) as client:
        response = client.post("/api/library/saves", json={"select": True})
        state_response = client.get("/api/state")

    assert response.status_code == 200
    payload = response.json()
    assert payload["active_save_id"] is not None
    assert len(payload["saves"]) == 1
    assert payload["saves"][0]["campaign_status"] == "character_creation"
    assert state_response.status_code == 200
    assert state_response.json()["campaign_status"] == "character_creation"


def test_select_save_endpoint_switches_the_active_state_store(tmp_path: Path) -> None:
    service = _library_service(tmp_path)
    library = SaveLibrary(tmp_path / "game_state.json")

    first_id = library.create_save(create_state=sample_state(), select=True)
    second_id = library.create_save(create_state=sample_state(), select=False)

    first_store = StateStore(library.state_path_for(first_id))
    first_state = first_store.load()
    first_state.character.name = "Vrtanes"
    first_state.character.epithet = "Myrrh-stained anathematist"
    first_store.save(first_state, create_checkpoint=False)

    second_store = StateStore(library.state_path_for(second_id))
    second_state = second_store.load()
    second_state.character.name = "Sahak"
    second_state.character.epithet = "Apostolic penitent"
    second_store.save(second_state, create_checkpoint=False)

    with TestClient(create_app(service=service, save_library=library)) as client:
        initial = client.get("/api/state")
        switched = client.post("/api/library/select", json={"save_id": second_id})
        after_switch = client.get("/api/state")

    assert initial.status_code == 200
    assert initial.json()["character"]["name"] == "Vrtanes"
    assert switched.status_code == 200
    assert switched.json()["active_save_id"] == second_id
    assert after_switch.status_code == 200
    assert after_switch.json()["character"]["name"] == "Sahak"


def test_select_save_endpoint_rejects_switch_while_request_is_in_flight(
    tmp_path: Path,
) -> None:
    service = _library_service(tmp_path)
    library = SaveLibrary(tmp_path / "game_state.json")

    library.create_save(create_state=service.new_setup_state(), select=True)
    second_id = library.create_save(create_state=service.new_setup_state(), select=False)

    with TestClient(create_app(service=service, save_library=library)) as client:
        cast("Any", client.app).state.cancellation_registry.register("req_live")
        response = client.post("/api/library/select", json={"save_id": second_id})

    assert response.status_code == 409
    assert (
        response.json()["detail"]
        == "Cannot switch saves while a request is still in flight."
    )


def test_reattach_request_stream_rejects_different_active_save(tmp_path: Path) -> None:
    narrative = BlockingThoughtfulNarrative()
    service = GameService(
        store=StateStore(tmp_path / "seed_game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=narrative,
        explainer=FakeExplainer(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=SetupCharacterGenerator(),
        cairn_engine=FakePlayableCairnEngine(),
        turn_router=TurnRouter(classifier=scripted_classifier),
    )
    library = SaveLibrary(tmp_path / "game_state.json")
    first_id = library.create_save(create_state=sample_state(), select=True)
    second_id = library.create_save(create_state=sample_state(), select=False)

    with TestClient(create_app(service=service, save_library=library)) as client:
        app = cast("Any", client.app)
        response = submit_turn_stream(
            request=_request_for_app(app, "/api/turn/stream"),
            svc=app.state.service,
            registry=app.state.cancellation_registry,
            session_registry=app.state.session_registry,
            payload=PlayerTurnRequest(text="I swing my cudgel at the abbey ghoul."),
        )
        initial_events = asyncio.run(_collect_stream_events(response.body_iterator, limit=1))
        request_id = cast("str", initial_events[0]["request_id"])
        assert narrative.started.wait(timeout=1.0)
        narrative.release.set()
        resumed = reattach_request_stream(
            request=_request_for_app(app, f"/api/requests/{request_id}/stream"),
            request_id=request_id,
            session_registry=app.state.session_registry,
        )
        resumed_events = asyncio.run(_collect_stream_events(resumed.body_iterator))
        assert resumed_events[-1]["type"] == "final_state"
        assert client.post("/api/library/select", json={"save_id": second_id}).status_code == 200
        wrong_save = client.get(f"/api/requests/{request_id}/stream")

    assert first_id != second_id
    assert wrong_save.status_code == 409
    assert wrong_save.json()["detail"] == "Request belongs to a different active save."


def test_state_round_trip(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        first = client.get("/api/state").json()
        second = client.get("/api/state").json()
    # The campaign is generated once on the first read and persisted, so a
    # second read must return the same canonical state - this is what
    # protects us from "the oracle keeps regenerating my campaign" bugs.
    assert first["id"] == second["id"]
    assert len(first["threads"]) == 3


def test_chaos_factor_clamped(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post("/api/state/chaos", json={"value": 12})
    # Pydantic must reject out-of-range values up front; we never want a
    # chaos factor outside [1, 9] to slip into the persisted state file.
    assert response.status_code == 422


def test_chaos_factor_persists(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        client.post("/api/state/chaos", json={"value": 7})
        state = client.get("/api/state").json()
    assert state["chaos_factor"] == 7


def test_oracle_yes_no(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/api/oracle/yes-no",
            json={"question": "Does anything stir?", "likelihood": "Even odds"},
        )
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["oracle_history"]) == 1
    assert payload["oracle_history"][0]["kind"] == "yes_no"


def test_oracle_yes_no_preview_returns_non_canonical_outcome(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/api/oracle/yes-no/preview",
            json={"question": "Does anything stir?", "likelihood": "Even odds"},
        )
        state = client.get("/api/state").json()

    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "yes_no"
    assert payload["question"] == "Does anything stir?"
    assert state["oracle_history"] == []
    assert all(event["title"] != "Oracle answer" for event in state["action_log"])


def test_random_event_uses_generated_tables(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post("/api/oracle/random-event")
    assert response.status_code == 200
    outcome = response.json()["oracle_history"][0]
    # Random events must pull from the campaign-generated word banks; a
    # missing focus/action would mean we accidentally re-introduced the
    # hardcoded oracle tables.
    assert outcome["event_focus"]
    assert outcome["event_action"]


def test_scene_check_advances_scene(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/api/oracle/scene-check",
            json={"expected_scene": "I cross the bone bridge."},
        )
    state = response.json()
    assert state["scene_number"] >= 2


def test_scene_check_same_scene_does_not_increment_scene_number(tmp_path: Path) -> None:
    class SameSceneOracle(OracleEngine):
        def check_scene(self, state: GameState, expected_scene: str) -> OracleOutcome:
            return OracleOutcome(
                kind=OracleKind.SCENE_CHECK,
                summary=f"expected: {expected_scene}",
                question=expected_scene,
                chaos_factor=state.chaos_factor,
                scene_status=SceneStatus.EXPECTED,
            )

    store = StateStore(tmp_path / "game_state.json")
    state = sample_state()
    state.current_scene = "The ossuary chapel."
    state.scene_status = SceneStatus.EXPECTED
    store.save(state, create_checkpoint=False)
    service = GameService(
        store=store,
        oracle=SameSceneOracle(),
        narrative=FakeNarrative(),
        explainer=FakeExplainer(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakePlayableCairnEngine(),
        turn_router=TurnRouter(classifier=scripted_classifier),
    )
    with TestClient(create_app(service=service)) as client:
        response = client.post(
            "/api/oracle/scene-check",
            json={"expected_scene": "The ossuary chapel."},
        )

    assert response.status_code == 200
    assert response.json()["scene_number"] == 1


def test_submit_action_records_player_then_narrative(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/api/action",
            json={"action": "I sift the ash for teeth."},
        )
    log = response.json()["action_log"]
    titles = [event["title"] for event in log]
    assert "Player action" in titles
    assert "Narrative response" in titles


def test_submit_turn_routes_natural_question(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/api/turn",
            json={"text": "Is the abbey gate watched? [unlikely]"},
        )
    assert response.status_code == 200
    payload = response.json()
    log = payload["action_log"]
    assert [event["title"] for event in log] == [
        "Player action",
        "Oracle answer",
        "Narrative response",
    ]
    outcome = payload["oracle_history"][0]
    assert outcome["kind"] == "yes_no"
    assert outcome["likelihood"] == "Unlikely"


def test_submit_turn_recon_question_does_not_advance_scene(tmp_path: Path) -> None:
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

    with _client(tmp_path, turn_router=TurnRouter(classifier=recon_classifier)) as client:
        initial = client.get("/api/state").json()
        response = client.post(
            "/api/turn",
            json={"text": "Are there enemies along the goat-path?"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["scene_number"] == initial["scene_number"]
    assert payload["current_scene"] == initial["current_scene"]
    assert [event["title"] for event in payload["action_log"]] == [
        "Player action",
        "Narrative response",
    ]
    assert payload["oracle_history"][-1]["kind"] == OracleKind.PLAYER_ACTION.value
    assert "current vantage without advancing" in payload["action_log"][-1]["content"]


def test_submit_turn_degrades_to_safe_narration_when_planning_fails(tmp_path: Path) -> None:
    with _broken_planner_client(tmp_path) as client:
        response = client.post(
            "/api/turn",
            json={"text": "I listen at the abbey door."},
        )

    assert response.status_code == 200
    payload = response.json()
    assert [event["title"] for event in payload["action_log"]] == [
        "Player action",
        "Narrative response",
    ]
    assert len(payload["oracle_history"]) == 1
    assert payload["oracle_history"][-1]["kind"] == OracleKind.PLAYER_ACTION.value


def test_submit_turn_routes_obvious_cairn_save(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/api/turn",
            json={"text": "I balance across the abbey beam."},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["oracle_history"][0]["kind"] == "save"
    assert payload["oracle_history"][0]["cairn"]["ability"] == "DEX"


def test_submit_turn_routes_attack(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/api/turn",
            json={"text": "I swing my cudgel at the abbey ghoul."},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["oracle_history"][0]["kind"] == "attack"
    assert payload["oracle_history"][0]["cairn"]["target_name"] == "Abbey ghoul"


def test_submit_turn_routes_enemy_opener_into_tracked_encounter(tmp_path: Path) -> None:
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

    with _client(tmp_path, turn_router=TurnRouter(classifier=ambush_classifier)) as client:
        response = client.post(
            "/api/turn",
            json={
                "text": (
                    "The abbey ghoul drops from the choir loft and claws me before I can "
                    "raise my cudgel."
                ),
            },
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["oracle_history"][0]["kind"] == "harm"
    assert payload["oracle_history"][0]["cairn"]["combat_started"] is True
    assert payload["oracle_history"][0]["cairn"]["combat_initiator"] == "enemy"
    assert payload["encounter"]["active"] is True
    assert payload["encounter"]["initiator"] == "enemy"


def test_submit_turn_routes_recovery(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/api/turn",
            json={"text": "I catch my breath and drink water."},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["oracle_history"][0]["kind"] == "recovery"
    assert payload["oracle_history"][0]["cairn"]["rest_kind"] == "breather"


def test_submit_turn_persists_survival_clock_fields(tmp_path: Path) -> None:
    def waiting_classifier(text: str, likelihood: Likelihood | None) -> TurnPlan:
        del likelihood
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

    with TestClient(create_app(service=service)) as client:
        response = client.post(
            "/api/turn",
            json={"text": "I keep watch by the thorn hedge until dusk."},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["character"]["cairn"]["survival"]["watch_index"] == 1
    assert payload["oracle_history"][-1]["cairn"]["time_advance"] == "watch"


def test_cairn_recover_full_rest_consumes_rations_before_healing(tmp_path: Path) -> None:
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
        turn_router=TurnRouter(classifier=scripted_classifier),
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
    service._store.save(state, create_checkpoint=False)  # noqa: SLF001

    with TestClient(create_app(service=service)) as client:
        response = client.post(
            "/api/cairn/recover",
            json={"kind": CairnRestKind.FULL_REST.value},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["character"]["cairn"]["hp"] == payload["character"]["cairn"]["max_hp"]
    assert payload["character"]["cairn"]["deprived"] is False
    assert payload["oracle_history"][-1]["cairn"]["ration_uses_before"] == 3
    assert payload["oracle_history"][-1]["cairn"]["ration_uses_after"] == 2


def test_submit_turn_routes_retreat(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")
    seeded = sample_state()
    seeded.encounter = EncounterState(
        active=True,
        round_number=2,
        combatants=[EnemyCombatant(name="Abbey ghoul", hp=4, max_hp=4)],
    )
    store.save(seeded, create_checkpoint=True)

    with _client(tmp_path) as client:
        response = client.post(
            "/api/turn",
            json={"text": "I fall back through the chapel arch."},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["oracle_history"][0]["kind"] == "retreat"
    assert payload["oracle_history"][0]["cairn"]["retreat_outcome"] == "escaped"


def test_submit_turn_routes_equip(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/api/turn",
            json={"text": "I draw the test knife."},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["oracle_history"][0]["summary"] == "Equipment updated: Test knife equipped."
    assert payload["action_log"][-1]["title"] == "Narrative response"


def test_submit_turn_routes_holy_relic_use_with_receipt_fields(tmp_path: Path) -> None:
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
                tags=[CairnItemTag.HOLY, CairnItemTag.RELIC],
                slots=0,
                uses=1,
                power=CairnItemPower(
                    kind=CairnItemPowerKind.HOLY_RELIC,
                    name="Intercession of the Nameless Patriarch",
                    effect=CairnItemEffectKind.RESTORE_ATTRIBUTE,
                    effect_amount=1,
                ),
            ),
        ),
    )
    store.save(seeded, create_checkpoint=False)
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        explainer=FakeExplainer(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=CairnEngine(
            seed=1,
            config=NarrativeConfig(model="", api_key=None, base_url=None),
        ),
        turn_router=TurnRouter(classifier=relic_classifier),
    )
    with TestClient(create_app(service=service)) as client:
        response = client.post(
            "/api/turn",
            json={"text": "I kiss the leaden icon and ask for intercession."},
        )

    assert response.status_code == 200
    payload = response.json()
    outcome = payload["oracle_history"][0]
    assert outcome["kind"] == "player_action"
    assert outcome["cairn"]["item_name"] == "Leaden icon"
    assert outcome["cairn"]["item_power_kind"] == "holy_relic"
    assert outcome["cairn"]["item_effect_kind"] == "restore_attribute"
    assert outcome["cairn"]["wil_before"] == 7
    assert outcome["cairn"]["wil_after"] == 8
    assert payload["character"]["cairn"]["wil_score"] == 8


def test_submit_turn_can_return_dynamic_thread_updates(tmp_path: Path) -> None:
    def mutate(state: GameState, outcome: OracleOutcome) -> tuple[str, ...]:
        del outcome
        created = GameThread(
            title="The hierophant's unfinished demand",
            stakes="If ignored, the abbey's claim hardens into pursuit.",
        )
        state.threads.append(created)
        return (created.id,)

    with _client(tmp_path, thread_updater=FakeThreadUpdater(mutate=mutate)) as client:
        response = client.post(
            "/api/turn",
            json={"text": "I agree to hear the hierophant's charge."},
        )
    assert response.status_code == 200
    payload = response.json()
    created = next(
        thread
        for thread in payload["threads"]
        if thread["title"] == "The hierophant's unfinished demand"
    )
    assert payload["oracle_history"][0]["referenced_thread_id"] == created["id"]
    assert payload["oracle_history"][0]["referenced_thread_ids"] == [created["id"]]


def test_submit_turn_can_return_dynamic_npc_updates(tmp_path: Path) -> None:
    def mutate(state: GameState, outcome: OracleOutcome) -> tuple[str, ...]:
        del outcome
        created = NPC(
            name="Brother Vahagn",
            role="Bell-ringer hiding a blood debt",
            disposition="guarded",
        )
        state.npcs.append(created)
        return (created.id,)

    with _client(tmp_path, npc_updater=FakeNpcUpdater(mutate=mutate)) as client:
        response = client.post(
            "/api/turn",
            json={"text": "I ask the bell-ringer why he watches me."},
        )

    assert response.status_code == 200
    payload = response.json()
    created = next(npc for npc in payload["npcs"] if npc["name"] == "Brother Vahagn")
    assert created["status"] == NPCStatus.ACTIVE.value
    assert payload["oracle_history"][0]["referenced_npc_id"] == created["id"]
    assert payload["oracle_history"][0]["referenced_npc_ids"] == [created["id"]]


def test_update_directives_endpoint_persists_ooc_guidance(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/api/state/directives",
            json={
                "world_guidance": "Keep miracles subtle and costly.",
                "play_guidance": "The hierophant cannot speak first.",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["directives"]["world_guidance"] == "Keep miracles subtle and costly."
    assert payload["directives"]["play_guidance"] == "The hierophant cannot speak first."
    assert all(event["title"] != "Campaign directives updated" for event in payload["action_log"])


def test_submit_turn_stream_emits_ndjson_events(tmp_path: Path) -> None:
    """The streaming endpoint speaks the NDJSON contract the frontend expects.

    We assert the wire shape rather than parsing — a regression that
    drops `meta` or fakes the discriminator would still pass a parser
    test that's lenient about field names. Strict substring checks pin
    each event type and the order they fire (`meta` before any deltas,
    `final_state` last).
    """
    with _thoughtful_client(tmp_path) as client:
        response = client.post(
            "/api/turn/stream",
            json={"text": "I swing my cudgel at the abbey ghoul."},
        )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    lines = [line for line in response.text.splitlines() if line.strip()]
    parsed = [json.loads(line) for line in lines]
    types = [event["type"] for event in parsed]
    assert types[0] == "meta"
    assert "stage" in types
    assert "thinking_delta" in types
    assert "content_delta" in types
    assert types[-1] == "final_state"
    stages = [event for event in parsed if event["type"] == "stage"]
    stage_statuses = {(event["stage_id"], event["status"]) for event in stages}
    assert ("planning_turn", "active") in stage_statuses
    assert ("planning_turn", "done") in stage_statuses
    assert ("resolving_mechanics", "active") in stage_statuses
    assert ("resolving_mechanics", "done") in stage_statuses
    assert ("classifying_continuity", "active") in stage_statuses
    assert ("classifying_continuity", "done") in stage_statuses
    assert ("preparing_narration", "active") in stage_statuses
    assert ("preparing_narration", "done") in stage_statuses
    assert ("streaming_narration", "active") in stage_statuses
    assert ("streaming_narration", "done") in stage_statuses
    assert ("reconciling_continuity", "skipped") in stage_statuses
    final = parsed[-1]
    assert final["state"]["action_log"][-1]["title"] == "Narrative response"
    assert final["thinking"] == "Thought about attack."


def test_submit_turn_stream_can_reattach_after_disconnect(tmp_path: Path) -> None:
    narrative = BlockingThoughtfulNarrative()
    with _client(tmp_path, narrative=narrative) as client:
        app = cast("Any", client.app)
        response = submit_turn_stream(
            request=_request_for_app(app, "/api/turn/stream"),
            svc=app.state.service,
            registry=app.state.cancellation_registry,
            session_registry=app.state.session_registry,
            payload=PlayerTurnRequest(text="I swing my cudgel at the abbey ghoul."),
        )
        initial_events = asyncio.run(
            _collect_stream_events(
                response.body_iterator,
                until_type="thinking_delta",
            ),
        )
        meta = initial_events[0]
        thinking = next(event for event in initial_events if event["type"] == "thinking_delta")
        request_id = cast("str", meta["request_id"])
        assert meta["type"] == "meta"
        assert thinking == {"type": "thinking_delta", "text": "Thought about attack."}
        assert narrative.started.wait(timeout=1.0)
        persisted_before = client.get("/api/state").json()
        assert all(
            event["title"] != "Narrative response" for event in persisted_before["action_log"]
        )
        resumed = reattach_request_stream(
            request=_request_for_app(app, f"/api/requests/{request_id}/stream"),
            request_id=request_id,
            session_registry=app.state.session_registry,
        )
        resumed_events = asyncio.run(
            _collect_stream_events(
                resumed.body_iterator,
                release=narrative.release,
                release_on_type="thinking_delta",
            ),
        )

    assert resumed_events[0]["request_id"] == request_id
    assert thinking in resumed_events
    assert resumed_events[-1]["type"] == "final_state"
    assert resumed_events[-1]["state"]["action_log"][-1]["title"] == "Narrative response"


def test_submit_turn_stream_degrades_to_safe_final_state_on_planning_failure(
    tmp_path: Path,
) -> None:
    with _broken_planner_client(tmp_path) as client:
        response = client.post(
            "/api/turn/stream",
            json={"text": "I listen at the abbey door."},
        )

    assert response.status_code == 200
    parsed = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    assert parsed[0]["type"] == "meta"
    assert parsed[-1]["type"] == "final_state"
    assert len(parsed[-1]["state"]["oracle_history"]) == 1
    assert (
        parsed[-1]["state"]["oracle_history"][-1]["kind"]
        == OracleKind.PLAYER_ACTION.value
    )
    assert parsed[-1]["state"]["action_log"][-1]["title"] == "Narrative response"


def test_explain_endpoint_returns_non_canonical_answer(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        client.post(
            "/api/oracle/yes-no",
            json={"question": "Does anything stir?", "likelihood": "Even odds"},
        )
        response = client.post(
            "/api/explain",
            json={"question": "Why did that outcome happen?"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"].startswith("OOC: Why did that outcome happen?")
    assert "latest" in payload["answer"]
    assert payload["thinking"] == ""


def test_explain_endpoint_receives_party_member_weapon_state(tmp_path: Path) -> None:
    explainer = FakeExplainer()
    with _client(tmp_path, explainer=explainer) as client:
        state_response = client.get("/api/state")
        state_payload = state_response.json()
        state = GameState.model_validate(state_payload)
        weapon = InventoryItem(
            name="Rusted wood-axe",
            details="Already surfaced as this companion's weapon.",
            cairn=CairnItemState(
                source=CairnMechanicsSource.EXPLICIT,
                tags=[CairnItemTag.WEAPON],
                weapon_damage_die=6,
                equipped=True,
            ),
        )
        companion_sheet = state.character.model_copy(
            update={
                "name": "Test Companion",
                "inventory": [weapon],
                "cairn": CairnCharacterState(
                    source=CairnMechanicsSource.EXPLICIT,
                    hp=3,
                    max_hp=3,
                    primary_weapon_item_id=weapon.id,
                ),
            },
            deep=True,
        )
        state.party_members.append(PartyMember(sheet=companion_sheet))
        StateStore(tmp_path / "game_state.json").save(state, create_checkpoint=False)

        response = client.post(
            "/api/explain",
            json={"question": "What weapon does my companion use by default?"},
        )

    assert response.status_code == 200
    assert explainer.state is not None
    assert explainer.state.party_members[0].sheet.inventory[0].name == "Rusted wood-axe"
    assert (
        explainer.state.party_members[0].sheet.cairn.primary_weapon_item_id
        == explainer.state.party_members[0].sheet.inventory[0].id
    )


def test_explain_stream_emits_final_payload(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/api/explain/stream",
            json={"question": "What does ambush mean here?"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    parsed = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    types = [event["type"] for event in parsed]
    assert types[0] == "meta"
    assert parsed[0]["route"] == "explanation"
    assert "thinking_delta" in types
    assert "content_delta" in types
    assert types[-1] == "final_payload"
    final = parsed[-1]
    assert final["kind"] == "explanation"
    assert final["payload"]["answer"].startswith("OOC: What does ambush mean here?")
    assert final["thinking"] == "Explainer considered the current state."


def test_explain_endpoint_does_not_mutate_state_or_memory(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")
    with _client(tmp_path) as client:
        client.post(
            "/api/oracle/yes-no",
            json={"question": "Does anything stir?", "likelihood": "Even odds"},
        )
        before_state = store.state_path.read_text(encoding="utf-8")
        before_memory = store.memory_path.read_text(encoding="utf-8")

        response = client.post(
            "/api/explain",
            json={"question": "Why did I get that receipt?"},
        )

        after_state = store.state_path.read_text(encoding="utf-8")
        after_memory = store.memory_path.read_text(encoding="utf-8")

    assert response.status_code == 200
    assert before_state == after_state
    assert before_memory == after_memory


def test_streamed_turn_persists_thinking_on_narrative_event(tmp_path: Path) -> None:
    with _thoughtful_client(tmp_path) as client:
        response = client.post(
            "/api/turn",
            json={"text": "I swing my cudgel at the abbey ghoul."},
        )
    assert response.status_code == 200
    narrative_event = response.json()["action_log"][-1]
    assert narrative_event["title"] == "Narrative response"
    assert narrative_event["thinking"] == "Thought about attack."


def test_reset_replaces_state(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        original = client.get("/api/state").json()
        reset_state = client.post("/api/state/reset").json()
    assert original["id"] != reset_state["id"]


def test_character_templates_endpoint(tmp_path: Path) -> None:
    with _setup_client(tmp_path) as client:
        response = client.get("/api/character/templates")
    assert response.status_code == 200
    assert len(response.json()["templates"]) == 1


def test_finalize_character_then_start_campaign(tmp_path: Path) -> None:
    character = sample_state().character.model_copy(deep=True)
    character.name = "Rook"

    with _setup_client(tmp_path) as client:
        finalized = client.post(
            "/api/character/finalize",
            json={"character": character.model_dump()},
        )
        started = client.post("/api/campaign/start")

    assert finalized.status_code == 200
    assert finalized.json()["campaign_status"] == "ready_to_start"
    assert started.status_code == 200
    assert started.json()["campaign_status"] == "active"
    assert started.json()["character"]["name"] == "Rook"


def test_character_quiz_endpoint_returns_questions(tmp_path: Path) -> None:
    with _setup_client(tmp_path) as client:
        response = client.post(
            "/api/character/quiz",
            json={"concept": "Armenian Apostolic paladin who refuses magic."},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["quiz"]["concept"] == "Armenian Apostolic paladin who refuses magic."
    assert len(payload["quiz"]["questions"]) >= 3
    assert payload["thinking"] == ""


def test_character_quizzed_draft_threads_inputs(tmp_path: Path) -> None:
    with _setup_client(tmp_path) as client:
        quiz = client.post(
            "/api/character/quiz",
            json={"concept": "A scarred deserter."},
        ).json()["quiz"]
        questions = quiz["questions"]
        answers = [
            {
                "question_id": questions[0]["id"],
                "prompt": questions[0]["prompt"],
                "value": "Wounded but standing.",
                "is_other": False,
            },
            {
                "question_id": questions[1]["id"],
                "prompt": questions[1]["prompt"],
                "value": "A name I cannot say.",
                "is_other": False,
            },
            {
                "question_id": questions[2]["id"],
                "prompt": questions[2]["prompt"],
                "value": "An old company that won't forget.",
                "is_other": True,
            },
        ]
        response = client.post(
            "/api/character/draft/quizzed",
            json={
                "concept": "A scarred deserter.",
                "answers": answers,
                "final_note": "Carries a brand they cannot read.",
            },
        )
    assert response.status_code == 200
    draft = response.json()["draft"]
    assert draft["epithet"] == "A scarred deserter."
    assert "Wounded but standing." in draft["backstory"]
    assert "A name I cannot say." in draft["backstory"]
    assert "An old company that won't forget." in draft["backstory"]
    assert draft["condition"] == "Carries a brand they cannot read."


def test_character_quiz_stream_emits_final_payload(tmp_path: Path) -> None:
    with _setup_client(tmp_path) as client:
        response = client.post(
            "/api/character/quiz/stream",
            json={"concept": "A scarred deserter."},
        )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    parsed = [
        json.loads(line) for line in response.text.splitlines() if line.strip()
    ]
    types = [event["type"] for event in parsed]
    assert types[0] == "meta"
    assert parsed[0]["route"] == "character_quiz"
    assert "content_delta" in types
    assert types[-1] == "final_payload"
    final = parsed[-1]
    assert final["kind"] == "character_quiz"
    assert "quiz" in final["payload"]


def test_character_draft_stream_emits_final_payload(tmp_path: Path) -> None:
    with _setup_client(tmp_path) as client:
        response = client.post(
            "/api/character/draft/stream",
            json={"mode": "scratch", "prompt": "A hollow-eyed pilgrim."},
        )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    parsed = [
        json.loads(line) for line in response.text.splitlines() if line.strip()
    ]
    types = [event["type"] for event in parsed]
    assert types[0] == "meta"
    assert parsed[0]["route"] == "character_draft"
    assert "content_delta" in types
    assert types[-1] == "final_payload"
    final = parsed[-1]
    assert final["kind"] == "character_draft"
    assert "draft" in final["payload"]


def test_campaign_start_persists_thinking_on_init_event(tmp_path: Path) -> None:
    character = sample_state().character.model_copy(deep=True)
    with _thoughtful_setup_client(tmp_path) as client:
        client.post("/api/character/finalize", json={"character": character.model_dump()})
        response = client.post("/api/campaign/start")
    assert response.status_code == 200
    system_event = response.json()["action_log"][-1]
    assert system_event["title"] == "Campaign initialized"
    assert "Thought" in system_event["thinking"] or system_event["thinking"] == ""


def test_campaign_end_endpoint_marks_retirement_and_blocks_future_turns(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        ended = client.post(
            "/api/campaign/end",
            json={
                "reason": CampaignEndReason.RETIREMENT.value,
                "summary": "Vrtanes leaves the abbey road and does not return.",
            },
        )
        blocked = client.post("/api/turn", json={"text": "I keep walking into the hills."})

    assert ended.status_code == 200
    body = ended.json()
    assert body["campaign_status"] == CampaignStatus.ENDED.value
    assert body["campaign_end_reason"] == CampaignEndReason.RETIREMENT.value
    assert body["campaign_end_summary"] == "Vrtanes leaves the abbey road and does not return."
    assert body["action_log"][-1]["title"] == "Campaign ended"
    assert blocked.status_code == 409
    assert "retirement" in blocked.json()["detail"]


def test_cairn_save_endpoint(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/api/cairn/save",
            json={"ability": CairnAbility.STR.value, "reason": "Force the chapel door."},
        )
    assert response.status_code == 200
    outcome = response.json()["oracle_history"][-1]
    assert outcome["kind"] == "save"
    assert outcome["cairn"]["ability"] == "STR"


def test_cairn_attack_endpoint(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        state = client.get("/api/state").json()
        weapon_id = state["character"]["cairn"]["primary_weapon_item_id"]
        response = client.post(
            "/api/cairn/attack",
            json={
                "target_name": "Abbey ghoul",
                "target_armor": 1,
                "weapon_item_id": weapon_id,
                "stance": AttackStance.NORMAL.value,
            },
        )
    assert response.status_code == 200
    outcome = response.json()["oracle_history"][-1]
    assert outcome["kind"] == "attack"
    assert outcome["cairn"]["weapon_item_id"] == weapon_id


def test_cairn_harm_and_recover_endpoints(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        harmed = client.post(
            "/api/cairn/harm",
            json={
                "amount": 2,
                "source": "Falling masonry",
                "in_combat": True,
                "armor_applies": False,
            },
        )
        recovered = client.post(
            "/api/cairn/recover",
            json={"kind": CairnRestKind.BREATHER.value},
        )
    assert harmed.status_code == 200
    assert harmed.json()["oracle_history"][-1]["kind"] == "harm"
    assert recovered.status_code == 200
    assert recovered.json()["oracle_history"][-1]["kind"] == "recovery"


def test_cairn_harm_endpoint_can_end_campaign_on_death(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FatalPlayableCairnEngine(),
        turn_router=TurnRouter(classifier=scripted_classifier),
    )

    with TestClient(create_app(service=service)) as client:
        seeded = client.get("/api/state").json()
        seeded["character"]["cairn"]["hp"] = 1
        seeded["character"]["cairn"]["str_score"] = 1
        store.save(GameState.model_validate(seeded), create_checkpoint=False)

        response = client.post(
            "/api/cairn/harm",
            json={
                "amount": 5,
                "source": "Falling masonry",
                "in_combat": True,
                "armor_applies": False,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["campaign_status"] == CampaignStatus.ENDED.value
    assert body["campaign_end_reason"] == CampaignEndReason.DEATH.value
    assert "Final turn: Fatal harm from Falling masonry." in body["campaign_end_summary"]
    assert body["action_log"][-1]["title"] == "Campaign ended"


def test_cairn_retreat_endpoint(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")
    seeded = sample_state()
    seeded.encounter = EncounterState(
        active=True,
        round_number=2,
        combatants=[EnemyCombatant(name="Abbey ghoul", hp=4, max_hp=4)],
    )
    store.save(seeded, create_checkpoint=True)

    with _client(tmp_path) as client:
        response = client.post(
            "/api/cairn/retreat",
            json={"reason": "Break contact and reach the chapel arch."},
        )
    assert response.status_code == 200
    outcome = response.json()["oracle_history"][-1]
    assert outcome["kind"] == "retreat"
    assert outcome["cairn"]["retreat_outcome"] == "escaped"


def test_cairn_acquire_endpoint(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/api/cairn/acquire",
            json={"text": "I buy a lantern and a purse of old silver."},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["action_log"][0]["title"] == "Inventory acquired"
    assert body["oracle_history"][-1]["summary"] == "Acquired Pilgrim lantern, Purse of old silver."
    assert [item["name"] for item in body["character"]["inventory"]][-2:] == [
        "Pilgrim lantern",
        "Purse of old silver",
    ]


def test_cairn_equip_endpoint(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        state = client.get("/api/state").json()
        item_id = state["character"]["inventory"][0]["id"]
        response = client.post(
            "/api/cairn/equip",
            json={"item_id": item_id, "equipped": True},
        )
    assert response.status_code == 200
    assert response.json()["action_log"][-1]["title"] == "Equipment updated"


def test_regenerate_latest_message(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        first = client.post(
            "/api/oracle/yes-no",
            json={"question": "Does anything stir?", "likelihood": "Even odds"},
        ).json()
        narrative_event_id = first["action_log"][-1]["id"]
        repaired = client.post(f"/api/messages/{narrative_event_id}/regenerate")

    assert repaired.status_code == 200
    log_titles = [event["title"] for event in repaired.json()["action_log"]]
    assert "Narrative regenerated" in log_titles
