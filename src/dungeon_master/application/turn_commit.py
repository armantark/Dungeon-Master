from __future__ import annotations

from typing import Protocol

from dungeon_master.application.continuity import ContinuityReconciler, NarratedTurn
from dungeon_master.cancel import CancellationToken
from dungeon_master.character_effect_updater import CharacterEffectUpdateResult
from dungeon_master.inventory_updater import InventoryUpdateResult
from dungeon_master.memory import CommittedTurnMemory, MemoryManager, MemoryState
from dungeon_master.models import (
    NPC,
    GameState,
    NPCPlayerLabelKind,
    OracleOutcome,
)


class CharacterEffectUpdater(Protocol):
    def update_character_effects(  # noqa: PLR0913
        self,
        state: GameState,
        *,
        player_input: str,
        outcome: OracleOutcome,
        execution_context: str | None,
        narrative_text: str,
        cancel_token: CancellationToken | None = None,
    ) -> CharacterEffectUpdateResult: ...


class InventoryUpdater(Protocol):
    def update_inventory(  # noqa: PLR0913
        self,
        state: GameState,
        *,
        player_input: str,
        outcome: OracleOutcome,
        execution_context: str | None,
        narrative_text: str,
        cancel_token: CancellationToken | None = None,
    ) -> InventoryUpdateResult: ...


class ContextMemoryForState(Protocol):
    def __call__(
        self,
        state: GameState,
        working_memory: MemoryState | None,
    ) -> MemoryState: ...


