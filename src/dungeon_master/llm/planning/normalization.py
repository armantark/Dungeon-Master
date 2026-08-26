from __future__ import annotations

import re

from dungeon_master.llm.planning.contracts import (
    GeneratedTurnPlan,
    PlannedTurnOp,
    PlannedTurnOpKind,
    TurnPlan,
    TurnRoute,
)
from dungeon_master.models import CairnTimeAdvance, Likelihood

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


def fallback_harm_source(op: PlannedTurnOp) -> str | None:
    if op.kind in {PlannedTurnOpKind.HARM, PlannedTurnOpKind.ENEMY_OPENER}:
        return op.target_name
    return None


class PlanNormalizer:
    def _fallback_plan(self, text: str) -> TurnPlan:
        return TurnPlan(
            route=TurnRoute.PLAYER_ACTION,
            text=text,
            ops=(PlannedTurnOp(kind=PlannedTurnOpKind.NARRATE, text=text),),
            time_advance=CairnTimeAdvance.NONE,
            survival_actions=(),
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
                    supporting_actor_names=tuple(op.supporting_actor_names),
                    source_actor_name=op.source_actor_name,
                    target_actor_name=op.target_actor_name,
                    equipped=op.equipped,
                    harm_amount=op.harm_amount,
                    harm_source=op.harm_source,
                    armor_applies=op.armor_applies,
                    in_combat=op.in_combat,
                    advantage_payoff=op.advantage_payoff,
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

    def _normalize_op(  # noqa: C901, PLR0912, PLR0915
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
        if op.kind == PlannedTurnOpKind.BEGIN_ENCOUNTER and op.target_name is None:
            message = "begin_encounter ops require a target_name."
            raise ValueError(message)
        if op.kind == PlannedTurnOpKind.ATTACK and op.target_name is None:
            message = "Attack ops require a target_name."
            raise ValueError(message)
        if op.kind == PlannedTurnOpKind.COORDINATED_ATTACK:
            if op.target_name is None:
                message = "Coordinated attack ops require a target_name."
                raise ValueError(message)
            if not op.supporting_actor_names:
                message = "Coordinated attack ops require at least one supporting actor."
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
        if op.kind == PlannedTurnOpKind.SETUP_ADVANTAGE:
            if route != TurnRoute.PLAYER_ACTION:
                message = "setup_advantage ops require the legacy route to remain player_action."
                raise ValueError(message)
            if op.target_name is None:
                message = "setup_advantage ops require a target_name."
                raise ValueError(message)
            if op.advantage_payoff is None:
                message = "setup_advantage ops require an advantage_payoff."
                raise ValueError(message)
        if (
            op.kind
            in (
                PlannedTurnOpKind.EQUIP,
                PlannedTurnOpKind.USE_ITEM,
                PlannedTurnOpKind.DROP_ITEM,
                PlannedTurnOpKind.TRANSFER_ITEM,
            )
            and op.item_name is None
        ):
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
        if (
            op.kind
            in (
                PlannedTurnOpKind.INSPECT_INVENTORY,
                PlannedTurnOpKind.SEARCH_SCENE,
                PlannedTurnOpKind.ACQUIRE_ITEM,
                PlannedTurnOpKind.USE_ITEM,
                PlannedTurnOpKind.TRANSFER_ITEM,
                PlannedTurnOpKind.RECRUIT_NPC,
                PlannedTurnOpKind.DROP_ITEM,
                PlannedTurnOpKind.SETUP_ADVANTAGE,
                PlannedTurnOpKind.BEGIN_ENCOUNTER,
                PlannedTurnOpKind.CLARIFY,
                PlannedTurnOpKind.NARRATE,
            )
            and route != TurnRoute.PLAYER_ACTION
        ):
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
            supporting_actor_names=tuple(dict.fromkeys(op.supporting_actor_names)),
            source_actor_name=op.source_actor_name,
            target_actor_name=op.target_actor_name,
            equipped=op.equipped,
            harm_amount=op.harm_amount,
            harm_source=op.harm_source or fallback_harm_source(op),
            armor_applies=op.armor_applies,
            in_combat=op.in_combat,
            advantage_payoff=op.advantage_payoff,
        )

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
