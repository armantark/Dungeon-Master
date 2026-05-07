from __future__ import annotations

import shutil
from pathlib import Path

from pydantic import Field

from dungeon_master.models import (
    CampaignEndReason,
    CampaignStatus,
    GameState,
    StrictModel,
    new_id,
    utc_now,
)
from dungeon_master.state_store import StateStore


class SaveRecord(StrictModel):
    save_id: str
    created_at: str


class SaveLibraryManifest(StrictModel):
    active_save_id: str | None = None
    saves: list[SaveRecord] = Field(default_factory=list)


class SaveSummary(StrictModel):
    save_id: str
    state_id: str
    character_name: str
    character_epithet: str
    identifying_line: str
    state_summary: str
    campaign_status: CampaignStatus
    campaign_end_reason: CampaignEndReason | None = None
    updated_at: str
    created_at: str


class SaveLibrary:
    """Manage a local library of save slots rooted under one data directory.

    The key design choice is to keep the *per-save* on-disk layout identical to
    the current single-save layout:

    - `game_state.json`
    - `events.jsonl`
    - `memory.json`
    - `checkpoints/`
    - `turn-checkpoints/`

    F-12 only adds a small manifest (`library.json`) plus a `saves/<save_id>/`
    directory fan-out. That means `StateStore` can stay oblivious to the save
    library and keep treating one save as "whatever directory contains the
    current `game_state.json`."
    """

    def __init__(self, legacy_state_path: Path) -> None:
        self.legacy_state_path = legacy_state_path
        self.root_dir = legacy_state_path.parent
        self.manifest_path = self.root_dir / "library.json"
        self.saves_dir = self.root_dir / "saves"

    def ensure_initialized(self) -> SaveLibraryManifest:
        if self.manifest_path.exists():
            return self.load_manifest()

        if self.legacy_state_path.exists():
            return self._migrate_legacy_layout()

        manifest = SaveLibraryManifest()
        self.save_manifest(manifest)
        return manifest

    def load_manifest(self) -> SaveLibraryManifest:
        return SaveLibraryManifest.model_validate_json(
            self.manifest_path.read_text(encoding="utf-8")
        )

    def save_manifest(self, manifest: SaveLibraryManifest) -> None:
        self.root_dir.mkdir(parents=True, exist_ok=True)
        payload = manifest.model_dump_json(indent=2)
        temp_path = self.manifest_path.with_suffix(f"{self.manifest_path.suffix}.tmp")
        temp_path.write_text(payload, encoding="utf-8")
        temp_path.replace(self.manifest_path)

    def active_save_id(self) -> str | None:
        manifest = self.ensure_initialized()
        if manifest.active_save_id is None:
            return None
        if not self.state_path_for(manifest.active_save_id).exists():
            manifest.active_save_id = None
            self.save_manifest(manifest)
            return None
        return manifest.active_save_id

    def active_state_path(self) -> Path | None:
        active = self.active_save_id()
        if active is None:
            return None
        return self.state_path_for(active)

    def state_path_for(self, save_id: str) -> Path:
        return self.save_dir_for(save_id) / "game_state.json"

    def save_dir_for(self, save_id: str) -> Path:
        return self.saves_dir / save_id

    def create_save(
        self,
        *,
        create_state: GameState,
        select: bool,
    ) -> str:
        manifest = self.ensure_initialized()
        save_id = new_id("save")
        store = StateStore(self.state_path_for(save_id))
        # `StateStore.save(..., create_checkpoint=True)` preserves the current
        # invariant that a brand-new save has a canonical state blob and an
        # initial checkpoint immediately, matching what the legacy one-file
        # bootstrap path did through `load_or_create(...)`.
        store.save(create_state, create_checkpoint=True)

        manifest.saves.append(
            SaveRecord(save_id=save_id, created_at=utc_now().isoformat())
        )
        if select:
            manifest.active_save_id = save_id
        self.save_manifest(manifest)
        return save_id

    def select_active(self, save_id: str) -> None:
        manifest = self.ensure_initialized()
        if not any(record.save_id == save_id for record in manifest.saves):
            message = f"Unknown save: {save_id}"
            raise ValueError(message)
        if not self.state_path_for(save_id).exists():
            message = f"Save is missing its state file: {save_id}"
            raise ValueError(message)
        manifest.active_save_id = save_id
        self.save_manifest(manifest)

    def list_summaries(self) -> list[SaveSummary]:
        manifest = self.ensure_initialized()
        summaries: list[SaveSummary] = []
        for record in manifest.saves:
            state_path = self.state_path_for(record.save_id)
            if not state_path.exists():
                continue
            state = StateStore(state_path).load()
            summaries.append(
                SaveSummary(
                    save_id=record.save_id,
                    state_id=state.id,
                    character_name=_character_name(state),
                    character_epithet=state.character.epithet.strip(),
                    identifying_line=_identifying_line(state),
                    state_summary=_state_summary(state),
                    campaign_status=state.campaign_status,
                    campaign_end_reason=state.campaign_end_reason,
                    updated_at=state.updated_at.isoformat(),
                    created_at=record.created_at,
                )
            )

        active = manifest.active_save_id
        summaries.sort(
            key=lambda summary: (
                0 if summary.save_id == active else 1,
                summary.updated_at,
            ),
            reverse=False,
        )
        # Preserve the active save first, then most-recently-updated after it.
        if len(summaries) > 1:
            active_summaries = [summary for summary in summaries if summary.save_id == active]
            other_summaries = [summary for summary in summaries if summary.save_id != active]
            other_summaries.sort(key=lambda summary: summary.updated_at, reverse=True)
            return active_summaries + other_summaries
        return summaries

    def bootstrap_payload(self) -> tuple[str | None, list[SaveSummary]]:
        manifest = self.ensure_initialized()
        active = self.active_save_id()
        if active != manifest.active_save_id:
            manifest.active_save_id = active
            self.save_manifest(manifest)
        return active, self.list_summaries()

    def _migrate_legacy_layout(self) -> SaveLibraryManifest:
        save_id = new_id("save")
        destination_dir = self.save_dir_for(save_id)
        destination_dir.mkdir(parents=True, exist_ok=True)

        self._copy_if_exists(self.legacy_state_path, destination_dir / "game_state.json")
        self._copy_if_exists(self.root_dir / "events.jsonl", destination_dir / "events.jsonl")
        self._copy_if_exists(self.root_dir / "memory.json", destination_dir / "memory.json")
        self._copy_dir_if_exists(self.root_dir / "checkpoints", destination_dir / "checkpoints")
        self._copy_dir_if_exists(
            self.root_dir / "turn-checkpoints",
            destination_dir / "turn-checkpoints",
        )

        manifest = SaveLibraryManifest(
            active_save_id=save_id,
            saves=[SaveRecord(save_id=save_id, created_at=utc_now().isoformat())],
        )
        self.save_manifest(manifest)
        return manifest

    def _copy_if_exists(self, source: Path, destination: Path) -> None:
        if not source.exists():
            return
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    def _copy_dir_if_exists(self, source: Path, destination: Path) -> None:
        if not source.exists():
            return
        shutil.copytree(source, destination, dirs_exist_ok=True)


