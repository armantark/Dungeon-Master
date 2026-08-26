"""Narration prompt assembly and orchestration."""

from dungeon_master.llm.narration.engine import (
    OUTMATCHED_THREAT_MARGIN,
    PARTY_ADVANTAGE_THREAT_MARGIN,
    SYSTEM_PROMPT,
    TACTICALLY_DANGEROUS_THREAT_MARGIN,
    TERMINAL_NARRATION_PROMPT,
    NarrativeEngine,
)

__all__ = [
    "OUTMATCHED_THREAT_MARGIN",
    "PARTY_ADVANTAGE_THREAT_MARGIN",
    "SYSTEM_PROMPT",
    "TACTICALLY_DANGEROUS_THREAT_MARGIN",
    "TERMINAL_NARRATION_PROMPT",
    "NarrativeEngine",
]
