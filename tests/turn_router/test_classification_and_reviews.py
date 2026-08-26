import pytest
from litellm.types.utils import ModelResponse

from dungeon_master.models import (
    AttackStance,
    CairnAbility,
    Likelihood,
)
from dungeon_master.narrative import CompletionRequest, NarrativeConfig
from dungeon_master.turn_router import (
    SAVE_MECHANICS_REVIEW_SYSTEM_PROMPT,
    TURN_ROUTER_SYSTEM_PROMPT,
    PlannedTurnOp,
    PlannedTurnOpKind,
    TurnPlan,
    TurnRoute,
    TurnRouter,
)
from tests.turn_router.support import (
    CombatReviewRouterCompletion,
    RecordingRouterCompletion,
    SaveReviewRouterCompletion,
)


def test_preserves_explicit_likelihood_hint_for_classifier() -> None:
    router = TurnRouter(
        classifier=lambda text, likelihood: TurnPlan(
            route=TurnRoute.YES_NO,
            text=text,
            ops=(
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.YES_NO,
                    text=text,
                    likelihood=likelihood,
                ),
            ),
        ),
    )
    routed = router.plan("Is the abbey gate watched? [unlikely]")

    assert routed.route == TurnRoute.YES_NO
    assert routed.text == "Is the abbey gate watched?"
    assert routed.ops[0].likelihood == Likelihood.UNLIKELY


def test_classifier_can_return_scene_check() -> None:
    router = TurnRouter(
        classifier=lambda text, likelihood: TurnPlan(
            route=TurnRoute.SCENE_CHECK,
            text=text,
            ops=(
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.SCENE_CHECK,
                    text=text,
                    likelihood=likelihood,
                ),
            ),
        ),
    )
    routed = router.plan("I cross the bone bridge before dawn.")

    assert routed.route == TurnRoute.SCENE_CHECK
    assert routed.text == "I cross the bone bridge before dawn."


def test_classifier_can_return_random_event() -> None:
    router = TurnRouter(
        classifier=lambda text, likelihood: TurnPlan(
            route=TurnRoute.RANDOM_EVENT,
            text=text,
            ops=(
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.RANDOM_EVENT,
                    text=text,
                    likelihood=likelihood,
                ),
            ),
        ),
    )
    routed = router.plan("Something happens in the chapel.")

    assert routed.route == TurnRoute.RANDOM_EVENT


def test_unconfigured_router_falls_back_to_player_action() -> None:
    routed = TurnRouter(config=NarrativeConfig(model="", api_key=None, base_url=None)).plan(
        "I listen at the abbey door.",
    )

    assert routed.route == TurnRoute.PLAYER_ACTION
    assert routed.ops[0].likelihood is None


def test_router_prompt_avoids_saves_when_context_already_grants_opening() -> None:
    save_review_prompt = " ".join(SAVE_MECHANICS_REVIEW_SYSTEM_PROMPT.split())

    assert "clear opening, access, or permission" in TURN_ROUTER_SYSTEM_PROMPT
    assert "remaining danger, pressure, resistance, or meaningful uncertainty" in (
        TURN_ROUTER_SYSTEM_PROMPT
    )
    assert "making someone like/dislike the player is usually `narrate`" in (
        TURN_ROUTER_SYSTEM_PROMPT
    )
    assert "ordinary social exchange lands" in save_review_prompt
    assert "exposure with durable consequences" in TURN_ROUTER_SYSTEM_PROMPT


