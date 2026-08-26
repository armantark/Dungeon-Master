from __future__ import annotations

from dungeon_master.domain.models import GameState, NPCStatus, OracleOutcome, ThreadStatus
from dungeon_master.memory.contracts import (
    MemoryState,
    NarrativeMemoryContext,
    NPCUpdateMemoryContext,
    PlannerMemoryContext,
    ThreadUpdateMemoryContext,
)
from dungeon_master.memory.projection import (
    MemoryProjection,
    _dedupe_strings,
    _npc_memory_label,
    _scene_key,
)


class MemoryRetrieval(MemoryProjection):
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
            scene_messages=self._scene_transcript_messages(memory.current_scene_turns),
            campaign_chronicle=self._campaign_chronicle_lines(memory),
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
        query = player_input.lower()
        completed_scene_turns = memory.current_scene_turns
        if completed_scene_turns and not completed_scene_turns[-1].narrative_excerpt.strip():
            completed_scene_turns = completed_scene_turns[:-1]
        transcript_turns = completed_scene_turns
        recent_turns = (
            []
            if completed_scene_turns
            else self._narrative_timeline_lines(memory.recent_turn_summaries[-3:])
        )
        return NarrativeMemoryContext(
            scene_summary=memory.current_scene_summary,
            active_encounter_summary=memory.active_encounter_summary,
            scene_messages=self._scene_transcript_messages(transcript_turns),
            recent_turns=recent_turns,
            campaign_chronicle=self._campaign_chronicle_lines(memory),
            open_loops=[loop.text for loop in memory.open_loops[:4]],
            relevant_memory=self._narrative_memory_lines(state, memory, outcome, query),
            revealed_facts=self._narrative_facts(memory, outcome, query),
            callback_candidates=self._narrative_callbacks(memory, outcome),
        )

    def retrieve_for_thread_updater(
        self,
        state: GameState,
        memory: MemoryState,
        player_input: str,
        outcome: OracleOutcome,
    ) -> ThreadUpdateMemoryContext:
        del state
        query = player_input.lower()
        direct_thread_ids = self._thread_ids_for_outcome(outcome)
        direct_threads = [
            thread for thread in memory.thread_memory if thread.thread_id in direct_thread_ids
        ]
        matched_threads = [
            thread
            for thread in memory.thread_memory
            if (
                thread.status == ThreadStatus.ACTIVE
                and thread.thread_id not in direct_thread_ids
                and self._query_matches_label(query, thread.title)
            )
        ]
        fallback_threads = [
            thread
            for thread in memory.thread_memory
            if (
                thread.status == ThreadStatus.ACTIVE
                and thread.thread_id not in direct_thread_ids
                and thread not in matched_threads
            )
        ]
        active_threads = [
            f"{thread.title} ({thread.status.value}): {thread.summary}"
            for thread in [*direct_threads[:2], *matched_threads[:2], *fallback_threads[:2]]
        ]
        return ThreadUpdateMemoryContext(
            scene_summary=memory.current_scene_summary,
            recent_turns=[self._render_turn(turn) for turn in memory.recent_turn_summaries[-2:]],
            active_threads=active_threads[:4],
            open_loops=[loop.text for loop in memory.open_loops[:4]],
            revealed_facts=self._narrative_facts(memory, outcome, query)[:4],
            callback_candidates=self._narrative_callbacks(memory, outcome)[:3],
        )

    def retrieve_for_npc_updater(
        self,
        state: GameState,
        memory: MemoryState,
        player_input: str,
        outcome: OracleOutcome,
    ) -> NPCUpdateMemoryContext:
        del state
        query = player_input.lower()
        direct_npc_ids = self._npc_ids_for_outcome(outcome)
        direct_npcs = [npc for npc in memory.npc_memory if npc.npc_id in direct_npc_ids]
        matched_npcs = [
            npc
            for npc in memory.npc_memory
            if (
                npc.status == NPCStatus.ACTIVE
                and npc.npc_id not in direct_npc_ids
                and self._query_matches_label(query, npc.name)
            )
        ]
        fallback_npcs = [
            npc
            for npc in memory.npc_memory
            if (
                npc.status == NPCStatus.ACTIVE
                and npc.npc_id not in direct_npc_ids
                and npc not in matched_npcs
            )
        ]
        active_npcs = [
            f"{_npc_memory_label(npc)} ({npc.status.value})"
            + (
                f" - {npc.role}; {npc.disposition}: {npc.summary}"
                if npc.role or npc.disposition
                else f": {npc.summary}"
            )
            for npc in [*direct_npcs[:2], *matched_npcs[:2], *fallback_npcs[:2]]
        ]
        return NPCUpdateMemoryContext(
            scene_summary=memory.current_scene_summary,
            scene_transcript=[
                self._render_npc_update_scene_turn(turn)
                for turn in memory.current_scene_turns
                if turn.narrative_excerpt.strip()
            ],
            recent_turns=[
                self._render_turn(turn)
                for turn in memory.recent_turn_summaries[-4:]
                if turn.scene_key != memory.current_scene_key
            ],
            active_npcs=active_npcs[:4],
            open_loops=[loop.text for loop in memory.open_loops[:4]],
            revealed_facts=self._narrative_facts(memory, outcome, query)[:4],
            callback_candidates=self._narrative_callbacks(memory, outcome)[:3],
        )

    def _planner_memory_lines(
        self,
        state: GameState,
        memory: MemoryState,
        query: str,
    ) -> list[str]:
        lines: list[str] = []
        current_scene_key = _scene_key(state.scene_number)
        location = next(
            (item for item in memory.location_memory if item.location_key == current_scene_key),
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
            if (
                npc.status == NPCStatus.ACTIVE
                and npc.last_touched_turn > 0
                and self._query_matches_label(query, npc.name)
            )
        ]
        fallback_npcs = [
            npc
            for npc in memory.npc_memory
            if (
                npc.status == NPCStatus.ACTIVE
                and npc.last_touched_turn > 0
                and npc not in matched_npcs
            )
        ]
        lines.extend(
            f"NPC - {_npc_memory_label(npc)}: {npc.summary}"
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
        query: str,
    ) -> list[str]:
        lines: list[str] = []
        direct_thread_ids = self._thread_ids_for_outcome(outcome)
        current_scene_key = _scene_key(state.scene_number)
        location = next(
            (item for item in memory.location_memory if item.location_key == current_scene_key),
            None,
        )
        if location is not None:
            lines.append(f"Location - {location.label}: {location.summary}")
        for thread_id in direct_thread_ids:
            thread = next(
                (item for item in memory.thread_memory if item.thread_id == thread_id),
                None,
            )
            if thread is not None:
                lines.append(f"Thread - {thread.title}: {thread.summary}")
        matched_threads = [
            thread
            for thread in memory.thread_memory
            if (
                thread.status == ThreadStatus.ACTIVE
                and thread.thread_id not in direct_thread_ids
                and self._query_matches_label(query, thread.title)
            )
        ]
        fallback_threads = sorted(
            [
                thread
                for thread in memory.thread_memory
                if (
                    thread.status == ThreadStatus.ACTIVE
                    and thread.thread_id not in direct_thread_ids
                    and thread not in matched_threads
                )
            ],
            key=lambda thread: thread.last_touched_turn,
            reverse=True,
        )
        lines.extend(
            f"Thread - {thread.title}: {thread.summary}"
            for thread in [*matched_threads[:2], *fallback_threads[:2]]
        )
        direct_npc_ids = self._npc_ids_for_outcome(outcome)
        for npc_id in direct_npc_ids:
            npc = next(
                (item for item in memory.npc_memory if item.npc_id == npc_id),
                None,
            )
            if npc is not None:
                lines.append(f"NPC - {_npc_memory_label(npc)}: {npc.summary}")
        matched_npcs = [
            npc
            for npc in memory.npc_memory
            if (
                npc.status == NPCStatus.ACTIVE
                and npc.npc_id not in direct_npc_ids
                and (
                    self._query_matches_label(query, npc.name)
                    or self._query_matches_label(query, _npc_memory_label(npc))
                )
            )
        ]
        fallback_npcs = sorted(
            [
                npc
                for npc in memory.npc_memory
                if (
                    npc.status == NPCStatus.ACTIVE
                    and npc.last_touched_turn > 0
                    and npc.npc_id not in direct_npc_ids
                    and npc not in matched_npcs
                )
            ],
            key=lambda npc: npc.last_touched_turn,
            reverse=True,
        )
        lines.extend(
            f"NPC - {_npc_memory_label(npc)}: {npc.summary}"
            for npc in [*matched_npcs[:2], *fallback_npcs[:2]]
        )
        return lines[:6]

    def _narrative_facts(
        self,
        memory: MemoryState,
        outcome: OracleOutcome,
        query: str,
    ) -> list[str]:
        selected: list[str] = []
        direct_thread_ids = self._thread_ids_for_outcome(outcome)
        direct_npc_ids = self._npc_ids_for_outcome(outcome)
        if direct_thread_ids or direct_npc_ids:
            selected.extend(
                fact.text
                for fact in reversed(memory.revealed_facts)
                if (
                    any(thread_id in fact.related_thread_ids for thread_id in direct_thread_ids)
                    or any(npc_id in fact.related_npc_ids for npc_id in direct_npc_ids)
                )
            )
        selected.extend(
            fact.text
            for fact in reversed(memory.revealed_facts)
            if fact.scene_key == memory.current_scene_key
        )
        if query:
            selected.extend(
                fact.text
                for fact in reversed(memory.revealed_facts)
                if self._query_matches_label(query, fact.text)
            )
        return _dedupe_strings(selected)[:5]

    def _narrative_callbacks(self, memory: MemoryState, outcome: OracleOutcome) -> list[str]:
        direct_thread_ids = self._thread_ids_for_outcome(outcome)
        direct_npc_ids = self._npc_ids_for_outcome(outcome)
        direct = [
            f"{candidate.text} ({candidate.reason})"
            for candidate in memory.callback_candidates
            if (
                (
                    direct_thread_ids
                    and any(
                        thread_id in candidate.related_thread_ids for thread_id in direct_thread_ids
                    )
                )
                or (
                    direct_npc_ids
                    and any(npc_id in candidate.related_npc_ids for npc_id in direct_npc_ids)
                )
            )
        ]
        fallback = [
            f"{candidate.text} ({candidate.reason})" for candidate in memory.callback_candidates
        ]
        return _dedupe_strings(direct + fallback)[:4]

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
