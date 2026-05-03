from __future__ import annotations

import random
from collections.abc import Sequence

from dungeon_master.models import (
    NPC,
    GameState,
    Likelihood,
    OracleKind,
    OracleOutcome,
    Roll,
    SceneStatus,
    ThreadStatus,
)

FATE_DIE_SIDES = 100

BASE_PROBABILITIES: dict[Likelihood, int] = {
    Likelihood.IMPOSSIBLE: 5,
    Likelihood.VERY_UNLIKELY: 15,
    Likelihood.UNLIKELY: 30,
    Likelihood.EVEN: 50,
    Likelihood.LIKELY: 70,
    Likelihood.VERY_LIKELY: 85,
    Likelihood.NEARLY_CERTAIN: 95,
}

class OracleEngine:
    def __init__(self, seed: int | None = None) -> None:
        self._rng = random.Random(seed)

    def ask_yes_no(
        self,
        state: GameState,
        question: str,
        likelihood: Likelihood,
    ) -> OracleOutcome:
        probability = self._probability_for(likelihood, state.chaos_factor)
        roll = self._roll(FATE_DIE_SIDES, "fate")
        is_yes = roll.result <= probability
        is_double = roll.result % 11 == 0 and roll.result < FATE_DIE_SIDES
        answer = "Yes" if is_yes else "No"
        if is_double:
            answer = f"Exceptional {answer}"

        return OracleOutcome(
            kind=OracleKind.YES_NO,
            summary=f"{answer}: {question}",
            rolls=[roll],
            question=question,
            likelihood=likelihood,
            answer=answer,
            probability=probability,
            chaos_factor=state.chaos_factor,
        )

    def generate_random_event(self, state: GameState) -> OracleOutcome:
        tables = state.oracle_tables
        focus = self._choice(tables.event_focus)
        action = self._choice(tables.event_actions)
        tone = self._choice(tables.event_tones)
        subject = self._choice(tables.event_subjects)
        thread_id = self._pick_thread_id(state, focus)
        npc_id = self._pick_npc_id(state.npcs, focus)
        rolls = [
            self._roll(len(tables.event_focus), "event_focus"),
            self._roll(len(tables.event_actions), "event_action"),
            self._roll(len(tables.event_tones), "event_tone"),
            self._roll(len(tables.event_subjects), "event_subject"),
        ]

        return OracleOutcome(
            kind=OracleKind.RANDOM_EVENT,
            summary=f"{focus}: {action} {tone} {subject}",
            rolls=rolls,
            chaos_factor=state.chaos_factor,
            event_focus=focus,
            event_action=action,
            event_tone=tone,
            event_subject=subject,
            referenced_thread_id=thread_id,
            referenced_npc_id=npc_id,
        )

    def check_scene(self, state: GameState, expected_scene: str) -> OracleOutcome:
        roll = self._roll(10, "scene_check")
        if roll.result > state.chaos_factor:
            status = SceneStatus.EXPECTED
            summary = f"{status.value}: {expected_scene}"
        elif roll.result % 2 == 0:
            status = SceneStatus.ALTERED
            summary = f"{status.value}: {expected_scene}"
        else:
            status = SceneStatus.INTERRUPTED
            summary = f"{status.value}: {expected_scene}"

        return OracleOutcome(
            kind=OracleKind.SCENE_CHECK,
            summary=summary,
            rolls=[roll],
            question=expected_scene,
            chaos_factor=state.chaos_factor,
            scene_status=status,
        )

    def _roll(self, sides: int, label: str) -> Roll:
        return Roll(sides=sides, result=self._rng.randint(1, sides), label=label)

    def _choice(self, values: Sequence[str]) -> str:
        return values[self._rng.randrange(len(values))]

    def _probability_for(self, likelihood: Likelihood, chaos_factor: int) -> int:
        base = BASE_PROBABILITIES[likelihood]
        chaos_shift = (chaos_factor - 5) * 5
        return max(1, min(99, base + chaos_shift))

    def _pick_thread_id(self, state: GameState, focus: str) -> str | None:
        if "thread" not in focus.lower() or not state.threads:
            return None
        active_threads = [
            thread for thread in state.threads if thread.status == ThreadStatus.ACTIVE
        ]
        candidates = active_threads or state.threads
        return candidates[self._rng.randrange(len(candidates))].id

    def _pick_npc_id(self, npcs: list[NPC], focus: str) -> str | None:
        if "npc" not in focus.lower() or not npcs:
            return None
        return npcs[self._rng.randrange(len(npcs))].id