def test_model_can_emit_coordinated_attack_plan() -> None:
    class CoordinatedAttackCompletion:
        def __call__(self, request: CompletionRequest) -> ModelResponse:
            def _stream(content: str) -> list[dict[str, object]]:
                return [{"choices": [{"delta": {"content": content}}]}]

            if request.trace_route == "turn_router.combat_review":
                return _stream(
                    '{"allow_combat_mechanics":true,"reason":"explicit coordinated strike"}',
                )  # type: ignore[return-value]
            return _stream(
                '{"route":"attack","text":"Kaelen strikes the arm while I smash the knee.",'
                '"ops":[{"kind":"coordinated_attack",'
                '"text":"Kaelen strikes the arm while I smash the knee.",'
                '"likelihood":null,"ability":null,"target_name":"Vanguard",'
                '"stance":"normal","rest_kind":null,"item_name":null,'
                '"npc_name":null,"actor_name":null,'
                '"supporting_actor_names":["Kaelen"],'
                '"source_actor_name":null,"target_actor_name":null,'
                '"equipped":null,"harm_amount":null,"harm_source":null,'
                '"armor_applies":null,"in_combat":null}]}',
            )  # type: ignore[return-value]

    router = TurnRouter(
        config=NarrativeConfig(model="test-model", api_key="test-key", base_url=None),
        completion_function=CoordinatedAttackCompletion(),
    )

    plan = router.plan("Order Kaelen to attack the arm. I smash the knee.")

    assert plan.route == TurnRoute.ATTACK
    assert plan.ops[0].kind == PlannedTurnOpKind.COORDINATED_ATTACK
    assert plan.ops[0].supporting_actor_names == ("Kaelen",)


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
        classifier=lambda text, likelihood: TurnPlan(
            route=TurnRoute.SAVE,
            text=text,
            ops=(
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.SAVE,
                    text=text,
                    likelihood=likelihood,
                    ability=CairnAbility.DEX,
                ),
            ),
        ),
    )
    routed = router.plan("I balance across the abbey beam.")

    assert routed.route == TurnRoute.SAVE
    assert routed.ops[0].ability == CairnAbility.DEX


def test_classifier_can_return_wil_save() -> None:
    router = TurnRouter(
        classifier=lambda text, likelihood: TurnPlan(
            route=TurnRoute.SAVE,
            text=text,
            ops=(
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.SAVE,
                    text=text,
                    likelihood=likelihood,
                    ability=CairnAbility.WIL,
                ),
            ),
        ),
    )
    routed = router.plan("I persuade the guard to lower the pike.")

    assert routed.route == TurnRoute.SAVE
    assert routed.ops[0].ability == CairnAbility.WIL


def test_classifier_can_return_attack_route() -> None:
    router = TurnRouter(
        classifier=lambda text, likelihood: TurnPlan(
            route=TurnRoute.ATTACK,
            text=text,
            ops=(
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.ATTACK,
                    text=text,
                    likelihood=likelihood,
                    target_name="Abbey ghoul",
                    stance=AttackStance.NORMAL,
                ),
            ),
        ),
    )
    routed = router.plan("I swing my cudgel at the abbey ghoul.")

    assert routed.route == TurnRoute.ATTACK
    assert routed.ops[0].target_name == "Abbey ghoul"
    assert routed.ops[0].stance == AttackStance.NORMAL


def test_turn_router_prompt_keeps_broad_combat_intent_out_of_attack() -> None:
    completion = RecordingRouterCompletion()
    router = TurnRouter(
        config=NarrativeConfig(model="test-model", api_key="test-key", base_url=None),
        completion_function=completion,
    )

    routed = router.plan("Let's find a fight.")

    assert routed.route == TurnRoute.PLAYER_ACTION
    assert completion.messages is not None
    system_prompt = " ".join(completion.messages[0]["content"].split())
    assert "A broad request to seek, start, or enter danger/combat" in system_prompt
    assert "concrete attack by itself" in system_prompt
    assert "`begin_encounter` with `target_name`" in system_prompt
    assert "Active-combat companion weapon commands are also immediate attacks" in system_prompt


def test_model_can_begin_encounter_without_spending_attack() -> None:
    class BeginEncounterRouterCompletion:
        def __call__(self, request: CompletionRequest) -> ModelResponse:
            del request

            def _stream() -> list[dict[str, object]]:
                return [
                    {
                        "choices": [
                            {
                                "delta": {
                                    "content": (
                                        '{"route":"player_action",'
                                        '"text":"Let us start an encounter with the horde.",'
                                        '"ops":[{"kind":"begin_encounter",'
                                        '"text":"Let us start an encounter with the horde.",'
                                        '"likelihood":null,"ability":null,'
                                        '"target_name":"Infected horde",'
                                        '"stance":null,"rest_kind":null,"item_name":null,'
                                        '"supporting_actor_names":[],"source_actor_name":null,'
                                        '"target_actor_name":null,"equipped":null,'
                                        '"harm_amount":null,"harm_source":null,'
                                        '"armor_applies":null,"in_combat":null,'
                                        '"advantage_payoff":null}]}'
                                    ),
                                },
                            },
                        ],
                    },
                ]

            return _stream()  # type: ignore[return-value]

    router = TurnRouter(
        config=NarrativeConfig(model="test-model", api_key="test-key", base_url=None),
        completion_function=BeginEncounterRouterCompletion(),
    )

    planned = router.plan("Let us start an encounter with the horde.")

    assert planned.route == TurnRoute.PLAYER_ACTION
    assert planned.ops == (
        PlannedTurnOp(
            kind=PlannedTurnOpKind.BEGIN_ENCOUNTER,
            text="Let us start an encounter with the horde.",
            target_name="Infected horde",
        ),
    )


