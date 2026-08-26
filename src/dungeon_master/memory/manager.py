"""Facade object composing memory projection, retrieval, and rendering."""

from dungeon_master.domain.models import GameState
from dungeon_master.memory.projection import (
    active_encounter_line_for_state as _active_encounter_line_for_state,
)
from dungeon_master.memory.retrieval import MemoryRetrieval


class MemoryManager(MemoryRetrieval):
    """Build and query bounded campaign memory through one stable interface."""


def active_encounter_line_for_state(state: GameState) -> str | None:
    return _active_encounter_line_for_state(state)
