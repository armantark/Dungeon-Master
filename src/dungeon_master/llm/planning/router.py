from __future__ import annotations

import json
import time

from pydantic import ValidationError

from dungeon_master.cancel import CancellationToken
from dungeon_master.llm.planning.contracts import (
    EmptyRouteContentError,
    GeneratedTurnPlan,
    RouterClassifier,
    TurnPlan,
)
from dungeon_master.llm.planning.normalization import PlanNormalizer
from dungeon_master.llm.planning.prompts import (
    TURN_ROUTER_REPAIR_SYSTEM_PROMPT,
    TURN_ROUTER_SYSTEM_PROMPT,
    TURN_ROUTER_USER_PROMPT_TEMPLATE,
)
from dungeon_master.llm.planning.review_gates import ReviewGates
from dungeon_master.models import Likelihood
from dungeon_master.narrative import (
    LITELLM_RETRYABLE_ERRORS,
    CompletionFunction,
    CompletionRequest,
    NarrativeConfig,
    _completion,
    complete_text,
    extract_json_object,
)
from dungeon_master.observability import log_decision


def _raise_empty_route_content_error() -> None:
    message = "Route classifier returned empty content."
    raise EmptyRouteContentError(message)


class TurnRouter(ReviewGates, PlanNormalizer):
    def __init__(
        self,
        classifier: RouterClassifier | None = None,
        config: NarrativeConfig | None = None,
        completion_function: CompletionFunction = _completion,
    ) -> None:
        self._classifier = classifier
        self._config = config or NarrativeConfig.from_env()
        self._completion = completion_function

    def plan(
        self,
        text: str,
        *,
        memory_context: str | None = None,
        scene_messages: list[dict[str, str]] | None = None,
        combat_encounter_hint: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> TurnPlan:
        body, likelihood = self._strip_likelihood_hint(text)
        normalized = body.strip()
        if not normalized:
            plan = self._fallback_plan(text.strip() or text)
            self._log_plan_decision(plan, source="empty")
            return plan

        if self._classifier is not None:
            classified = self._classifier(normalized, likelihood)
            plan = self._finalize_plan(classified, normalized, likelihood)
            self._log_plan_decision(plan, source="classifier")
            return plan

        if not self._config.is_usable():
            plan = self._fallback_plan(normalized)
            self._log_plan_decision(plan, source="no_model")
            return plan

        prompt_core = (
            TURN_ROUTER_USER_PROMPT_TEMPLATE.replace("<<TURN>>", normalized)
            .replace("<<MEMORY>>", memory_context or "(none)")
            .replace("<<LIKELIHOOD>>", likelihood.value if likelihood is not None else "null")
        )
        hint = combat_encounter_hint.strip() if combat_encounter_hint is not None else ""
        prompt = (
            f"{prompt_core}\nCanonical encounter status from backend (authoritative):\n"
            f"{hint}\n"
            if hint
            else prompt_core
        )
        profile = self._config.profiles.turn_router
        request = CompletionRequest(
            model=self._config.model,
            messages=[
                {"role": "system", "content": TURN_ROUTER_SYSTEM_PROMPT},
                *(scene_messages or []),
                {"role": "user", "content": prompt},
            ],
            temperature=profile.temperature,
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
            trace_route="turn_router.plan",
            trace_profile="turn_router",
        )

        last_error: Exception | None = None
        last_content: str = ""
        for attempt in range(self._config.max_retries + 1):
            try:
                completed = complete_text(request, self._completion)
                content = completed.content
                last_content = content
                if not content:
                    _raise_empty_route_content_error()
                payload = extract_json_object(content)
                parsed = GeneratedTurnPlan.model_validate_json(payload)
                plan = self._normalize_generated_plan(parsed, normalized, likelihood)
                plan = self._review_combat_mechanics_plan(
                    plan,
                    normalized_text=normalized,
                    combat_encounter_hint=combat_encounter_hint,
                    cancel_token=cancel_token,
                )
                plan = self._review_save_mechanics_plan(
                    plan,
                    normalized_text=normalized,
                    memory_context=memory_context,
                    cancel_token=cancel_token,
                )
                self._log_plan_decision(plan, source="model")
            except (
                *LITELLM_RETRYABLE_ERRORS,
                ValidationError,
                json.JSONDecodeError,
                EmptyRouteContentError,
                ValueError,
            ) as exc:
                last_error = exc
                if attempt < self._config.max_retries:
                    time.sleep(0.4 * (attempt + 1))
            else:
                return plan

        repaired = self._repair_generated_plan(
            raw_content=last_content,
            validation_error=last_error,
            normalized_text=normalized,
            likelihood=likelihood,
            cancel_token=cancel_token,
        )
        if repaired is not None:
            repaired = self._review_combat_mechanics_plan(
                repaired,
                normalized_text=normalized,
                combat_encounter_hint=combat_encounter_hint,
                cancel_token=cancel_token,
            )
            repaired = self._review_save_mechanics_plan(
                repaired,
                normalized_text=normalized,
                memory_context=memory_context,
                cancel_token=cancel_token,
            )
            self._log_plan_decision(repaired, source="repair")
            return repaired

        plan = self._fallback_plan(normalized)
        self._log_plan_decision(
            plan,
            source="fallback" if last_error is None else "model_error_fallback",
        )
        return plan

    def _repair_generated_plan(
        self,
        *,
        raw_content: str,
        validation_error: Exception | None,
        normalized_text: str,
        likelihood: Likelihood | None,
        cancel_token: CancellationToken | None,
    ) -> TurnPlan | None:
        if not raw_content.strip() and validation_error is None:
            return None
        profile = self._config.profiles.turn_router
        repair_payload = {
            "schema": GeneratedTurnPlan.model_json_schema(),
            "original_player_turn": normalized_text,
            "explicit_likelihood_hint": likelihood.value if likelihood is not None else None,
            "failed_payload": raw_content,
            "validation_error": str(validation_error) if validation_error is not None else None,
        }
        request = CompletionRequest(
            model=self._config.model,
            messages=[
                {"role": "system", "content": TURN_ROUTER_REPAIR_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(repair_payload)},
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
            trace_route="turn_router.repair",
            trace_profile="turn_router",
        )
        try:
            completed = complete_text(request, self._completion)
            payload = extract_json_object(completed.content)
            parsed = GeneratedTurnPlan.model_validate_json(payload)
            return self._normalize_generated_plan(parsed, normalized_text, likelihood)
        except (
            *LITELLM_RETRYABLE_ERRORS,
            ValidationError,
            json.JSONDecodeError,
            EmptyRouteContentError,
            ValueError,
        ):
            return None

    def _log_plan_decision(self, plan: TurnPlan, *, source: str) -> None:
        ops = ",".join(op.kind.value for op in plan.ops)
        log_decision(
            "turn.router",
            route=plan.route.value,
            source=source,
            ops=ops,
            time_advance=plan.time_advance.value,
            survival_actions=",".join(action.value for action in plan.survival_actions) or "none",
        )

    def _openrouter_headers(self) -> dict[str, str] | None:
        if not self._config.model.startswith("openrouter/"):
            return None
        headers: dict[str, str] = {}
        if self._config.site_url is not None:
            headers["HTTP-Referer"] = self._config.site_url
        if self._config.app_name is not None:
            headers["X-Title"] = self._config.app_name
        return headers or None
