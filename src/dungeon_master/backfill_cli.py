from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from dungeon_master.save_library import SaveLibrary
from dungeon_master.service import GameService, SaveBackfillReport
from dungeon_master.settings import state_path_from_env
from dungeon_master.state_store import StateStore


@dataclass(frozen=True)
class BackfillTarget:
    save_id: str | None
    state_path: Path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="dungeon-master-backfill",
        description=(
            "Audit/backfill one save against current backend core features "
            "without reseeding the campaign."
        ),
    )
    parser.add_argument(
        "--state-path",
        type=Path,
        default=None,
        help=(
            "Root state path (defaults to DUNGEON_MASTER_STATE_PATH or "
            "data/game_state.json). When a save-library manifest exists, this "
            "should still point at the legacy root state path, not a save slot."
        ),
    )
    parser.add_argument(
        "--save-id",
        default=None,
        help=(
            "Specific save slot to target. Defaults to the active save when a "
            "save library is present."
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist the backfill. Dry-run/audit only by default.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the report as JSON instead of human-readable text.",
    )
    args = parser.parse_args(argv)

    try:
        root_state_path = args.state_path or state_path_from_env()
        target = _resolve_target(root_state_path, save_id=args.save_id)
        service = GameService(store=StateStore(target.state_path))
        report = service.backfill_current_save(apply=args.apply)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    if args.json:
        print(_report_json(target, report))  # noqa: T201
        return
    print(_report_text(target, report))  # noqa: T201


def _resolve_target(root_state_path: Path, *, save_id: str | None) -> BackfillTarget:
    library = SaveLibrary(root_state_path)
    if library.manifest_path.exists():
        target_save_id = save_id or library.active_save_id()
        if target_save_id is None:
            message = "No active save selected. Pass --save-id explicitly."
            raise ValueError(message)
        state_path = library.state_path_for(target_save_id)
        if not state_path.exists():
            message = f"Save is missing its state file: {target_save_id}"
            raise ValueError(message)
        return BackfillTarget(save_id=target_save_id, state_path=state_path)

    if save_id is not None:
        message = "--save-id requires a save library manifest."
        raise ValueError(message)
    if not root_state_path.exists():
        message = f"No save state exists at {root_state_path}."
        raise ValueError(message)
    return BackfillTarget(save_id=None, state_path=root_state_path)


def _report_json(target: BackfillTarget, report: SaveBackfillReport) -> str:
    payload = {
        "save_id": target.save_id,
        "state_path": str(target.state_path),
        "applied": report.applied,
        "state_changed": report.state_changed,
        "character_backfilled": report.character_backfilled,
        "npc_roster_repaired": report.npc_roster_repaired,
        "terminal_state_synced": report.terminal_state_synced,
        "memory_rebuilt": report.memory_rebuilt,
        "checkpoint_written": report.checkpoint_written,
        "campaign_status_before": report.campaign_status_before.value,
        "campaign_status_after": report.campaign_status_after.value,
        "visible_npc_count_before": report.visible_npc_count_before,
        "visible_npc_count_after": report.visible_npc_count_after,
        "hidden_npc_count_before": report.hidden_npc_count_before,
        "hidden_npc_count_after": report.hidden_npc_count_after,
        "visible_name_warnings": list(report.visible_name_warnings),
    }
    return json.dumps(payload, indent=2)


def _report_text(target: BackfillTarget, report: SaveBackfillReport) -> str:
    lines = [
        "Save backfill report",
        f"- Target save: {target.save_id or '(direct state file)'}",
        f"- State path: {target.state_path}",
        f"- Mode: {'apply' if report.applied else 'dry-run'}",
        f"- State changed: {'yes' if report.state_changed else 'no'}",
        f"- Character mechanics backfilled: {'yes' if report.character_backfilled else 'no'}",
        f"- NPC roster repaired: {'yes' if report.npc_roster_repaired else 'no'}",
        f"- Terminal state synced: {'yes' if report.terminal_state_synced else 'no'}",
        f"- Memory rebuilt: {'yes' if report.memory_rebuilt else 'no'}",
        f"- Checkpoint written: {'yes' if report.checkpoint_written else 'no'}",
        (
            "- Campaign status: "
            f"{report.campaign_status_before.value} -> {report.campaign_status_after.value}"
        ),
        (
            "- Visible NPCs: "
            f"{report.visible_npc_count_before} -> {report.visible_npc_count_after}"
        ),
        (
            "- Hidden NPCs: "
            f"{report.hidden_npc_count_before} -> {report.hidden_npc_count_after}"
        ),
    ]
    if report.visible_name_warnings:
        lines.append("- Visible-name audit warnings:")
        lines.extend(f"  - {warning}" for warning in report.visible_name_warnings)
    else:
        lines.append("- Visible-name audit warnings: none")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
