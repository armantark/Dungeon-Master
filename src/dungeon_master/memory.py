from __future__ import annotations

from datetime import datetime
from typing import Final

from pydantic import Field

from dungeon_master.models import (
    NPC,
    EventType,
    GameState,
    GameThread,
    OracleKind,
    OracleOutcome,
    SceneStatus,
    StrictModel,
    ThreadStatus,
    new_id,
    utc_now,
)

MAX_RECENT_TURNS: Final[int] = 8
MAX_RECENT_DEVELOPMENTS: Final[int] = 4
MAX_SCENE_SUMMARIES: Final[int] = 12
MAX_REVEALED_FACTS: Final[int] = 24
MAX_OPEN_LOOPS: Final[int] = 10
MAX_CALLBACKS: Final[int] = 8
SALIENT_CALLBACK_THRESHOLD: Final[int] = 4


class TurnMemory(StrictModel):
    turn_index: int = Field(ge=1)
    oracle_outcome_id: str = Field(min_length=1)
    scene_key: str = Field(min_length=1)
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
    role: str = ""
    disposition: str = ""
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
    state_id: str = ""
    updated_at: datetime = Field(default_factory=utc_now)
    turn_count: int = Field(default=0, ge=0)
    current_scene_key: str = ""
    active_location_key: str = ""
    current_scene_summary: str = "No compacted scene summary yet."
    active_encounter_summary: str = ""
    recent_turn_summaries: list[TurnMemory] = Field(default_factory=list)
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


class PlannerMemoryContext(StrictModel):
    scene_summary: str = ""
    active_encounter_summary: str = ""
    inventory_summary: str = ""
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


class NarrativeMemoryContext(StrictModel):
    scene_summary: str = ""
    active_encounter_summary: str = ""
    recent_turns: list[str] = Field(default_factory=list)
    open_loops: list[str] = Field(default_factory=list)
    relevant_memory: list[str] = Field(default_factory=list)
    revealed_facts: list[str] = Field(default_factory=list)
    callback_candidates: list[str] = Field(default_factory=list)

    def render(self) -> str:
        sections: list[str] = []
        if self.scene_summary:
            sections.append(f"Current scene summary: {self.scene_summary}")
        if self.active_encounter_summary:
            sections.append(f"Active encounter: {self.active_encounter_summary}")
        if self.recent_turns:
            sections.append(
                "Recent turn summaries:\n" + "\n".join(f"- {item}" for item in self.recent_turns),
            )
        if self.open_loops:
            sections.append("Open loops:\n" + "\n".join(f"- {item}" for item in self.open_loops))
        if self.relevant_memory:
            sections.append(
                "Relevant world memory:\n"
                + "\n".join(f"- {item}" for item in self.relevant_memory),
            )
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


