from __future__ import annotations

from collections.abc import Generator
from typing import Protocol

from dungeon_master.application.cancellation import CancellationToken
from dungeon_master.application.capability_guard import (
    CapabilityOracleGuardResult,
)
from dungeon_master.application.continuity import (
    NPCUpdater as ContinuityNPCUpdaterPort,
)
from dungeon_master.application.updates.npcs import LegacyNPCRosterRepairResult
from dungeon_master.domain.models import (
    AttackStance,
    CairnAbility,
    CairnRestKind,
    CairnSurvivalAction,
    CairnTimeAdvance,
    CampaignSeed,
    CharacterQuiz,
    CharacterQuizAnswer,
    CharacterSheet,
    EncounterAdvantagePayoff,
    GameState,
    Likelihood,
    OracleOutcome,
)
from dungeon_master.generation import (
    CampaignWorldResult,
    CharacterDraftMode,
    CharacterDraftResult,
    CharacterQuizResult,
    CharacterTemplatesResult,
)
from dungeon_master.llm.explanation import ExplanationResult
from dungeon_master.llm.narration import (
    CompletionDelta,
)
from dungeon_master.mechanics.engine import AttackActor, SurvivalUpdate


class NarrativePort(Protocol):
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
        raise NotImplementedError


class CampaignPort(Protocol):
    def generate(self, character: CharacterSheet, seed: CampaignSeed | None = None) -> GameState:
        raise NotImplementedError

    def generate_result(
        self,
        character: CharacterSheet,
        seed: CampaignSeed | None = None,
    ) -> CampaignWorldResult:
        raise NotImplementedError

    def iter_generate(
        self,
        character: CharacterSheet,
        *,
        seed: CampaignSeed | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, CampaignWorldResult]:
        raise NotImplementedError


