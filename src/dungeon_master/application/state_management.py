from __future__ import annotations

import json
from collections.abc import Mapping

from dungeon_master.application import turn_commit
from dungeon_master.application.service_models import (
    CURRENT_NPC_ROSTER_VERSION,
    SaveBackfillReport,
)
from dungeon_master.application.service_ports import CairnPort, CharacterPort, NPCUpdaterPort
from dungeon_master.cancel import CancellationToken
from dungeon_master.memory import (
    CURRENT_MEMORY_SCHEMA_VERSION,
    CommittedTurnMemory,
    MemoryManager,
    MemoryState,
)
from dungeon_master.models import (
    NPC,
    CampaignEndReason,
    CampaignStatus,
    EventType,
    GameEvent,
    GameState,
    JSONValue,
    OracleOutcome,
    utc_now,
)
from dungeon_master.state_store import StateStore, TurnCheckpointRecord


class ApplicationState:
    """Own canonical state loading, repair, event ordering, and persistence."""

    def __init__(
        self,
        *,
        store: StateStore,
        cairn: CairnPort,
        character_generator: CharacterPort,
        npc_updater: NPCUpdaterPort,
        memory_manager: MemoryManager,
    ) -> None:
        self._store = store
        self._cairn = cairn
        self._character_generator = character_generator
        self._npc_updater = npc_updater
        self._memory = memory_manager

    @property
    def store(self) -> StateStore:
        return self._store

    def bind_store(self, store: StateStore) -> None:
        self._store = store

    def backfill_current_save(
        self,
        *,
        apply: bool,
        create_checkpoint: bool = True,
        cancel_token: CancellationToken | None = None,
    ) -> SaveBackfillReport:
        """Audit/backfill one existing save against current core features.

        This is intentionally *not* a campaign reseed. The goal is to bring an
        older save forward so it carries the canonical state newer features now
        expect (character Cairn backfill, visible/hidden NPC split, terminal
        status sync, rebuilt `memory.json`) without regenerating the campaign's
        world or rewriting cast canon.

        `apply=False` performs a dry run and reports what would change without
        touching disk. `apply=True` persists canonical state only when the state
        itself changed, and rebuilds/saves the memory sidecar when needed.
        """
        if not self._store.exists():
            message = "No save state exists to backfill."
            raise ValueError(message)

        before_state = self._store.load()
        before_memory = self._store.load_memory_or_none()
        working = before_state.model_copy(deep=True)

        character_backfilled = self._cairn.ensure_character_state(
            working,
            allow_backfill=working.campaign_status == CampaignStatus.ACTIVE,
            cancel_token=cancel_token,
        )
        npc_roster_repaired = self._repair_npc_roster_on_load(
            working,
            cancel_token=cancel_token,
        )
        terminal_state_synced = self._sync_terminal_state_on_load(working)
        party_members_synced = turn_commit.sync_party_members_from_visible_npcs(working)
        schema_defaults_persisted = self._ensure_current_save_schema(working)
        state_changed = (
            character_backfilled
            or npc_roster_repaired
            or terminal_state_synced
            or party_members_synced
            or schema_defaults_persisted
        )

        rebuilt_memory = self.memory_for_state(
            working,
            existing_memory=before_memory,
            force_rebuild=True,
        )
        memory_rebuilt = before_memory is None or rebuilt_memory.model_dump(
            mode="json"
        ) != before_memory.model_dump(mode="json")
        visible_name_warnings = self._audit_visible_npc_name_support(working)

        checkpoint_written = False
        if apply:
            if state_changed:
                self._store.save(working, create_checkpoint=create_checkpoint)
                checkpoint_written = create_checkpoint
            if memory_rebuilt:
                self._store.save_memory(rebuilt_memory)

        return SaveBackfillReport(
            applied=apply,
            state_changed=state_changed,
            character_backfilled=character_backfilled,
            npc_roster_repaired=npc_roster_repaired,
            terminal_state_synced=terminal_state_synced,
            memory_rebuilt=memory_rebuilt,
            checkpoint_written=checkpoint_written,
            campaign_status_before=before_state.campaign_status,
            campaign_status_after=working.campaign_status,
            visible_npc_count_before=len(before_state.npcs),
            visible_npc_count_after=len(working.npcs),
            hidden_npc_count_before=len(before_state.hidden_npcs),
            hidden_npc_count_after=len(working.hidden_npcs),
            visible_name_warnings=visible_name_warnings,
        )

    def load_state(self, *, cancel_token: CancellationToken | None = None) -> GameState:
        state = self._store.load_or_create(self.new_setup_state)
        changed = self._cairn.ensure_character_state(
            state,
            allow_backfill=state.campaign_status == CampaignStatus.ACTIVE,
            cancel_token=cancel_token,
        )
        changed = (
            self._repair_npc_roster_on_load(
                state,
                cancel_token=cancel_token,
            )
            or changed
        )
        changed = turn_commit.sync_party_members_from_visible_npcs(state) or changed
        changed = self._sync_terminal_state_on_load(state) or changed
        if changed:
            self._store.save(state, create_checkpoint=False)
            self._store.save_memory(self.memory_for_state(state, force_rebuild=True))
        return state

    def load_state_readonly(
        self,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> GameState:
        state = self._store.load() if self._store.exists() else self.new_setup_state()
        self._cairn.ensure_character_state(
            state,
            allow_backfill=state.campaign_status == CampaignStatus.ACTIVE,
            cancel_token=cancel_token,
        )
        self._repair_npc_roster_on_load(
            state,
            cancel_token=cancel_token,
        )
        turn_commit.sync_party_members_from_visible_npcs(state)
        self._sync_terminal_state_on_load(state)
        return state

    def new_setup_state(self) -> GameState:
        return self._character_generator.setup_state()

    def record_event(self, state: GameState, event: GameEvent) -> None:
        state.action_log.append(event)
        self._store.append_event(event)

    def queue_event(self, state: GameState, queue: list[GameEvent], event: GameEvent) -> None:
        state.action_log.append(event)
        queue.append(event)

    def persist_streamed_state(
        self,
        state: GameState,
        events: list[GameEvent],
        *,
        turn_checkpoint: TurnCheckpointRecord | None = None,
        committed_turn: CommittedTurnMemory | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> None:
        self.raise_if_cancelled(cancel_token)
        if turn_checkpoint is not None:
            self._store.write_turn_checkpoint(
                turn_id=turn_checkpoint.turn_id,
                oracle_outcome_id=turn_checkpoint.oracle_outcome_id,
                player_input=turn_checkpoint.player_input,
                execution_context=turn_checkpoint.execution_context,
                state=turn_checkpoint.state,
            )
            self.raise_if_cancelled(cancel_token)
        self._store.append_events(events)
        self.raise_if_cancelled(cancel_token)
        self.save_state_commit(
            state,
            create_checkpoint=True,
            committed_turn=committed_turn,
        )

    def ensure_active(self, state: GameState) -> None:
        if state.campaign_status == CampaignStatus.ENDED:
            message = self.campaign_end_conflict_message(state)
            raise ValueError(message)
        if state.campaign_status != CampaignStatus.ACTIVE:
            message = "Campaign has not started. Finalize a character and start the campaign."
            raise ValueError(message)

    def _sync_terminal_state_on_load(self, state: GameState) -> bool:
        if state.campaign_status == CampaignStatus.ACTIVE and state.character.cairn.dead:
            return self.mark_campaign_ended(state, reason=CampaignEndReason.DEATH)
        return False

    def _audit_visible_npc_name_support(self, state: GameState) -> tuple[str, ...]:
        """Warn when a visible NPC label lacks explicit textual support.

        This is an audit signal for one-time save repair, not an automatic
        demotion rule. The user clarified that backend continuity is allowed to
        know a true name before the player does, and that a name should only be
        player-visible once the fiction explicitly grants it (dialogue, clues,
        divination, etc.). Descriptor-visible figures follow the same rule: the
        player-facing label should be grounded in committed text somewhere. We
        conservatively approximate that by checking whether the visible label
        appears anywhere in the committed current scene or transcript. A miss
        does *not* prove the label is wrong — it may have been granted
        indirectly — so the script reports rather than mutates.
        """
        lowered = self._audit_name_support_text(state).lower()
        return tuple(
            f"Visible NPC label lacks explicit text support: {npc.display_label()}"
            for npc in state.npcs
            if not self._npc_label_has_text_support(lowered, npc)
        )

    def _audit_name_support_text(self, state: GameState) -> str:
        chunks: list[str] = [
            state.current_scene,
            state.player_notes,
        ]
        if state.campaign_end_summary is not None:
            chunks.append(state.campaign_end_summary)
        chunks.extend(event.content for event in state.action_log)
        chunks.extend(outcome.summary for outcome in state.oracle_history)
        return "\n".join(chunk for chunk in chunks if chunk.strip())

    def auto_end_campaign_if_needed(
        self,
        state: GameState,
        *,
        outcome: OracleOutcome,
    ) -> GameEvent | None:
        if state.campaign_status != CampaignStatus.ACTIVE or not state.character.cairn.dead:
            return None
        summary = (
            self._default_campaign_end_summary(state, reason=CampaignEndReason.DEATH)
            + f" Final turn: {outcome.summary}"
        )
        self.mark_campaign_ended(
            state,
            reason=CampaignEndReason.DEATH,
            summary=summary,
        )
        return self.campaign_end_event(state)

    def mark_campaign_ended(
        self,
        state: GameState,
        *,
        reason: CampaignEndReason,
        summary: str | None = None,
    ) -> bool:
        normalized_summary = (
            summary.strip()
            if summary is not None and summary.strip() != ""
            else self._default_campaign_end_summary(state, reason=reason)
        )
        changed = False
        if state.campaign_status != CampaignStatus.ENDED:
            state.campaign_status = CampaignStatus.ENDED
            changed = True
        if state.campaign_end_reason != reason:
            state.campaign_end_reason = reason
            changed = True
        if state.campaign_ended_at is None:
            state.campaign_ended_at = utc_now()
            changed = True
        if state.campaign_end_summary != normalized_summary:
            state.campaign_end_summary = normalized_summary
            changed = True
        return changed

    def _default_campaign_end_summary(
        self,
        state: GameState,
        *,
        reason: CampaignEndReason,
    ) -> str:
        name = state.character.name.strip() or "The wanderer"
        if reason == CampaignEndReason.DEATH:
            return f"{name}'s campaign ended in death."
        if reason == CampaignEndReason.RETIREMENT:
            return f"{name} retired from the campaign."
        return f"{name} achieved a final victory."

    def campaign_end_event(self, state: GameState) -> GameEvent:
        summary = state.campaign_end_summary or "The campaign has ended."
        return GameEvent(
            event_type=EventType.SYSTEM,
            title="Campaign ended",
            content=summary,
        )

    def campaign_end_conflict_message(self, state: GameState) -> str:
        reason = state.campaign_end_reason
        if reason == CampaignEndReason.DEATH:
            return "Campaign has ended in death. Reset to start a new run."
        if reason == CampaignEndReason.RETIREMENT:
            return "Campaign has ended in retirement. Reset to start a new run."
        if reason == CampaignEndReason.VICTORY:
            return "Campaign has already ended in victory. Reset to start a new run."
        return "Campaign has already ended. Reset to start a new run."

    def context_memory_for_state(
        self,
        state: GameState,
        working_memory: MemoryState | None,
    ) -> MemoryState:
        if working_memory is None:
            return self.memory_for_state(state)
        memory = self._memory.sync_from_state(
            state,
            working_memory.model_copy(deep=True),
        )
        if (
            memory.current_scene_turns
            and memory.current_scene_turns[-1].scene_key != memory.current_scene_key
        ):
            memory.current_scene_turns = []
        return memory

    def _repair_npc_roster_on_load(
        self,
        state: GameState,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> bool:
        if state.npc_roster_version >= CURRENT_NPC_ROSTER_VERSION:
            return False
        repaired = self._npc_updater.reseed_legacy_roster(
            state,
            memory_context=self._memory_context_for_legacy_npc_repair(state),
            cancel_token=cancel_token,
        )
        state.npcs = [npc.model_copy(deep=True) for npc in repaired.introduced_npcs]
        state.hidden_npcs = [npc.model_copy(deep=True) for npc in repaired.hidden_npcs]
        state.npc_roster_version = CURRENT_NPC_ROSTER_VERSION
        return True

    def _memory_context_for_legacy_npc_repair(self, state: GameState) -> str | None:
        existing_memory = self._store.load_memory_or_none()
        context = self._memory.retrieve_for_planner(
            state,
            self.memory_for_state(state, existing_memory=existing_memory),
            state.current_scene,
        ).render()
        return context or None

    def _npc_label_has_text_support(self, lowered_text: str, npc: NPC) -> bool:
        return self._npc_label_appears_in_text(lowered_text, npc.display_label())

    def _npc_label_appears_in_text(self, lowered_text: str, label: str) -> bool:
        return " ".join(label.lower().split()) in lowered_text

    def save_state_commit(
        self,
        state: GameState,
        *,
        create_checkpoint: bool,
        committed_turn: CommittedTurnMemory | None = None,
    ) -> None:
        del committed_turn
        self._store.save(state, create_checkpoint=create_checkpoint)
        self._store.save_memory(self.memory_for_state(state, force_rebuild=True))

    def _ensure_current_save_schema(self, state: GameState) -> bool:
        """Persist newly-added schema defaults during explicit backfill.

        Pydantic fills missing fields (for example item `power` objects and
        `party_members`) while loading old saves, but that alone does not rewrite
        the JSON file. The explicit backfill command should therefore compare the
        original parsed payload to the current model dump and mark the state dirty
        when the on-disk shape lacks fields that now have canonical defaults.
        """
        if not self._store.exists():
            return False

        before: JSONValue = json.loads(self._store.state_path.read_text(encoding="utf-8"))
        after = state.model_dump(mode="json")
        return before != after

    def memory_for_state(
        self,
        state: GameState,
        *,
        existing_memory: MemoryState | None = None,
        force_rebuild: bool = False,
        checkpoint_overrides: Mapping[str, TurnCheckpointRecord] | None = None,
    ) -> MemoryState:
        if force_rebuild:
            return self._memory.bootstrap_from_turns(
                state,
                self._committed_turns_for_state(
                    state,
                    checkpoint_overrides=checkpoint_overrides,
                ),
            )
        memory = self._store.load_memory_or_none() if existing_memory is None else existing_memory
        if self._memory_needs_rebuild(state, memory):
            return self._memory.bootstrap_from_turns(
                state,
                self._committed_turns_for_state(state),
            )
        return self._memory.sync_from_state(state, memory)

    def _memory_needs_rebuild(self, state: GameState, memory: MemoryState | None) -> bool:
        if memory is None:
            return True
        return (
            memory.state_id != state.id
            or memory.turn_count != len(state.oracle_history)
            or memory.schema_version != CURRENT_MEMORY_SCHEMA_VERSION
        )

    def _committed_turns_for_state(
        self,
        state: GameState,
        *,
        checkpoint_overrides: Mapping[str, TurnCheckpointRecord] | None = None,
    ) -> list[CommittedTurnMemory]:
        player_events = [
            event for event in state.action_log if event.event_type == EventType.PLAYER
        ]
        overrides = {} if checkpoint_overrides is None else checkpoint_overrides
        player_event_index = 0
        latest_narrative_by_outcome_id = {
            event.oracle_outcome_id: event
            for event in state.action_log
            if event.event_type == EventType.NARRATIVE and event.oracle_outcome_id is not None
        }
        turns: list[CommittedTurnMemory] = []
        for outcome in state.oracle_history:
            checkpoint = overrides.get(outcome.id)
            if checkpoint is None:
                checkpoint = self._store.load_turn_checkpoint_or_none(outcome.id)
            if checkpoint is not None:
                player_input = checkpoint.player_input
                execution_context = checkpoint.execution_context or ""
            else:
                player_input = (
                    player_events[player_event_index].content
                    if player_event_index < len(player_events)
                    else outcome.summary
                )
                execution_context = ""
            if player_event_index < len(player_events):
                player_event = player_events[player_event_index]
                if player_event.content == player_input:
                    player_event_index += 1
            narrative = latest_narrative_by_outcome_id.get(outcome.id)
            turns.append(
                CommittedTurnMemory(
                    player_input=player_input,
                    outcome=outcome,
                    narrative_text="" if narrative is None else narrative.content,
                    execution_context=execution_context,
                ),
            )
        return turns

    def raise_if_cancelled(self, cancel_token: CancellationToken | None) -> None:
        if cancel_token is not None:
            cancel_token.raise_if_cancelled()
