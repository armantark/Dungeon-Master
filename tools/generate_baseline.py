from dungeon_master.config import LLMConfig
from dungeon_master.narrative import NarrativeEngine
from dungeon_master.turn_router import TurnRouter
from tools.eval_harness import (
    EVAL_USER_INPUTS,
    EvalBaselineRecord,
    eval_case_for,
    eval_llm_config,
    sample_eval_state,
    write_baseline,
)


def main() -> None:
    config = eval_llm_config(LLMConfig.from_env())
    if not config.is_usable():
        msg = (
            "Cannot generate DeepEval baseline without a usable LLM config. "
            "Configure the same provider credentials used by the app."
        )
        raise RuntimeError(msg)

    router = TurnRouter(config=config)
    narrator = NarrativeEngine(config=config)
    baseline: dict[str, EvalBaselineRecord] = {}

    for user_input in EVAL_USER_INPUTS:
        state = sample_eval_state()
        case = eval_case_for(user_input)
        routed = router.route(text=user_input)
        narration = narrator.generate(
            state=state,
            player_input=case.user_input,
            outcome=case.outcome,
            execution_context=case.execution_context,
        )
        baseline[user_input] = EvalBaselineRecord(
            route=routed.route.value,
            target_name=routed.target_name,
            routed_text=routed.text,
            narration=narration,
        )

    write_baseline(baseline)


if __name__ == "__main__":
    main()
