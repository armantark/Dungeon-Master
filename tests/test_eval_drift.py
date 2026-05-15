import json
from pathlib import Path
from typing import cast

import pytest
from deepeval import assert_test  # type: ignore[attr-defined]
from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCase, LLMTestCaseParams

from dungeon_master.models import GameState, OracleKind, OracleOutcome, OracleTables
from dungeon_master.narrative import NarrativeEngine


@pytest.fixture
def baseline_data() -> dict[str, dict[str, str]] | None:
    path = Path(__file__).parent / "eval_data" / "baseline.json"
    if path.exists():
        raw_data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw_data, dict):
            return cast("dict[str, dict[str, str]]", raw_data)
    return None


def test_narrative_drift(baseline_data: dict[str, dict[str, str]] | None) -> None:
    if not baseline_data:
        pytest.skip("No baseline data found. Run tools/generate_baseline.py first.")

    user_input = "I swing my sword at the goblin."
    baseline_narration = baseline_data.get(user_input, {}).get("narration", "")
    if not baseline_narration:
        pytest.skip("No usable narration baseline found. Regenerate tests/eval_data/baseline.json.")

    state = _sample_eval_state()
    state.current_scene = "A dark dungeon room."
    narrator = NarrativeEngine()
    outcome = OracleOutcome(
        kind=OracleKind.PLAYER_ACTION,
        question=f"Does the player succeed at: {user_input}?",
        summary="Success",
        chaos_factor=5,
    )
    new_narration = narrator.generate(
        state=state,
        player_input=user_input,
        outcome=outcome,
        execution_context="Steps executed successfully.",
    )

    drift_metric = GEval(
        name="Prompt Drift Evaluation",
        criteria=(
            "The actual output should maintain the exact same narrative style, "
            "second-person perspective ('you'), and strict adherence to the "
            "outcome as the expected output. It should not invent new mechanical facts."
        ),
        evaluation_params=[
            LLMTestCaseParams.INPUT,
            LLMTestCaseParams.ACTUAL_OUTPUT,
            LLMTestCaseParams.EXPECTED_OUTPUT,
        ],
        threshold=0.8,
    )

    test_case = LLMTestCase(
        input=user_input,
        actual_output=new_narration,
        expected_output=baseline_narration,
    )

    assert_test(test_case, [drift_metric])


def _sample_eval_state() -> GameState:
    return GameState(
        current_scene="A dark dungeon room.",
        setting_notes="A compact dungeon used for prompt drift evaluation.",
        player_notes="A cautious adventurer with a sword.",
        oracle_tables=OracleTables(
            event_focus=[
                "NPC action",
                "New NPC",
                "Move toward thread",
                "Move away from thread",
                "Close thread",
                "Ambiguous event",
            ],
            event_actions=[
                "attack",
                "reveal",
                "betray",
                "pursue",
                "hide",
                "break",
                "guard",
                "signal",
            ],
            event_tones=[
                "grim",
                "quiet",
                "urgent",
                "strange",
                "tense",
                "hopeful",
                "cold",
                "bright",
            ],
            event_subjects=[
                "goblin",
                "door",
                "torch",
                "guard",
                "trap",
                "altar",
                "coin",
                "blade",
            ],
        ),
    )
