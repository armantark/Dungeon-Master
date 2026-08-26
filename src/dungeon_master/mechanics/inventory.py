from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from dungeon_master.domain.models import (
    AttackStance,
    CairnAbility,
    CairnCharacterState,
    CairnConditionKey,
    CairnItemEffectKind,
    CairnItemPower,
    CairnItemPowerKind,
    CairnItemTag,
    CairnMechanicsSource,
    CairnResolution,
    CairnResourceCost,
    CairnResourceDelta,
    CairnResourceDeltaReason,
    CharacterSheet,
    GameState,
    InventoryItem,
    OracleKind,
    OracleOutcome,
    Roll,
)

if TYPE_CHECKING:
    from dungeon_master.mechanics.survival import ResolvedResourceCost

MAX_ARMOR = 3
D20_SIDES = 20
FOOD_DEPRIVED_WATCHES = 3
SLEEP_DEPRIVED_WATCHES = 6


def sync_survival_flags(cairn: CairnCharacterState) -> None:
    cairn.survival.food_deprived = cairn.survival.watches_since_meal >= FOOD_DEPRIVED_WATCHES
    cairn.survival.sleep_deprived = cairn.survival.watches_since_sleep >= SLEEP_DEPRIVED_WATCHES
    cairn.deprived = (
        cairn.survival.food_deprived
        or cairn.survival.sleep_deprived
        or cairn.survival.other_deprived
    )


@dataclass(frozen=True)
class ItemUseResolution:
    summary: str
    effect_summary: str
    rolls: list[Roll]
    uses_before: int | None
    uses_after: int | None
    item_removed: bool
    hp_before: int
    hp_after: int
    str_before: int
    str_after: int
    dex_before: int
    dex_after: int
    wil_before: int
    wil_after: int
    fatigue_before: int
    fatigue_after: int
    attack_stance: AttackStance | None = None
    target_name: str | None = None
    wil_save_target: int | None = None
    wil_save_success: bool | None = None
    resource_deltas: tuple[CairnResourceDelta, ...] = ()


@dataclass(frozen=True)
class ResolvedActor:
    id: str
    name: str
    sheet: CharacterSheet
    is_player: bool


