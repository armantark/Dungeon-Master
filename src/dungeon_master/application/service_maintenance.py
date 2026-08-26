# mypy: disable-error-code="misc"
from __future__ import annotations

from typing import TYPE_CHECKING

from dungeon_master.application import turn_commit
from dungeon_master.application.service_models import (
    SaveBackfillReport,
)
from dungeon_master.cancel import CancellationToken
from dungeon_master.models import (
    CampaignStatus,
    EventType,
    GameEvent,
    GameState,
)

if TYPE_CHECKING:
    from dungeon_master.service import GameService


class ServiceMaintenanceMixin:
    def new_setup_state(self: GameService) -> GameState:
        """Return a fresh setup-state skeleton for a brand-new save slot."""
        return self._new_setup_state()

    def backfill_current_save(
        self: GameService,
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

        rebuilt_memory = self._memory_for_state(
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

    def load_state(
        self: GameService, *, cancel_token: CancellationToken | None = None
    ) -> GameState:
        state = self._store.load_or_create(self._new_setup_state)
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
            self._store.save_memory(self._memory_for_state(state, force_rebuild=True))
        return state

    def _load_state_readonly(
        self: GameService,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> GameState:
        state = self._store.load() if self._store.exists() else self._new_setup_state()
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

    def reset(self: GameService) -> GameState:
        state = self._new_setup_state()
        self._record_event(
            state,
            GameEvent(
                event_type=EventType.SYSTEM,
                title="Setup reset",
                content="Returned to character creation.",
            ),
        )
        self._save_state_commit(state, create_checkpoint=True)
        return state

    def _new_setup_state(self: GameService) -> GameState:
        return self._character_generator.setup_state()
