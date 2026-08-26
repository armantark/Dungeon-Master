# mypy: disable-error-code="misc"
from __future__ import annotations

from collections.abc import Generator
from typing import TYPE_CHECKING

from dungeon_master.application.service_models import (
    GuardedYesNoOutcome,
)
from dungeon_master.cancel import CancellationToken
from dungeon_master.explainer import ExplanationResult
from dungeon_master.models import (
    AttackStance,
    CairnAbility,
    CairnRestKind,
    CampaignDirectives,
    EventType,
    GameEvent,
    GameState,
    Likelihood,
    OracleKind,
    OracleOutcome,
)
from dungeon_master.narrative import (
    CompletionDelta,
)

if TYPE_CHECKING:
    from dungeon_master.service import GameService


class DirectCommandsMixin:
    def explain(self: GameService, question: str) -> ExplanationResult:
        state, memory_context = self._load_state_and_memory_context_for_explainer(question)
        return self._explainer.generate_result(
            state,
            question,
            memory_context=memory_context,
        )

    def stream_explain(
        self: GameService,
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

    def resolve_cairn_save(self: GameService, ability: CairnAbility, reason: str) -> GameState:
        state = self.load_state()
        self._ensure_active(state)
        outcome = self._cairn.resolve_save(state, ability, reason)
        self._commit_oracle_turn(
            state=state,
            player_input=f"{ability.value} save: {reason}",
            outcome=outcome,
            oracle_title="Cairn save",
        )
        return state

    def attack_target(
        self: GameService,
        *,
        target_name: str,
        target_armor: int,
        weapon_item_id: str | None,
        stance: AttackStance,
    ) -> GameState:
        state = self.load_state()
        self._ensure_active(state)
        outcome = self._cairn.resolve_attack(
            state,
            target_name=target_name,
            target_armor=target_armor,
            weapon_item_id=weapon_item_id,
            stance=stance,
        )
        self._commit_oracle_turn(
            state=state,
            player_input=f"Attack {target_name}",
            outcome=outcome,
            oracle_title="Attack resolution",
        )
        return state

    def suffer_harm(
        self: GameService,
        *,
        amount: int,
        source: str,
        in_combat: bool,
        armor_applies: bool,
    ) -> GameState:
        state = self.load_state()
        self._ensure_active(state)
        outcome = self._cairn.suffer_harm(
            state,
            amount=amount,
            source=source,
            in_combat=in_combat,
            armor_applies=armor_applies,
        )
        self._commit_oracle_turn(
            state=state,
            player_input=f"Suffer harm from {source}",
            outcome=outcome,
            oracle_title="Harm resolution",
        )
        return state

    def recover_character(self: GameService, kind: CairnRestKind) -> GameState:
        state = self.load_state()
        self._ensure_active(state)
        survival_update = self._advance_survival_for_rest(
            state,
            kind=kind,
        )
        outcome = self._cairn.recover(state, kind)
        if survival_update is not None:
            outcome.cairn = self._merge_cairn_resolution(outcome.cairn, survival_update.resolution)
        self._commit_oracle_turn(
            state=state,
            player_input=f"Recovery: {kind.value}",
            outcome=outcome,
            oracle_title="Recovery",
            execution_context=self._format_execution_context(
                [survival_update.summary] if survival_update is not None else []
            ),
        )
        return state

    def retreat_from_encounter(self: GameService, reason: str) -> GameState:
        state = self.load_state()
        self._ensure_active(state)
        outcome = self._cairn.resolve_retreat(state, reason)
        self._commit_oracle_turn(
            state=state,
            player_input=f"Retreat: {reason}",
            outcome=outcome,
            oracle_title="Retreat resolution",
        )
        return state

    def set_item_equipped(self: GameService, *, item_id: str, equipped: bool) -> GameState:
        state = self.load_state()
        self._ensure_active(state)
        self._cairn.set_item_equipped(state, item_id=item_id, equipped=equipped)
        title = "Equipment updated"
        verb = "equipped" if equipped else "unequipped"
        self._record_event(
            state,
            GameEvent(
                event_type=EventType.SYSTEM,
                title=title,
                content=f"Item {item_id} {verb}.",
            ),
        )
        self._save_state_commit(state, create_checkpoint=True)
        return state

    def acquire_inventory(self: GameService, text: str) -> GameState:
        state = self.load_state()
        self._ensure_active(state)
        summary = self._cairn.acquire_items(state, text=text)
        self._record_event(
            state,
            GameEvent(
                event_type=EventType.SYSTEM,
                title="Inventory acquired",
                content=summary,
            ),
        )
        outcome = OracleOutcome(
            kind=OracleKind.PLAYER_ACTION,
            summary=summary,
            question=text,
            chaos_factor=state.chaos_factor,
        )
        execution_context = self._format_execution_context([summary])
        self._commit_oracle_turn(
            state=state,
            player_input=text,
            outcome=outcome,
            oracle_title=None,
            execution_context=execution_context,
        )
        return state

    def set_chaos_factor(self: GameService, value: int) -> GameState:
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
        self._save_state_commit(state, create_checkpoint=True)
        return state

    def update_notes(self: GameService, *, setting_notes: str, player_notes: str) -> GameState:
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
        self._save_state_commit(state, create_checkpoint=True)
        return state

    def update_directives(
        self: GameService,
        *,
        world_guidance: str,
        play_guidance: str,
    ) -> GameState:
        state = self.load_state()
        self._ensure_active(state)
        state.directives = CampaignDirectives(
            world_guidance=world_guidance,
            play_guidance=play_guidance,
        )
        # Directives are durable OOC steering, not in-fiction transcript
        # events. Persist the state change, but do not append a visible
        # system message to the action log.
        self._save_state_commit(state, create_checkpoint=True)
        return state

    def ask_oracle(self: GameService, question: str, likelihood: Likelihood) -> GameState:
        state = self.load_state()
        self._ensure_active(state)
        guarded = self._resolve_yes_no_oracle(
            state,
            question=question,
            likelihood=likelihood,
        )
        self._commit_oracle_turn(
            state=state,
            player_input=f"Oracle question: {question}",
            outcome=guarded.outcome,
            oracle_title="Oracle answer",
            execution_context=guarded.execution_context,
        )
        return state

    def preview_oracle(self: GameService, question: str, likelihood: Likelihood) -> OracleOutcome:
        state = self._load_state_readonly()
        self._ensure_active(state)
        return self._resolve_yes_no_oracle(
            state,
            question=question,
            likelihood=likelihood,
        ).outcome

    def _resolve_yes_no_oracle(
        self: GameService,
        state: GameState,
        *,
        question: str,
        likelihood: Likelihood,
        cancel_token: CancellationToken | None = None,
    ) -> GuardedYesNoOutcome:
        guarded = self._capability_oracle_guard.guard_yes_no(
            state,
            question=question,
            requested_likelihood=likelihood,
            cancel_token=cancel_token,
        )
        if guarded.outcome is not None:
            return GuardedYesNoOutcome(
                outcome=guarded.outcome,
                execution_context=guarded.execution_summary,
            )
        resolved_likelihood = guarded.likelihood or likelihood
        outcome = self._oracle.ask_yes_no(state, question, resolved_likelihood)
        return GuardedYesNoOutcome(
            outcome=outcome,
            execution_context=guarded.execution_summary,
        )

    def generate_random_event(self: GameService) -> GameState:
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

    def check_scene(self: GameService, expected_scene: str) -> GameState:
        state = self.load_state()
        self._ensure_active(state)
        outcome = self._oracle.check_scene(state, expected_scene)
        if outcome.scene_status is not None:
            self._apply_scene_transition(state, expected_scene, outcome.scene_status)

        self._commit_oracle_turn(
            state=state,
            player_input=f"Check scene: {expected_scene}",
            outcome=outcome,
            oracle_title="Scene check",
        )
        return state