class InventoryMechanics:
    if TYPE_CHECKING:

        def _require_ready(self, state: GameState) -> None: ...

        def _resolve_resource_costs(
            self,
            actor: ResolvedActor,
            source_item: InventoryItem,
            costs: list[CairnResourceCost],
        ) -> list[ResolvedResourceCost]: ...

        def _consume_resolved_resource_costs(
            self,
            resolved: list[ResolvedResourceCost],
            *,
            actor: ResolvedActor,
            reason: CairnResourceDeltaReason,
        ) -> list[CairnResourceDelta]: ...

        def _roll(self, sides: int, label: str) -> Roll: ...

        def _save_succeeds(self, result: int, target: int) -> bool: ...

    def set_item_equipped(
        self,
        state: GameState,
        *,
        item_id: str,
        equipped: bool,
        actor_id: str | None = None,
    ) -> None:
        self._require_ready(state)
        actor = self._resolve_actor(state, actor_id)
        target = self._find_item(actor.sheet, item_id)
        if target is None:
            message = f"Unknown inventory item: {item_id}"
            raise ValueError(message)

        if CairnItemTag.WEAPON in target.cairn.tags and equipped:
            for item in actor.sheet.inventory:
                if item.id != item_id and CairnItemTag.WEAPON in item.cairn.tags:
                    item.cairn.equipped = False
        target.cairn.equipped = equipped
        self._recompute_derived(actor.sheet)

    def transfer_item(
        self,
        state: GameState,
        *,
        item_id: str,
        source_actor_id: str | None,
        target_actor_id: str | None,
    ) -> str:
        self._require_ready(state)
        source = self._resolve_actor(state, source_actor_id)
        target = self._resolve_actor(state, target_actor_id)
        if source.id == target.id:
            message = "Cannot transfer an item to the same actor."
            raise ValueError(message)

        transferred_item = self._find_item(source.sheet, item_id)
        if transferred_item is None:
            message = f"Unknown inventory item: {item_id}"
            raise ValueError(message)

        source.sheet.inventory = [item for item in source.sheet.inventory if item.id != item_id]
        transferred_item.cairn.equipped = False
        target.sheet.inventory = [*target.sheet.inventory, transferred_item]
        self._recompute_derived(source.sheet)
        self._recompute_derived(target.sheet)
        return f"Transferred {transferred_item.name} from {source.name} to {target.name}."

    def use_item(
        self,
        state: GameState,
        *,
        item_id: str,
        intent: str,
        actor_id: str | None = None,
    ) -> OracleOutcome:
        self._require_ready(state)
        actor = self._resolve_actor(state, actor_id)
        target = self._find_item(actor.sheet, item_id)
        if target is None:
            message = f"Unknown inventory item: {item_id}"
            raise ValueError(message)

        resolution = self._resolve_item_use(state, actor, target, intent=intent)
        self._recompute_derived(actor.sheet)
        actor_prefix = "" if actor.is_player else f"{actor.name}: "
        return OracleOutcome(
            kind=OracleKind.PLAYER_ACTION,
            summary=f"{actor_prefix}{resolution.summary}",
            rolls=resolution.rolls,
            question=intent,
            chaos_factor=state.chaos_factor,
            cairn=CairnResolution(
                actor_id=None if actor.is_player else actor.id,
                actor_name=None if actor.is_player else actor.name,
                item_id=item_id,
                item_name=target.name,
                item_power_kind=target.cairn.power.kind,
                item_effect_kind=target.cairn.power.effect,
                effect_summary=resolution.effect_summary,
                uses_before=resolution.uses_before,
                uses_after=resolution.uses_after,
                resource_deltas=list(resolution.resource_deltas),
                recharge_condition=target.cairn.power.recharge_condition or None,
                ability=CairnAbility.WIL if resolution.wil_save_target is not None else None,
                target=resolution.wil_save_target,
                success=resolution.wil_save_success,
                attack_stance=resolution.attack_stance,
                target_name=resolution.target_name,
                hp_before=resolution.hp_before,
                hp_after=resolution.hp_after,
                str_before=resolution.str_before,
                str_after=resolution.str_after,
                dex_before=resolution.dex_before,
                dex_after=resolution.dex_after,
                wil_before=resolution.wil_before,
                wil_after=resolution.wil_after,
                fatigue_before=resolution.fatigue_before,
                fatigue_after=resolution.fatigue_after,
                overloaded=actor.sheet.cairn.overloaded,
            ),
        )

    def _resolve_item_use(
        self,
        state: GameState,
        actor: ResolvedActor,
        item: InventoryItem,
        *,
        intent: str,
    ) -> ItemUseResolution:
        character = actor.sheet
        cairn = character.cairn
        power = self._effective_item_power(item)
        hp_before = cairn.hp
        str_before = cairn.str_score
        dex_before = cairn.dex_score
        wil_before = cairn.wil_score
        fatigue_before = cairn.fatigue
        uses_before = item.cairn.uses
        rolls: list[Roll] = []
        effect_notes: list[str] = []
        attack_stance: AttackStance | None = None
        target_name: str | None = None
        wil_save_target: int | None = None
        wil_save_success: bool | None = None

        if CairnItemTag.LIGHT in item.cairn.tags:
            item.cairn.equipped = True
            effect_notes.append("light readied")

        if item.cairn.uses == 0:
            recharge = f" Recharge: {power.recharge_condition}." if power.recharge_condition else ""
            return ItemUseResolution(
                summary=f"Used {item.name}: no charges remain.{recharge}",
                effect_summary="No effect; the item is depleted.",
                rolls=[],
                uses_before=uses_before,
                uses_after=item.cairn.uses,
                item_removed=False,
                hp_before=hp_before,
                hp_after=cairn.hp,
                str_before=str_before,
                str_after=cairn.str_score,
                dex_before=dex_before,
                dex_after=cairn.dex_score,
                wil_before=wil_before,
                wil_after=cairn.wil_score,
                fatigue_before=fatigue_before,
                fatigue_after=cairn.fatigue,
            )

        resolved_resource_costs = self._resolve_resource_costs(
            actor,
            item,
            item.cairn.use_costs,
        )
        if power.adds_fatigue or power.kind == CairnItemPowerKind.SPELLBOOK:
            cairn.fatigue += 1
            effect_notes.append("Fatigue +1")

        if self._item_use_requires_wil_save(state, character, power):
            wil_save_target = wil_before
            roll = self._roll(D20_SIDES, "item_wil_save")
            rolls.append(roll)
            wil_save_success = self._save_succeeds(roll.result, wil_save_target)
            if not wil_save_success:
                cairn.fatigue += 1
                effect_notes.append("WIL save failed; Fatigue +1")

        effect_summary, attack_stance, target_name = self._apply_item_power_effect(
            cairn,
            power=power,
            intent=intent,
        )
        effect_notes.insert(0, effect_summary)

        resource_deltas = tuple(
            self._consume_resolved_resource_costs(
                resolved_resource_costs,
                actor=actor,
                reason=CairnResourceDeltaReason.ITEM_USE,
            ),
        )
        item_removed = self._spend_item_use(character, item, power)
        uses_after = None if item_removed else item.cairn.uses
        summary = self._item_use_summary(
            item,
            power=power,
            effect_notes=effect_notes,
            uses_before=uses_before,
            uses_after=uses_after,
            item_removed=item_removed,
        )
        return ItemUseResolution(
            summary=summary,
            effect_summary="; ".join(note for note in effect_notes if note),
            rolls=rolls,
            uses_before=uses_before,
            uses_after=uses_after,
            item_removed=item_removed,
            hp_before=hp_before,
            hp_after=cairn.hp,
            str_before=str_before,
            str_after=cairn.str_score,
            dex_before=dex_before,
            dex_after=cairn.dex_score,
            wil_before=wil_before,
            wil_after=cairn.wil_score,
            fatigue_before=fatigue_before,
            fatigue_after=cairn.fatigue,
            attack_stance=attack_stance,
            target_name=target_name,
            wil_save_target=wil_save_target,
            wil_save_success=wil_save_success,
            resource_deltas=resource_deltas,
        )

    def _effective_item_power(self, item: InventoryItem) -> CairnItemPower:
        power = item.cairn.power
        if power.kind != CairnItemPowerKind.NONE or power.effect != CairnItemEffectKind.NONE:
            return power
        tags = set(item.cairn.tags)
        if CairnItemTag.HOLY in tags and CairnItemTag.RELIC in tags:
            return CairnItemPower(
                kind=CairnItemPowerKind.HOLY_RELIC,
                name=item.name,
                summary=item.details,
                effect=CairnItemEffectKind.REVEAL_SIGN,
            )
        if CairnItemTag.RELIC in tags:
            return CairnItemPower(
                kind=CairnItemPowerKind.RELIC,
                name=item.name,
                summary=item.details,
                effect=CairnItemEffectKind.REVEAL_SIGN,
            )
        return power

    def _item_use_requires_wil_save(
        self,
        state: GameState,
        character: CharacterSheet,
        power: CairnItemPower,
    ) -> bool:
        if not power.requires_wil_save_in_danger and power.kind != CairnItemPowerKind.SPELLBOOK:
            return False
        return state.encounter.active or character.cairn.deprived

    def _apply_item_power_effect(  # noqa: C901, PLR0911, PLR0912
        self,
        cairn: CairnCharacterState,
        *,
        power: CairnItemPower,
        intent: str,
    ) -> tuple[str, AttackStance | None, str | None]:
        amount = power.effect_amount
        if power.effect == CairnItemEffectKind.RESTORE_HP:
            before = cairn.hp
            cairn.hp = cairn.max_hp if amount == 0 else min(cairn.max_hp, cairn.hp + amount)
            return (f"HP restored {before}->{cairn.hp}", None, None)
        if power.effect == CairnItemEffectKind.RESTORE_ATTRIBUTE:
            ability = power.effect_ability or (
                CairnAbility.WIL if power.kind == CairnItemPowerKind.HOLY_RELIC else None
            )
            if ability is None:
                return ("no attribute named for restoration", None, None)
            before, after = self._restore_attribute(cairn, ability, amount)
            return (f"{ability.value} restored {before}->{after}", None, None)
        if power.effect == CairnItemEffectKind.CLEAR_CONDITION:
            condition = power.clears_condition
            if condition is None:
                return ("no condition named to clear", None, None)
            cleared = self._clear_condition(cairn, condition)
            return (
                f"{condition.value.replace('_', ' ')} {'cleared' if cleared else 'unchanged'}",
                None,
                None,
            )
        if power.effect == CairnItemEffectKind.ENHANCE_ATTACK:
            return (
                "next relevant attack is Enhanced by position or permission",
                AttackStance.ENHANCED,
                None,
            )
        if power.effect == CairnItemEffectKind.IMPAIR_TARGET:
            return (
                "target opposition is Impaired by the item effect",
                AttackStance.IMPAIRED,
                intent,
            )
        if power.effect == CairnItemEffectKind.FORCE_SAVE:
            ability = power.effect_ability or CairnAbility.WIL
            return (f"the target must make a {ability.value} save if they resist", None, intent)
        if power.effect == CairnItemEffectKind.CREATE_SAFE_PASSAGE:
            return ("a narrow safe passage or escape permission is established", None, None)
        if power.effect == CairnItemEffectKind.WARD_OR_PACIFY:
            return (
                "nearby violence or hostile will is warded or pacified if the fiction allows",
                None,
                None,
            )
        if power.effect == CairnItemEffectKind.EXTRAORDINARY_AID:
            before_hp = cairn.hp
            cairn.hp = cairn.max_hp
            cairn.critically_wounded = False
            return (
                f"extraordinary aid restores HP {before_hp}->{cairn.hp} and stabilizes "
                "critical harm",
                None,
                None,
            )
        if power.effect == CairnItemEffectKind.RESURRECT:
            cairn.dead = False
            cairn.critically_wounded = False
            cairn.str_score = max(1, cairn.str_score)
            cairn.hp = cairn.max_hp
            return ("extraordinary aid returns the dead to full health", None, None)
        if power.effect == CairnItemEffectKind.REVEAL_SIGN:
            if power.kind == CairnItemPowerKind.HOLY_RELIC:
                return ("intercession yields a subtle sign, not a standing buff", None, None)
            return ("the item reveals a bounded sign or direction", None, None)
        if power.summary:
            return (power.summary, None, None)
        return (f"used for its ordinary purpose: {intent}", None, None)

    def _restore_attribute(
        self,
        cairn: CairnCharacterState,
        ability: CairnAbility,
        amount: int,
    ) -> tuple[int, int]:
        if ability == CairnAbility.STR:
            before = cairn.str_score
            cairn.str_score = (
                cairn.max_str_score
                if amount == 0
                else min(
                    cairn.max_str_score,
                    cairn.str_score + amount,
                )
            )
            return (before, cairn.str_score)
        if ability == CairnAbility.DEX:
            before = cairn.dex_score
            cairn.dex_score = (
                cairn.max_dex_score
                if amount == 0
                else min(
                    cairn.max_dex_score,
                    cairn.dex_score + amount,
                )
            )
            return (before, cairn.dex_score)
        before = cairn.wil_score
        cairn.wil_score = (
            cairn.max_wil_score
            if amount == 0
            else min(
                cairn.max_wil_score,
                cairn.wil_score + amount,
            )
        )
        return (before, cairn.wil_score)

    def _clear_condition(self, cairn: CairnCharacterState, condition: CairnConditionKey) -> bool:
        if condition == CairnConditionKey.DEPRIVED:
            was_active = cairn.deprived
            cairn.survival.food_deprived = False
            cairn.survival.sleep_deprived = False
            cairn.survival.other_deprived = False
            sync_survival_flags(cairn)
            return was_active
        if condition == CairnConditionKey.CRITICALLY_WOUNDED:
            was_active = cairn.critically_wounded
            cairn.critically_wounded = False
            return was_active
        if condition == CairnConditionKey.DOOMED:
            was_active = cairn.doomed
            cairn.doomed = False
            return was_active
        if condition == CairnConditionKey.PARALYZED:
            was_active = cairn.paralyzed
            cairn.dex_score = max(1, cairn.dex_score)
            cairn.paralyzed = False
            return was_active
        was_active = cairn.delirious
        cairn.wil_score = max(1, cairn.wil_score)
        cairn.delirious = False
        return was_active

    def _spend_item_use(
        self,
        character: CharacterSheet,
        item: InventoryItem,
        power: CairnItemPower,
    ) -> bool:
        if item.cairn.uses is not None:
            item.cairn.uses = max(0, item.cairn.uses - 1)
        should_remove = (
            power.consumed_on_use
            or power.kind == CairnItemPowerKind.SCROLL
            or CairnItemTag.CONSUMABLE in item.cairn.tags
        )
        if should_remove and (item.cairn.uses is None or item.cairn.uses == 0):
            character.inventory = [
                candidate for candidate in character.inventory if candidate.id != item.id
            ]
            return True
        return False

    def _item_use_summary(  # noqa: PLR0913
        self,
        item: InventoryItem,
        *,
        power: CairnItemPower,
        effect_notes: list[str],
        uses_before: int | None,
        uses_after: int | None,
        item_removed: bool,
    ) -> str:
        label = power.name.strip() or item.name
        effect = "; ".join(note for note in effect_notes if note)
        if item_removed:
            return f"Used {label}: {effect}. Item consumed."
        if uses_before is not None:
            recharge = f" Recharge: {power.recharge_condition}." if power.recharge_condition else ""
            return f"Used {label}: {effect}. Uses {uses_before}->{uses_after}.{recharge}"
        return f"Used {label}: {effect}. No limited uses were consumed."

    def drop_item(
        self,
        state: GameState,
        *,
        item_id: str,
        actor_id: str | None = None,
    ) -> str:
        self._require_ready(state)
        actor = self._resolve_actor(state, actor_id)
        target = self._find_item(actor.sheet, item_id)
        if target is None:
            message = f"Unknown inventory item: {item_id}"
            raise ValueError(message)

        actor.sheet.inventory = [item for item in actor.sheet.inventory if item.id != item_id]
        self._recompute_derived(actor.sheet)
        actor_prefix = "" if actor.is_player else f"{actor.name} "
        return f"{actor_prefix}dropped {target.name}."

    def _resolve_actor(self, state: GameState, actor_id: str | None) -> ResolvedActor:
        if actor_id is None or actor_id == "player":
            return ResolvedActor(
                id="player",
                name=state.character.name,
                sheet=state.character,
                is_player=True,
            )
        for member in state.party_members:
            if member.id == actor_id and member.active:
                if member.sheet.cairn.source == CairnMechanicsSource.UNSET:
                    message = f"Cairn mechanics are not available for {member.display_label()} yet."
                    raise ValueError(message)
                return ResolvedActor(
                    id=member.id,
                    name=member.display_label(),
                    sheet=member.sheet,
                    is_player=False,
                )
        message = f"Unknown active party member: {actor_id}"
        raise ValueError(message)

    def _recompute_derived(self, character: CharacterSheet) -> None:
        cairn = character.cairn
        weapons = [item for item in character.inventory if CairnItemTag.WEAPON in item.cairn.tags]
        equipped_weapons = [item for item in weapons if item.cairn.equipped]
        primary_weapon = next(
            (item for item in equipped_weapons if item.id == cairn.primary_weapon_item_id),
            equipped_weapons[0] if equipped_weapons else (weapons[0] if weapons else None),
        )

        for weapon in weapons:
            weapon.cairn.equipped = primary_weapon is not None and weapon.id == primary_weapon.id
        cairn.primary_weapon_item_id = primary_weapon.id if primary_weapon is not None else None

        cairn.armor = min(
            MAX_ARMOR,
            sum(
                item.cairn.armor_bonus
                for item in character.inventory
                if item.cairn.equipped
                and (
                    CairnItemTag.ARMOR in item.cairn.tags or CairnItemTag.SHIELD in item.cairn.tags
                )
            ),
        )
        cairn.slots_used = cairn.fatigue + sum(item.cairn.slots for item in character.inventory)
        cairn.overloaded = cairn.slots_used >= cairn.slots_total
        sync_survival_flags(cairn)
        if cairn.overloaded:
            cairn.hp = 0
        cairn.paralyzed = cairn.dex_score == 0
        cairn.delirious = cairn.wil_score == 0
        cairn.dead = cairn.dead or cairn.str_score == 0

    def _resolve_weapon(
        self,
        character: CharacterSheet,
        weapon_item_id: str | None,
    ) -> InventoryItem | None:
        if weapon_item_id is not None:
            explicit = self._find_item(character, weapon_item_id)
            if explicit is not None and CairnItemTag.WEAPON in explicit.cairn.tags:
                return explicit
        if character.cairn.primary_weapon_item_id is not None:
            primary = self._find_item(character, character.cairn.primary_weapon_item_id)
            if primary is not None:
                return primary
        return next(
            (item for item in character.inventory if CairnItemTag.WEAPON in item.cairn.tags),
            None,
        )

    def _find_item(self, character: CharacterSheet, item_id: str) -> InventoryItem | None:
        return next((item for item in character.inventory if item.id == item_id), None)