def _character_name(state: GameState) -> str:
    name = state.character.name.strip()
    if name != "":
        return name
    return "Unnamed Wanderer"


def _identifying_line(state: GameState) -> str:
    backstory = state.character.backstory.strip()
    if backstory != "":
        return backstory
    archetype = state.character.archetype.strip()
    if archetype != "":
        return archetype
    current_scene = state.current_scene.strip()
    if current_scene != "":
        return current_scene
    return "A campaign waiting to be resumed."


def _state_summary(state: GameState) -> str:
    summary: str
    if state.campaign_status == CampaignStatus.ENDED:
        reason = (state.campaign_end_reason or CampaignEndReason.RETIREMENT).value
        if state.campaign_end_summary is not None and state.campaign_end_summary.strip() != "":
            summary = f"Ended by {reason}. {state.campaign_end_summary.strip()}"
        else:
            summary = f"Ended by {reason}."
    elif state.campaign_status == CampaignStatus.CHARACTER_CREATION:
        summary = "Character creation in progress."
    elif state.campaign_status == CampaignStatus.READY_TO_START:
        summary = "Character finalized and ready to begin the campaign."
    elif state.encounter.active:
        active_foes = sum(
            1
            for combatant in state.encounter.combatants
            if not combatant.defeated and not combatant.fled
        )
        if active_foes > 0:
            summary = (
                f"Scene {state.scene_number}. In combat, round {state.encounter.round_number} "
                f"against {active_foes} foe{'s' if active_foes != 1 else ''}."
            )
        else:
            summary = f"Scene {state.scene_number}. In combat."
    else:
        scene = state.current_scene.strip()
        if scene == "":
            summary = f"Scene {state.scene_number}."
        else:
            summary = f"Scene {state.scene_number}. {_clip(scene, limit=150)}"
    return summary


def _clip(text: str, *, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."
