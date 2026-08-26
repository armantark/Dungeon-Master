from dungeon_master.domain.models import (
    AttackStance,
    CairnRestKind,
    CairnSurvivalAction,
    CairnTimeAdvance,
    Likelihood,
)
from dungeon_master.llm.planning import (
    PlannedTurnOp,
    PlannedTurnOpKind,
    TurnPlan,
    TurnRoute,
    TurnRouter,
)


def test_classifier_can_return_recovery_route() -> None:
    router = TurnRouter(
        classifier=lambda text, likelihood: TurnPlan(
            route=TurnRoute.RECOVERY,
            text=text,
            ops=(
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.RECOVERY,
                    text=text,
                    likelihood=likelihood,
                    rest_kind=CairnRestKind.BREATHER,
                ),
            ),
        ),
    )
    routed = router.plan("I catch my breath and drink water.")

    assert routed.route == TurnRoute.RECOVERY
    assert routed.ops[0].rest_kind == CairnRestKind.BREATHER


def test_classifier_can_return_survival_time_and_actions() -> None:
    router = TurnRouter(
        classifier=lambda text, _likelihood: TurnPlan(
            route=TurnRoute.PLAYER_ACTION,
            text=text,
            time_advance=CairnTimeAdvance.WATCH,
            survival_actions=(CairnSurvivalAction.EAT,),
            ops=(PlannedTurnOp(kind=PlannedTurnOpKind.NARRATE, text=text),),
        ),
    )

    planned = router.plan("I eat some trail rations and keep moving.")

    assert planned.time_advance == CairnTimeAdvance.WATCH
    assert planned.survival_actions == (CairnSurvivalAction.EAT,)


def test_classifier_can_return_equip_route() -> None:
    router = TurnRouter(
        classifier=lambda text, likelihood: TurnPlan(
            route=TurnRoute.EQUIP,
            text=text,
            ops=(
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.EQUIP,
                    text=text,
                    likelihood=likelihood,
                    item_name="Test knife",
                    equipped=True,
                ),
            ),
        ),
    )
    routed = router.plan("I draw the test knife.")

    assert routed.route == TurnRoute.EQUIP
    assert routed.ops[0].item_name == "Test knife"
    assert routed.ops[0].equipped is True


def test_classifier_can_return_retreat_route() -> None:
    router = TurnRouter(
        classifier=lambda text, likelihood: TurnPlan(
            route=TurnRoute.RETREAT,
            text=text,
            ops=(
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.RETREAT,
                    text=text,
                    likelihood=likelihood,
                ),
            ),
        ),
    )
    routed = router.plan("I fall back through the chapel arch.")

    assert routed.route == TurnRoute.RETREAT
    assert routed.text == "I fall back through the chapel arch."


def test_classifier_can_return_recon_search_scene_plan() -> None:
    router = TurnRouter(
        classifier=lambda text, _likelihood: TurnPlan(
            route=TurnRoute.PLAYER_ACTION,
            text=text,
            ops=(
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.SEARCH_SCENE,
                    text=text,
                ),
            ),
        ),
    )

    planned = router.plan("Are there enemies along the goat-path?")

    assert planned.route == TurnRoute.PLAYER_ACTION
    assert [op.kind for op in planned.ops] == [PlannedTurnOpKind.SEARCH_SCENE]
    assert planned.text == "Are there enemies along the goat-path?"


def test_classifier_can_return_committed_scene_transition_plan() -> None:
    router = TurnRouter(
        classifier=lambda text, _likelihood: TurnPlan(
            route=TurnRoute.SCENE_CHECK,
            text=text,
            ops=(
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.SCENE_CHECK,
                    text=text,
                ),
            ),
        ),
    )

    planned = router.plan("I continue down the goat-path.")

    assert planned.route == TurnRoute.SCENE_CHECK
    assert [op.kind for op in planned.ops] == [PlannedTurnOpKind.SCENE_CHECK]
    assert planned.text == "I continue down the goat-path."


