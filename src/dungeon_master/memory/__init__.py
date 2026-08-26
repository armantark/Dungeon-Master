"""Stable public facade for bounded campaign memory."""

from dungeon_master.memory.contracts import (
    CallbackCandidate,
    CommittedTurnMemory,
    ConversationMessage,
    LocationMemory,
    MemoryState,
    NarrativeMemoryContext,
    NPCMemory,
    NPCUpdateMemoryContext,
    OpenLoop,
    PlannerMemoryContext,
    RevealedFact,
    SceneMemory,
    ThreadMemory,
    ThreadUpdateMemoryContext,
    TurnMemory,
)
from dungeon_master.memory.manager import MemoryManager, active_encounter_line_for_state

__all__ = [
    "CallbackCandidate",
    "CommittedTurnMemory",
    "ConversationMessage",
    "LocationMemory",
    "MemoryManager",
    "MemoryState",
    "NPCMemory",
    "NPCUpdateMemoryContext",
    "NarrativeMemoryContext",
    "OpenLoop",
    "PlannerMemoryContext",
    "RevealedFact",
    "SceneMemory",
    "ThreadMemory",
    "ThreadUpdateMemoryContext",
    "TurnMemory",
    "active_encounter_line_for_state",
]
