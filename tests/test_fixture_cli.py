from __future__ import annotations

import json
from pathlib import Path

import pytest

from dungeon_master.fixture_cli import main, seed_fixture_library
from dungeon_master.models import CampaignEndReason, CampaignStatus, NPCPlayerLabelKind
from dungeon_master.save_library import SaveLibrary
from dungeon_master.state_store import StateStore


def test_seed_fixture_library_creates_isolated_save_library(tmp_path: Path) -> None:
    state_path = tmp_path / "fixtures" / "game_state.json"

    report = seed_fixture_library(state_path)

    library = SaveLibrary(state_path)
    active_save_id, summaries = library.bootstrap_payload()

    assert active_save_id == report.active_save_id
    assert len(summaries) == 2
    assert {summary.character_name for summary in summaries} == {
        "Fixture Bellringer",
        "Fixture Archive",
    }

    continuity_summary = next(
        summary for summary in summaries if summary.character_name == "Fixture Bellringer"
    )
    continuity_state = StateStore(library.state_path_for(continuity_summary.save_id)).load()
    assert continuity_state.campaign_status == CampaignStatus.ACTIVE
    assert continuity_state.npc_roster_version == 2
    assert continuity_state.hidden_npcs
    assert continuity_state.oracle_history[-1].referenced_thread_ids
    assert continuity_state.oracle_history[-1].referenced_npc_ids
    assert any(
        npc.player_label_kind == NPCPlayerLabelKind.DESCRIPTOR for npc in continuity_state.npcs
    )

    archive_summary = next(
        summary for summary in summaries if summary.character_name == "Fixture Archive"
    )
    archive_state = StateStore(library.state_path_for(archive_summary.save_id)).load()
    assert archive_state.campaign_status == CampaignStatus.ENDED
    assert archive_state.campaign_end_reason == CampaignEndReason.RETIREMENT


def test_seed_fixture_library_requires_force_to_replace_existing_root(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "fixtures" / "game_state.json"
    seed_fixture_library(state_path)

    with pytest.raises(ValueError, match="Fixture root already exists"):
        seed_fixture_library(state_path)


def test_seed_fixture_library_force_replaces_existing_root(tmp_path: Path) -> None:
    state_path = tmp_path / "fixtures" / "game_state.json"
    seed_fixture_library(state_path)
    stale_file = state_path.parent / "stale.txt"
    stale_file.write_text("old", encoding="utf-8")

    report = seed_fixture_library(state_path, force=True)

    assert report.root_state_path == state_path
    assert not stale_file.exists()


def test_fixture_cli_emits_json_report(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state_path = tmp_path / "fixtures" / "game_state.json"

    main(["--state-path", str(state_path), "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert payload["root_state_path"] == str(state_path)
    assert len(payload["save_ids"]) == 2
    assert payload["save_names"] == ["Fixture Bellringer", "Fixture Archive"]