class TurnCommitter:
    """Apply every canonical mutation authorized by completed narration."""

    def __init__(
        self,
        *,
        memory_manager: MemoryManager,
        context_memory_for_state: ContextMemoryForState,
        continuity_reconciler: ContinuityReconciler,
        character_effect_updater: CharacterEffectUpdater,
        inventory_updater: InventoryUpdater,
    ) -> None:
        self._memory = memory_manager
        self._context_memory_for_state = context_memory_for_state
        self._continuity = continuity_reconciler
        self._character_effects = character_effect_updater
        self._inventory = inventory_updater

    def apply(
        self,
        state: GameState,
        turn: NarratedTurn,
        *,
        working_memory: MemoryState | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> CommittedTurnMemory:
        revealed_npc_ids = _disclose_npcs_from_text(state, turn.narrative_text)
        if revealed_npc_ids:
            sync_party_members_from_visible_npcs(state, npc_ids=revealed_npc_ids)
            _apply_npc_references(state, turn.outcome, revealed_npc_ids)

        self._character_effects.update_character_effects(
            state,
            player_input=turn.player_input,
            outcome=turn.outcome,
            execution_context=turn.execution_context,
            narrative_text=turn.narrative_text,
            cancel_token=cancel_token,
        )
        self._inventory.update_inventory(
            state,
            player_input=turn.player_input,
            outcome=turn.outcome,
            execution_context=turn.execution_context,
            narrative_text=turn.narrative_text,
            cancel_token=cancel_token,
        )

        memory = self._context_memory_for_state(state, working_memory)
        thread_context = self._memory.retrieve_for_thread_updater(
            state,
            memory,
            turn.player_input,
            turn.outcome,
        ).render()
        npc_context = self._memory.retrieve_for_npc_updater(
            state,
            memory,
            turn.player_input,
            turn.outcome,
        ).render()
        changes = self._continuity.reconcile(
            state,
            turn,
            thread_memory_context=thread_context or None,
            npc_memory_context=npc_context or None,
            cancel_token=cancel_token,
        )
        if changes.touched_npc_ids:
            sync_party_members_from_visible_npcs(
                state,
                npc_ids=changes.touched_npc_ids,
            )
        _apply_thread_references(turn.outcome, changes.touched_thread_ids)
        _apply_npc_references(state, turn.outcome, changes.touched_npc_ids)

        return CommittedTurnMemory(
            player_input=turn.player_input,
            outcome=turn.outcome,
            narrative_text=turn.narrative_text,
            execution_context=turn.execution_context or "",
        )


def _disclose_npcs_from_text(state: GameState, text: str) -> tuple[str, ...]:
    lowered = text.lower()
    revealed = [
        npc.id for npc in state.npcs if _maybe_promote_visible_npc_label_from_text(npc, lowered)
    ]
    still_hidden: list[NPC] = []
    for npc in state.hidden_npcs:
        if _npc_label_appears_in_text(lowered, npc.name):
            npc.player_label = npc.name
            npc.player_label_kind = NPCPlayerLabelKind.PROPER_NAME
            state.npcs.append(npc)
            revealed.append(npc.id)
        elif npc.player_label_kind == NPCPlayerLabelKind.DESCRIPTOR and _npc_label_appears_in_text(
            lowered, npc.display_label()
        ):
            state.npcs.append(npc)
            revealed.append(npc.id)
        else:
            still_hidden.append(npc)
    state.hidden_npcs = still_hidden
    return tuple(revealed)


def _maybe_promote_visible_npc_label_from_text(npc: NPC, lowered_text: str) -> bool:
    if npc.player_label_kind == NPCPlayerLabelKind.PROPER_NAME:
        return False
    if not _npc_label_appears_in_text(lowered_text, npc.name):
        return False
    npc.player_label = npc.name
    npc.player_label_kind = NPCPlayerLabelKind.PROPER_NAME
    return True


def _npc_label_appears_in_text(lowered_text: str, label: str) -> bool:
    return " ".join(label.lower().split()) in lowered_text


def _apply_thread_references(
    outcome: OracleOutcome,
    touched_thread_ids: tuple[str, ...],
) -> None:
    merged = _merge_ids(
        outcome.referenced_thread_id,
        outcome.referenced_thread_ids,
        touched_thread_ids,
    )
    outcome.referenced_thread_ids = merged
    outcome.referenced_thread_id = merged[0] if merged else None


def _apply_npc_references(
    state: GameState,
    outcome: OracleOutcome,
    touched_npc_ids: tuple[str, ...],
) -> None:
    visible_ids = {npc.id for npc in state.npcs}
    merged = [
        npc_id
        for npc_id in _merge_ids(
            outcome.referenced_npc_id,
            outcome.referenced_npc_ids,
            touched_npc_ids,
        )
        if npc_id in visible_ids
    ]
    outcome.referenced_npc_ids = merged
    outcome.referenced_npc_id = merged[0] if merged else None


def _merge_ids(
    singular_id: str | None,
    existing_ids: list[str],
    touched_ids: tuple[str, ...],
) -> list[str]:
    merged = [] if singular_id is None else [singular_id]
    for item_id in (*existing_ids, *touched_ids):
        if item_id not in merged:
            merged.append(item_id)
    return merged


def sync_party_members_from_visible_npcs(
    state: GameState,
    *,
    npc_ids: tuple[str, ...] | None = None,
) -> bool:
    visible_by_id = {npc.id: npc for npc in state.npcs}
    allowed_ids = None if npc_ids is None else set(npc_ids)
    changed = False
    for member in state.party_members:
        if member.npc_id is None or not member.active:
            continue
        if allowed_ids is not None and member.npc_id not in allowed_ids:
            continue
        npc = visible_by_id.get(member.npc_id)
        if npc is None:
            continue
        label = npc.display_label().strip()
        if label and member.sheet.name != label:
            member.sheet.name = label
            changed = True
        if npc.role and member.sheet.archetype != npc.role:
            member.sheet.archetype = npc.role
            changed = True
        if npc.disposition and member.sheet.epithet != npc.disposition:
            member.sheet.epithet = npc.disposition
            changed = True
        if npc.disposition and member.loyalty != npc.disposition:
            member.loyalty = npc.disposition
            changed = True
    return changed
