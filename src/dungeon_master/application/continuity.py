from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Protocol

from dungeon_master.application.cancellation import CancellationToken
from dungeon_master.application.updates.npcs import GeneratedNPCUpdateBatch, NPCUpdateResult
from dungeon_master.application.updates.threads import (
    GeneratedThreadUpdateBatch,
    ThreadUpdateResult,
)
from dungeon_master.domain.models import GameState, OracleOutcome


class ThreadUpdater(Protocol):
    def generate_thread_updates(  # noqa: PLR0913
        self,
        state: GameState,
        *,
        player_input: str,
        outcome: OracleOutcome,
        execution_context: str | None,
        narrative_text: str,
        memory_context: str | None,
        cancel_token: CancellationToken | None,
    ) -> GeneratedThreadUpdateBatch | None: ...

    def apply_generated_updates(
        self,
        state: GameState,
        generated: GeneratedThreadUpdateBatch,
    ) -> ThreadUpdateResult: ...


class NPCUpdater(Protocol):
    def generate_npc_updates(  # noqa: PLR0913
        self,
        state: GameState,
        *,
        player_input: str,
        outcome: OracleOutcome,
        execution_context: str | None,
        narrative_text: str,
        memory_context: str | None,
        cancel_token: CancellationToken | None,
    ) -> GeneratedNPCUpdateBatch | None: ...

    def apply_generated_updates(
        self,
        state: GameState,
        generated: GeneratedNPCUpdateBatch,
    ) -> NPCUpdateResult: ...


@dataclass(frozen=True)
class NarratedTurn:
    player_input: str
    outcome: OracleOutcome
    execution_context: str | None
    narrative_text: str


@dataclass(frozen=True)
class ContinuityChanges:
    touched_thread_ids: tuple[str, ...]
    touched_npc_ids: tuple[str, ...]


class ContinuityReconciler:
    """Propose continuity changes in parallel, then apply them in a fixed order."""

    def __init__(self, *, thread_updater: ThreadUpdater, npc_updater: NPCUpdater) -> None:
        self._thread_updater = thread_updater
        self._npc_updater = npc_updater

    def reconcile(
        self,
        state: GameState,
        turn: NarratedTurn,
        *,
        thread_memory_context: str | None,
        npc_memory_context: str | None,
        cancel_token: CancellationToken | None = None,
    ) -> ContinuityChanges:
        with ThreadPoolExecutor(max_workers=2) as executor:
            thread_future = executor.submit(
                self._thread_updater.generate_thread_updates,
                state,
                player_input=turn.player_input,
                outcome=turn.outcome,
                execution_context=turn.execution_context,
                narrative_text=turn.narrative_text,
                memory_context=thread_memory_context,
                cancel_token=cancel_token,
            )
            npc_future = executor.submit(
                self._npc_updater.generate_npc_updates,
                state,
                player_input=turn.player_input,
                outcome=turn.outcome,
                execution_context=turn.execution_context,
                narrative_text=turn.narrative_text,
                memory_context=npc_memory_context,
                cancel_token=cancel_token,
            )
            thread_updates = thread_future.result()
            npc_updates = npc_future.result()

        touched_thread_ids = (
            self._thread_updater.apply_generated_updates(state, thread_updates).touched_thread_ids
            if thread_updates is not None
            else ()
        )
        touched_npc_ids = (
            self._npc_updater.apply_generated_updates(state, npc_updates).touched_npc_ids
            if npc_updates is not None
            else ()
        )
        return ContinuityChanges(
            touched_thread_ids=touched_thread_ids,
            touched_npc_ids=touched_npc_ids,
        )
