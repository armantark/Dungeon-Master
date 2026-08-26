from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from dungeon_master.models import (
    NPCPlayerLabelKind,
    NPCStatus,
    OracleKind,
    OracleOutcome,
    SceneStatus,
    StrictModel,
    ThreadStatus,
    new_id,
    utc_now,
)


class TurnMemory(StrictModel):
    turn_index: int = Field(ge=1)
    oracle_outcome_id: str = Field(min_length=1)
    scene_key: str = Field(min_length=1)
    scene_number: int = Field(ge=1)
    scene_label: str = Field(min_length=1)
    scene_status: SceneStatus
    player_input: str = Field(min_length=1)
    oracle_kind: OracleKind
    oracle_summary: str = Field(min_length=1)
    narrative_excerpt: str = ""
    execution_context: str = ""
    related_thread_ids: list[str] = Field(default_factory=list)
    related_npc_ids: list[str] = Field(default_factory=list)
    related_location_keys: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class SceneMemory(StrictModel):
    scene_key: str = Field(min_length=1)
    scene_number: int = Field(ge=1)
    scene_label: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    status: SceneStatus
    first_turn_index: int = Field(ge=1)
    last_turn_index: int = Field(ge=1)
    visit_count: int = Field(default=1, ge=1)
    recent_developments: list[str] = Field(default_factory=list)


class ThreadMemory(StrictModel):
    thread_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    status: ThreadStatus
    stakes: str = ""
    summary: str = Field(min_length=1)
    last_touched_turn: int = Field(default=0, ge=0)
    recent_developments: list[str] = Field(default_factory=list)


class NPCMemory(StrictModel):
    npc_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    label_kind: NPCPlayerLabelKind = NPCPlayerLabelKind.PROPER_NAME
    role: str = ""
    disposition: str = ""
    status: NPCStatus = NPCStatus.ACTIVE
    summary: str = Field(min_length=1)
    last_touched_turn: int = Field(default=0, ge=0)
    recent_developments: list[str] = Field(default_factory=list)


class LocationMemory(StrictModel):
    location_key: str = Field(min_length=1)
    label: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    last_touched_turn: int = Field(default=0, ge=0)
    recent_developments: list[str] = Field(default_factory=list)


class RevealedFact(StrictModel):
    id: str = Field(default_factory=lambda: new_id("fact"))
    text: str = Field(min_length=1)
    scene_key: str = Field(min_length=1)
    source_oracle_outcome_id: str | None = None
    related_thread_ids: list[str] = Field(default_factory=list)
    related_npc_ids: list[str] = Field(default_factory=list)
    related_location_keys: list[str] = Field(default_factory=list)
    salience: int = Field(default=3, ge=1, le=5)
    last_touched_turn: int = Field(default=0, ge=0)


class OpenLoop(StrictModel):
    id: str = Field(default_factory=lambda: new_id("loop"))
    text: str = Field(min_length=1)
    priority: int = Field(default=3, ge=1, le=5)
    scene_key: str = Field(min_length=1)
    related_thread_ids: list[str] = Field(default_factory=list)
    related_npc_ids: list[str] = Field(default_factory=list)
    related_location_keys: list[str] = Field(default_factory=list)
    last_touched_turn: int = Field(default=0, ge=0)


class CallbackCandidate(StrictModel):
    id: str = Field(default_factory=lambda: new_id("callback"))
    text: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    priority: int = Field(default=3, ge=1, le=5)
    last_touched_turn: int = Field(default=0, ge=0)
    related_thread_ids: list[str] = Field(default_factory=list)
    related_npc_ids: list[str] = Field(default_factory=list)
    related_location_keys: list[str] = Field(default_factory=list)


