from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from pydantic import Field

from dungeon_master.domain.models import (
    AttackStance,
    CairnAbility,
    CairnRestKind,
    CairnSurvivalAction,
    CairnTimeAdvance,
    EncounterAdvantagePayoff,
    Likelihood,
    StrictModel,
)


class TurnRoute(StrEnum):
    """High-level summary of the typed operations in a turn plan."""

    PLAYER_ACTION = "player_action"
    YES_NO = "yes_no"
    RANDOM_EVENT = "random_event"
    SCENE_CHECK = "scene_check"
    SAVE = "save"
    ATTACK = "attack"
    HARM = "harm"
    RECOVERY = "recovery"
    EQUIP = "equip"
    RETREAT = "retreat"


class PlannedTurnOpKind(StrEnum):
    YES_NO = "yes_no"
    RANDOM_EVENT = "random_event"
    SCENE_CHECK = "scene_check"
    SAVE = "save"
    BEGIN_ENCOUNTER = "begin_encounter"
    ATTACK = "attack"
    COORDINATED_ATTACK = "coordinated_attack"
    ENEMY_OPENER = "enemy_opener"
    HARM = "harm"
    RECOVERY = "recovery"
    SETUP_ADVANTAGE = "setup_advantage"
    EQUIP = "equip"
    RETREAT = "retreat"
    INSPECT_INVENTORY = "inspect_inventory"
    SEARCH_SCENE = "search_scene"
    ACQUIRE_ITEM = "acquire_item"
    TRANSFER_ITEM = "transfer_item"
    RECRUIT_NPC = "recruit_npc"
    USE_ITEM = "use_item"
    DROP_ITEM = "drop_item"
    CLARIFY = "clarify"
    NARRATE = "narrate"


@dataclass(frozen=True)
class PlannedTurnOp:
    kind: PlannedTurnOpKind
    text: str
    likelihood: Likelihood | None = None
    ability: CairnAbility | None = None
    target_name: str | None = None
    stance: AttackStance | None = None
    rest_kind: CairnRestKind | None = None
    item_name: str | None = None
    npc_name: str | None = None
    actor_name: str | None = None
    supporting_actor_names: tuple[str, ...] = ()
    source_actor_name: str | None = None
    target_actor_name: str | None = None
    equipped: bool | None = None
    harm_amount: int | None = None
    harm_source: str | None = None
    armor_applies: bool | None = None
    in_combat: bool | None = None
    advantage_payoff: EncounterAdvantagePayoff | None = None


@dataclass(frozen=True)
class TurnPlan:
    route: TurnRoute
    text: str
    ops: tuple[PlannedTurnOp, ...]
    time_advance: CairnTimeAdvance = CairnTimeAdvance.NONE
    survival_actions: tuple[CairnSurvivalAction, ...] = ()


class GeneratedPlannedTurnOp(StrictModel):
    kind: PlannedTurnOpKind
    text: str = Field(min_length=1)
    likelihood: Likelihood | None = None
    ability: CairnAbility | None = None
    target_name: str | None = None
    stance: AttackStance | None = None
    rest_kind: CairnRestKind | None = None
    item_name: str | None = None
    npc_name: str | None = None
    actor_name: str | None = None
    supporting_actor_names: list[str] = Field(default_factory=list, max_length=3)
    source_actor_name: str | None = None
    target_actor_name: str | None = None
    equipped: bool | None = None
    harm_amount: int | None = Field(default=None, ge=0)
    harm_source: str | None = None
    armor_applies: bool | None = None
    in_combat: bool | None = None
    advantage_payoff: EncounterAdvantagePayoff | None = None


class GeneratedTurnPlan(StrictModel):
    route: TurnRoute
    text: str = Field(min_length=1)
    ops: list[GeneratedPlannedTurnOp] = Field(min_length=1, max_length=3)
    time_advance: CairnTimeAdvance = CairnTimeAdvance.NONE
    survival_actions: list[CairnSurvivalAction] = Field(default_factory=list, max_length=2)


class GeneratedCombatMechanicsReview(StrictModel):
    allow_combat_mechanics: bool
    reason: str = Field(min_length=1)


class GeneratedSaveMechanicsReview(StrictModel):
    allow_save_mechanics: bool
    reason: str = Field(min_length=1)


RouterClassifier = Callable[[str, Likelihood | None], TurnPlan]


class EmptyRouteContentError(ValueError):
    pass


class TurnPlanningError(ValueError):
    pass
