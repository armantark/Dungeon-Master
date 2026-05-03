from dungeon_master.models import Likelihood
from dungeon_master.turn_router import TurnRoute, TurnRouter


def test_routes_yes_no_question_with_likelihood_hint() -> None:
    routed = TurnRouter().route("Is the abbey gate watched? [unlikely]")

    assert routed.route == TurnRoute.YES_NO
    assert routed.text == "Is the abbey gate watched?"
    assert routed.likelihood == Likelihood.UNLIKELY


def test_routes_obvious_scene_transition() -> None:
    routed = TurnRouter().route("I cross the bone bridge before dawn.")

    assert routed.route == TurnRoute.SCENE_CHECK
    assert routed.text == "I cross the bone bridge before dawn."


def test_routes_random_event_prompt() -> None:
    routed = TurnRouter().route("Something happens in the chapel.")

    assert routed.route == TurnRoute.RANDOM_EVENT


def test_keeps_ambiguous_action_narrative_only() -> None:
    routed = TurnRouter().route("I listen at the abbey door.")

    assert routed.route == TurnRoute.PLAYER_ACTION
    assert routed.likelihood is None
