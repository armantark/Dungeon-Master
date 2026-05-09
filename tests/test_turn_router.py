import pytest
from litellm.types.utils import ModelResponse

from dungeon_master.models import (
    AttackStance,
    CairnAbility,
    CairnRestKind,
    CairnSurvivalAction,
    CairnTimeAdvance,
    Likelihood,
)
from dungeon_master.narrative import CompletionRequest, NarrativeConfig
from dungeon_master.turn_router import (
    PlannedTurnOp,
    PlannedTurnOpKind,
    RoutedTurn,
    TurnPlan,
    TurnRoute,
    TurnRouter,
)


class RecordingRouterCompletion:
    def __init__(self) -> None:
        self.messages: list[dict[str, str]] | None = None
        self.request: CompletionRequest | None = None

    def __call__(self, request: CompletionRequest) -> ModelResponse:
        self.request = request
        self.messages = request.messages

        def _stream() -> list[dict[str, object]]:
            return [
                {
                    "choices": [
                        {
                            "delta": {
                                "content": (
                                    '{"route":"player_action","text":"I listen at the abbey door.",'
                                    '"ops":[{"kind":"narrate","text":"I listen at the abbey door.",'
                                    '"likelihood":null,"ability":null,"target_name":null,'
                                    '"stance":null,"rest_kind":null,"item_name":null,'
                                    '"equipped":null,"harm_amount":null,"harm_source":null,'
                                    '"armor_applies":null,"in_combat":null}]}'
                                ),
                            },
                        },
                    ],
                },
            ]

        return _stream()  # type: ignore[return-value]


class BrokenRouterCompletion:
    def __call__(self, request: CompletionRequest) -> ModelResponse:
        del request
        return []  # type: ignore[return-value]


class RepairingRouterCompletion:
    def __init__(self) -> None:
        self.requests: list[CompletionRequest] = []

    def __call__(self, request: CompletionRequest) -> ModelResponse:
        self.requests.append(request)

        def _stream(content: str) -> list[dict[str, object]]:
            return [{"choices": [{"delta": {"content": content}}]}]

        if request.trace_route == "turn_router.repair":
            return _stream(
                '{"route":"player_action","text":"I listen at the abbey door.",'
                '"ops":[{"kind":"narrate","text":"I listen at the abbey door.",'
                '"likelihood":null,"ability":null,"target_name":null,'
                '"stance":null,"rest_kind":null,"item_name":null,'
                '"equipped":null,"harm_amount":null,"harm_source":null,'
                '"armor_applies":null,"in_combat":null}]}',
            )  # type: ignore[return-value]
        return _stream("not json")  # type: ignore[return-value]


def test_preserves_explicit_likelihood_hint_for_classifier() -> None:
    router = TurnRouter(
        classifier=lambda text, likelihood: RoutedTurn(
            route=TurnRoute.YES_NO,
            text=text,
            likelihood=likelihood,
        ),
    )
    routed = router.route("Is the abbey gate watched? [unlikely]")

    assert routed.route == TurnRoute.YES_NO
    assert routed.text == "Is the abbey gate watched?"
    assert routed.likelihood == Likelihood.UNLIKELY


def test_classifier_can_return_scene_check() -> None:
    router = TurnRouter(
        classifier=lambda text, likelihood: RoutedTurn(
            route=TurnRoute.SCENE_CHECK,
            text=text,
            likelihood=likelihood,
        ),
    )
    routed = router.route("I cross the bone bridge before dawn.")

    assert routed.route == TurnRoute.SCENE_CHECK
    assert routed.text == "I cross the bone bridge before dawn."


def test_classifier_can_return_random_event() -> None:
    router = TurnRouter(
        classifier=lambda text, likelihood: RoutedTurn(
            route=TurnRoute.RANDOM_EVENT,
            text=text,
            likelihood=likelihood,
        ),
    )
    routed = router.route("Something happens in the chapel.")

    assert routed.route == TurnRoute.RANDOM_EVENT


def test_unconfigured_router_falls_back_to_player_action() -> None:
    routed = TurnRouter(config=NarrativeConfig(model="", api_key=None, base_url=None)).route(
        "I listen at the abbey door.",
    )

    assert routed.route == TurnRoute.PLAYER_ACTION
    assert routed.likelihood is None


def test_router_logs_decision_and_traces_request(caplog: pytest.LogCaptureFixture) -> None:
    completion = RecordingRouterCompletion()
    router = TurnRouter(
        config=NarrativeConfig(model="test-model", api_key=None, base_url="https://example.com"),
        completion_function=completion,
    )

    caplog.set_level("INFO", logger="dungeon_master.trace")
    planned = router.plan("I listen at the abbey door.")

    assert planned.route == TurnRoute.PLAYER_ACTION
    assert completion.request is not None
    assert completion.request.trace_route == "turn_router.plan"
    assert completion.request.trace_profile == "turn_router"
    assert any(
        'turn.router route="player_action" source="model" ops="narrate"' in message
        for message in caplog.messages
    )


