from pathlib import Path

from dungeon_master.memory import MemoryState
from dungeon_master.models import EventType, GameEvent
from dungeon_master.state_store import StateStore
from tests.factories import sample_state


def test_state_store_creates_default_state_and_checkpoint(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")

    state = store.load_or_create(sample_state)

    assert state.chaos_factor == 5
    assert len(state.threads) == 3
    assert store.state_path.exists()
    assert store.checkpoints_dir.exists()
    assert len(list(store.checkpoints_dir.glob("*.json"))) == 1


def test_state_store_round_trips_state(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")
    state = store.load_or_create(sample_state)
    state.chaos_factor = 9

    store.save(state, create_checkpoint=True)
    loaded = store.load_or_create(sample_state)

    assert loaded.chaos_factor == 9
    assert len(list(store.checkpoints_dir.glob("*.json"))) == 2


def test_state_store_appends_jsonl_events(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")
    event = GameEvent(event_type=EventType.SYSTEM, title="Test", content="Event persisted.")

    store.append_event(event)

    assert store.events_path.read_text(encoding="utf-8").count("\n") == 1


def test_state_store_round_trips_memory_sidecar(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")
    memory = MemoryState(turn_count=2, current_scene_key="Abbey yard")

    store.save_memory(memory)
    loaded = store.load_memory()

    assert loaded.turn_count == 2
    assert loaded.current_scene_key == "Abbey yard"


def test_turn_checkpoint_round_trips_execution_context(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")
    state = sample_state()

    store.write_turn_checkpoint(
        turn_id="oracle_1",
        oracle_outcome_id="oracle_1",
        player_input="I draw the knife.",
        execution_context="Executed backend steps:\n- Equipment updated.",
        state=state,
    )
    loaded = store.load_turn_checkpoint("oracle_1")

    assert loaded.player_input == "I draw the knife."
    assert loaded.execution_context == "Executed backend steps:\n- Equipment updated."
