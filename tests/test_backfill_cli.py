from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from dungeon_master.backfill_cli import main
from dungeon_master.models import (
    NPC,
    CairnCharacterState,
    CairnItemState,
    CairnMechanicsSource,
)
from dungeon_master.save_library import SaveLibrary
from dungeon_master.service import GameService
from dungeon_master.state_store import StateStore
from tests.factories import sample_state
from tests.test_service import FakeCairnEngine, FakeNpcUpdater

if TYPE_CHECKING:
    import pytest


def test_backfill_current_save_apply_persists_state_memory_and_checkpoint(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "game_state.json")
    state = sample_state()
    state.npc_roster_version = 1
    store.save(state, create_checkpoint=False)

    service = GameService(
        store=store,
        cairn_engine=FakeCairnEngine(),
        npc_updater=FakeNpcUpdater(),
    )

    report = service.backfill_current_save(apply=True)

    persisted = store.load()
    assert report.applied is True
    assert report.state_changed is True
    assert report.character_backfilled is True
    assert report.npc_roster_repaired is True
    assert report.terminal_state_synced is False
    assert report.memory_rebuilt is True
    assert report.checkpoint_written is True
    assert persisted.character.cairn.source == CairnMechanicsSource.NARRATIVE_BACKFILL
    assert persisted.npc_roster_version == 2
    assert store.memory_path.exists()
    assert len(list(store.checkpoints_dir.glob("*.json"))) == 1


def test_backfill_current_save_dry_run_does_not_persist_changes(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")
    state = sample_state()
    state.npc_roster_version = 1
    store.save(state, create_checkpoint=False)

    service = GameService(
        store=store,
        cairn_engine=FakeCairnEngine(),
        npc_updater=FakeNpcUpdater(),
    )

    report = service.backfill_current_save(apply=False)

    persisted = store.load()
    assert report.applied is False
    assert report.state_changed is True
    assert report.character_backfilled is True
    assert report.npc_roster_repaired is True
    assert persisted.character.cairn.source == CairnMechanicsSource.UNSET
    assert persisted.npc_roster_version == 1
    assert not store.memory_path.exists()
    assert not store.checkpoints_dir.exists()


def test_backfill_current_save_reports_visible_name_without_text_support(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "game_state.json")
    state = sample_state()
    state.npc_roster_version = 2
    state.current_scene = "A nameless figure watches from the belfry."
    state.npcs = [NPC(name="Theuas", role="Watcher", disposition="unknown")]
    state.hidden_npcs = []
    state.character.cairn = CairnCharacterState(source=CairnMechanicsSource.EXPLICIT)
    for item in state.character.inventory:
        item.cairn = CairnItemState(source=CairnMechanicsSource.EXPLICIT)
    store.save(state, create_checkpoint=False)

    service = GameService(store=store)

    report = service.backfill_current_save(apply=False)

    assert report.state_changed is False
    assert report.visible_name_warnings == (
        "Visible NPC label lacks explicit text support: Theuas",
    )


def test_backfill_cli_targets_active_save_and_emits_json_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root_state_path = tmp_path / "game_state.json"
    library = SaveLibrary(root_state_path)
    state = sample_state()
    state.npc_roster_version = 2
    state.character.cairn = CairnCharacterState(source=CairnMechanicsSource.EXPLICIT)
    for item in state.character.inventory:
        item.cairn = CairnItemState(source=CairnMechanicsSource.EXPLICIT)
    save_id = library.create_save(create_state=state, select=True)

    monkeypatch.setenv("DUNGEON_MASTER_STATE_PATH", str(root_state_path))

    main(["--apply", "--json"])

    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["save_id"] == save_id
    assert payload["applied"] is True
    assert payload["state_changed"] is False
    assert payload["memory_rebuilt"] is True
    assert payload["state_path"].endswith(f"{save_id}/game_state.json")
    assert (library.save_dir_for(save_id) / "memory.json").exists()
