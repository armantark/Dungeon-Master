# ruff: noqa: PLR2004

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TYPE_CHECKING

from dungeon_master.mechanics.inventory import ResolvedActor, sync_survival_flags
from dungeon_master.models import (
    AttackStance,
    CairnAbility,
    CairnCharacterState,
    CairnMechanicsSource,
    CharacterSheet,
    EncounterEndReason,
    EncounterState,
    EnemyCombatant,
    GameState,
    InventoryItem,
    PendingEncounterAdvantage,
    Roll,
)

D20_SIDES = 20
D6_SIDES = 6
D4_SIDES = 4
D8_SIDES = 8
D12_SIDES = 12
STR_BRANCH_MAX = 2
DEX_BRANCH_MAX = 4
LASTING_SCAR_LOCATIONS: tuple[str, ...] = ("Neck", "Hands", "Eye", "Chest", "Legs", "Ear")
BROKEN_LIMB_PARTS: tuple[str, ...] = ("Leg", "Leg", "Arm", "Arm", "Rib", "Skull")


@dataclass(frozen=True)
class HarmApplication:
    source: str
    summary: str
    rolls: list[Roll]
    armor_value: int
    damage_after_armor: int
    hp_before: int
    hp_after: int
    str_before: int
    str_after: int
    scar_result: str | None


