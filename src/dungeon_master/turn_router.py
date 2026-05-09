from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from pydantic import Field, ValidationError

from dungeon_master.cancel import CancellationToken
from dungeon_master.models import (
    AttackStance,
    CairnAbility,
    CairnRestKind,
    CairnSurvivalAction,
    CairnTimeAdvance,
    Likelihood,
    StrictModel,
)
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


class TurnRoute(StrEnum):
    """Legacy summary route surfaced to the rest of the backend/frontend."""

    PLAYER_ACTION = "player_action"
    YES_NO = "yes_no"
    RANDOM_EVENT = "random_event"
    SCENE_CHECK = "scene_check"
    SAVE = "save"
    ATTACK = "attack"
    HARM = "harm"
    RECOVERY = "recovery"
    EQUIP = "equip"
    RETREAT = "retreat"


class PlannedTurnOpKind(StrEnum):
    YES_NO = "yes_no"
    RANDOM_EVENT = "random_event"
    SCENE_CHECK = "scene_check"
    SAVE = "save"
    ATTACK = "attack"
    ENEMY_OPENER = "enemy_opener"
    HARM = "harm"
    RECOVERY = "recovery"
    EQUIP = "equip"
    RETREAT = "retreat"
    INSPECT_INVENTORY = "inspect_inventory"
    SEARCH_SCENE = "search_scene"
    ACQUIRE_ITEM = "acquire_item"
    TRANSFER_ITEM = "transfer_item"
    RECRUIT_NPC = "recruit_npc"
    USE_ITEM = "use_item"
    DROP_ITEM = "drop_item"
    NARRATE = "narrate"


@dataclass(frozen=True)
class PlannedTurnOp:
    kind: PlannedTurnOpKind
    text: str
    likelihood: Likelihood | None = None
    ability: CairnAbility | None = None
    target_name: str | None = None
    stance: AttackStance | None = None
    rest_kind: CairnRestKind | None = None
    item_name: str | None = None
    npc_name: str | None = None
    actor_name: str | None = None
    source_actor_name: str | None = None
    target_actor_name: str | None = None
    equipped: bool | None = None
    harm_amount: int | None = None
    harm_source: str | None = None
    armor_applies: bool | None = None
    in_combat: bool | None = None


@dataclass(frozen=True)
class TurnPlan:
    route: TurnRoute
    text: str
    ops: tuple[PlannedTurnOp, ...]
    time_advance: CairnTimeAdvance = CairnTimeAdvance.NONE
    survival_actions: tuple[CairnSurvivalAction, ...] = ()


@dataclass(frozen=True)
class RoutedTurn:
    route: TurnRoute
    text: str
    likelihood: Likelihood | None = None
    ability: CairnAbility | None = None
    target_name: str | None = None
    stance: AttackStance | None = None
    rest_kind: CairnRestKind | None = None
    item_name: str | None = None
    npc_name: str | None = None
    actor_name: str | None = None
    source_actor_name: str | None = None
    target_actor_name: str | None = None
    equipped: bool | None = None
    harm_amount: int | None = None
    harm_source: str | None = None
    armor_applies: bool | None = None
    in_combat: bool | None = None
    time_advance: CairnTimeAdvance = CairnTimeAdvance.NONE
    survival_actions: tuple[CairnSurvivalAction, ...] = ()
    plan: TurnPlan | None = None


class GeneratedPlannedTurnOp(StrictModel):
    kind: PlannedTurnOpKind
    text: str = Field(min_length=1)
    likelihood: Likelihood | None = None
    ability: CairnAbility | None = None
    target_name: str | None = None
    stance: AttackStance | None = None
    rest_kind: CairnRestKind | None = None
    item_name: str | None = None
    npc_name: str | None = None
    actor_name: str | None = None
    source_actor_name: str | None = None
    target_actor_name: str | None = None
    equipped: bool | None = None
    harm_amount: int | None = Field(default=None, ge=0)
    harm_source: str | None = None
    armor_applies: bool | None = None
    in_combat: bool | None = None


class GeneratedTurnPlan(StrictModel):
    route: TurnRoute
    text: str = Field(min_length=1)
    ops: list[GeneratedPlannedTurnOp] = Field(min_length=1, max_length=3)
    time_advance: CairnTimeAdvance = CairnTimeAdvance.NONE
    survival_actions: list[CairnSurvivalAction] = Field(default_factory=list, max_length=2)


