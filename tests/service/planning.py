from dungeon_master.domain.models import (
    AttackStance,
    CairnAbility,
    CairnRestKind,
    Likelihood,
)
from dungeon_master.llm.planning import (
    PlannedTurnOp,
    PlannedTurnOpKind,
    TurnPlan,
    TurnRoute,
)


def scripted_classifier(text: str, likelihood: Likelihood | None) -> TurnPlan:  # noqa: PLR0911
    if text == "Is the abbey gate watched?":
        return TurnPlan(
            route=TurnRoute.YES_NO,
            text=text,
            ops=(
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.YES_NO,
                    text=text,
                    likelihood=likelihood or Likelihood.LIKELY,
                ),
            ),
        )
    if text == "I cross the bone bridge before dawn.":
        return TurnPlan(
            route=TurnRoute.SCENE_CHECK,
            text=text,
            ops=(PlannedTurnOp(kind=PlannedTurnOpKind.SCENE_CHECK, text=text),),
        )
    if text == "I balance across the abbey beam.":
        return TurnPlan(
            route=TurnRoute.SAVE,
            text=text,
            ops=(
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.SAVE,
                    text=text,
                    ability=CairnAbility.DEX,
                ),
            ),
        )
    if text == "I swing my cudgel at the abbey ghoul.":
        return TurnPlan(
            route=TurnRoute.ATTACK,
            text=text,
            ops=(
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.ATTACK,
                    text=text,
                    target_name="Abbey ghoul",
                    stance=AttackStance.NORMAL,
                ),
            ),
        )
    if text == "I catch my breath and drink water.":
        return TurnPlan(
            route=TurnRoute.RECOVERY,
            text=text,
            ops=(
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.RECOVERY,
                    text=text,
                    rest_kind=CairnRestKind.BREATHER,
                ),
            ),
        )
    if text == "I draw the test knife.":
        return TurnPlan(
            route=TurnRoute.EQUIP,
            text=text,
            ops=(
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.EQUIP,
                    text=text,
                    item_name="Test knife",
                    equipped=True,
                ),
            ),
        )
    if text == "I fall back through the chapel arch.":
        return TurnPlan(
            route=TurnRoute.RETREAT,
            text=text,
            ops=(PlannedTurnOp(kind=PlannedTurnOpKind.RETREAT, text=text),),
        )
    return TurnPlan(
        route=TurnRoute.PLAYER_ACTION,
        text=text,
        ops=(PlannedTurnOp(kind=PlannedTurnOpKind.NARRATE, text=text),),
    )