class MemoryManager:
    def bootstrap_from_state(self, state: GameState) -> MemoryState:
        return self.bootstrap_from_turns(state, self._turns_from_state(state))

    def bootstrap_from_turns(
        self,
        state: GameState,
        turns: list[CommittedTurnMemory],
    ) -> MemoryState:
        memory = MemoryState()
        self._sync_canonical(memory, state)
        for turn in turns:
            self._apply_turn(memory, state, turn)
        self._refresh_derived(memory, state)
        return memory

    def sync_from_state(self, state: GameState, memory: MemoryState | None = None) -> MemoryState:
        working = memory.model_copy(deep=True) if memory is not None else MemoryState()
        self._sync_canonical(working, state)
        self._refresh_derived(working, state)
        return working

    def update_from_turn(
        self,
        state: GameState,
        turn: CommittedTurnMemory,
        memory: MemoryState | None = None,
    ) -> MemoryState:
        working = memory.model_copy(deep=True) if memory is not None else MemoryState()
        self._sync_canonical(working, state)
        self._apply_turn(working, state, turn)
        self._refresh_derived(working, state)
        return working

    def retrieve_for_planner(
        self,
        state: GameState,
        memory: MemoryState,
        player_input: str,
    ) -> PlannerMemoryContext:
        query = player_input.lower()
        return PlannerMemoryContext(
            scene_summary=memory.current_scene_summary,
            active_encounter_summary=memory.active_encounter_summary,
            inventory_summary=self._planner_inventory_summary(state, query),
            open_loops=[loop.text for loop in memory.open_loops[:3]],
            relevant_memory=self._planner_memory_lines(state, memory, query),
            revealed_facts=self._planner_facts(memory, query),
        )

    def retrieve_for_narrator(
        self,
        state: GameState,
        memory: MemoryState,
        player_input: str,
        outcome: OracleOutcome,
    ) -> NarrativeMemoryContext:
        del player_input
        recent_turns = [self._render_turn(turn) for turn in memory.recent_turn_summaries[-3:]]
        return NarrativeMemoryContext(
            scene_summary=memory.current_scene_summary,
            active_encounter_summary=memory.active_encounter_summary,
            recent_turns=recent_turns,
            open_loops=[loop.text for loop in memory.open_loops[:4]],
            relevant_memory=self._narrative_memory_lines(state, memory, outcome),
            revealed_facts=self._narrative_facts(memory, outcome),
            callback_candidates=self._narrative_callbacks(memory, outcome),
        )

    def _apply_turn(self, memory: MemoryState, state: GameState, turn: CommittedTurnMemory) -> None:
        turn_index = memory.turn_count + 1
        scene_key = state.current_scene
        thread_ids = (
            [turn.outcome.referenced_thread_id]
            if turn.outcome.referenced_thread_id is not None
            else []
        )
        npc_ids = (
            [turn.outcome.referenced_npc_id]
            if turn.outcome.referenced_npc_id is not None
            else []
        )
        turn_memory = TurnMemory(
            turn_index=turn_index,
            oracle_outcome_id=turn.outcome.id,
            scene_key=scene_key,
            scene_label=state.current_scene,
            scene_status=state.scene_status,
            player_input=turn.player_input,
            oracle_kind=turn.outcome.kind,
            oracle_summary=turn.outcome.summary,
            narrative_excerpt=_clip(turn.narrative_text, 220),
            execution_context=_clip(turn.execution_context, 220),
            related_thread_ids=thread_ids,
            related_npc_ids=npc_ids,
            related_location_keys=[scene_key],
            created_at=turn.outcome.created_at,
        )
        memory.turn_count = turn_index
        memory.recent_turn_summaries.append(turn_memory)
        memory.recent_turn_summaries = memory.recent_turn_summaries[-MAX_RECENT_TURNS:]
        self._update_scene_memory(memory, turn_memory)
        self._update_thread_memory(memory, state.threads, turn_memory)
        self._update_npc_memory(memory, state.npcs, turn_memory)
        self._update_location_memory(memory, turn_memory)
        self._update_facts(memory, turn_memory)

    def _refresh_derived(self, memory: MemoryState, state: GameState) -> None:
        memory.updated_at = utc_now()
        self._sync_canonical(memory, state)
        self._sync_thread_cards(memory, state.threads)
        self._sync_npc_cards(memory, state.npcs)
        self._sync_location_cards(memory, state)
        memory.current_scene_summary = self._current_scene_summary(memory, state)
        memory.open_loops = self._build_open_loops(memory, state)
        memory.callback_candidates = self._build_callbacks(memory, state)
        memory.revealed_facts = self._dedupe_facts(memory.revealed_facts)
        memory.scene_summaries = memory.scene_summaries[-MAX_SCENE_SUMMARIES:]

    def _sync_canonical(self, memory: MemoryState, state: GameState) -> None:
        memory.state_id = state.id
        memory.current_scene_key = state.current_scene
        memory.active_location_key = state.current_scene
        memory.active_encounter_summary = _encounter_summary(state)

    def _update_scene_memory(self, memory: MemoryState, turn: TurnMemory) -> None:
        scene = next(
            (item for item in memory.scene_summaries if item.scene_key == turn.scene_key),
            None,
        )
        development = self._render_turn(turn)
        if scene is None:
            memory.scene_summaries.append(
                SceneMemory(
                    scene_key=turn.scene_key,
                    scene_label=turn.scene_label,
                    summary=development,
                    status=turn.scene_status,
                    first_turn_index=turn.turn_index,
                    last_turn_index=turn.turn_index,
                    visit_count=1,
                    recent_developments=[development],
                ),
            )
            return
        scene.scene_label = turn.scene_label
        scene.status = turn.scene_status
        scene.last_turn_index = turn.turn_index
        scene.visit_count += 1
        scene.recent_developments.append(development)
        scene.recent_developments = scene.recent_developments[-MAX_RECENT_DEVELOPMENTS:]
        scene.summary = _clip(" ".join(scene.recent_developments[-2:]), 240)

    def _update_thread_memory(
        self,
        memory: MemoryState,
        threads: list[GameThread],
        turn: TurnMemory,
    ) -> None:
        by_id = {card.thread_id: card for card in memory.thread_memory}
        for thread in threads:
            card = by_id.get(thread.id)
            touched = thread.id in turn.related_thread_ids
            development = self._render_turn(turn) if touched else ""
            if card is None:
                memory.thread_memory.append(
                    ThreadMemory(
                        thread_id=thread.id,
                        title=thread.title,
                        status=thread.status,
                        stakes=thread.stakes,
                        summary=_thread_summary(thread, development),
                        last_touched_turn=turn.turn_index if touched else 0,
                        recent_developments=[development] if touched else [],
                    ),
                )
                continue
            card.title = thread.title
            card.status = thread.status
            card.stakes = thread.stakes
            if touched:
                card.last_touched_turn = turn.turn_index
                card.recent_developments.append(development)
                card.recent_developments = card.recent_developments[-MAX_RECENT_DEVELOPMENTS:]
            latest = card.recent_developments[-1] if card.recent_developments else ""
            card.summary = _thread_summary(thread, latest)
        memory.thread_memory = [
            card
            for card in memory.thread_memory
            if any(card.thread_id == thread.id for thread in threads)
        ]
        memory.thread_memory.sort(
            key=lambda card: (
                card.status != ThreadStatus.ACTIVE,
                -card.last_touched_turn,
                card.title,
            ),
        )

    def _update_npc_memory(self, memory: MemoryState, npcs: list[NPC], turn: TurnMemory) -> None:
        by_id = {card.npc_id: card for card in memory.npc_memory}
        for npc in npcs:
            card = by_id.get(npc.id)
            touched = npc.id in turn.related_npc_ids
            development = self._render_turn(turn) if touched else ""
            if card is None:
                memory.npc_memory.append(
                    NPCMemory(
                        npc_id=npc.id,
                        name=npc.name,
                        role=npc.role,
                        disposition=npc.disposition,
                        summary=_npc_summary(npc, development),
                        last_touched_turn=turn.turn_index if touched else 0,
                        recent_developments=[development] if touched else [],
                    ),
                )
                continue
            card.name = npc.name
            card.role = npc.role
            card.disposition = npc.disposition
            if touched:
                card.last_touched_turn = turn.turn_index
                card.recent_developments.append(development)
                card.recent_developments = card.recent_developments[-MAX_RECENT_DEVELOPMENTS:]
            latest = card.recent_developments[-1] if card.recent_developments else ""
            card.summary = _npc_summary(npc, latest)
        memory.npc_memory = [
            card
            for card in memory.npc_memory
            if any(card.npc_id == npc.id for npc in npcs)
        ]
        memory.npc_memory.sort(key=lambda card: (-card.last_touched_turn, card.name))

    def _update_location_memory(self, memory: MemoryState, turn: TurnMemory) -> None:
        card = next(
            (item for item in memory.location_memory if item.location_key == turn.scene_key),
            None,
        )
        development = self._render_turn(turn)
        if card is None:
            memory.location_memory.append(
                LocationMemory(
                    location_key=turn.scene_key,
                    label=turn.scene_label,
                    summary=development,
                    last_touched_turn=turn.turn_index,
                    recent_developments=[development],
                ),
            )
            return
        card.label = turn.scene_label
        card.last_touched_turn = turn.turn_index
        card.recent_developments.append(development)
        card.recent_developments = card.recent_developments[-MAX_RECENT_DEVELOPMENTS:]
        card.summary = _clip(" ".join(card.recent_developments[-2:]), 240)

    def _update_facts(self, memory: MemoryState, turn: TurnMemory) -> None:
        fact_texts = [turn.oracle_summary]
        if turn.execution_context:
            fact_texts.extend(
                line.strip().lstrip("- ").strip()
                for line in turn.execution_context.splitlines()
                if line.strip()
            )
        for text in fact_texts:
            compact = _clip(text, 220)
            if not compact:
                continue
            memory.revealed_facts.append(
                RevealedFact(
                    text=compact,
                    scene_key=turn.scene_key,
                    source_oracle_outcome_id=turn.oracle_outcome_id,
                    related_thread_ids=turn.related_thread_ids,
                    related_npc_ids=turn.related_npc_ids,
                    related_location_keys=turn.related_location_keys,
                    salience=_fact_salience(turn.oracle_kind),
                    last_touched_turn=turn.turn_index,
                ),
            )

    def _sync_thread_cards(self, memory: MemoryState, threads: list[GameThread]) -> None:
        current_ids = {thread.id for thread in threads}
        memory.thread_memory = [
            card for card in memory.thread_memory if card.thread_id in current_ids
        ]
        for thread in threads:
            if any(card.thread_id == thread.id for card in memory.thread_memory):
                continue
            memory.thread_memory.append(
                ThreadMemory(
                    thread_id=thread.id,
                    title=thread.title,
                    status=thread.status,
                    stakes=thread.stakes,
                    summary=_thread_summary(thread, ""),
                ),
            )

    def _sync_npc_cards(self, memory: MemoryState, npcs: list[NPC]) -> None:
        current_ids = {npc.id for npc in npcs}
        memory.npc_memory = [card for card in memory.npc_memory if card.npc_id in current_ids]
        for npc in npcs:
            if any(card.npc_id == npc.id for card in memory.npc_memory):
                continue
            memory.npc_memory.append(
                NPCMemory(
                    npc_id=npc.id,
                    name=npc.name,
                    role=npc.role,
                    disposition=npc.disposition,
                    summary=_npc_summary(npc, ""),
                ),
            )

    def _sync_location_cards(self, memory: MemoryState, state: GameState) -> None:
        if any(card.location_key == state.current_scene for card in memory.location_memory):
            return
        memory.location_memory.append(
            LocationMemory(
                location_key=state.current_scene,
                label=state.current_scene,
                summary=state.current_scene,
            ),
        )

    def _current_scene_summary(self, memory: MemoryState, state: GameState) -> str:
        scene = next(
            (item for item in memory.scene_summaries if item.scene_key == state.current_scene),
            None,
        )
        if scene is None:
            base = f"{state.current_scene} ({state.scene_status.value})."
            if memory.active_encounter_summary:
                return _clip(f"{base} {memory.active_encounter_summary}", 420)
            return base
        parts = [f"{scene.scene_label} ({scene.status.value}).", scene.summary]
        if memory.active_encounter_summary:
            parts.append(memory.active_encounter_summary)
        return _clip(" ".join(part for part in parts if part), 420)

    def _build_open_loops(self, memory: MemoryState, state: GameState) -> list[OpenLoop]:
        loops: list[OpenLoop] = []
        for thread in state.threads:
            if thread.status != ThreadStatus.ACTIVE:
                continue
            loops.append(
                OpenLoop(
                    text=_thread_summary(thread, ""),
                    priority=4 if thread.stakes else 3,
                    scene_key=state.current_scene,
                    related_thread_ids=[thread.id],
                    related_location_keys=[state.current_scene],
                    last_touched_turn=self._thread_last_touched(memory, thread.id),
                ),
            )
        if state.encounter.active and state.encounter.combatants:
            foes = ", ".join(combatant.name for combatant in state.encounter.combatants[:4])
            loops.append(
                OpenLoop(
                    text=f"Resolve the active encounter with {foes}.",
                    priority=5,
                    scene_key=state.current_scene,
                    related_location_keys=[state.current_scene],
                    last_touched_turn=memory.turn_count,
                ),
            )
        loops.sort(key=lambda loop: (-loop.priority, -loop.last_touched_turn, loop.text))
        return loops[:MAX_OPEN_LOOPS]

    def _build_callbacks(self, memory: MemoryState, state: GameState) -> list[CallbackCandidate]:
        del state
        candidates: list[CallbackCandidate] = []
        for thread in memory.thread_memory:
            if thread.status != ThreadStatus.ACTIVE:
                continue
            candidates.append(
                CallbackCandidate(
                    text=f"Return to thread: {thread.title}",
                    reason=thread.stakes or thread.summary,
                    priority=4,
                    last_touched_turn=thread.last_touched_turn,
                    related_thread_ids=[thread.thread_id],
                ),
            )
        for npc in memory.npc_memory:
            if npc.last_touched_turn <= 0:
                continue
            candidates.append(
                CallbackCandidate(
                    text=f"Bring back NPC: {npc.name}",
                    reason=npc.summary,
                    priority=3,
                    last_touched_turn=npc.last_touched_turn,
                    related_npc_ids=[npc.npc_id],
                ),
            )
        for fact in memory.revealed_facts:
            if fact.salience < SALIENT_CALLBACK_THRESHOLD:
                continue
            candidates.append(
                CallbackCandidate(
                    text=f"Echo revealed fact: {fact.text}",
                    reason="High-salience canon worth paying off later.",
                    priority=fact.salience,
                    last_touched_turn=fact.last_touched_turn,
                    related_thread_ids=fact.related_thread_ids,
                    related_npc_ids=fact.related_npc_ids,
                    related_location_keys=fact.related_location_keys,
                ),
            )
        candidates.sort(
            key=lambda candidate: (
                -candidate.priority,
                -candidate.last_touched_turn,
                candidate.text,
            ),
        )
        return candidates[:MAX_CALLBACKS]

    def _planner_memory_lines(
        self,
        state: GameState,
        memory: MemoryState,
        query: str,
    ) -> list[str]:
        lines: list[str] = []
        location = next(
            (item for item in memory.location_memory if item.location_key == state.current_scene),
            None,
        )
        if location is not None:
            lines.append(f"Location - {location.label}: {location.summary}")
        matched_threads = [
            thread
            for thread in memory.thread_memory
            if (
                thread.status == ThreadStatus.ACTIVE
                and self._query_matches_label(query, thread.title)
            )
        ]
        fallback_threads = [
            thread
            for thread in memory.thread_memory
            if thread.status == ThreadStatus.ACTIVE and thread not in matched_threads
        ]
        lines.extend(
            f"Thread - {thread.title}: {thread.summary}"
            for thread in [*matched_threads[:2], *fallback_threads[:2]]
        )
        matched_npcs = [
            npc
            for npc in memory.npc_memory
            if npc.last_touched_turn > 0 and self._query_matches_label(query, npc.name)
        ]
        fallback_npcs = [
            npc
            for npc in memory.npc_memory
            if npc.last_touched_turn > 0 and npc not in matched_npcs
        ]
        lines.extend(
            f"NPC - {npc.name}: {npc.summary}"
            for npc in [*matched_npcs[:2], *fallback_npcs[:1]]
        )
        return lines[:5]

    def _planner_facts(self, memory: MemoryState, query: str) -> list[str]:
        matched_facts = [
            fact.text
            for fact in reversed(memory.revealed_facts)
            if (
                fact.scene_key == memory.current_scene_key
                and self._query_matches_label(query, fact.text)
            )
        ]
        current_scene_facts = [
            fact.text
            for fact in reversed(memory.revealed_facts)
            if fact.scene_key == memory.current_scene_key
        ]
        return _dedupe_strings(matched_facts + current_scene_facts)[:3]

    def _narrative_memory_lines(
        self,
        state: GameState,
        memory: MemoryState,
        outcome: OracleOutcome,
    ) -> list[str]:
        lines: list[str] = []
        location = next(
            (item for item in memory.location_memory if item.location_key == state.current_scene),
            None,
        )
        if location is not None:
            lines.append(f"Location - {location.label}: {location.summary}")
        if outcome.referenced_thread_id is not None:
            thread = next(
                (
                    item
                    for item in memory.thread_memory
                    if item.thread_id == outcome.referenced_thread_id
                ),
                None,
            )
            if thread is not None:
                lines.append(f"Thread - {thread.title}: {thread.summary}")
        lines.extend(
            f"Thread - {thread.title}: {thread.summary}"
            for thread in memory.thread_memory
            if (
                thread.status == ThreadStatus.ACTIVE
                and thread.thread_id != outcome.referenced_thread_id
            )
        )
        if outcome.referenced_npc_id is not None:
            npc = next(
                (item for item in memory.npc_memory if item.npc_id == outcome.referenced_npc_id),
                None,
            )
            if npc is not None:
                lines.append(f"NPC - {npc.name}: {npc.summary}")
        lines.extend(
            f"NPC - {npc.name}: {npc.summary}"
            for npc in memory.npc_memory
            if npc.last_touched_turn > 0 and npc.npc_id != outcome.referenced_npc_id
        )
        return lines[:6]

    def _narrative_facts(self, memory: MemoryState, outcome: OracleOutcome) -> list[str]:
        selected: list[str] = []
        if outcome.referenced_thread_id is not None or outcome.referenced_npc_id is not None:
            selected.extend(
                fact.text
                for fact in reversed(memory.revealed_facts)
                if (
                    outcome.referenced_thread_id in fact.related_thread_ids
                    or outcome.referenced_npc_id in fact.related_npc_ids
                )
            )
        selected.extend(
            fact.text
            for fact in reversed(memory.revealed_facts)
            if fact.scene_key == memory.current_scene_key
        )
        return _dedupe_strings(selected)[:5]

    def _narrative_callbacks(self, memory: MemoryState, outcome: OracleOutcome) -> list[str]:
        direct = [
            f"{candidate.text} ({candidate.reason})"
            for candidate in memory.callback_candidates
            if (
                (
                    outcome.referenced_thread_id is not None
                    and outcome.referenced_thread_id in candidate.related_thread_ids
                )
                or (
                    outcome.referenced_npc_id is not None
                    and outcome.referenced_npc_id in candidate.related_npc_ids
                )
            )
        ]
        fallback = [
            f"{candidate.text} ({candidate.reason})" for candidate in memory.callback_candidates
        ]
        return _dedupe_strings(direct + fallback)[:4]

    def _dedupe_facts(self, facts: list[RevealedFact]) -> list[RevealedFact]:
        seen: dict[tuple[str, str], RevealedFact] = {}
        for fact in facts:
            key = (fact.scene_key, fact.text.strip().lower())
            existing = seen.get(key)
            if existing is None or fact.last_touched_turn >= existing.last_touched_turn:
                seen[key] = fact
        deduped = list(seen.values())
        deduped.sort(key=lambda fact: (-fact.salience, -fact.last_touched_turn, fact.text))
        return deduped[:MAX_REVEALED_FACTS]

    def _thread_last_touched(self, memory: MemoryState, thread_id: str) -> int:
        card = next((item for item in memory.thread_memory if item.thread_id == thread_id), None)
        return 0 if card is None else card.last_touched_turn

    def _turns_from_state(self, state: GameState) -> list[CommittedTurnMemory]:
        player_events = [
            event for event in state.action_log if event.event_type == EventType.PLAYER
        ]
        latest_narrative_by_outcome_id = {
            event.oracle_outcome_id: event
            for event in state.action_log
            if event.event_type == EventType.NARRATIVE and event.oracle_outcome_id is not None
        }
        turns: list[CommittedTurnMemory] = []
        for index, outcome in enumerate(state.oracle_history):
            player_input = (
                player_events[index].content
                if index < len(player_events)
                else outcome.summary
            )
            narrative = latest_narrative_by_outcome_id.get(outcome.id)
            turns.append(
                CommittedTurnMemory(
                    player_input=player_input,
                    outcome=outcome,
                    narrative_text="" if narrative is None else narrative.content,
                    execution_context="",
                ),
            )
        return turns

    def _render_turn(self, turn: TurnMemory) -> str:
        return _clip(f"Turn {turn.turn_index}: {turn.player_input} -> {turn.oracle_summary}", 180)

    def _planner_inventory_summary(self, state: GameState, query: str) -> str:
        items = state.character.inventory
        if not items:
            return "nothing"
        matched_items = [item.name for item in items if self._query_matches_label(query, item.name)]
        if matched_items:
            return ", ".join(matched_items[:4])
        equipped_items = [item.name for item in items if item.cairn.equipped]
        if equipped_items:
            carried = equipped_items + [
                item.name for item in items if item.name not in equipped_items
            ]
            return ", ".join(carried[:4])
        return ", ".join(item.name for item in items[:4])

    def _query_matches_label(self, query: str, label: str) -> bool:
        if not query:
            return False
        lowered = label.lower()
        return lowered in query