RouterClassifier = Callable[[str, Likelihood | None], RoutedTurn | TurnPlan]


class EmptyRouteContentError(ValueError):
    pass


class TurnPlanningError(ValueError):
    pass


def _raise_empty_route_content_error() -> None:
    message = "Route classifier returned empty content."
    raise EmptyRouteContentError(message)


LIKELIHOOD_HINTS: dict[str, Likelihood] = {
    "impossible": Likelihood.IMPOSSIBLE,
    "very-unlikely": Likelihood.VERY_UNLIKELY,
    "very_unlikely": Likelihood.VERY_UNLIKELY,
    "very unlikely": Likelihood.VERY_UNLIKELY,
    "unlikely": Likelihood.UNLIKELY,
    "even": Likelihood.EVEN,
    "even-odds": Likelihood.EVEN,
    "even_odds": Likelihood.EVEN,
    "even odds": Likelihood.EVEN,
    "likely": Likelihood.LIKELY,
    "very-likely": Likelihood.VERY_LIKELY,
    "very_likely": Likelihood.VERY_LIKELY,
    "very likely": Likelihood.VERY_LIKELY,
    "certain": Likelihood.NEARLY_CERTAIN,
    "nearly-certain": Likelihood.NEARLY_CERTAIN,
    "nearly_certain": Likelihood.NEARLY_CERTAIN,
    "nearly certain": Likelihood.NEARLY_CERTAIN,
}