class CombatConsequences:
    _rng: random.Random

    if TYPE_CHECKING:

        def _recompute_derived(self, character: CharacterSheet) -> None: ...

    def _require_target(self, encounter: EncounterState, target_name: str) -> EnemyCombatant:
        target = self._find_combatant(encounter, target_name)
        if target is None:
            message = f"No active foe matches '{target_name}'."
            raise ValueError(message)
        return target

    def _resolve_opening_attack_target(
        self,
        encounter: EncounterState,
        target_name: str,
    ) -> EnemyCombatant:
        matched = self._find_combatant(encounter, target_name)
        if matched is not None:
            return matched

        active = [
            combatant
            for combatant in encounter.combatants
            if not combatant.defeated and not combatant.fled
        ]
        if not active:
            message = "No active foe is available for the opening attack."
            raise ValueError(message)

        leader = next((combatant for combatant in active if combatant.leader), None)
        return leader or active[0]

    def _find_combatant(self, encounter: EncounterState, target_name: str) -> EnemyCombatant | None:
        cleaned = target_name.strip().lower()
        active = [
            combatant
            for combatant in encounter.combatants
            if not combatant.defeated and not combatant.fled
        ]
        for combatant in active:
            name = combatant.name.lower()
            if cleaned == name or cleaned in name or name in cleaned:
                return combatant
        return None

    def _has_active_enemies(self, encounter: EncounterState) -> bool:
        return any(
            not combatant.defeated and not combatant.fled for combatant in encounter.combatants
        )

    def _consume_pending_advantage(
        self,
        encounter: EncounterState,
        actor: ResolvedActor,
        target: EnemyCombatant,
    ) -> PendingEncounterAdvantage | None:
        for index, advantage in enumerate(encounter.pending_advantages):
            actor_matches = advantage.actor_id == (None if actor.is_player else actor.id)
            target_matches = (
                advantage.target_combatant_id == target.id
                or advantage.target_name.lower() == target.name.lower()
            )
            if actor_matches and target_matches:
                return encounter.pending_advantages.pop(index)
        return None

    def _save_succeeds(self, result: int, target: int) -> bool:
        return result == 1 or (result != D20_SIDES and result <= target)

    def _apply_harm_to_character(
        self,
        cairn: CairnCharacterState,
        *,
        amount: int,
        source: str,
        in_combat: bool,
        armor_applies: bool,
    ) -> HarmApplication:
        armor_value = cairn.armor if armor_applies and in_combat else 0
        damage_after_armor = max(0, amount - armor_value)
        hp_before = cairn.hp
        str_before = cairn.str_score
        rolls: list[Roll] = []
        scar_result: str | None = None

        if damage_after_armor == 0:
            summary = f"No harm taken from {source}; armor absorbed the blow."
        elif in_combat:
            hp_after = hp_before - damage_after_armor
            if hp_after > 0:
                cairn.hp = hp_after
                summary = f"Took {damage_after_armor} damage from {source}."
            elif hp_after == 0:
                cairn.hp = 0
                scar_result, scar_rolls = self._apply_scar(cairn, damage_after_armor)
                rolls.extend(scar_rolls)
                summary = f"Reduced to 0 HP by {source}; scar rolled: {scar_result}"
            else:
                cairn.hp = 0
                overflow = abs(hp_after)
                cairn.str_score = max(0, cairn.str_score - overflow)
                save_roll = self._roll(D20_SIDES, "critical_damage")
                rolls.append(save_roll)
                success = self._save_succeeds(save_roll.result, cairn.str_score)
                if not success:
                    cairn.critically_wounded = True
                if cairn.str_score == 0:
                    cairn.dead = True
                summary = (
                    f"Critical damage from {source}: {overflow} STR lost and "
                    f"critical save {'passed' if success else 'failed'}."
                )
        else:
            cairn.str_score = max(0, cairn.str_score - damage_after_armor)
            if cairn.str_score == 0:
                cairn.dead = True
            summary = f"Suffered {damage_after_armor} STR damage from {source}."

        return HarmApplication(
            source=source,
            summary=summary,
            rolls=rolls,
            armor_value=armor_value,
            damage_after_armor=damage_after_armor,
            hp_before=hp_before,
            hp_after=cairn.hp,
            str_before=str_before,
            str_after=cairn.str_score,
            scar_result=scar_result,
        )

    def _apply_harm_to_combatant(
        self,
        combatant: EnemyCombatant,
        damage_after_armor: int,
    ) -> tuple[str, list[Roll], bool, bool]:
        rolls: list[Roll] = []
        lone_zero_triggered = False
        if damage_after_armor == 0:
            return ("Armor or poor positioning turned the blow aside.", rolls, False, False)

        hp_after = combatant.hp - damage_after_armor
        if hp_after > 0:
            combatant.hp = hp_after
            return (f"{combatant.name} loses {damage_after_armor} HP.", rolls, False, False)

        if hp_after == 0:
            combatant.hp = 0
            lone_zero_triggered = True
            return (
                f"{combatant.name} is driven to 0 HP and wavers.",
                rolls,
                False,
                lone_zero_triggered,
            )

        combatant.hp = 0
        overflow = abs(hp_after)
        combatant.str_score = max(0, combatant.str_score - overflow)
        save_roll = self._roll(D20_SIDES, "enemy_critical_damage")
        rolls.append(save_roll)
        success = self._save_succeeds(save_roll.result, combatant.str_score)
        if not success or combatant.str_score == 0:
            combatant.critically_wounded = True
            combatant.defeated = True
            return (
                f"{combatant.name} suffers critical damage, loses {overflow} STR, and collapses.",
                rolls,
                True,
                False,
            )
        combatant.critically_wounded = True
        return (
            f"{combatant.name} suffers critical damage but remains in the fight.",
            rolls,
            False,
            False,
        )

    def _resolve_enemy_turn(
        self,
        state: GameState,
        encounter: EncounterState,
        *,
        defender: CharacterSheet | None = None,
        preferred_attacker_name: str | None = None,
    ) -> HarmApplication:
        target_sheet = defender or state.character
        active = [
            combatant
            for combatant in encounter.combatants
            if not combatant.defeated and not combatant.fled
        ]
        if not active:
            return HarmApplication(
                source="No active foes",
                summary="No enemy retaliation; no active foes remain.",
                rolls=[],
                armor_value=target_sheet.cairn.armor,
                damage_after_armor=0,
                hp_before=target_sheet.cairn.hp,
                hp_after=target_sheet.cairn.hp,
                str_before=target_sheet.cairn.str_score,
                str_after=target_sheet.cairn.str_score,
                scar_result=None,
            )

        preferred_attacker = (
            self._find_combatant(encounter, preferred_attacker_name)
            if preferred_attacker_name is not None
            else None
        )
        if (
            preferred_attacker is not None
            and not preferred_attacker.defeated
            and not preferred_attacker.fled
        ):
            enemy_rolls = [
                (
                    preferred_attacker,
                    self._roll(
                        preferred_attacker.weapon_damage_die,
                        f"enemy_damage_{preferred_attacker.id}",
                    ),
                ),
            ]
        else:
            enemy_rolls = [
                (combatant, self._roll(combatant.weapon_damage_die, f"enemy_damage_{combatant.id}"))
                for combatant in active
            ]
        highest_combatant, highest_roll = max(enemy_rolls, key=lambda pair: pair[1].result)
        applied = self._apply_harm_to_character(
            target_sheet.cairn,
            amount=highest_roll.result,
            source=highest_combatant.name,
            in_combat=True,
            armor_applies=True,
        )
        return HarmApplication(
            source=highest_combatant.name,
            summary=applied.summary,
            rolls=[roll for _, roll in enemy_rolls] + applied.rolls,
            armor_value=applied.armor_value,
            damage_after_armor=applied.damage_after_armor,
            hp_before=applied.hp_before,
            hp_after=applied.hp_after,
            str_before=applied.str_before,
            str_after=applied.str_after,
            scar_result=applied.scar_result,
        )

    def _empty_harm_application(
        self,
        state: GameState,
        *,
        source: str,
        defender: CharacterSheet | None = None,
    ) -> HarmApplication:
        target_sheet = defender or state.character
        return HarmApplication(
            source=source,
            summary="No enemy retaliation landed.",
            rolls=[],
            armor_value=target_sheet.cairn.armor,
            damage_after_armor=0,
            hp_before=target_sheet.cairn.hp,
            hp_after=target_sheet.cairn.hp,
            str_before=target_sheet.cairn.str_score,
            str_after=target_sheet.cairn.str_score,
            scar_result=None,
        )

    def _highest_enemy_pursuit_target(self, encounter: EncounterState) -> int:
        active = [
            combatant
            for combatant in encounter.combatants
            if not combatant.defeated and not combatant.fled
        ]
        if not active:
            return 1
        return max(combatant.dex_score for combatant in active)

    def _maybe_resolve_enemy_morale(
        self,
        encounter: EncounterState,
        *,
        lone_zero_triggered: bool,
    ) -> tuple[Roll | None, int | None, bool | None, list[str]]:
        active = [
            combatant
            for combatant in encounter.combatants
            if not combatant.defeated and not combatant.fled
        ]
        total = len(encounter.combatants)
        defeated_or_fled = [
            combatant for combatant in encounter.combatants if combatant.defeated or combatant.fled
        ]
        if not active:
            encounter.active = False
            encounter.end_reason = EncounterEndReason.VICTORY
            return (None, None, None, [])

        check_needed = False
        if lone_zero_triggered and len(active) == 1 and active[0].hp == 0:
            check_needed = True
        elif not encounter.casualty_morale_checked and defeated_or_fled:
            check_needed = True
            encounter.casualty_morale_checked = True
            if len(defeated_or_fled) * 2 >= total:
                encounter.half_force_morale_checked = True
        elif not encounter.half_force_morale_checked and len(defeated_or_fled) * 2 >= total:
            check_needed = True
            encounter.half_force_morale_checked = True

        if not check_needed:
            return (None, None, None, [])

        leader = next((combatant for combatant in active if combatant.leader), active[0])
        target = leader.wil_score
        roll = self._roll(D20_SIDES, "morale")
        success = self._save_succeeds(roll.result, target)
        if success:
            return (roll, target, True, [])

        fled_ids: list[str] = []
        for combatant in active:
            combatant.fled = True
            fled_ids.append(combatant.id)
        encounter.active = False
        encounter.end_reason = EncounterEndReason.ENEMY_ROUT
        encounter.notes = "The remaining enemies broke and fled."
        return (roll, target, False, fled_ids)

    def _resolve_enemy_morale(
        self,
        encounter: EncounterState,
    ) -> tuple[Roll | None, int | None, bool | None, list[str]]:
        active = [
            combatant
            for combatant in encounter.combatants
            if not combatant.defeated and not combatant.fled
        ]
        if not active:
            encounter.active = False
            encounter.end_reason = EncounterEndReason.VICTORY
            return (None, None, None, [])
        leader = next((combatant for combatant in active if combatant.leader), active[0])
        target = leader.wil_score
        roll = self._roll(D20_SIDES, "morale")
        success = self._save_succeeds(roll.result, target)
        if success:
            return (roll, target, True, [])
        fled_ids: list[str] = []
        for combatant in active:
            combatant.fled = True
            fled_ids.append(combatant.id)
        encounter.active = False
        encounter.end_reason = EncounterEndReason.ENEMY_ROUT
        encounter.notes = "The remaining enemies broke and fled."
        return (roll, target, False, fled_ids)

    def _attack_summary(
        self,
        *,
        attack_summary: str,
        enemy_summary: str,
        encounter: EncounterState,
    ) -> str:
        if encounter.active:
            return (
                f"{attack_summary} {enemy_summary} Combat presses into round "
                f"{encounter.round_number}."
            )
        return f"{attack_summary} {enemy_summary} The immediate fight is no longer active."

    def _require_ready(self, state: GameState) -> None:
        if state.character.cairn.source == CairnMechanicsSource.UNSET:
            message = "Cairn mechanics are not available for this character yet."
            raise ValueError(message)

    def _apply_scar(  # noqa: C901, PLR0911, PLR0912, PLR0915
        self,
        cairn: CairnCharacterState,
        hp_lost: int,
    ) -> tuple[str, list[Roll]]:
        rolls: list[Roll] = []
        entry = max(1, min(12, hp_lost))
        if entry == 1:
            location_roll = self._roll(D6_SIDES, "scar_location")
            hp_roll = self._roll(D6_SIDES, "scar_hp")
            rolls.extend((location_roll, hp_roll))
            cairn.max_hp = max(cairn.max_hp, hp_roll.result)
            return (
                f"Lasting Scar ({LASTING_SCAR_LOCATIONS[location_roll.result - 1]})",
                rolls,
            )
        if entry == 2:
            hp_roll = self._roll(D6_SIDES, "scar_hp")
            rolls.append(hp_roll)
            cairn.max_hp = max(cairn.max_hp, hp_roll.result)
            return ("Rattling Blow", rolls)
        if entry == 3:
            hp_roll = self._roll(D6_SIDES, "scar_hp")
            rolls.append(hp_roll)
            cairn.max_hp += hp_roll.result
            cairn.survival.other_deprived = True
            sync_survival_flags(cairn)
            return ("Walloped", rolls)
        if entry == 4:
            part_roll = self._roll(D6_SIDES, "scar_part")
            hp_roll = self._roll(D8_SIDES, "scar_hp")
            rolls.extend((part_roll, hp_roll))
            cairn.max_hp = max(cairn.max_hp, hp_roll.result)
            cairn.critically_wounded = True
            return (f"Broken Limb ({BROKEN_LIMB_PARTS[part_roll.result - 1]})", rolls)
        if entry == 5:
            hp_roll = self._roll(D8_SIDES, "scar_hp")
            rolls.append(hp_roll)
            cairn.max_hp = max(cairn.max_hp, hp_roll.result)
            return ("Diseased", rolls)
        if entry == 6:
            ability_roll = self._roll(D6_SIDES, "scar_ability")
            stat_roll = self._roll_nd6(3, "scar_attribute")
            rolls.extend((ability_roll, stat_roll))
            value = stat_roll.result
            if ability_roll.result <= STR_BRANCH_MAX:
                cairn.max_str_score = max(cairn.max_str_score, value)
                cairn.str_score = min(value, cairn.max_str_score)
                ability = CairnAbility.STR
            elif ability_roll.result <= DEX_BRANCH_MAX:
                cairn.max_dex_score = max(cairn.max_dex_score, value)
                cairn.dex_score = min(value, cairn.max_dex_score)
                ability = CairnAbility.DEX
            else:
                cairn.max_wil_score = max(cairn.max_wil_score, value)
                cairn.wil_score = min(value, cairn.max_wil_score)
                ability = CairnAbility.WIL
            return (f"Reorienting Head Wound ({ability.value})", rolls)
        if entry == 7:
            dex_roll = self._roll_nd6(3, "scar_dex")
            rolls.append(dex_roll)
            value = dex_roll.result
            cairn.max_dex_score = max(cairn.max_dex_score, value)
            return ("Hamstrung", rolls)
        if entry == 8:
            save_roll = self._roll(D20_SIDES, "scar_wil_save")
            bonus_roll = self._roll(D4_SIDES, "scar_wil_bonus")
            rolls.extend((save_roll, bonus_roll))
            success = save_roll.result == 1 or (
                save_roll.result != D20_SIDES and save_roll.result <= cairn.wil_score
            )
            if success:
                cairn.max_wil_score += bonus_roll.result
            return ("Deafened", rolls)
        if entry == 9:
            wil_roll = self._roll_nd6(3, "scar_wil")
            rolls.append(wil_roll)
            value = wil_roll.result
            cairn.max_wil_score = max(cairn.max_wil_score, value)
            return ("Re-brained", rolls)
        if entry == 10:
            save_roll = self._roll(D20_SIDES, "scar_wil_save")
            bonus_roll = self._roll(D6_SIDES, "scar_wil_bonus")
            rolls.extend((save_roll, bonus_roll))
            success = save_roll.result == 1 or (
                save_roll.result != D20_SIDES and save_roll.result <= cairn.wil_score
            )
            if success:
                cairn.max_wil_score += bonus_roll.result
            cairn.critically_wounded = True
            return ("Sundered", rolls)
        if entry == 11:
            hp_roll = self._roll(D8_SIDES, "scar_hp")
            rolls.append(hp_roll)
            cairn.max_hp = hp_roll.result
            cairn.survival.other_deprived = True
            sync_survival_flags(cairn)
            cairn.critically_wounded = True
            return ("Mortal Wound", rolls)

        hp_roll = self._roll_nd6(3, "scar_hp")
        rolls.append(hp_roll)
        cairn.max_hp = max(cairn.max_hp, hp_roll.result)
        cairn.doomed = True
        return ("Doomed", rolls)

    def _attack_die(self, weapon: InventoryItem | None, stance: AttackStance) -> int:
        if stance == AttackStance.IMPAIRED:
            return D4_SIDES
        if stance == AttackStance.ENHANCED:
            return D12_SIDES
        if weapon is None or weapon.cairn.weapon_damage_die is None:
            return D4_SIDES
        return weapon.cairn.weapon_damage_die

    def _ability_score(self, cairn: CairnCharacterState, ability: CairnAbility) -> int:
        if ability == CairnAbility.STR:
            return cairn.str_score
        if ability == CairnAbility.DEX:
            return cairn.dex_score
        return cairn.wil_score

    def _roll(self, sides: int, label: str) -> Roll:
        return Roll(sides=sides, result=self._rng.randint(1, sides), label=label)

    def _roll_nd6(self, count: int, label: str) -> Roll:
        return Roll(
            sides=D6_SIDES * count,
            result=sum(self._rng.randint(1, D6_SIDES) for _ in range(count)),
            label=label,
        )