class CairnPort(Protocol):
    def ensure_character_state(
        self,
        state: GameState,
        *,
        allow_backfill: bool,
        cancel_token: CancellationToken | None = None,
    ) -> bool:
        raise NotImplementedError

    def resolve_save(
        self,
        state: GameState,
        ability: CairnAbility,
        reason: str,
        *,
        actor_id: str | None = None,
    ) -> OracleOutcome:
        raise NotImplementedError

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
        raise NotImplementedError

    def resolve_coordinated_attack(
        self,
        state: GameState,
        *,
        target_name: str,
        target_armor: int,
        participants: tuple[AttackActor, ...],
        cancel_token: CancellationToken | None = None,
    ) -> OracleOutcome:
        del state, target_name, target_armor, participants, cancel_token
        raise NotImplementedError

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
        raise NotImplementedError

    def begin_encounter(
        self,
        state: GameState,
        *,
        target_name: str,
        text: str,
        cancel_token: CancellationToken | None = None,
    ) -> OracleOutcome:
        raise NotImplementedError

    def resolve_enemy_opener(
        self,
        state: GameState,
        *,
        source: str,
        text: str,
        cancel_token: CancellationToken | None = None,
    ) -> OracleOutcome:
        raise NotImplementedError

    def recover(
        self,
        state: GameState,
        kind: CairnRestKind,
        *,
        actor_id: str | None = None,
    ) -> OracleOutcome:
        raise NotImplementedError

    def advance_survival_clock(
        self,
        state: GameState,
        *,
        time_advance: CairnTimeAdvance,
        actions: tuple[CairnSurvivalAction, ...] = (),
        actor_id: str | None = None,
        extra_days: int = 0,
    ) -> SurvivalUpdate:
        raise NotImplementedError

    def resolve_retreat(self, state: GameState, reason: str) -> OracleOutcome:
        raise NotImplementedError

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
        raise NotImplementedError

    def set_item_equipped(
        self,
        state: GameState,
        *,
        item_id: str,
        equipped: bool,
        actor_id: str | None = None,
    ) -> None:
        raise NotImplementedError

    def acquire_items(
        self,
        state: GameState,
        *,
        text: str,
        actor_id: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> str:
        raise NotImplementedError

    def use_item(
        self,
        state: GameState,
        *,
        item_id: str,
        intent: str,
        actor_id: str | None = None,
    ) -> OracleOutcome:
        raise NotImplementedError

    def drop_item(
        self,
        state: GameState,
        *,
        item_id: str,
        actor_id: str | None = None,
    ) -> str:
        raise NotImplementedError

    def transfer_item(
        self,
        state: GameState,
        *,
        item_id: str,
        source_actor_id: str | None,
        target_actor_id: str | None,
    ) -> str:
        raise NotImplementedError

    def backfill_companion_sheet(
        self,
        state: GameState,
        authored: CharacterSheet,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> CharacterSheet:
        raise NotImplementedError


class CharacterPort(Protocol):
    def setup_state(self, seed: CampaignSeed | None = None) -> GameState:
        raise NotImplementedError

    def generate_templates(self, seed: CampaignSeed | None = None) -> list[CharacterSheet]:
        raise NotImplementedError

    def generate_templates_result(
        self,
        seed: CampaignSeed | None = None,
    ) -> CharacterTemplatesResult:
        raise NotImplementedError

    def iter_generate_templates(
        self,
        *,
        seed: CampaignSeed | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, CharacterTemplatesResult]:
        raise NotImplementedError

    def generate_draft(
        self,
        *,
        mode: CharacterDraftMode,
        prompt: str | None,
        template: CharacterSheet | None,
        seed: CampaignSeed | None = None,
    ) -> CharacterSheet:
        raise NotImplementedError

    def generate_draft_result(
        self,
        *,
        mode: CharacterDraftMode,
        prompt: str | None,
        template: CharacterSheet | None,
        seed: CampaignSeed | None = None,
    ) -> CharacterDraftResult:
        raise NotImplementedError

    def iter_generate_draft(
        self,
        *,
        mode: CharacterDraftMode,
        prompt: str | None,
        template: CharacterSheet | None,
        seed: CampaignSeed | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, CharacterDraftResult]:
        raise NotImplementedError

    def generate_quiz(self, concept: str, seed: CampaignSeed | None = None) -> CharacterQuiz:
        raise NotImplementedError

    def generate_quiz_result(
        self,
        concept: str,
        seed: CampaignSeed | None = None,
    ) -> CharacterQuizResult:
        raise NotImplementedError

    def iter_generate_quiz(
        self,
        concept: str,
        *,
        seed: CampaignSeed | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, CharacterQuizResult]:
        raise NotImplementedError

    def generate_quizzed_draft(
        self,
        *,
        concept: str,
        answers: list[CharacterQuizAnswer],
        final_note: str | None,
        seed: CampaignSeed | None = None,
    ) -> CharacterSheet:
        raise NotImplementedError

    def generate_quizzed_draft_result(
        self,
        *,
        concept: str,
        answers: list[CharacterQuizAnswer],
        final_note: str | None,
        seed: CampaignSeed | None = None,
    ) -> CharacterDraftResult:
        raise NotImplementedError

    def iter_generate_quizzed_draft(
        self,
        *,
        concept: str,
        answers: list[CharacterQuizAnswer],
        final_note: str | None,
        seed: CampaignSeed | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, CharacterDraftResult]:
        raise NotImplementedError


class ExplainerPort(Protocol):
    def generate_result(
        self,
        state: GameState,
        question: str,
        *,
        memory_context: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> ExplanationResult:
        raise NotImplementedError

    def iter_stream(
        self,
        state: GameState,
        question: str,
        *,
        memory_context: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, ExplanationResult]:
        raise NotImplementedError


class NPCUpdaterPort(ContinuityNPCUpdaterPort, Protocol):
    def reseed_legacy_roster(
        self,
        state: GameState,
        *,
        memory_context: str | None = None,
        cancel_token: CancellationToken | None = None,
        use_model: bool = False,
    ) -> LegacyNPCRosterRepairResult:
        raise NotImplementedError


class CapabilityOracleGuardPort(Protocol):
    def guard_yes_no(
        self,
        state: GameState,
        *,
        question: str,
        requested_likelihood: Likelihood,
        cancel_token: CancellationToken | None = None,
    ) -> CapabilityOracleGuardResult:
        raise NotImplementedError