def test_classifier_can_return_dex_save() -> None:
    router = TurnRouter(
        classifier=lambda text, likelihood: RoutedTurn(
            route=TurnRoute.SAVE,
            text=text,
            likelihood=likelihood,
            ability=CairnAbility.DEX,
        ),
    )
    routed = router.route("I balance across the abbey beam.")

    assert routed.route == TurnRoute.SAVE
    assert routed.ability == CairnAbility.DEX


def test_classifier_can_return_wil_save() -> None:
    router = TurnRouter(
        classifier=lambda text, likelihood: RoutedTurn(
            route=TurnRoute.SAVE,
            text=text,
            likelihood=likelihood,
            ability=CairnAbility.WIL,
        ),
    )
    routed = router.route("I persuade the guard to lower the pike.")

    assert routed.route == TurnRoute.SAVE
    assert routed.ability == CairnAbility.WIL


def test_classifier_can_return_attack_route() -> None:
    router = TurnRouter(
        classifier=lambda text, likelihood: RoutedTurn(
            route=TurnRoute.ATTACK,
            text=text,
            likelihood=likelihood,
            target_name="Abbey ghoul",
            stance=AttackStance.NORMAL,
        ),
    )
    routed = router.route("I swing my cudgel at the abbey ghoul.")

    assert routed.route == TurnRoute.ATTACK
    assert routed.target_name == "Abbey ghoul"
    assert routed.stance == AttackStance.NORMAL


def test_classifier_can_return_recovery_route() -> None:
    router = TurnRouter(
        classifier=lambda text, likelihood: RoutedTurn(
            route=TurnRoute.RECOVERY,
            text=text,
            likelihood=likelihood,
            rest_kind=CairnRestKind.BREATHER,
        ),
    )
    routed = router.route("I catch my breath and drink water.")

    assert routed.route == TurnRoute.RECOVERY
    assert routed.rest_kind == CairnRestKind.BREATHER


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
    routed = router.route("I eat some trail rations and keep moving.")

    assert planned.time_advance == CairnTimeAdvance.WATCH
    assert planned.survival_actions == (CairnSurvivalAction.EAT,)
    assert routed.time_advance == CairnTimeAdvance.WATCH
    assert routed.survival_actions == (CairnSurvivalAction.EAT,)


def test_classifier_can_return_equip_route() -> None:
    router = TurnRouter(
        classifier=lambda text, likelihood: RoutedTurn(
            route=TurnRoute.EQUIP,
            text=text,
            likelihood=likelihood,
            item_name="Test knife",
            equipped=True,
        ),
    )
    routed = router.route("I draw the test knife.")

    assert routed.route == TurnRoute.EQUIP
    assert routed.item_name == "Test knife"
    assert routed.equipped is True


def test_classifier_can_return_retreat_route() -> None:
    router = TurnRouter(
        classifier=lambda text, likelihood: RoutedTurn(
            route=TurnRoute.RETREAT,
            text=text,
            likelihood=likelihood,
        ),
    )
    routed = router.route("I fall back through the chapel arch.")

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
    routed = router.route("Are there enemies along the goat-path?")

    assert planned.route == TurnRoute.PLAYER_ACTION
    assert [op.kind for op in planned.ops] == [PlannedTurnOpKind.SEARCH_SCENE]
    assert routed.route == TurnRoute.PLAYER_ACTION
    assert routed.text == "Are there enemies along the goat-path?"


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
    routed = router.route("I continue down the goat-path.")

    assert planned.route == TurnRoute.SCENE_CHECK
    assert [op.kind for op in planned.ops] == [PlannedTurnOpKind.SCENE_CHECK]
    assert routed.route == TurnRoute.SCENE_CHECK
    assert routed.text == "I continue down the goat-path."


