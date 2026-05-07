from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dungeon_master.models import (
    NPC,
    CairnCharacterState,
    CairnItemState,
    CairnItemTag,
    CairnMechanicsSource,
    CampaignEndReason,
    CampaignStatus,
    CharacterSheet,
    EventType,
    GameEvent,
    GameState,
    GameThread,
    InventoryItem,
    Likelihood,
    NPCPlayerLabelKind,
    OracleKind,
    OracleOutcome,
    OracleTables,
    Roll,
    SceneStatus,
)
from dungeon_master.save_library import SaveLibrary
from dungeon_master.state_store import StateStore

# Intentional dev-only default outside the repo so fixture seeding can never
# clobber the canonical `data/` tree by accident.
DEFAULT_FIXTURE_STATE_PATH = (
    Path(tempfile.gettempdir()) / "dungeon-master-fixtures" / "game_state.json"
)


@dataclass(frozen=True)
class FixtureSeedReport:
    root_state_path: Path
    active_save_id: str
    save_ids: tuple[str, ...]
    save_names: tuple[str, ...]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="dungeon-master-fixtures",
        description=(
            "Seed an isolated save-library root with canned fixture saves for "
            "browser/manual testing without touching a real campaign."
        ),
    )
    parser.add_argument(
        "--state-path",
        type=Path,
        default=DEFAULT_FIXTURE_STATE_PATH,
        help=(
            "Fixture root state path. Defaults to "
            f"{DEFAULT_FIXTURE_STATE_PATH}. The surrounding directory becomes "
            "the isolated save-library root."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Wipe and recreate the fixture root if it already exists.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the seed report as JSON instead of human-readable text.",
    )
    args = parser.parse_args(argv)

    try:
        report = seed_fixture_library(args.state_path, force=args.force)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    if args.json:
        print(_report_json(report))  # noqa: T201
        return
    print(_report_text(report))  # noqa: T201


def seed_fixture_library(
    root_state_path: Path,
    *,
    force: bool = False,
) -> FixtureSeedReport:
    root_dir = root_state_path.parent
    if root_dir.exists():
        if not force:
            message = (
                f"Fixture root already exists at {root_dir}. "
                "Pass --force to replace it."
            )
            raise ValueError(message)
        _clear_root_dir(root_dir)

    library = SaveLibrary(root_state_path)
    fixtures = (
        _continuity_fixture_state(),
        _archive_fixture_state(),
    )

    save_ids: list[str] = []
    save_names: list[str] = []

    for index, state in enumerate(fixtures):
        save_id = library.create_save(create_state=state, select=index == 0)
        save_ids.append(save_id)
        save_names.append(state.character.name)

        store = StateStore(library.state_path_for(save_id))
        if state.action_log:
            store.append_events(state.action_log)

    active_save_id = library.active_save_id()
    if active_save_id is None:
        message = "Fixture seeding failed to select an active save."
        raise ValueError(message)

    return FixtureSeedReport(
        root_state_path=root_state_path,
        active_save_id=active_save_id,
        save_ids=tuple(save_ids),
        save_names=tuple(save_names),
    )


def _clear_root_dir(root_dir: Path) -> None:
    resolved = root_dir.resolve()
    dangerous = {Path("/").resolve(), Path.home().resolve()}
    if resolved in dangerous:
        message = f"Refusing to wipe unsafe fixture root: {resolved}"
        raise ValueError(message)
    shutil.rmtree(resolved)


def _continuity_fixture_state() -> GameState:
    dusk_thread = GameThread(
        title="Why does the bell toll at dusk?",
        stakes="The old bell answers trespassers before anyone else does.",
    )
    relic_thread = GameThread(
        title="Who carries the saint's jawbone now?",
        stakes="The reliquary changes hands whenever the lane draws blood.",
    )
    ferryman_thread = GameThread(
        title="What debt keeps the ferryman on the marsh road?",
        stakes="He cannot leave until someone else accepts the drowned tithe.",
    )

    bellringer = NPC(
        name="Ysoria Thane",
        player_label="The ash-veiled bellringer",
        player_label_kind=NPCPlayerLabelKind.DESCRIPTOR,
        role="Belfry watcher",
        disposition=(
            "Speaks only after the bell answers first, and even then in clipped "
            "half-confessions."
        ),
    )
    ferryman = NPC(
        name="Brother Sava",
        role="Marsh ferryman",
        disposition="Knows the road's true toll and hates being asked about it.",
    )
    hidden_abbot = NPC(
        name="Abbot Theocrit",
        player_label="the shuttered abbot",
        player_label_kind=NPCPlayerLabelKind.DESCRIPTOR,
        role="Hidden patron",
        disposition="Still unseen in person; only his bells and debts reach the lane.",
    )

    linked_outcome = OracleOutcome(
        kind=OracleKind.YES_NO,
        summary="Yes: the belfry answers, and the bellringer finally steps into view.",
        question="If I strike the chapel bell, will anyone answer from the lane?",
        likelihood=Likelihood.LIKELY,
        answer="Yes",
        probability=78,
        chaos_factor=6,
        rolls=[Roll(sides=100, result=23, label="fate")],
        referenced_thread_id=dusk_thread.id,
        referenced_thread_ids=[dusk_thread.id, relic_thread.id],
        referenced_npc_id=bellringer.id,
        referenced_npc_ids=[bellringer.id, ferryman.id],
    )
    prior_outcome = OracleOutcome(
        kind=OracleKind.SCENE_CHECK,
        summary="expected: The lane waits under a drowned sunset.",
        scene_status=SceneStatus.EXPECTED,
        chaos_factor=5,
    )

    player_event = GameEvent(
        event_type=EventType.PLAYER,
        title="Player action",
        content="I strike the cracked chapel bell and wait to see who answers.",
        created_at=_timestamp(0),
    )
    oracle_event = GameEvent(
        event_type=EventType.ORACLE,
        title="Oracle answered",
        content="Yes",
        oracle_outcome_id=linked_outcome.id,
        created_at=_timestamp(1),
    )
    narrative_event = GameEvent(
        event_type=EventType.NARRATIVE,
        title="The bell answers",
        content=(
            "The first toll crawls over the marsh road like a blade drawn across wet "
            "stone. A second answer comes from the belfry: slower, hoarser, and close "
            "enough that the ash-veiled bellringer finally leans into sight above the "
            "lane while Brother Sava waits below with one hand on the ferry-rope. "
            "Whoever holds the saint's jawbone is listening too."
        ),
        thinking=(
            "Fixture narrative for receipt-link testing. Keeps both referenced threads "
            "and the descriptor-visible NPC in one compact reply."
        ),
        oracle_outcome_id=linked_outcome.id,
        created_at=_timestamp(2),
    )
    state = GameState(
        current_scene=(
            "Fixture continuity save: dusk presses down on the marsh chapel while the "
            "road-bell answers from somewhere above the lane."
        ),
        setting_notes=(
            "This isolated fixture exists to exercise descriptor-visible NPC labels, "
            "receipt links, and inspector focus jumps without touching a live campaign."
        ),
        player_notes=(
            "You came to the marsh chapel to learn why the bell tolls before the dead "
            "are counted."
        ),
        campaign_status=CampaignStatus.ACTIVE,
        npc_roster_version=2,
        chaos_factor=6,
        scene_number=4,
        character=_fixture_character(
            name="Fixture Bellringer",
            epithet="Continuity fixture - descriptor NPCs and receipt links",
        ),
        threads=[dusk_thread, relic_thread, ferryman_thread],
        npcs=[bellringer, ferryman],
        hidden_npcs=[hidden_abbot],
        oracle_tables=_fixture_oracle_tables(),
        oracle_history=[prior_outcome, linked_outcome],
        action_log=[player_event, oracle_event, narrative_event],
    )
    state.created_at = _timestamp(-240)
    state.updated_at = _timestamp(4)
    return state


def _archive_fixture_state() -> GameState:
    closing_outcome = OracleOutcome(
        kind=OracleKind.PLAYER_ACTION,
        summary="The wanderer laid down the road-bell and walked away.",
        chaos_factor=4,
    )
    closing_narrative = GameEvent(
        event_type=EventType.NARRATIVE,
        title="The ledger closes",
        content=(
            "At dawn the wanderer left the bell-rope swinging and walked the marsh road "
            "without once looking back. The chapel kept its answer; the ledger did not."
        ),
        oracle_outcome_id=closing_outcome.id,
        created_at=_timestamp(10),
    )
    closing_system = GameEvent(
        event_type=EventType.SYSTEM,
        title="Campaign ended",
        content="Campaign ended: retirement.",
        created_at=_timestamp(11),
    )
    state = GameState(
        current_scene="Fixture archive save: the road is quiet and the bell has fallen still.",
        setting_notes="Archive fixture for shelf / ended-state smoke testing.",
        player_notes="This save exists so the shelf always has an ended campaign to bind.",
        campaign_status=CampaignStatus.ENDED,
        campaign_end_reason=CampaignEndReason.RETIREMENT,
        campaign_ended_at=_timestamp(12),
        campaign_end_summary=(
            "The wanderer retired with the bell unanswered, leaving only a closed ledger."
        ),
        npc_roster_version=2,
        chaos_factor=4,
        scene_number=7,
        character=_fixture_character(
            name="Fixture Archive",
            epithet="Shelf fixture - archived campaign",
        ),
        threads=[
            GameThread(
                title="Should the bell be rung again?",
                stakes="No one is left willing to test the answer.",
            ),
        ],
        npcs=[],
        hidden_npcs=[],
        oracle_tables=_fixture_oracle_tables(),
        oracle_history=[closing_outcome],
        action_log=[closing_narrative, closing_system],
    )
    state.created_at = _timestamp(-600)
    state.updated_at = _timestamp(12)
    return state


def _fixture_character(*, name: str, epithet: str) -> CharacterSheet:
    cudgel = InventoryItem(
        name="Notched chapel cudgel",
        details="A practice cudgel hardened by old incense and brine.",
        cairn=CairnItemState(
            source=CairnMechanicsSource.EXPLICIT,
            tags=[CairnItemTag.WEAPON, CairnItemTag.HOLY],
            weapon_damage_die=6,
            equipped=True,
        ),
    )
    bell = InventoryItem(
        name="Road-bell shard",
        details="A cracked brass fragment that still hums when the marsh answers.",
        cairn=CairnItemState(
            source=CairnMechanicsSource.EXPLICIT,
            tags=[CairnItemTag.RELIC, CairnItemTag.UTILITY, CairnItemTag.PETTY],
            slots=0,
        ),
    )
    lamp = InventoryItem(
        name="Pitch lamp",
        details="A hooded lamp dark enough for marsh roads.",
        cairn=CairnItemState(
            source=CairnMechanicsSource.EXPLICIT,
            tags=[CairnItemTag.LIGHT, CairnItemTag.CONSUMABLE],
            uses=2,
        ),
    )
    return CharacterSheet(
        name=name,
        archetype="Fixture wanderer",
        epithet=epithet,
        backstory=(
            "A canned protagonist built only to exercise frontend surfaces without "
            "forcing a live model round-trip."
        ),
        drive="Confirm that continuity surfaces stay legible and safe.",
        flaw="Knows this world is scaffolding and cannot quite stop mentioning it.",
        condition="Travel-worn, ash-dusted, and still listening for the next toll.",
        inventory=[cudgel, bell, lamp],
        cairn=CairnCharacterState(
            source=CairnMechanicsSource.EXPLICIT,
            str_score=9,
            dex_score=11,
            wil_score=12,
            max_str_score=9,
            max_dex_score=11,
            max_wil_score=12,
            hp=4,
            max_hp=4,
            armor=0,
            slots_used=2,
            primary_weapon_item_id=cudgel.id,
            skills=["listen for bells", "read marsh roads"],
            abilities=["hold your breath when the dead reply"],
            notes=(
                "Fixture-only explicit Cairn state so manual/browser tests never "
                "trigger a mechanics backfill."
            ),
        ),
    )


def _fixture_oracle_tables() -> OracleTables:
    return OracleTables(
        event_focus=[
            "bell omen",
            "thread pressure",
            "npc demand",
            "road danger",
            "debt collected",
            "hidden witness",
        ],
        event_actions=[
            "beckon",
            "conceal",
            "demand",
            "echo",
            "fracture",
            "pursue",
            "refuse",
            "withhold",
        ],
        event_tones=[
            "ashen",
            "bitter",
            "drowned",
            "forbidden",
            "hushed",
            "patient",
            "solemn",
            "wounded",
        ],
        event_subjects=[
            "a bell",
            "a bone reliquary",
            "a ferryman",
            "a lane",
            "a marsh prayer",
            "a watcher",
            "an old debt",
            "wet stone",
        ],
    )


def _timestamp(seconds: int) -> datetime:
    base = datetime(2026, 5, 7, 16, 0, tzinfo=UTC)
    return base + timedelta(seconds=seconds)


def _report_json(report: FixtureSeedReport) -> str:
    payload = {
        "root_state_path": str(report.root_state_path),
        "active_save_id": report.active_save_id,
        "save_ids": list(report.save_ids),
        "save_names": list(report.save_names),
    }
    return json.dumps(payload, indent=2)


def _report_text(report: FixtureSeedReport) -> str:
    lines = [
        "Fixture save library seeded",
        f"- Root state path: {report.root_state_path}",
        f"- Active save id: {report.active_save_id}",
        "- Saves:",
    ]
    lines.extend(
        f"  - {save_id}: {save_name}"
        for save_id, save_name in zip(report.save_ids, report.save_names, strict=True)
    )
    lines.extend(
        [
            "- Start an isolated backend against this fixture root with:",
            (
                "  DUNGEON_MASTER_STATE_PATH="
                f"{report.root_state_path} uv run dungeon-master --port 8000"
            ),
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    main()