class MemoryState(StrictModel):
    schema_version: int = Field(default=1, ge=1)
    state_id: str = ""
    updated_at: datetime = Field(default_factory=utc_now)
    turn_count: int = Field(default=0, ge=0)
    current_scene_key: str = ""
    active_location_key: str = ""
    current_scene_summary: str = "No compacted scene summary yet."
    active_encounter_summary: str = ""
    recent_turn_summaries: list[TurnMemory] = Field(default_factory=list)
    current_scene_turns: list[TurnMemory] = Field(default_factory=list)
    scene_summaries: list[SceneMemory] = Field(default_factory=list)
    thread_memory: list[ThreadMemory] = Field(default_factory=list)
    npc_memory: list[NPCMemory] = Field(default_factory=list)
    location_memory: list[LocationMemory] = Field(default_factory=list)
    revealed_facts: list[RevealedFact] = Field(default_factory=list)
    open_loops: list[OpenLoop] = Field(default_factory=list)
    callback_candidates: list[CallbackCandidate] = Field(default_factory=list)


class CommittedTurnMemory(StrictModel):
    player_input: str = Field(min_length=1)
    outcome: OracleOutcome
    narrative_text: str = ""
    execution_context: str = ""


class ConversationMessage(StrictModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class PlannerMemoryContext(StrictModel):
    scene_summary: str = ""
    active_encounter_summary: str = ""
    inventory_summary: str = ""
    scene_messages: list[ConversationMessage] = Field(default_factory=list)
    campaign_chronicle: list[str] = Field(default_factory=list)
    open_loops: list[str] = Field(default_factory=list)
    relevant_memory: list[str] = Field(default_factory=list)
    revealed_facts: list[str] = Field(default_factory=list)

    def render(self) -> str:
        sections: list[str] = []
        if self.scene_summary:
            sections.append(f"Current scene summary: {self.scene_summary}")
        if self.active_encounter_summary:
            sections.append(f"Active encounter: {self.active_encounter_summary}")
        if self.inventory_summary:
            sections.append(f"Carried gear: {self.inventory_summary}")
        if self.campaign_chronicle:
            sections.append(
                "Campaign chronicle:\n"
                + "\n".join(f"- {item}" for item in self.campaign_chronicle),
            )
        if self.open_loops:
            sections.append("Open loops:\n" + "\n".join(f"- {item}" for item in self.open_loops))
        if self.relevant_memory:
            sections.append(
                "Relevant memory:\n" + "\n".join(f"- {item}" for item in self.relevant_memory),
            )
        if self.revealed_facts:
            sections.append(
                "Revealed facts:\n" + "\n".join(f"- {item}" for item in self.revealed_facts),
            )
        return "\n\n".join(sections)


class ThreadUpdateMemoryContext(StrictModel):
    scene_summary: str = ""
    recent_turns: list[str] = Field(default_factory=list)
    active_threads: list[str] = Field(default_factory=list)
    open_loops: list[str] = Field(default_factory=list)
    revealed_facts: list[str] = Field(default_factory=list)
    callback_candidates: list[str] = Field(default_factory=list)

    def render(self) -> str:
        sections: list[str] = []
        if self.scene_summary:
            sections.append(f"Current scene summary: {self.scene_summary}")
        if self.recent_turns:
            sections.append(
                "Recent turn summaries:\n" + "\n".join(f"- {item}" for item in self.recent_turns),
            )
        if self.active_threads:
            sections.append(
                "Current threads:\n" + "\n".join(f"- {item}" for item in self.active_threads),
            )
        if self.open_loops:
            sections.append("Open loops:\n" + "\n".join(f"- {item}" for item in self.open_loops))
        if self.revealed_facts:
            sections.append(
                "Revealed facts:\n" + "\n".join(f"- {item}" for item in self.revealed_facts),
            )
        if self.callback_candidates:
            sections.append(
                "Callback candidates:\n"
                + "\n".join(f"- {item}" for item in self.callback_candidates),
            )
        return "\n\n".join(sections)


class NPCUpdateMemoryContext(StrictModel):
    scene_summary: str = ""
    scene_transcript: list[str] = Field(default_factory=list)
    recent_turns: list[str] = Field(default_factory=list)
    active_npcs: list[str] = Field(default_factory=list)
    open_loops: list[str] = Field(default_factory=list)
    revealed_facts: list[str] = Field(default_factory=list)
    callback_candidates: list[str] = Field(default_factory=list)

    def render(self) -> str:
        sections: list[str] = []
        if self.scene_summary:
            sections.append(f"Current scene summary: {self.scene_summary}")
        if self.scene_transcript:
            sections.append(
                "Current scene transcript:\n"
                + "\n".join(f"- {item}" for item in self.scene_transcript),
            )
        if self.recent_turns:
            sections.append(
                "Recent turn summaries:\n" + "\n".join(f"- {item}" for item in self.recent_turns),
            )
        if self.active_npcs:
            sections.append(
                "Current NPCs:\n" + "\n".join(f"- {item}" for item in self.active_npcs),
            )
        if self.open_loops:
            sections.append("Open loops:\n" + "\n".join(f"- {item}" for item in self.open_loops))
        if self.revealed_facts:
            sections.append(
                "Revealed facts:\n" + "\n".join(f"- {item}" for item in self.revealed_facts),
            )
        if self.callback_candidates:
            sections.append(
                "Callback candidates:\n"
                + "\n".join(f"- {item}" for item in self.callback_candidates),
            )
        return "\n\n".join(sections)


class NarrativeMemoryContext(StrictModel):
    scene_summary: str = ""
    active_encounter_summary: str = ""
    scene_messages: list[ConversationMessage] = Field(default_factory=list)
    recent_turns: list[str] = Field(default_factory=list)
    campaign_chronicle: list[str] = Field(default_factory=list)
    open_loops: list[str] = Field(default_factory=list)
    relevant_memory: list[str] = Field(default_factory=list)
    revealed_facts: list[str] = Field(default_factory=list)
    callback_candidates: list[str] = Field(default_factory=list)

    def render(self) -> str:
        sections: list[str] = []
        if self.scene_summary:
            sections.append(
                f'<SCENE_SUMMARY REFERENCE_ONLY="true">\n{self.scene_summary}\n</SCENE_SUMMARY>',
            )
        if self.active_encounter_summary:
            sections.append(
                '<ACTIVE_ENCOUNTER_SUMMARY REFERENCE_ONLY="true">\n'
                f"{self.active_encounter_summary}\n"
                "</ACTIVE_ENCOUNTER_SUMMARY>",
            )
        if self.recent_turns:
            sections.append(
                '<OLDER_TIMELINE_SUMMARIES REFERENCE_ONLY="true">\n'
                + "\n".join(f"- {item}" for item in self.recent_turns)
                + "\n</OLDER_TIMELINE_SUMMARIES>",
            )
        if self.open_loops:
            sections.append(
                '<OPEN_LOOPS REFERENCE_ONLY="true">\n'
                + "\n".join(f"- {item}" for item in self.open_loops)
                + "\n</OPEN_LOOPS>",
            )
        if self.relevant_memory:
            sections.append(
                '<RELEVANT_WORLD_MEMORY REFERENCE_ONLY="true">\n'
                + "\n".join(f"- {item}" for item in self.relevant_memory)
                + "\n</RELEVANT_WORLD_MEMORY>",
            )
        if self.revealed_facts:
            sections.append(
                '<REVEALED_FACTS REFERENCE_ONLY="true">\n'
                + "\n".join(f"- {item}" for item in self.revealed_facts)
                + "\n</REVEALED_FACTS>",
            )
        if self.callback_candidates:
            sections.append(
                '<CALLBACK_CANDIDATES REFERENCE_ONLY="true">\n'
                + "\n".join(f"- {item}" for item in self.callback_candidates)
                + "\n</CALLBACK_CANDIDATES>",
            )
        if self.campaign_chronicle:
            sections.append(
                '<EARLIER_SCENE_CHRONICLE REFERENCE_ONLY="true">\n'
                + "\n".join(f"- {item}" for item in self.campaign_chronicle)
                + "\n</EARLIER_SCENE_CHRONICLE>",
            )
        return "\n\n".join(sections)
