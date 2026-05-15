import json
from pathlib import Path

from dungeon_master.models import OracleKind, OracleOutcome
from dungeon_master.narrative import NarrativeEngine
from dungeon_master.turn_router import TurnRouter
from tests.test_narrative import sample_state


def main() -> None:
    state = sample_state()
    state.current_scene = "A dark dungeon room."

    router = TurnRouter()
    narrator = NarrativeEngine()

    inputs = [
        "I swing my sword at the goblin.",
        "I look around the room for traps.",
        "I try to talk my way past the guard.",
    ]

    baselines: dict[str, dict[str, object]] = {}

    for user_input in inputs:
        try:
            plan = router.route(
                text=user_input,
            )

            outcome = OracleOutcome(
                kind=OracleKind.PLAYER_ACTION,
                question=f"Does the player succeed at: {user_input}?",
                summary="Success",
                chaos_factor=5,
            )

            narration = narrator.generate(
                state=state,
                player_input=user_input,
                outcome=outcome,
                execution_context="Steps executed successfully.",
            )

            baselines[user_input] = {
                "route_plan": {
                    "route": plan.route.value if plan and plan.route else None,
                    "target_name": plan.target_name if plan else None,
                    "text": plan.text if plan else None,
                },
                "narration": narration,
            }
        except ValueError as exc:
            baselines[user_input] = {"error": str(exc)}

    out_path = Path("tests/eval_data/baseline.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(baselines, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
