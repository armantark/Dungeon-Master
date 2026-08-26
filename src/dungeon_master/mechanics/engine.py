from __future__ import annotations

import random

from dungeon_master.llm.completion import CompletionFunction
from dungeon_master.llm.narration import NarrativeConfig, _completion
from dungeon_master.mechanics.combat import (
    AttackActor,
    CombatMechanics,
    EncounterScalingPolicy,
    HarmApplication,
)
from dungeon_master.mechanics.generation import (
    BackfillFunction,
    EmptyBackfillContentError,
    GeneratedCairnBackfill,
    GeneratedCairnItemProfile,
    GeneratedEncounterCombatant,
    GeneratedEncounterSeed,
    GeneratedInventoryAcquisition,
    GenerationSupport,
)
from dungeon_master.mechanics.inventory import (
    InventoryMechanics,
    ItemUseResolution,
    ResolvedActor,
)
from dungeon_master.mechanics.survival import (
    ResolvedResourceCost,
    SurvivalMechanics,
    SurvivalUpdate,
)

__all__ = [
    "AttackActor",
    "BackfillFunction",
    "CairnEngine",
    "EmptyBackfillContentError",
    "EncounterScalingPolicy",
    "GeneratedCairnBackfill",
    "GeneratedCairnItemProfile",
    "GeneratedEncounterCombatant",
    "GeneratedEncounterSeed",
    "GeneratedInventoryAcquisition",
    "HarmApplication",
    "ItemUseResolution",
    "ResolvedActor",
    "ResolvedResourceCost",
    "SurvivalUpdate",
]


class CairnEngine(GenerationSupport, CombatMechanics, SurvivalMechanics, InventoryMechanics):
    def __init__(
        self,
        seed: int | None = None,
        config: NarrativeConfig | None = None,
        completion_function: CompletionFunction = _completion,
        backfill_function: BackfillFunction | None = None,
    ) -> None:
        self._rng = random.Random(seed)
        self._config = config or NarrativeConfig.from_env()
        self._completion = completion_function
        self._backfill_function = backfill_function
