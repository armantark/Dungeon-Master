from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from dungeon_master.mechanics.inventory import ResolvedActor, sync_survival_flags
from dungeon_master.models import (
    CairnCharacterState,
    CairnDayPhase,
    CairnItemTag,
    CairnResolution,
    CairnResourceCost,
    CairnResourceDelta,
    CairnResourceDeltaReason,
    CairnResourceDrawPolicy,
    CairnResourcePool,
    CairnResourceRechargePolicy,
    CairnRestKind,
    CairnSurvivalAction,
    CairnTimeAdvance,
    CharacterSheet,
    GameState,
    InventoryItem,
    OracleKind,
    OracleOutcome,
)

D6_SIDES = 6
WATCHES_PER_DAY = 6
FOOD_WARNING_WATCHES = 2
FOOD_DEPRIVED_WATCHES = 3
SLEEP_WARNING_WATCHES = 4
SLEEP_DEPRIVED_WATCHES = 6


@dataclass(frozen=True)
class SurvivalUpdate:
    summary: str
    resolution: CairnResolution


@dataclass(frozen=True)
class ResolvedResourceCost:
    cost: CairnResourceCost
    item: InventoryItem
    pool: CairnResourcePool
    before: int
    after: int


class SurvivalMechanics:
    if TYPE_CHECKING:

        def _require_ready(self, state: GameState) -> None: ...

        def _resolve_actor(self, state: GameState, actor_id: str | None) -> ResolvedActor: ...

        def _recompute_derived(self, character: CharacterSheet) -> None: ...

        def _find_item(
            self,
            character: CharacterSheet,
            item_id: str,
        ) -> InventoryItem | None: ...

    def recover(
        self,
        state: GameState,
        kind: CairnRestKind,
        *,
        actor_id: str | None = None,
    ) -> OracleOutcome:
        self._require_ready(state)
        actor = self._resolve_actor(state, actor_id)
        cairn = actor.sheet.cairn
        hp_before = cairn.hp
        fatigue_before = cairn.fatigue
        str_before = cairn.str_score

        if cairn.dead:
            message = "Dead characters cannot recover through ordinary rest."
            raise ValueError(message)

        if kind == CairnRestKind.BREATHER:
            if not cairn.deprived:
                cairn.hp = cairn.max_hp
        elif kind == CairnRestKind.FULL_REST:
            if not cairn.deprived:
                cairn.hp = cairn.max_hp
                cairn.fatigue = 0
                cairn.critically_wounded = False
        elif not cairn.deprived:
            cairn.hp = cairn.max_hp
            cairn.fatigue = 0
            cairn.str_score = cairn.max_str_score
            cairn.dex_score = cairn.max_dex_score
            cairn.wil_score = cairn.max_wil_score
            cairn.critically_wounded = False
            cairn.paralyzed = False
            cairn.delirious = False

        resource_deltas: list[CairnResourceDelta] = []
        if kind != CairnRestKind.BREATHER:
            self._recharge_resources_for_policy(
                actor,
                CairnResourceRechargePolicy.ON_REST,
                deltas=resource_deltas,
            )
        self._recompute_derived(actor.sheet)
        actor_prefix = "" if actor.is_player else f"{actor.name}: "
        return OracleOutcome(
            kind=OracleKind.RECOVERY,
            summary=f"{actor_prefix}Recovery resolved: {kind.value}.",
            rolls=[],
            question=kind.value,
            chaos_factor=state.chaos_factor,
            cairn=CairnResolution(
                rest_kind=kind,
                actor_id=None if actor.is_player else actor.id,
                actor_name=None if actor.is_player else actor.name,
                hp_before=hp_before,
                hp_after=cairn.hp,
                str_before=str_before,
                str_after=cairn.str_score,
                fatigue_before=fatigue_before,
                fatigue_after=cairn.fatigue,
                resource_deltas=resource_deltas,
                overloaded=cairn.overloaded,
            ),
        )

    def advance_survival_clock(
        self,
        state: GameState,
        *,
        time_advance: CairnTimeAdvance,
        actions: tuple[CairnSurvivalAction, ...] = (),
        actor_id: str | None = None,
        extra_days: int = 0,
    ) -> SurvivalUpdate:
        self._require_ready(state)
        actor = self._resolve_actor(state, actor_id)
        cairn = actor.sheet.cairn
        sync_survival_flags(cairn)
        before = cairn.survival.model_copy(deep=True)
        deprived_before = cairn.deprived
        ration_item_id: str | None = None
        ration_item_name: str | None = None
        ration_uses_before: int | None = None
        ration_uses_after: int | None = None
        notes: list[str] = []
        resource_deltas: list[CairnResourceDelta] = []

        watches = self._watch_count_for_time_advance(before.watch_index, time_advance)
        if watches > 0:
            self._advance_survival_watches(cairn, watches)
            recharge_reason = (
                CairnResourceRechargePolicy.PER_WATCH
                if watches < WATCHES_PER_DAY
                else CairnResourceRechargePolicy.PER_DAY
            )
            notes.extend(
                self._recharge_resources_for_policy(
                    actor,
                    recharge_reason,
                    deltas=resource_deltas,
                ),
            )
        if extra_days > 0:
            cairn.survival.day_number += extra_days
            notes.extend(
                self._recharge_resources_for_policy(
                    actor,
                    CairnResourceRechargePolicy.PER_DAY,
                    deltas=resource_deltas,
                ),
            )
        if CairnSurvivalAction.EAT in actions:
            ration = self._find_ration_item(actor.sheet)
            if ration is None:
                notes.append("No rations available to eat")
            else:
                ration_item_id = ration.id
                ration_item_name = ration.name
                ration_uses_before, ration_uses_after = self._consume_ration(actor.sheet, ration)
                cairn.survival.watches_since_meal = 0
                cairn.survival.food_deprived = False
                notes.append(f"Ate {ration.name} ({ration_uses_before}->{ration_uses_after})")
        if CairnSurvivalAction.SLEEP in actions:
            cairn.survival.watches_since_sleep = 0
            cairn.survival.sleep_deprived = False
            notes.append("Slept and reset exhaustion pressure")
        sync_survival_flags(cairn)
        self._recompute_derived(actor.sheet)
        after = cairn.survival.model_copy(deep=True)
        actor_prefix = "" if actor.is_player else f"{actor.name}: "
        if time_advance != CairnTimeAdvance.NONE:
            notes.insert(
                0,
                f"time {time_advance.value} ({before.day_number}:{before.day_phase.value} -> "
                f"{after.day_number}:{after.day_phase.value})",
            )
        if not notes:
            notes.append("No survival-clock change")
        return SurvivalUpdate(
            summary=f"{actor_prefix}Survival clock updated: {'; '.join(notes)}.",
            resolution=CairnResolution(
                time_advance=time_advance,
                actor_id=None if actor.is_player else actor.id,
                actor_name=None if actor.is_player else actor.name,
                day_number_before=before.day_number,
                day_number_after=after.day_number,
                watch_index_before=before.watch_index,
                watch_index_after=after.watch_index,
                day_phase_before=before.day_phase,
                day_phase_after=after.day_phase,
                watches_since_meal_before=before.watches_since_meal,
                watches_since_meal_after=after.watches_since_meal,
                watches_since_sleep_before=before.watches_since_sleep,
                watches_since_sleep_after=after.watches_since_sleep,
                food_deprived_before=before.food_deprived,
                food_deprived_after=after.food_deprived,
                sleep_deprived_before=before.sleep_deprived,
                sleep_deprived_after=after.sleep_deprived,
                deprived_before=deprived_before,
                deprived_after=cairn.deprived,
                ration_item_id=ration_item_id,
                ration_item_name=ration_item_name,
                ration_uses_before=ration_uses_before,
                ration_uses_after=ration_uses_after,
                resource_deltas=resource_deltas,
                overloaded=cairn.overloaded,
            ),
        )

    def _watch_count_for_time_advance(
        self,
        watch_index: int,
        time_advance: CairnTimeAdvance,
    ) -> int:
        if time_advance in (CairnTimeAdvance.NONE, CairnTimeAdvance.BRIEF):
            return 0
        if time_advance == CairnTimeAdvance.WATCH:
            return 1
        if time_advance == CairnTimeAdvance.DAY:
            return 3
        return WATCHES_PER_DAY - watch_index if watch_index > 0 else WATCHES_PER_DAY

    def _advance_survival_watches(self, cairn: CairnCharacterState, watches: int) -> None:
        if watches <= 0:
            return
        total = cairn.survival.watch_index + watches
        day_increment, watch_index = divmod(total, WATCHES_PER_DAY)
        cairn.survival.day_number += day_increment
        cairn.survival.watch_index = watch_index
        cairn.survival.day_phase = self._phase_for_watch_index(watch_index)
        cairn.survival.watches_since_meal += watches
        cairn.survival.watches_since_sleep += watches
        sync_survival_flags(cairn)

    def _phase_for_watch_index(self, watch_index: int) -> CairnDayPhase:
        phases = (
            CairnDayPhase.DAWN,
            CairnDayPhase.DAY,
            CairnDayPhase.DAY,
            CairnDayPhase.DUSK,
            CairnDayPhase.NIGHT,
            CairnDayPhase.DEEP_NIGHT,
        )
        return phases[watch_index]

    def _find_ration_item(self, character: CharacterSheet) -> InventoryItem | None:
        candidates = [
            item
            for item in character.inventory
            if CairnItemTag.SUPPLIES in item.cairn.tags
            and (item.cairn.uses is None or item.cairn.uses > 0)
        ]
        if not candidates:
            return None
        candidates.sort(
            key=lambda item: (
                CairnItemTag.CONSUMABLE not in item.cairn.tags,
                item.cairn.uses is None,
                item.cairn.slots,
                item.name,
            ),
        )
        return candidates[0]

    def _consume_ration(
        self,
        character: CharacterSheet,
        item: InventoryItem,
    ) -> tuple[int, int]:
        uses_before = (
            item.cairn.uses if item.cairn.uses is not None else max(1, item.cairn.slots * 3)
        )
        uses_after = max(0, uses_before - 1)
        if uses_after == 0:
            character.inventory = [
                candidate for candidate in character.inventory if candidate.id != item.id
            ]
        else:
            item.cairn.uses = uses_after
        self._recompute_derived(character)
        return (uses_before, uses_after)

    def _resolve_resource_costs(
        self,
        actor: ResolvedActor,
        source_item: InventoryItem,
        costs: list[CairnResourceCost],
    ) -> list[ResolvedResourceCost]:
        resolved: list[ResolvedResourceCost] = []
        remaining_by_pool: dict[tuple[str, str], int] = {}
        for cost in costs:
            if cost.amount <= 0:
                continue
            match = self._find_resource_pool(actor.sheet, source_item, cost)
            if match is None:
                if cost.required:
                    message = f"{actor.name} lacks required {cost.label} for {source_item.name}."
                    raise ValueError(message)
                continue
            item, pool = match
            key = (item.id, pool.id)
            before = remaining_by_pool.get(key, pool.current)
            after = before - cost.amount
            if after < 0:
                message = (
                    f"{actor.name} has insufficient {pool.label} "
                    f"for {source_item.name} ({before} available, "
                    f"{cost.amount} required)."
                )
                raise ValueError(message)
            remaining_by_pool[key] = after
            resolved.append(
                ResolvedResourceCost(
                    cost=cost,
                    item=item,
                    pool=pool,
                    before=before,
                    after=after,
                ),
            )
        return resolved

    def _consume_resolved_resource_costs(
        self,
        resolved: list[ResolvedResourceCost],
        *,
        actor: ResolvedActor,
        reason: CairnResourceDeltaReason,
    ) -> list[CairnResourceDelta]:
        deltas: list[CairnResourceDelta] = []
        for entry in resolved:
            entry.pool.current = entry.after
            deltas.append(
                CairnResourceDelta(
                    actor_id=None if actor.is_player else actor.id,
                    actor_name=None if actor.is_player else actor.name,
                    item_id=entry.item.id,
                    item_name=entry.item.name,
                    resource_id=entry.pool.id,
                    resource_label=entry.pool.label,
                    resource_kind=entry.pool.kind,
                    before=entry.before,
                    after=entry.after,
                    amount=entry.cost.amount,
                    reason=reason,
                    note=f"{entry.cost.label} for {entry.cost.draw_policy.value}",
                ),
            )
        return deltas

    def _recharge_resources_for_policy(
        self,
        actor: ResolvedActor,
        policy: CairnResourceRechargePolicy,
        *,
        deltas: list[CairnResourceDelta],
    ) -> list[str]:
        notes: list[str] = []
        for item in actor.sheet.inventory:
            for pool in item.cairn.resources:
                if pool.recharge_policy != policy:
                    continue
                if pool.max is None or pool.current >= pool.max:
                    continue
                before = pool.current
                pool.current = min(pool.max, pool.current + pool.recharge_amount)
                if pool.current == before:
                    continue
                delta = CairnResourceDelta(
                    actor_id=None if actor.is_player else actor.id,
                    actor_name=None if actor.is_player else actor.name,
                    item_id=item.id,
                    item_name=item.name,
                    resource_id=pool.id,
                    resource_label=pool.label,
                    resource_kind=pool.kind,
                    before=before,
                    after=pool.current,
                    amount=pool.current - before,
                    reason=CairnResourceDeltaReason.RECHARGE,
                    note=pool.recharge_condition or policy.value,
                )
                deltas.append(delta)
                notes.append(f"{pool.label} recharged {before}->{pool.current}")
        return notes

    def _find_resource_pool(
        self,
        character: CharacterSheet,
        source_item: InventoryItem,
        cost: CairnResourceCost,
    ) -> tuple[InventoryItem, CairnResourcePool] | None:
        if cost.draw_policy == CairnResourceDrawPolicy.SELF:
            return self._find_resource_pool_on_item(source_item, cost)

        if cost.draw_policy == CairnResourceDrawPolicy.LINKED_ITEM:
            if cost.linked_item_id is None:
                return None
            item = self._find_item(character, cost.linked_item_id)
            if item is None:
                return None
            return self._find_resource_pool_on_item(item, cost)

        if cost.draw_policy in (
            CairnResourceDrawPolicy.ACTOR_INVENTORY,
            CairnResourceDrawPolicy.ACTOR_POOL,
        ):
            for item in character.inventory:
                found = self._find_resource_pool_on_item(item, cost)
                if found is not None:
                    return found
        return None

    def _find_resource_pool_on_item(
        self,
        item: InventoryItem,
        cost: CairnResourceCost,
    ) -> tuple[InventoryItem, CairnResourcePool] | None:
        for pool in item.cairn.resources:
            if cost.resource_id is not None and pool.id != cost.resource_id:
                continue
            if cost.resource_id is None and pool.kind != cost.kind:
                continue
            if cost.resource_id is None and not self._resource_label_matches(
                pool.label, cost.label
            ):
                continue
            return (item, pool)
        return None

    def _resource_label_matches(self, pool_label: str, cost_label: str) -> bool:
        left = pool_label.strip().casefold()
        right = cost_label.strip().casefold()
        return left == right or left.rstrip("s") == right.rstrip("s")