TURN_ROUTER_SYSTEM_PROMPT = """You plan a bounded backend action sequence for a solo
TTRPG player's free-text turn before narration happens.

Return only valid JSON.

`route` is the legacy summary label for the whole turn:
- player_action
- yes_no
- random_event
- scene_check
- save
- attack
- harm
- recovery
- equip
- retreat

`ops` is an ordered list of 1-3 bounded backend steps.

Allowed op kinds:
- narrate: pure narration, no deterministic backend step inferred
- yes_no: an explicit yes/no oracle question about uncertainty, fate, luck,
  or facts not directly answerable by immediate observation
- random_event: the player is explicitly asking for a complication, twist, or random event
- scene_check: the player is explicitly pushing into a new scene, location, or
  travel transition right now
- save: the player is attempting one risky immediate action that should
  resolve as a Cairn-style save
- attack: the player is attacking or striking a concrete foe right now
- enemy_opener: a hostile foe is clearly striking first, springing an ambush,
  or seizing initiative in a way that should start a tracked encounter now
- harm: the player is explicitly taking damage or a blow should be resolved directly
- recovery: the player is explicitly resting, catching breath, or recovering
- equip: the player is explicitly readying, drawing, donning, stowing,
  equipping, or unequipping gear
- retreat: the player is explicitly disengaging, falling back, fleeing,
  withdrawing, or trying to escape an active fight
- inspect_inventory: the player is checking carried gear, supplies, burden,
  or what they currently have
- search_scene: the player is visually or physically inspecting the immediate
  area, path ahead, doorway, or nearby situation from the current vantage
  without definitely transitioning scenes
- acquire_item: the player is explicitly taking, looting, receiving, buying,
  or otherwise adding a concrete item or bundle to their carried gear now
- transfer_item: an existing carried item is being moved between the player
  and a named party member, hireling, animal, or companion
- recruit_npc: a visible NPC is joining the player's party as a companion
  or hireling now
- use_item: the player is explicitly drinking, lighting, applying,
  consuming, reading, invoking, praying with, or otherwise using a carried item
- drop_item: the player is explicitly dropping, abandoning, or setting down a carried item

Rules:
- Be conservative. If uncertain, return route `player_action` and a single `narrate` op.
- Do not invent mechanics not implied by the text.
- Do not invent items, foes, or scene discoveries that the text does not support.
- Use any supplied memory context as support, not as permission to invent.
- Prefer canonical supplied memory over improvising from tone.
- Preserve the player's meaning; clean wording lightly but do not rewrite
  it into a different action.
- You may emit preparatory ops before one primary deterministic op,
  e.g. `equip` then `attack`, or `inspect_inventory` then `scene_check`.
- Emit at most one primary oracle/mechanical op from this set:
  `yes_no`, `random_event`, `scene_check`, `save`, `attack`, `enemy_opener`,
  `harm`, `recovery`.
- If ops contain one of those primary oracle/mechanical ops, `route` must match it.
- Exception: if the primary op is `enemy_opener`, `route` must be `harm`
  because the stable public outcome kind remains `harm`.
- If ops contain only `equip`, `route` may be `equip`.
- If ops contain only `inspect_inventory`, `search_scene`, `acquire_item`, `use_item`,
  `transfer_item`, `recruit_npc`, `drop_item`, or `narrate`, route must be
  `player_action`.
- Use `save` only when the player is attempting one concrete risky action right now.
- If kind is `save`, choose exactly one ability: `STR`, `DEX`, or `WIL`.
- If kind is `attack`, include `target_name`, and choose `stance` if clearly implied.
- If kind is `enemy_opener`, include `harm_source` naming the hostile opener.
- If kind is `recovery`, choose one `rest_kind`: `breather`, `full_rest`, or `week_recovery`.
- If kind is `equip`, include `item_name` and whether the player is
  equipping (`true`) or unequipping (`false`).
- If kind is `retreat`, use it only for an explicit attempt to break contact or flee.
- If kind is `acquire_item`, use it only when the text supports adding gear
  to inventory immediately. Preserve the player's wording; do not invent a
  full item list in the planner itself.
- If kind is `transfer_item`, include `item_name`, `source_actor_name`, and
  `target_actor_name`. Use "player" for the main character when needed.
- If kind is `recruit_npc`, include `npc_name` naming the visible NPC who
  joins the party now.
- If another action is performed by a named party member, include `actor_name`.
- If kind is `use_item` or `drop_item`, include `item_name`.
- A prayer by itself is usually `narrate` or an oracle/save if risk is explicit.
  A prayer that explicitly invokes a carried icon, relic, scroll, prayer book,
  spellbook, oil, or similar object should be `use_item` with that item name.
- Use `harm` sparingly. Prefer `save` for risky actions and `attack` for offensive actions.
- If kind is `yes_no`, preserve a supplied likelihood hint if one was explicitly given.
- Also classify elapsed time for the whole turn:
  - `none`: no meaningful fiction time passes
  - `brief`: a quick exchange, breath, glance, or immediate beat
  - `watch`: exploration, waiting, one travel leg, or an extended search
  - `day`: a major daylight push, march, or downtime span
  - `overnight`: bedding down, camp sleep, or resting through the night
- Also classify explicit survival actions for the whole turn:
  - include `eat` only when the player explicitly eats carried food, rations, or supplies now
  - include `sleep` only when the player explicitly sleeps, makes camp, or beds down now
  - a `full_rest` usually includes `sleep`, and often `eat` when the player clearly consumes rations
- If the player is asking what they can currently see, hear, notice, or make
  out about the immediate area or path ahead, prefer `search_scene` even if
  the wording is a question.
- Do not treat recon questions like "Are there enemies ahead?", "Do I see
  movement on the trail?", or "Can I spot a guard from here?" as committed
  travel or a scene transition by themselves.
- Use `scene_check` only when the player explicitly commits to moving onward,
  entering, crossing, descending, approaching, traveling, or otherwise
  advancing into a new scene now.
"""


TURN_ROUTER_USER_PROMPT_TEMPLATE = (
    "Return JSON with this shape:\n"
    "{\n"
    '  "route": "player_action | yes_no | random_event | scene_check | save | '
    'attack | harm | recovery | equip | retreat",\n'
    '  "text": "normalized player text",\n'
    '  "time_advance": "none | brief | watch | day | overnight",\n'
    '  "survival_actions": ["eat | sleep", "..."],\n'
    '  "ops": [\n'
    "    {\n"
    '      "kind": "narrate | yes_no | random_event | scene_check | save | attack | '
    'enemy_opener | harm | recovery | equip | retreat | acquire_item | transfer_item | '
    'recruit_npc | inspect_inventory | search_scene | use_item | drop_item",\n'
    '      "text": "normalized text for this step",\n'
    '      "likelihood": "one Likelihood value or null",\n'
    '      "ability": "STR | DEX | WIL | null",\n'
    '      "target_name": "string or null",\n'
    '      "stance": "normal | impaired | enhanced | null",\n'
    '      "rest_kind": "breather | full_rest | week_recovery | null",\n'
    '      "item_name": "string or null",\n'
    '      "npc_name": "string or null",\n'
    '      "actor_name": "string or null",\n'
    '      "source_actor_name": "string or null",\n'
    '      "target_actor_name": "string or null",\n'
    '      "equipped": "true | false | null",\n'
    '      "harm_amount": "integer or null",\n'
    '      "harm_source": "string or null",\n'
    '      "armor_applies": "true | false | null",\n'
    '      "in_combat": "true | false | null"\n'
    "    }\n"
    "  ]\n"
    "}\n\n"
    "Player turn:\n"
    "<<TURN>>\n\n"
    "Bounded memory context (may be empty):\n"
    "<<MEMORY>>\n\n"
    "Explicit likelihood hint (may be null):\n"
    "<<LIKELIHOOD>>\n"
)