def _thread_summary(thread: GameThread, development: str) -> str:
    base = f"{thread.title}. Stakes: {thread.stakes or 'Unstated pressure.'}"
    if not development:
        return _clip(base, 240)
    return _clip(f"{base} Latest turn: {development}", 240)


def _npc_summary(npc: NPC, development: str) -> str:
    parts = [npc.name]
    if npc.role:
        parts.append(f"Role: {npc.role}.")
    if npc.disposition:
        parts.append(f"Disposition: {npc.disposition}.")
    if development:
        parts.append(f"Latest turn: {development}")
    return _clip(" ".join(parts), 240)


def _encounter_summary(state: GameState) -> str:
    if not state.encounter.active or not state.encounter.combatants:
        return ""
    living = [
        combatant.name
        for combatant in state.encounter.combatants
        if not combatant.defeated and not combatant.fled
    ]
    foes = ", ".join(living[:4]) if living else "no standing foes"
    return f"Combat is active in round {state.encounter.round_number} against {foes}."


def _fact_salience(kind: OracleKind) -> int:
    if kind in {
        OracleKind.RANDOM_EVENT,
        OracleKind.SCENE_CHECK,
        OracleKind.ATTACK,
        OracleKind.HARM,
    }:
        return 5
    if kind in {OracleKind.YES_NO, OracleKind.SAVE, OracleKind.RECOVERY}:
        return 4
    return 3


def _clip(text: str, limit: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return f"{compact[: limit - 3].rstrip()}..."


def _dedupe_strings(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return deduped
