from __future__ import annotations

from dataclasses import dataclass

from pydantic import Field

from dungeon_master.domain.models import (
    CampaignStatus,
    CharacterSheet,
    OracleOutcome,
    StrictModel,
)
from dungeon_master.llm.prompt_fragments import JSON_ONLY

CURRENT_NPC_ROSTER_VERSION = 2
PLAYER_ACTOR_ALIASES = {"player", "me", "myself", "you", "main character", "wanderer"}
MIN_COORDINATED_ATTACK_PARTICIPANTS = 2
RECENT_NPC_CONTEXT_LIMIT = 4
RECENT_RECRUITMENT_SCENE_CONTEXT_LIMIT = 6
CLARIFICATION_EVENT_TITLE = "Clarification needed"
RECRUITMENT_RESOLVER_SYSTEM_PROMPT = f"""You resolve a requested recruitment target to one
already-visible NPC in a solo tabletop RPG save.

{JSON_ONLY}

Hard rules:
- Choose only an exact npc_id from the supplied visible_npcs list.
- Never choose hidden, invented, or merely implied people.
- Use the player turn, planner label, current scene, and recent visible
  transcript to map descriptors, titles, and roles to the visible roster.
- If no visible NPC is clearly the target, return {{"npc_id": null}}.
- If more than one visible NPC is plausible, return {{"npc_id": null}}.
"""


class RecruitmentResolution(StrictModel):
    npc_id: str | None = Field(default=None, max_length=80)


@dataclass(frozen=True)
class ServiceActor:
    id: str
    name: str
    sheet: CharacterSheet
    is_player: bool


@dataclass(frozen=True)
class ClarificationPrompt:
    question: str


@dataclass(frozen=True)
class ExecutedTurn:
    outcome: OracleOutcome
    oracle_title: str | None
    execution_context: str | None = None


@dataclass(frozen=True)
class GuardedYesNoOutcome:
    outcome: OracleOutcome
    execution_context: str | None = None


@dataclass(frozen=True)
class SaveBackfillReport:
    applied: bool
    state_changed: bool
    character_backfilled: bool
    npc_roster_repaired: bool
    terminal_state_synced: bool
    memory_rebuilt: bool
    checkpoint_written: bool
    campaign_status_before: CampaignStatus
    campaign_status_after: CampaignStatus
    visible_npc_count_before: int
    visible_npc_count_after: int
    hidden_npc_count_before: int
    hidden_npc_count_after: int
    visible_name_warnings: tuple[str, ...] = ()
