import json

from litellm.types.utils import ModelResponse

from dungeon_master.llm.narration import CompletionRequest, NarrativeConfig
from dungeon_master.llm.planning import (
    TurnRoute,
    TurnRouter,
)
from tests.turn_router.support import (
    RecordingRouterCompletion,
)


def test_save_review_payload_includes_memory_context() -> None:
    captured: list[str] = []

    class RecordingSaveReviewCompletion:
        def __call__(self, request: CompletionRequest) -> ModelResponse:
            def _stream(content: str) -> list[dict[str, object]]:
                return [{"choices": [{"delta": {"content": content}}]}]

            if request.trace_route == "turn_router.save_review":
                payload = request.messages[-1]["content"]
                assert isinstance(payload, str)
                captured.append(payload)
                return _stream(
                    '{"allow_save_mechanics":false,"reason":"ordinary social beat"}',
                )  # type: ignore[return-value]
            return _stream(
                '{"route":"save","text":"I keep the bit going.",'
                '"ops":[{"kind":"save","text":"I keep the bit going.",'
                '"likelihood":null,"ability":"WIL","target_name":null,'
                '"stance":null,"rest_kind":null,"item_name":null,'
                '"npc_name":null,"actor_name":null,"supporting_actor_names":[],'
                '"source_actor_name":null,"target_actor_name":null,"equipped":null,'
                '"harm_amount":null,"harm_source":null,"armor_applies":null,'
                '"in_combat":null,"advantage_payoff":null}]}',
            )  # type: ignore[return-value]

    router = TurnRouter(
        config=NarrativeConfig(model="test-model", api_key="test-key", base_url=None),
        completion_function=RecordingSaveReviewCompletion(),
    )

    router.plan(
        "I keep the bit going.",
        memory_context="Recent scene: Chloe thinks the persona is a joke.",
    )

    assert len(captured) == 1
    payload = json.loads(captured[0])
    assert payload["bounded_memory_context"] == (
        "Recent scene: Chloe thinks the persona is a joke."
    )
    assert payload["proposed_plan"]["ops"][0]["ability"] == "WIL"


def test_combat_review_payload_includes_canonical_active_encounter_hint() -> None:
    captured: list[str] = []

    class RecordingCombatReviewCompletion:
        def __call__(self, request: CompletionRequest) -> ModelResponse:
            def _stream(content: str) -> list[dict[str, object]]:
                return [{"choices": [{"delta": {"content": content}}]}]

            if request.trace_route == "turn_router.combat_review":
                payload = request.messages[-1]["content"]
                assert isinstance(payload, str)
                captured.append(payload)
                return _stream(
                    '{"allow_combat_mechanics":true,"reason":"mid-combat slash"}',
                )  # type: ignore[return-value]
            return _stream(
                '{"route":"attack","text":"Slash it up.",'
                '"ops":[{"kind":"attack","text":"Slash it up.",'
                '"likelihood":null,"ability":null,"target_name":"Blob",'
                '"stance":"normal","rest_kind":null,"item_name":null,'
                '"npc_name":null,"actor_name":null,"supporting_actor_names":[],'
                '"source_actor_name":null,"target_actor_name":null,"equipped":null,'
                '"harm_amount":null,"harm_source":null,"armor_applies":null,'
                '"in_combat":null,"advantage_payoff":null}]}',
            )  # type: ignore[return-value]

    router = TurnRouter(
        config=NarrativeConfig(model="test-model", api_key="test-key", base_url=None),
        completion_function=RecordingCombatReviewCompletion(),
    )
    hint = "Combat is active in round 2 against Flesh-Bound Mass."
    router.plan("Slash it up wildly.", combat_encounter_hint=hint)

    assert len(captured) == 1
    payload = json.loads(captured[0])
    assert payload["canonical_active_encounter"] == hint


def test_turn_planner_user_prompt_appends_backend_encounter_hint() -> None:
    completion = RecordingRouterCompletion()
    router = TurnRouter(
        config=NarrativeConfig(model="test-model", api_key=None, base_url="https://example.com"),
        completion_function=completion,
    )
    hint = "Combat is active in round 2 against Flesh-Bound Mass."
    router.plan("I listen at the abbey door.", combat_encounter_hint=hint)

    assert completion.request is not None
    user = completion.request.messages[-1]["content"]
    assert isinstance(user, str)
    assert hint in user
    assert "Canonical encounter status from backend" in user


def test_combat_review_allows_active_companion_weapon_command_prompt() -> None:
    captured_system_prompts: list[str] = []

    class CompanionAttackCompletion:
        def __call__(self, request: CompletionRequest) -> ModelResponse:
            if request.trace_route == "turn_router.combat_review":
                captured_system_prompts.append(request.messages[0]["content"])
                return [
                    {
                        "choices": [
                            {
                                "delta": {
                                    "content": (
                                        '{"allow_combat_mechanics":true,'
                                        '"reason":"companion shoots"}'
                                    ),
                                },
                            },
                        ],
                    },
                ]  # type: ignore[return-value]
            return [
                {
                    "choices": [
                        {
                            "delta": {
                                "content": (
                                    '{"route":"attack",'
                                    '"text":"Drusus can use his bow to snipe them.",'
                                    '"ops":[{"kind":"attack",'
                                    '"text":"Drusus can use his bow to snipe them.",'
                                    '"likelihood":null,"ability":null,'
                                    '"target_name":"Fleeing zealot",'
                                    '"stance":"normal","rest_kind":null,'
                                    '"item_name":"bow","npc_name":null,'
                                    '"actor_name":"Drusus","supporting_actor_names":[],'
                                    '"source_actor_name":null,"target_actor_name":null,'
                                    '"equipped":null,"harm_amount":null,'
                                    '"harm_source":null,"armor_applies":null,'
                                    '"in_combat":null,"advantage_payoff":null}]}'
                                ),
                            },
                        },
                    ],
                },
            ]  # type: ignore[return-value]

    router = TurnRouter(
        config=NarrativeConfig(model="test-model", api_key="test-key", base_url=None),
        completion_function=CompanionAttackCompletion(),
    )

    plan = router.plan(
        "Drusus can use his bow to snipe them.",
        combat_encounter_hint="Combat is active in round 2 against Fleeing zealot.",
    )

    assert plan.route == TurnRoute.ATTACK
    assert plan.ops[0].actor_name == "Drusus"
    assert captured_system_prompts
    system_prompt = " ".join(captured_system_prompts[0].split())
    assert "Companion commands like" in system_prompt
    assert "bow/crossbow" in system_prompt
    assert "not color narration" in system_prompt