def test_classifier_can_return_compound_plan() -> None:
    router = TurnRouter(
        classifier=lambda text, likelihood: TurnPlan(
            route=TurnRoute.ATTACK,
            text=text,
            ops=(
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.EQUIP,
                    text="I draw the test knife.",
                    item_name="Test knife",
                    equipped=True,
                ),
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.ATTACK,
                    text=text,
                    target_name="Abbey ghoul",
                    stance=AttackStance.NORMAL,
                    likelihood=likelihood,
                ),
            ),
        ),
    )

    planned = router.plan("I draw the knife and strike the abbey ghoul.")

    assert planned.route == TurnRoute.ATTACK
    assert [op.kind for op in planned.ops] == [
        PlannedTurnOpKind.EQUIP,
        PlannedTurnOpKind.ATTACK,
    ]
    assert planned.ops[-1].target_name == "Abbey ghoul"


def test_classifier_can_return_inventory_acquisition_plan() -> None:
    def acquisition_classifier(text: str, _likelihood: Likelihood | None) -> TurnPlan:
        return TurnPlan(
            route=TurnRoute.PLAYER_ACTION,
            text=text,
            ops=(
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.ACQUIRE_ITEM,
                    text="I loot the abbey ghoul for a lantern and a purse of coins.",
                ),
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.EQUIP,
                    text="I ready the lantern.",
                    item_name="Pilgrim lantern",
                    equipped=True,
                ),
            ),
        )

    router = TurnRouter(
        classifier=acquisition_classifier,
    )

    planned = router.plan("I loot the abbey ghoul for a lantern and a purse of coins.")

    assert planned.route == TurnRoute.PLAYER_ACTION
    assert [op.kind for op in planned.ops] == [
        PlannedTurnOpKind.ACQUIRE_ITEM,
        PlannedTurnOpKind.EQUIP,
    ]
    assert planned.ops[-1].item_name == "Pilgrim lantern"
    assert planned.ops[-1].equipped is True


def test_classifier_can_return_inventory_transfer_plan() -> None:
    def transfer_classifier(text: str, _likelihood: Likelihood | None) -> TurnPlan:
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

    router = TurnRouter(classifier=transfer_classifier)

    planned = router.plan("I hand the test map to Brother Sava.")

    assert planned.route == TurnRoute.PLAYER_ACTION
    assert planned.ops[0].kind == PlannedTurnOpKind.TRANSFER_ITEM
    assert planned.ops[0].source_actor_name == "player"
    assert planned.ops[0].target_actor_name == "Brother Sava"
    assert planned.ops[0].item_name == "Test map"


def test_classifier_can_return_npc_recruitment_plan() -> None:
    def recruit_classifier(text: str, _likelihood: Likelihood | None) -> TurnPlan:
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

    router = TurnRouter(classifier=recruit_classifier)

    planned = router.plan("I ask Brother Sava to join us.")

    assert planned.route == TurnRoute.PLAYER_ACTION
    assert planned.ops[0].kind == PlannedTurnOpKind.RECRUIT_NPC
    assert planned.ops[0].npc_name == "Brother Sava"


def test_classifier_can_return_holy_relic_use_plan() -> None:
    def relic_classifier(text: str, _likelihood: Likelihood | None) -> TurnPlan:
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

    router = TurnRouter(classifier=relic_classifier)

    planned = router.plan("I kiss the leaden icon and ask for intercession.")

    assert planned.route == TurnRoute.PLAYER_ACTION
    assert planned.ops[0].kind == PlannedTurnOpKind.USE_ITEM
    assert planned.ops[0].item_name == "leaden icon"


def test_classifier_can_return_enemy_opener_plan_while_preserving_harm_route() -> None:
    def ambush_classifier(text: str, _likelihood: Likelihood | None) -> TurnPlan:
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

    router = TurnRouter(
        classifier=ambush_classifier,
    )

    planned = router.plan(
        "The abbey ghoul drops from the choir loft and claws me before I can raise my cudgel.",
    )

    assert planned.route == TurnRoute.HARM
    assert planned.ops[0].kind == PlannedTurnOpKind.ENEMY_OPENER
    assert planned.ops[0].harm_source == "Abbey ghoul"
