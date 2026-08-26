from __future__ import annotations

from dungeon_master.memory.contracts import (
    ConversationMessage,
    MemoryState,
    SceneMemory,
    TurnMemory,
)
from dungeon_master.models import OracleKind, SceneStatus

TIMELINE_SUMMARY_BLOCK_TURNS = 5


def clip(text: str, limit: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return f"{compact[: limit - 3].rstrip()}..."


class MemoryRendering:
    def _scene_transcript_messages(
        self,
        turns: list[TurnMemory],
    ) -> list[ConversationMessage]:
        messages: list[ConversationMessage] = []
        for turn in turns:
            player_text = turn.player_input.strip()
            if player_text:
                messages.append(ConversationMessage(role="user", content=player_text))
            assistant_parts: list[str] = []
            if turn.narrative_excerpt.strip():
                assistant_parts.append(turn.narrative_excerpt.strip())
            if assistant_parts:
                messages.append(
                    ConversationMessage(
                        role="assistant",
                        content="\n\n".join(part for part in assistant_parts if part),
                    ),
                )
        return messages

    def _campaign_chronicle_lines(self, memory: MemoryState) -> list[str]:
        lines = [
            self._render_scene_chronicle(scene)
            for scene in memory.scene_summaries
            if scene.scene_key != memory.current_scene_key
        ]
        return lines[-3:]

    def _render_scene_chronicle(self, scene: SceneMemory) -> str:
        return clip(f"Scene {scene.scene_number}: {scene.summary}", 320)

    def _scene_compaction(
        self,
        *,
        scene_label: str,
        scene_status: SceneStatus,
        developments: list[str],
    ) -> str:
        if not developments:
            return f"The scene remained focused on {scene_label} ({scene_status.value})."
        first = developments[0]
        latest = developments[-1]
        if first == latest:
            return clip(
                f"The scene centered on {scene_label} ({scene_status.value}). {latest}",
                420,
            )
        return clip(
            (
                f"The scene centered on {scene_label} ({scene_status.value}). "
                f"It opened with {first} The latest development was {latest}"
            ),
            420,
        )

    def _render_turn(self, turn: TurnMemory) -> str:
        return clip(f"Turn {turn.turn_index}: {turn.player_input} -> {turn.oracle_summary}", 180)

    def _render_npc_update_scene_turn(self, turn: TurnMemory) -> str:
        parts = [f"Turn {turn.turn_index}: {turn.player_input} -> {turn.oracle_summary}"]
        if turn.narrative_excerpt.strip():
            parts.append(f"Narration: {turn.narrative_excerpt.strip()}")
        return clip(" | ".join(parts), 900)

    def _narrative_timeline_lines(self, turns: list[TurnMemory]) -> list[str]:
        if not turns:
            return []
        lines = [
            self._render_narrative_timeline_block(
                turns[index : index + TIMELINE_SUMMARY_BLOCK_TURNS],
            )
            for index in range(0, len(turns), TIMELINE_SUMMARY_BLOCK_TURNS)
        ]
        return [line for line in lines if line]

    def _render_narrative_timeline_block(self, turns: list[TurnMemory]) -> str:
        if not turns:
            return ""
        if len(turns) == 1:
            turn = turns[0]
            return clip(
                (
                    f"Turn {turn.turn_index}: {turn.player_input} -> "
                    f"{self._timeline_oracle_summary(turn)}"
                ),
                320,
            )
        first = turns[0]
        latest = turns[-1]
        return clip(
            (
                f"Turns {first.turn_index}-{latest.turn_index}: "
                f"{first.player_input} -> {self._timeline_oracle_summary(first)}. "
                f"Latest: {latest.player_input} -> "
                f"{self._timeline_oracle_summary(latest)}."
            ),
            320,
        )

    def _timeline_oracle_summary(self, turn: TurnMemory) -> str:
        summary = turn.oracle_summary.strip()
        if turn.oracle_kind != OracleKind.SCENE_CHECK:
            return summary
        lowered = summary.lower()
        for prefix in ("expected: ", "altered: ", "interrupted before: "):
            if lowered.startswith(prefix):
                return f"Scene check resolved: {summary[len(prefix):]}"
        return f"Scene check resolved: {summary}"