TURN_ROUTER_REPAIR_SYSTEM_PROMPT = """You repair one failed turn-planner JSON payload.

Return only valid JSON matching the supplied schema.
Do not add prose, markdown fences, comments, or explanations.

If the failed payload cannot be repaired confidently, return a conservative plan:
- route: "player_action"
- text: the original player turn
- ops: one op with kind "narrate" and text equal to the original player turn
"""


class TurnRouter:
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
            plan = self._normalize_classifier_result(classified, normalized, likelihood)
            self._log_plan_decision(plan, source="classifier")
            return plan

        if not self._config.is_usable():
            plan = self._fallback_plan(normalized)
            self._log_plan_decision(plan, source="no_model")
            return plan

        prompt = (
            TURN_ROUTER_USER_PROMPT_TEMPLATE.replace("<<TURN>>", normalized)
            .replace("<<MEMORY>>", memory_context or "(none)")
            .replace("<<LIKELIHOOD>>", likelihood.value if likelihood is not None else "null")
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

    def route(
        self,
        text: str,
        *,
        memory_context: str | None = None,
        scene_messages: list[dict[str, str]] | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> RoutedTurn:
        return self._routed_turn_from_plan(
            self.plan(
                text,
                memory_context=memory_context,
                scene_messages=scene_messages,
                cancel_token=cancel_token,
            ),
        )

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

    def _fallback_plan(self, text: str) -> TurnPlan:
        return TurnPlan(
            route=TurnRoute.PLAYER_ACTION,
            text=text,
            ops=(PlannedTurnOp(kind=PlannedTurnOpKind.NARRATE, text=text),),
            time_advance=CairnTimeAdvance.NONE,
            survival_actions=(),
        )

    def _normalize_classifier_result(
        self,
        classified: RoutedTurn | TurnPlan,
        normalized_text: str,
        likelihood: Likelihood | None,
    ) -> TurnPlan:
        if isinstance(classified, TurnPlan):
            return self._finalize_plan(classified, normalized_text, likelihood)
        return self._finalize_plan(
            TurnPlan(
                route=classified.route,
                text=classified.text,
                ops=(self._planned_op_from_routed_turn(classified),),
                time_advance=classified.time_advance,
                survival_actions=classified.survival_actions,
            ),
            normalized_text,
            likelihood,
        )

    def _normalize_generated_plan(
        self,
        parsed: GeneratedTurnPlan,
        normalized_text: str,
        likelihood: Likelihood | None,
    ) -> TurnPlan:
        plan = TurnPlan(
            route=parsed.route,
            text=parsed.text,
            ops=tuple(
                PlannedTurnOp(
                    kind=op.kind,
                    text=op.text,
                    likelihood=op.likelihood,
                    ability=op.ability,
                    target_name=op.target_name,
                    stance=op.stance,
                    rest_kind=op.rest_kind,
                    item_name=op.item_name,
                    npc_name=op.npc_name,
                    actor_name=op.actor_name,
                    source_actor_name=op.source_actor_name,
                    target_actor_name=op.target_actor_name,
                    equipped=op.equipped,
                    harm_amount=op.harm_amount,
                    harm_source=op.harm_source,
                    armor_applies=op.armor_applies,
                    in_combat=op.in_combat,
                )
                for op in parsed.ops
            ),
            time_advance=parsed.time_advance,
            survival_actions=tuple(parsed.survival_actions),
        )
        return self._finalize_plan(plan, normalized_text, likelihood)

    def _finalize_plan(
        self,
        plan: TurnPlan,
        normalized_text: str,
        likelihood: Likelihood | None,
    ) -> TurnPlan:
        text = plan.text.strip() or normalized_text
        ops = tuple(
            self._normalize_op(
                op,
                route=plan.route,
                fallback_likelihood=likelihood,
            )
            for op in plan.ops
        )
        if not ops:
            return self._fallback_plan(text)
        return TurnPlan(
            route=plan.route,
            text=text,
            ops=ops,
            time_advance=plan.time_advance,
            survival_actions=tuple(dict.fromkeys(plan.survival_actions)),
        )

    def _normalize_op(  # noqa: C901, PLR0912
        self,
        op: PlannedTurnOp,
        *,
        route: TurnRoute,
        fallback_likelihood: Likelihood | None,
    ) -> PlannedTurnOp:
        step_text = op.text.strip()
        if not step_text:
            message = "Planned op text cannot be empty."
            raise ValueError(message)
        if op.kind == PlannedTurnOpKind.YES_NO:
            final_likelihood = op.likelihood or fallback_likelihood or Likelihood.EVEN
        else:
            final_likelihood = None
        if op.kind == PlannedTurnOpKind.SAVE and op.ability is None:
            message = "Save ops require an ability."
            raise ValueError(message)
        if op.kind == PlannedTurnOpKind.ATTACK and op.target_name is None:
            message = "Attack ops require a target_name."
            raise ValueError(message)
        if op.kind == PlannedTurnOpKind.ENEMY_OPENER:
            if route != TurnRoute.HARM:
                message = "enemy_opener ops require the legacy route to remain harm."
                raise ValueError(message)
            if op.harm_source is None and op.target_name is None:
                message = "enemy_opener ops require a harm_source or target_name."
                raise ValueError(message)
        if op.kind == PlannedTurnOpKind.RECOVERY and op.rest_kind is None:
            message = "Recovery ops require a rest_kind."
            raise ValueError(message)
        if op.kind in (
            PlannedTurnOpKind.EQUIP,
            PlannedTurnOpKind.USE_ITEM,
            PlannedTurnOpKind.DROP_ITEM,
            PlannedTurnOpKind.TRANSFER_ITEM,
        ) and op.item_name is None:
            message = f"{op.kind.value} ops require an item_name."
            raise ValueError(message)
        if op.kind == PlannedTurnOpKind.TRANSFER_ITEM and (
            op.source_actor_name is None or op.target_actor_name is None
        ):
            message = "transfer_item ops require source_actor_name and target_actor_name."
            raise ValueError(message)
        if op.kind == PlannedTurnOpKind.RECRUIT_NPC and op.npc_name is None:
            message = "recruit_npc ops require an npc_name."
            raise ValueError(message)
        if op.kind in (
            PlannedTurnOpKind.INSPECT_INVENTORY,
            PlannedTurnOpKind.SEARCH_SCENE,
            PlannedTurnOpKind.ACQUIRE_ITEM,
            PlannedTurnOpKind.USE_ITEM,
            PlannedTurnOpKind.TRANSFER_ITEM,
            PlannedTurnOpKind.RECRUIT_NPC,
            PlannedTurnOpKind.DROP_ITEM,
            PlannedTurnOpKind.NARRATE,
        ) and route != TurnRoute.PLAYER_ACTION:
            # Preparatory ops are allowed ahead of a primary mechanical op; the
            # route summary remains whatever the primary op is. We therefore only
            # need to normalize these, not remap the route.
            pass
        return PlannedTurnOp(
            kind=op.kind,
            text=step_text,
            likelihood=final_likelihood,
            ability=op.ability,
            target_name=op.target_name,
            stance=op.stance,
            rest_kind=op.rest_kind,
            item_name=op.item_name,
            npc_name=op.npc_name,
            actor_name=op.actor_name,
            source_actor_name=op.source_actor_name,
            target_actor_name=op.target_actor_name,
            equipped=op.equipped,
            harm_amount=op.harm_amount,
            harm_source=op.harm_source or op.target_name,
            armor_applies=op.armor_applies,
            in_combat=op.in_combat,
        )

    def _planned_op_from_routed_turn(self, routed: RoutedTurn) -> PlannedTurnOp:
        kind = {
            TurnRoute.YES_NO: PlannedTurnOpKind.YES_NO,
            TurnRoute.RANDOM_EVENT: PlannedTurnOpKind.RANDOM_EVENT,
            TurnRoute.SCENE_CHECK: PlannedTurnOpKind.SCENE_CHECK,
            TurnRoute.SAVE: PlannedTurnOpKind.SAVE,
            TurnRoute.ATTACK: PlannedTurnOpKind.ATTACK,
            TurnRoute.HARM: PlannedTurnOpKind.HARM,
            TurnRoute.RECOVERY: PlannedTurnOpKind.RECOVERY,
            TurnRoute.EQUIP: PlannedTurnOpKind.EQUIP,
            TurnRoute.RETREAT: PlannedTurnOpKind.RETREAT,
            TurnRoute.PLAYER_ACTION: PlannedTurnOpKind.NARRATE,
        }[routed.route]
        return PlannedTurnOp(
            kind=kind,
            text=routed.text,
            likelihood=routed.likelihood,
            ability=routed.ability,
            target_name=routed.target_name,
            stance=routed.stance,
            rest_kind=routed.rest_kind,
            item_name=routed.item_name,
            npc_name=routed.npc_name,
            actor_name=routed.actor_name,
            source_actor_name=routed.source_actor_name,
            target_actor_name=routed.target_actor_name,
            equipped=routed.equipped,
            harm_amount=routed.harm_amount,
            harm_source=routed.harm_source,
            armor_applies=routed.armor_applies,
            in_combat=routed.in_combat,
        )

    def _routed_turn_from_plan(self, plan: TurnPlan) -> RoutedTurn:
        primary = self._primary_op(plan)
        return RoutedTurn(
            route=plan.route,
            text=plan.text,
            likelihood=primary.likelihood if plan.route == TurnRoute.YES_NO else None,
            ability=primary.ability,
            target_name=primary.target_name,
            stance=primary.stance,
            rest_kind=primary.rest_kind,
            item_name=primary.item_name,
            npc_name=primary.npc_name,
            actor_name=primary.actor_name,
            source_actor_name=primary.source_actor_name,
            target_actor_name=primary.target_actor_name,
            equipped=primary.equipped,
            harm_amount=primary.harm_amount,
            harm_source=primary.harm_source,
            armor_applies=primary.armor_applies,
            in_combat=primary.in_combat,
            time_advance=plan.time_advance,
            survival_actions=plan.survival_actions,
            plan=plan,
        )

    def _primary_op(self, plan: TurnPlan) -> PlannedTurnOp:
        legacy_kind = {
            TurnRoute.YES_NO: PlannedTurnOpKind.YES_NO,
            TurnRoute.RANDOM_EVENT: PlannedTurnOpKind.RANDOM_EVENT,
            TurnRoute.SCENE_CHECK: PlannedTurnOpKind.SCENE_CHECK,
            TurnRoute.SAVE: PlannedTurnOpKind.SAVE,
            TurnRoute.ATTACK: PlannedTurnOpKind.ATTACK,
            TurnRoute.HARM: PlannedTurnOpKind.HARM,
            TurnRoute.RECOVERY: PlannedTurnOpKind.RECOVERY,
            TurnRoute.EQUIP: PlannedTurnOpKind.EQUIP,
            TurnRoute.RETREAT: PlannedTurnOpKind.RETREAT,
            TurnRoute.PLAYER_ACTION: PlannedTurnOpKind.NARRATE,
        }[plan.route]
        for op in reversed(plan.ops):
            if op.kind == legacy_kind:
                return op
        return plan.ops[-1]

    def _strip_likelihood_hint(self, text: str) -> tuple[str, Likelihood | None]:
        match = re.search(r"\[([^\]]+)\]\s*$", text)
        if match is None:
            return text, None

        raw_hint = match.group(1).strip().lower()
        canonical = re.sub(r"\s+", " ", raw_hint)
        likelihood = LIKELIHOOD_HINTS.get(canonical) or LIKELIHOOD_HINTS.get(
            canonical.replace(" ", "-"),
        )
        if likelihood is None:
            return text, None
        return text[: match.start()].strip(), likelihood

    def _openrouter_headers(self) -> dict[str, str] | None:
        if not self._config.model.startswith("openrouter/"):
            return None
        headers: dict[str, str] = {}
        if self._config.site_url is not None:
            headers["HTTP-Referer"] = self._config.site_url
        if self._config.app_name is not None:
            headers["X-Title"] = self._config.app_name
        return headers or None
