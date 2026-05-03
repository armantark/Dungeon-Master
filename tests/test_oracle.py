from dungeon_master.models import Likelihood, SceneStatus
from dungeon_master.oracle import OracleEngine
from tests.factories import sample_state


def test_yes_no_oracle_uses_chaos_adjusted_probability() -> None:
    state = sample_state()
    state.chaos_factor = 7
    oracle = OracleEngine(seed=1)

    outcome = oracle.ask_yes_no(state, "Is the abbey gate watched?", Likelihood.LIKELY)

    assert outcome.probability == 80
    assert outcome.rolls[0].result == 18
    assert outcome.answer == "Yes"
    assert outcome.summary == "Yes: Is the abbey gate watched?"


def test_scene_check_can_interrupt_expected_scene() -> None:
    state = sample_state()
    state.chaos_factor = 5
    oracle = OracleEngine(seed=1)

    outcome = oracle.check_scene(state, "I arrive before midnight.")

    assert outcome.scene_status == SceneStatus.INTERRUPTED
    assert outcome.rolls[0].result == 3
    assert "interrupted" in outcome.summary


def test_random_event_is_structured_and_deterministic() -> None:
    state = sample_state()
    oracle = OracleEngine(seed=8)

    outcome = oracle.generate_random_event(state)

    assert outcome.event_focus is not None
    assert outcome.event_action is not None
    assert outcome.event_tone is not None
    assert outcome.event_subject is not None
    assert len(outcome.rolls) == 4
