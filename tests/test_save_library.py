from __future__ import annotations

from pathlib import Path

import pytest

from dungeon_master.memory import MemoryState
from dungeon_master.models import CampaignEndReason, CampaignStatus
from dungeon_master.save_library import SaveLibrary
from dungeon_master.state_store import StateStore
from tests.factories import sample_state


def test_save_library_bootstraps_empty_manifest_when_no_legacy_state(
    tmp_path: Path,
) -> None:
    library = SaveLibrary(tmp_path / "game_state.json")

    active_save_id, saves = library.bootstrap_payload()

    assert active_save_id is None
    assert saves == []
    assert library.manifest_path.exists()


def test_save_library_migrates_legacy_layout_into_first_slot(tmp_path: Path) -> None:
    legacy_store = StateStore(tmp_path / "game_state.json")
    state = sample_state()
    legacy_store.save(state, create_checkpoint=True)
    legacy_store.save_memory(MemoryState(turn_count=3, current_scene_key="Test scene"))
    legacy_store.write_turn_checkpoint(
        turn_id="oracle_1",
        oracle_outcome_id="oracle_1",
        player_input="I press on.",
        state=state,
    )

    library = SaveLibrary(tmp_path / "game_state.json")

    active_save_id, saves = library.bootstrap_payload()

    assert active_save_id is not None
    assert len(saves) == 1
    migrated_dir = library.save_dir_for(active_save_id)
    assert (migrated_dir / "game_state.json").exists()
    assert (migrated_dir / "memory.json").exists()
    assert (migrated_dir / "checkpoints").exists()
    assert (migrated_dir / "turn-checkpoints" / "oracle_1.json").exists()
    # Migration is copy-based for safety; the legacy files remain as a fallback.
    assert legacy_store.state_path.exists()


def test_save_library_create_save_can_select_new_slot(tmp_path: Path) -> None:
    library = SaveLibrary(tmp_path / "game_state.json")

    new_state = sample_state()
    new_state.campaign_status = CampaignStatus.CHARACTER_CREATION
    new_state.character.name = "Sahak"
    new_state.character.epithet = "Apostolic Penitent"
    save_id = library.create_save(create_state=new_state, select=True)
    active_save_id, saves = library.bootstrap_payload()

    assert active_save_id == save_id
    assert [save.save_id for save in saves] == [save_id]
    assert saves[0].character_name == "Sahak"
    assert saves[0].character_epithet == "Apostolic Penitent"
    assert saves[0].campaign_status == CampaignStatus.CHARACTER_CREATION


def test_save_library_ended_summary_uses_terminal_metadata(tmp_path: Path) -> None:
    library = SaveLibrary(tmp_path / "game_state.json")
    state = sample_state()
    state.campaign_status = CampaignStatus.ENDED
    state.campaign_end_reason = CampaignEndReason.VICTORY
    state.campaign_end_summary = "The crown lies broken in the ash."

    save_id = library.create_save(create_state=state, select=False)
    summaries = library.list_summaries()

    summary = next(item for item in summaries if item.save_id == save_id)
    assert summary.state_summary == "Ended by victory. The crown lies broken in the ash."


def test_save_library_select_active_rejects_unknown_save(tmp_path: Path) -> None:
    library = SaveLibrary(tmp_path / "game_state.json")
    library.ensure_initialized()

    with pytest.raises(ValueError, match="Unknown save"):
        library.select_active("save_missing")

