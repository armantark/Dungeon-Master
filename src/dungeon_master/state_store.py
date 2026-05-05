from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from dungeon_master.memory import MemoryState
from dungeon_master.models import GameEvent, GameState, StrictModel


class TurnCheckpointRecord(StrictModel):
    turn_id: str
    oracle_outcome_id: str
    player_input: str
    execution_context: str | None = None
    state: GameState


class StateStore:
    def __init__(self, state_path: Path) -> None:
        self.state_path = state_path
        self.data_dir = state_path.parent
        self.events_path = self.data_dir / "events.jsonl"
        self.memory_path = self.data_dir / "memory.json"
        self.checkpoints_dir = self.data_dir / "checkpoints"
        self.turn_checkpoints_dir = self.data_dir / "turn-checkpoints"

    def exists(self) -> bool:
        return self.state_path.exists()

    def load(self) -> GameState:
        return GameState.model_validate_json(self.state_path.read_text(encoding="utf-8"))

    def load_or_create(self, create_state: Callable[[], GameState]) -> GameState:
        if not self.state_path.exists():
            state = create_state()
            self.save(state, create_checkpoint=True)
            return state

        return self.load()

    def save(self, state: GameState, *, create_checkpoint: bool) -> None:
        state.touch()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        payload = state.model_dump_json(indent=2)
        temp_path = self.state_path.with_suffix(f"{self.state_path.suffix}.tmp")
        temp_path.write_text(payload, encoding="utf-8")
        temp_path.replace(self.state_path)

        if create_checkpoint:
            self.write_checkpoint(state)

    def write_checkpoint(self, state: GameState) -> Path:
        self.checkpoints_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        checkpoint_path = self.checkpoints_dir / f"{stamp}.json"
        temp_path = checkpoint_path.with_suffix(f"{checkpoint_path.suffix}.tmp")
        temp_path.write_text(state.model_dump_json(indent=2), encoding="utf-8")
        temp_path.replace(checkpoint_path)
        return checkpoint_path

    def append_event(self, event: GameEvent) -> None:
        self.append_events([event])

    def append_events(self, events: list[GameEvent]) -> None:
        if not events:
            return
        self.data_dir.mkdir(parents=True, exist_ok=True)
        existing = ""
        if self.events_path.exists():
            existing = self.events_path.read_text(encoding="utf-8")
        payload = existing + "".join(f"{event.model_dump_json()}\n" for event in events)
        temp_path = self.events_path.with_suffix(f"{self.events_path.suffix}.tmp")
        temp_path.write_text(payload, encoding="utf-8")
        temp_path.replace(self.events_path)

    def load_memory(self) -> MemoryState:
        return MemoryState.model_validate_json(self.memory_path.read_text(encoding="utf-8"))

    def load_memory_or_none(self) -> MemoryState | None:
        if not self.memory_path.exists():
            return None
        return self.load_memory()

    def save_memory(self, memory: MemoryState) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        payload = memory.model_dump_json(indent=2)
        temp_path = self.memory_path.with_suffix(f"{self.memory_path.suffix}.tmp")
        temp_path.write_text(payload, encoding="utf-8")
        temp_path.replace(self.memory_path)

    def write_turn_checkpoint(
        self,
        *,
        turn_id: str,
        oracle_outcome_id: str,
        player_input: str,
        execution_context: str | None = None,
        state: GameState,
    ) -> Path:
        self.turn_checkpoints_dir.mkdir(parents=True, exist_ok=True)
        record = TurnCheckpointRecord(
            turn_id=turn_id,
            oracle_outcome_id=oracle_outcome_id,
            player_input=player_input,
            execution_context=execution_context,
            state=state,
        )
        path = self.turn_checkpoints_dir / f"{turn_id}.json"
        temp_path = path.with_suffix(f"{path.suffix}.tmp")
        temp_path.write_text(record.model_dump_json(indent=2), encoding="utf-8")
        temp_path.replace(path)
        return path

    def load_turn_checkpoint(self, turn_id: str) -> TurnCheckpointRecord:
        path = self.turn_checkpoints_dir / f"{turn_id}.json"
        return TurnCheckpointRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def load_turn_checkpoint_or_none(self, turn_id: str) -> TurnCheckpointRecord | None:
        path = self.turn_checkpoints_dir / f"{turn_id}.json"
        if not path.exists():
            return None
        return TurnCheckpointRecord.model_validate_json(path.read_text(encoding="utf-8"))