def test_classifier_can_return_compound_plan_and_route_uses_primary_op() -> None:
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
    routed = router.route("I draw the knife and strike the abbey ghoul.")

    assert planned.route == TurnRoute.ATTACK
    assert [op.kind for op in planned.ops] == [
        PlannedTurnOpKind.EQUIP,
        PlannedTurnOpKind.ATTACK,
    ]
    assert routed.route == TurnRoute.ATTACK
    assert routed.target_name == "Abbey ghoul"


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
    routed = router.route("I loot the abbey ghoul for a lantern and a purse of coins.")

    assert planned.route == TurnRoute.PLAYER_ACTION
    assert [op.kind for op in planned.ops] == [
        PlannedTurnOpKind.ACQUIRE_ITEM,
        PlannedTurnOpKind.EQUIP,
    ]
    assert routed.route == TurnRoute.PLAYER_ACTION
    assert routed.item_name == "Pilgrim lantern"
    assert routed.equipped is True


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
    routed = router.route("I hand the test map to Brother Sava.")

    assert planned.route == TurnRoute.PLAYER_ACTION
    assert planned.ops[0].kind == PlannedTurnOpKind.TRANSFER_ITEM
    assert planned.ops[0].source_actor_name == "player"
    assert planned.ops[0].target_actor_name == "Brother Sava"
    assert routed.item_name == "Test map"
    assert routed.source_actor_name == "player"
    assert routed.target_actor_name == "Brother Sava"


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
    routed = router.route("I ask Brother Sava to join us.")

    assert planned.route == TurnRoute.PLAYER_ACTION
    assert planned.ops[0].kind == PlannedTurnOpKind.RECRUIT_NPC
    assert planned.ops[0].npc_name == "Brother Sava"
    assert routed.npc_name == "Brother Sava"


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
    routed = router.route("I kiss the leaden icon and ask for intercession.")

    assert planned.route == TurnRoute.PLAYER_ACTION
    assert planned.ops[0].kind == PlannedTurnOpKind.USE_ITEM
    assert planned.ops[0].item_name == "leaden icon"
    assert routed.route == TurnRoute.PLAYER_ACTION
    assert routed.item_name == "leaden icon"


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
    routed = router.route(
        "The abbey ghoul drops from the choir loft and claws me before I can raise my cudgel.",
    )

    assert planned.route == TurnRoute.HARM
    assert planned.ops[0].kind == PlannedTurnOpKind.ENEMY_OPENER
    assert planned.ops[0].harm_source == "Abbey ghoul"
    assert routed.route == TurnRoute.HARM
    assert routed.harm_source == "Abbey ghoul"


def test_router_prompt_includes_bounded_memory_context() -> None:
    completion = RecordingRouterCompletion()
    router = TurnRouter(
        config=NarrativeConfig(
            model="test-model",
            api_key="test-key",
            base_url="https://example.com",
            exclude_reasoning=True,
        ),
        completion_function=completion,
    )

    plan = router.plan(
        "I listen at the abbey door.",
        memory_context="Current scene summary: Rain drums on the abbey gate.",
    )

    assert plan.route == TurnRoute.PLAYER_ACTION
    assert completion.messages is not None
    user_prompt = completion.messages[1]["content"]
    assert "Bounded memory context" in user_prompt
    assert "Rain drums on the abbey gate." in user_prompt


def test_router_prompt_distinguishes_recon_from_scene_transition() -> None:
    completion = RecordingRouterCompletion()
    router = TurnRouter(
        config=NarrativeConfig(
            model="test-model",
            api_key="test-key",
            base_url="https://example.com",
            exclude_reasoning=True,
        ),
        completion_function=completion,
    )

    router.plan("Are there enemies along the goat-path?")

    assert completion.messages is not None
    system_prompt = " ".join(completion.messages[0]["content"].split())
    assert "prefer `search_scene` even if the wording is a question" in system_prompt
    assert "Do not treat recon questions like" in system_prompt
    assert (
        "Use `scene_check` only when the player explicitly commits to moving onward"
        in system_prompt
    )
    assert "time_advance" in completion.messages[1]["content"]
    assert "survival_actions" in completion.messages[1]["content"]
    assert "Also classify elapsed time for the whole turn" in system_prompt
    assert "Also classify explicit survival actions for the whole turn" in system_prompt


def test_router_repairs_invalid_model_json_before_safe_fallback() -> None:
    completion = RepairingRouterCompletion()
    router = TurnRouter(
        config=NarrativeConfig(
            model="test-model",
            api_key="test-key",
            base_url="https://example.com",
            exclude_reasoning=True,
            max_retries=0,
        ),
        completion_function=completion,
    )

    plan = router.plan("I listen at the abbey door.")

    assert plan.route == TurnRoute.PLAYER_ACTION
    assert plan.ops == (
        PlannedTurnOp(
            kind=PlannedTurnOpKind.NARRATE,
            text="I listen at the abbey door.",
        ),
    )
    assert [request.trace_route for request in completion.requests] == [
        "turn_router.plan",
        "turn_router.repair",
    ]


def test_router_falls_back_to_narration_when_model_planning_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    router = TurnRouter(
        config=NarrativeConfig(
            model="test-model",
            api_key="test-key",
            base_url="https://example.com",
            exclude_reasoning=True,
        ),
        completion_function=BrokenRouterCompletion(),
    )

    caplog.set_level("INFO", logger="dungeon_master.trace")
    plan = router.plan("I listen at the abbey door.")

    assert plan.route == TurnRoute.PLAYER_ACTION
    assert plan.text == "I listen at the abbey door."
    assert plan.ops == (
        PlannedTurnOp(
            kind=PlannedTurnOpKind.NARRATE,
            text="I listen at the abbey door.",
        ),
    )
    assert any(
        'turn.router route="player_action" source="model_error_fallback" ops="narrate"'
        in message
        for message in caplog.messages
    )