def test_model_can_request_clarification_for_ambiguous_party_reference() -> None:
    class ClarifyingRouterCompletion:
        def __call__(self, request: CompletionRequest) -> ModelResponse:
            del request

            def _stream() -> list[dict[str, object]]:
                return [
                    {
                        "choices": [
                            {
                                "delta": {
                                    "content": (
                                        '{"route":"player_action",'
                                        '"text":"We retreat from the doorway.",'
                                        '"ops":[{"kind":"clarify",'
                                        '"text":"Who is retreating: you alone, or '
                                        'you and Kaelen together?",'
                                        '"likelihood":null,"ability":null,"target_name":null,'
                                        '"stance":null,"rest_kind":null,"item_name":null,'
                                        '"supporting_actor_names":[],"source_actor_name":null,'
                                        '"target_actor_name":null,"equipped":null,'
                                        '"harm_amount":null,"harm_source":null,'
                                        '"armor_applies":null,"in_combat":null}]}'
                                    ),
                                },
                            },
                        ],
                    },
                ]

            return _stream()  # type: ignore[return-value]

    router = TurnRouter(
        config=NarrativeConfig(model="test-model", api_key="test-key", base_url=None),
        completion_function=ClarifyingRouterCompletion(),
    )

    planned = router.plan("We retreat from the doorway.")

    assert planned.route == TurnRoute.PLAYER_ACTION
    assert planned.ops == (
        PlannedTurnOp(
            kind=PlannedTurnOpKind.CLARIFY,
            text="Who is retreating: you alone, or you and Kaelen together?",
        ),
    )


def test_model_attack_plan_requires_structured_combat_review_approval() -> None:
    completion = CombatReviewRouterCompletion(review_allows=False)
    router = TurnRouter(
        config=NarrativeConfig(model="test-model", api_key="test-key", base_url=None),
        completion_function=completion,
    )

    routed = router.plan("Let us find a fight.")

    assert routed.route == TurnRoute.PLAYER_ACTION
    assert [op.kind for op in routed.ops] == [PlannedTurnOpKind.NARRATE]
    assert [request.trace_route for request in completion.requests] == [
        "turn_router.plan",
        "turn_router.combat_review",
    ]


def test_structured_combat_review_can_allow_explicit_attack_plan() -> None:
    completion = CombatReviewRouterCompletion(review_allows=True)
    router = TurnRouter(
        config=NarrativeConfig(model="test-model", api_key="test-key", base_url=None),
        completion_function=completion,
    )

    routed = router.plan("I swing my cudgel at the abbey ghoul.")

    assert routed.route == TurnRoute.ATTACK
    assert routed.ops[0].target_name == "Abbey ghoul"
    assert [request.trace_route for request in completion.requests] == [
        "turn_router.plan",
        "turn_router.combat_review",
    ]


def test_model_save_plan_requires_structured_save_review_approval() -> None:
    completion = SaveReviewRouterCompletion(review_allows=False)
    router = TurnRouter(
        config=NarrativeConfig(model="test-model", api_key="test-key", base_url=None),
        completion_function=completion,
    )

    routed = router.plan("I keep the persona going.")

    assert routed.route == TurnRoute.PLAYER_ACTION
    assert [op.kind for op in routed.ops] == [PlannedTurnOpKind.NARRATE]
    assert [request.trace_route for request in completion.requests] == [
        "turn_router.plan",
        "turn_router.save_review",
    ]


def test_structured_save_review_can_allow_risky_save_plan() -> None:
    completion = SaveReviewRouterCompletion(review_allows=True)
    router = TurnRouter(
        config=NarrativeConfig(model="test-model", api_key="test-key", base_url=None),
        completion_function=completion,
    )

    routed = router.plan("I keep my nerve under pressure.")

    assert routed.route == TurnRoute.SAVE
    assert routed.ops[0].ability == CairnAbility.WIL
    assert [request.trace_route for request in completion.requests] == [
        "turn_router.plan",
        "turn_router.save_review",
    ]
