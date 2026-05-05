import pytest
from litellm.types.utils import ModelResponse

from dungeon_master.models import AttackStance, CairnAbility, CairnRestKind, Likelihood
from dungeon_master.narrative import CompletionRequest, NarrativeConfig
from dungeon_master.turn_router import (
    PlannedTurnOp,
    PlannedTurnOpKind,
    RoutedTurn,
    TurnPlan,
    TurnPlanningError,
    TurnRoute,
    TurnRouter,
)


class RecordingRouterCompletion:
    def __init__(self) -> None:
        self.messages: list[dict[str, str]] | None = None

    def __call__(self, request: CompletionRequest) -> ModelResponse:
        self.messages = request.messages
        del request

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


def test_router_raises_explicit_error_when_planning_fails() -> None:
    router = TurnRouter(
        config=NarrativeConfig(
            model="test-model",
            api_key="test-key",
            base_url="https://example.com",
            exclude_reasoning=True,
        ),
        completion_function=BrokenRouterCompletion(),
    )

    with pytest.raises(TurnPlanningError) as exc:
        router.plan("I listen at the abbey door.")

    assert "deterministic resolution" in str(exc.value)
