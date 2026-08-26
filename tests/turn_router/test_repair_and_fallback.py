import pytest

from dungeon_master.llm.narration import NarrativeConfig
from dungeon_master.llm.planning import (
    PlannedTurnOp,
    PlannedTurnOpKind,
    TurnRoute,
    TurnRouter,
)
from tests.turn_router.support import (
    BrokenRouterCompletion,
    RecordingRouterCompletion,
    RepairingRouterCompletion,
)


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
        'turn.router route="player_action" source="model_error_fallback" ops="narrate"' in message
        for message in caplog.messages
    )
