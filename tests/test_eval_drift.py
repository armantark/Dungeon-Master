import pytest
from deepeval import assert_test  # type: ignore[attr-defined]
from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCase, SingleTurnParams

from dungeon_master.config import LLMConfig
from dungeon_master.narrative import NarrativeEngine
from tools.eval_harness import (
    EVAL_USER_INPUTS,
    EvalBaseline,
    LiteLLMDeepEvalJudge,
    eval_case_for,
    eval_llm_config,
    load_baseline,
    sample_eval_state,
)


@pytest.fixture
def baseline_data() -> EvalBaseline | None:
    return load_baseline()


@pytest.mark.parametrize("user_input", EVAL_USER_INPUTS)
def test_narrative_drift(
    baseline_data: EvalBaseline | None,
    user_input: str,
) -> None:
    if not baseline_data:
        pytest.skip("No baseline data found. Run tools/generate_baseline.py first.")

    baseline = baseline_data.get(user_input)
    if baseline is None:
        pytest.skip("No usable narration baseline found. Regenerate the drift baseline.")

    config = eval_llm_config(LLMConfig.from_env())
    if not config.is_usable():
        pytest.skip("DeepEval drift check needs the app's LLM credentials.")

    state = sample_eval_state()
    narrator = NarrativeEngine(config=config)
    case = eval_case_for(user_input)
    new_narration = narrator.generate(
        state=state,
        player_input=case.user_input,
        outcome=case.outcome,
        execution_context=case.execution_context,
    )

    drift_metric = GEval(
        name="Prompt Drift Evaluation",
        evaluation_steps=[
            "Check that the actual output keeps the same second-person dark-fantasy style family.",
            "Check that the actual output follows the supplied successful player action.",
            (
                "Use the baseline narration only as a style reference, "
                "not as canonical scene state."
            ),
            (
                "Pass alternate incidental prose details unless they contradict "
                "the input or structured outcome."
            ),
            (
                "Fail outputs that add unsupported mechanical facts, extra rolls, "
                "state changes, or wrong outcomes."
            ),
        ],
        evaluation_params=[
            SingleTurnParams.INPUT,
            SingleTurnParams.ACTUAL_OUTPUT,
            SingleTurnParams.CONTEXT,
        ],
        model=LiteLLMDeepEvalJudge(config=config, max_tokens=1600),
        threshold=0.7,
        async_mode=False,
    )

    test_case = LLMTestCase(
        input=user_input,
        actual_output=new_narration,
        context=[
            (
                "<canonical_outcome>\n"
                f"kind: {case.outcome.kind.value}\n"
                f"summary: {case.outcome.summary}\n"
                f"baseline_route: {baseline.route}\n"
                f"baseline_target_name: {baseline.target_name or 'unspecified'}\n"
                "canonical_wound_location: unspecified\n"
                "canonical_enemy_weapon: unspecified\n"
                "</canonical_outcome>"
            ),
            f"<baseline_style_reference>\n{baseline.narration}\n</baseline_style_reference>",
        ],
    )

    assert_test(test_case, [drift_metric])
