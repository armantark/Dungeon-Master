from __future__ import annotations

import json

from pydantic import ValidationError

from dungeon_master.application.cancellation import CancellationToken
from dungeon_master.config import LLMConfig as NarrativeConfig
from dungeon_master.llm.completion.contracts import CompletionFunction, CompletionRequest
from dungeon_master.llm.completion.transport import (
    LITELLM_RETRYABLE_ERRORS,
    complete_text,
    extract_json_object,
)
from dungeon_master.llm.planning.contracts import (
    EmptyRouteContentError,
    GeneratedCombatMechanicsReview,
    GeneratedSaveMechanicsReview,
    PlannedTurnOp,
    PlannedTurnOpKind,
    RouterClassifier,
    TurnPlan,
    TurnRoute,
)
from dungeon_master.llm.planning.prompts import (
    COMBAT_MECHANICS_REVIEW_SYSTEM_PROMPT,
    SAVE_MECHANICS_REVIEW_SYSTEM_PROMPT,
)


class ReviewGates:
    _classifier: RouterClassifier | None
    _config: NarrativeConfig
    _completion: CompletionFunction

    def _openrouter_headers(self) -> dict[str, str] | None:
        raise NotImplementedError

    def _review_combat_mechanics_plan(
        self,
        plan: TurnPlan,
        *,
        normalized_text: str,
        combat_encounter_hint: str | None,
        cancel_token: CancellationToken | None,
    ) -> TurnPlan:
        if not self._requires_combat_mechanics_review(plan):
            return plan
        review = self._generate_combat_mechanics_review(
            plan,
            normalized_text=normalized_text,
            canonical_active_encounter=combat_encounter_hint,
            cancel_token=cancel_token,
        )
        if review is not None and review.allow_combat_mechanics:
            return plan
        return TurnPlan(
            route=TurnRoute.PLAYER_ACTION,
            text=plan.text,
            ops=(PlannedTurnOp(kind=PlannedTurnOpKind.NARRATE, text=plan.text),),
            time_advance=plan.time_advance,
            survival_actions=plan.survival_actions,
        )

    def _requires_combat_mechanics_review(self, plan: TurnPlan) -> bool:
        return any(
            op.kind
            in {
                PlannedTurnOpKind.ATTACK,
                PlannedTurnOpKind.COORDINATED_ATTACK,
                PlannedTurnOpKind.ENEMY_OPENER,
                PlannedTurnOpKind.HARM,
                PlannedTurnOpKind.SETUP_ADVANTAGE,
            }
            for op in plan.ops
        )

    def _generate_combat_mechanics_review(
        self,
        plan: TurnPlan,
        *,
        normalized_text: str,
        canonical_active_encounter: str | None,
        cancel_token: CancellationToken | None,
    ) -> GeneratedCombatMechanicsReview | None:
        if self._classifier is not None or not self._config.is_usable():
            return None
        profile = self._config.profiles.turn_router
        payload = {
            "original_player_turn": normalized_text,
            "canonical_active_encounter": canonical_active_encounter,
            "proposed_plan": {
                "route": plan.route.value,
                "text": plan.text,
                "ops": [
                    {
                        "kind": op.kind.value,
                        "text": op.text,
                        "target_name": op.target_name,
                        "item_name": op.item_name,
                        "harm_source": op.harm_source,
                        "in_combat": op.in_combat,
                        "advantage_payoff": (
                            None if op.advantage_payoff is None else op.advantage_payoff.value
                        ),
                    }
                    for op in plan.ops
                ],
            },
        }
        request = CompletionRequest(
            model=self._config.model,
            messages=[
                {"role": "system", "content": COMBAT_MECHANICS_REVIEW_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload)},
            ],
            temperature=0.0,
            max_tokens=profile.max_tokens,
            timeout=self._config.timeout_seconds,
            stream=True,
            api_key=self._config.api_key,
            base_url=self._config.base_url,
            reasoning_effort=profile.reasoning_effort,
            reasoning=profile.reasoning(default_exclude=self._config.exclude_reasoning),
            extra_headers=self._openrouter_headers(),
            response_format=None,
            cancel_token=cancel_token,
            trace_route="turn_router.combat_review",
            trace_profile="turn_router",
        )
        try:
            completed = complete_text(request, self._completion)
            payload_json = extract_json_object(completed.content)
            return GeneratedCombatMechanicsReview.model_validate_json(payload_json)
        except (
            *LITELLM_RETRYABLE_ERRORS,
            ValidationError,
            json.JSONDecodeError,
            EmptyRouteContentError,
            ValueError,
        ):
            return None

    def _review_save_mechanics_plan(
        self,
        plan: TurnPlan,
        *,
        normalized_text: str,
        memory_context: str | None,
        cancel_token: CancellationToken | None,
    ) -> TurnPlan:
        if not self._requires_save_mechanics_review(plan):
            return plan
        review = self._generate_save_mechanics_review(
            plan,
            normalized_text=normalized_text,
            memory_context=memory_context,
            cancel_token=cancel_token,
        )
        if review is not None and review.allow_save_mechanics:
            return plan
        return TurnPlan(
            route=TurnRoute.PLAYER_ACTION,
            text=plan.text,
            ops=(PlannedTurnOp(kind=PlannedTurnOpKind.NARRATE, text=plan.text),),
            time_advance=plan.time_advance,
            survival_actions=plan.survival_actions,
        )

    def _requires_save_mechanics_review(self, plan: TurnPlan) -> bool:
        return any(op.kind is PlannedTurnOpKind.SAVE for op in plan.ops)

    def _generate_save_mechanics_review(
        self,
        plan: TurnPlan,
        *,
        normalized_text: str,
        memory_context: str | None,
        cancel_token: CancellationToken | None,
    ) -> GeneratedSaveMechanicsReview | None:
        if self._classifier is not None or not self._config.is_usable():
            return None
        profile = self._config.profiles.turn_router
        payload = {
            "original_player_turn": normalized_text,
            "bounded_memory_context": memory_context or "(none)",
            "proposed_plan": {
                "route": plan.route.value,
                "text": plan.text,
                "ops": [
                    {
                        "kind": op.kind.value,
                        "text": op.text,
                        "ability": None if op.ability is None else op.ability.value,
                        "target_name": op.target_name,
                        "actor_name": op.actor_name,
                    }
                    for op in plan.ops
                ],
            },
        }
        request = CompletionRequest(
            model=self._config.model,
            messages=[
                {"role": "system", "content": SAVE_MECHANICS_REVIEW_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload)},
            ],
            temperature=0.0,
            max_tokens=profile.max_tokens,
            timeout=self._config.timeout_seconds,
            stream=True,
            api_key=self._config.api_key,
            base_url=self._config.base_url,
            reasoning_effort=profile.reasoning_effort,
            reasoning=profile.reasoning(default_exclude=self._config.exclude_reasoning),
            extra_headers=self._openrouter_headers(),
            response_format=None,
            cancel_token=cancel_token,
            trace_route="turn_router.save_review",
            trace_profile="turn_router",
        )
        try:
            completed = complete_text(request, self._completion)
            payload_json = extract_json_object(completed.content)
            return GeneratedSaveMechanicsReview.model_validate_json(payload_json)
        except (
            *LITELLM_RETRYABLE_ERRORS,
            ValidationError,
            json.JSONDecodeError,
            EmptyRouteContentError,
            ValueError,
        ):
            return None
