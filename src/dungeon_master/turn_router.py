from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from dungeon_master.models import Likelihood


class TurnRoute(StrEnum):
    """Mechanical route selected for a natural-language player turn."""

    PLAYER_ACTION = "player_action"
    YES_NO = "yes_no"
    RANDOM_EVENT = "random_event"
    SCENE_CHECK = "scene_check"


@dataclass(frozen=True)
class RoutedTurn:
    route: TurnRoute
    text: str
    likelihood: Likelihood | None = None


LIKELIHOOD_HINTS: dict[str, Likelihood] = {
    "impossible": Likelihood.IMPOSSIBLE,
    "very-unlikely": Likelihood.VERY_UNLIKELY,
    "very_unlikely": Likelihood.VERY_UNLIKELY,
    "very unlikely": Likelihood.VERY_UNLIKELY,
    "unlikely": Likelihood.UNLIKELY,
    "even": Likelihood.EVEN,
    "even-odds": Likelihood.EVEN,
    "even_odds": Likelihood.EVEN,
    "even odds": Likelihood.EVEN,
    "likely": Likelihood.LIKELY,
    "very-likely": Likelihood.VERY_LIKELY,
    "very_likely": Likelihood.VERY_LIKELY,
    "very likely": Likelihood.VERY_LIKELY,
    "certain": Likelihood.NEARLY_CERTAIN,
    "nearly-certain": Likelihood.NEARLY_CERTAIN,
    "nearly_certain": Likelihood.NEARLY_CERTAIN,
    "nearly certain": Likelihood.NEARLY_CERTAIN,
}

YES_NO_STARTERS: frozenset[str] = frozenset(
    {
        "am",
        "are",
        "can",
        "could",
        "did",
        "do",
        "does",
        "has",
        "have",
        "is",
        "may",
        "might",
        "must",
        "shall",
        "should",
        "was",
        "were",
        "will",
        "would",
    },
)

SCENE_TRANSITION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"^i\s+(?:enter|cross|leave|travel|ride|sail|descend|ascend|climb)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^i\s+(?:go|head|make my way|push on|press on)\s+"
        r"(?:to|toward|into|through)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^we\s+(?:enter|cross|leave|travel|ride|sail|descend|ascend|climb)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:new scene|next scene|scene check)\b", re.IGNORECASE),
)

RANDOM_EVENT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:something happens|what happens|random event|complication|twist)\b",
        re.IGNORECASE,
    ),
)


class TurnRouter:
    """Classify natural player chat into deterministic game operations.

    This is intentionally conservative. The router only claims mechanics
    when player intent is obvious: explicit yes/no questions, explicit
    random-event language, or strong scene-transition verbs. Ambiguous
    free text stays narrative-only so the game does not surprise the
    player with unwanted rolls.
    """

    def route(self, text: str) -> RoutedTurn:
        body, likelihood = self._strip_likelihood_hint(text)
        normalized = body.strip()
        if not normalized:
            return RoutedTurn(route=TurnRoute.PLAYER_ACTION, text=text.strip())

        if self._looks_like_random_event(normalized):
            return RoutedTurn(route=TurnRoute.RANDOM_EVENT, text=normalized)

        if self._looks_like_yes_no_question(normalized):
            return RoutedTurn(
                route=TurnRoute.YES_NO,
                text=normalized,
                likelihood=likelihood or Likelihood.EVEN,
            )

        if self._looks_like_scene_transition(normalized):
            return RoutedTurn(route=TurnRoute.SCENE_CHECK, text=normalized)

        return RoutedTurn(route=TurnRoute.PLAYER_ACTION, text=normalized)

    def _strip_likelihood_hint(self, text: str) -> tuple[str, Likelihood | None]:
        match = re.search(r"\[([^\]]+)\]\s*$", text)
        if match is None:
            return text, None

        raw_hint = match.group(1).strip().lower()
        canonical = re.sub(r"\s+", " ", raw_hint)
        likelihood = LIKELIHOOD_HINTS.get(canonical) or LIKELIHOOD_HINTS.get(
            canonical.replace(" ", "-"),
        )
        if likelihood is None:
            return text, None
        return text[: match.start()].strip(), likelihood

    def _looks_like_yes_no_question(self, text: str) -> bool:
        first_word = text.split(maxsplit=1)[0].strip("?!.,;:").lower()
        return text.endswith("?") and first_word in YES_NO_STARTERS

    def _looks_like_scene_transition(self, text: str) -> bool:
        return any(pattern.search(text) for pattern in SCENE_TRANSITION_PATTERNS)

    def _looks_like_random_event(self, text: str) -> bool:
        return any(pattern.search(text) for pattern in RANDOM_EVENT_PATTERNS)
