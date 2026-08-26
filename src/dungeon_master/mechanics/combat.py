# ruff: noqa: PLR2004

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TYPE_CHECKING

from dungeon_master.cancel import CancellationToken
from dungeon_master.mechanics.combat_consequences import (
    CombatConsequences,
)
from dungeon_master.mechanics.combat_consequences import (
    HarmApplication as _HarmApplication,
)
from dungeon_master.mechanics.inventory import ResolvedActor
from dungeon_master.mechanics.survival import ResolvedResourceCost
from dungeon_master.models import (
    AttackStance,
    CairnAbility,
    CairnResolution,
    CairnResourceCost,
    CairnResourceDelta,
    CairnResourceDeltaReason,
    CampaignDangerProfile,
    CharacterSheet,
    CoordinatedAttackParticipant,
    EncounterAdvantagePayoff,
    EncounterEndReason,
    EncounterInitiator,
    EncounterState,
    EncounterThreatLevel,
    GameState,
    InventoryItem,
    OracleKind,
    OracleOutcome,
    PendingEncounterAdvantage,
    RetreatOutcome,
    Roll,
)

HarmApplication = _HarmApplication

D20_SIDES = 20
D6_SIDES = 6
D4_SIDES = 4
D8_SIDES = 8
D10_SIDES = 10
D12_SIDES = 12
STR_BRANCH_MAX = 2
DEX_BRANCH_MAX = 4
ALLOWED_WEAPON_DICE: tuple[int, ...] = (D4_SIDES, D6_SIDES, D8_SIDES, D10_SIDES, D12_SIDES)
LASTING_SCAR_LOCATIONS: tuple[str, ...] = ("Neck", "Hands", "Eye", "Chest", "Legs", "Ear")
BROKEN_LIMB_PARTS: tuple[str, ...] = ("Leg", "Leg", "Arm", "Arm", "Rib", "Skull")


@dataclass(frozen=True)
class AttackActor:
    id: str | None
    name: str
    sheet: CharacterSheet
    weapon_item_id: str | None = None
    stance: AttackStance = AttackStance.NORMAL


@dataclass(frozen=True)
class EncounterScalingPolicy:
    danger_profile: CampaignDangerProfile
    max_combatants: int
    ordinary_hp_max: int
    hardier_hp_max: int
    serious_hp_max: int
    ordinary_armor_max: int
    hardier_armor_max: int
    serious_armor_max: int

    def hp_cap_for(self, threat_level: EncounterThreatLevel) -> int:
        if threat_level == EncounterThreatLevel.SERIOUS:
            return self.serious_hp_max
        if threat_level == EncounterThreatLevel.HARDIER:
            return self.hardier_hp_max
        return self.ordinary_hp_max

    def armor_cap_for(self, threat_level: EncounterThreatLevel) -> int:
        if threat_level == EncounterThreatLevel.SERIOUS:
            return self.serious_armor_max
        if threat_level == EncounterThreatLevel.HARDIER:
            return self.hardier_armor_max
        return self.ordinary_armor_max

    @classmethod
    def for_danger(cls, danger_profile: CampaignDangerProfile) -> EncounterScalingPolicy:
        if danger_profile == CampaignDangerProfile.STORY:
            return cls(
                danger_profile=danger_profile,
                max_combatants=2,
                ordinary_hp_max=3,
                hardier_hp_max=5,
                serious_hp_max=8,
                ordinary_armor_max=1,
                hardier_armor_max=2,
                serious_armor_max=3,
            )
        if danger_profile == CampaignDangerProfile.HARSH:
            return cls(
                danger_profile=danger_profile,
                max_combatants=4,
                ordinary_hp_max=4,
                hardier_hp_max=7,
                serious_hp_max=12,
                ordinary_armor_max=2,
                hardier_armor_max=3,
                serious_armor_max=3,
            )
        if danger_profile == CampaignDangerProfile.LETHAL:
            return cls(
                danger_profile=danger_profile,
                max_combatants=4,
                ordinary_hp_max=5,
                hardier_hp_max=8,
                serious_hp_max=12,
                ordinary_armor_max=2,
                hardier_armor_max=3,
                serious_armor_max=3,
            )
        return cls(
            danger_profile=danger_profile,
            max_combatants=4,
            ordinary_hp_max=3,
            hardier_hp_max=6,
            serious_hp_max=12,
            ordinary_armor_max=1,
            hardier_armor_max=2,
            serious_armor_max=3,
        )


class CombatMechanics(CombatConsequences):
    _rng: random.Random

    if TYPE_CHECKING:

        def _resolve_actor(self, state: GameState, actor_id: str | None) -> ResolvedActor: ...

        def _ensure_encounter(  # noqa: PLR0913
            self,
            state: GameState,
            *,
            player_input: str,
            target_name: str,
            fallback_target_armor: int,
            initiator: EncounterInitiator,
            cancel_token: CancellationToken | None = None,
        ) -> EncounterState: ...

        def _resolve_weapon(
            self,
            character: CharacterSheet,
            weapon_item_id: str | None,
        ) -> InventoryItem | None: ...

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

        def _recompute_derived(self, character: CharacterSheet) -> None: ...

    def resolve_save(
        self,
        state: GameState,
        ability: CairnAbility,
        reason: str,
        *,
        actor_id: str | None = None,
    ) -> OracleOutcome:
        self._require_ready(state)
        actor = self._resolve_actor(state, actor_id)
        score = self._ability_score(actor.sheet.cairn, ability)
        roll = self._roll(D20_SIDES, "save")
        success = roll.result == 1 or (roll.result != D20_SIDES and roll.result <= score)
        verdict = "passed" if success else "failed"
        actor_prefix = "" if actor.is_player else f"{actor.name}: "
        return OracleOutcome(
            kind=OracleKind.SAVE,
            summary=f"{actor_prefix}{ability.value} save {verdict}: {reason}",
            rolls=[roll],
            question=reason,
            chaos_factor=state.chaos_factor,
            cairn=CairnResolution(
                ability=ability,
                target=score,
                success=success,
                actor_id=None if actor.is_player else actor.id,
                actor_name=None if actor.is_player else actor.name,
            ),
        )

    def resolve_attack(  # noqa: C901, PLR0912, PLR0913, PLR0915
        self,
        state: GameState,
        *,
        target_name: str,
        target_armor: int,
        weapon_item_id: str | None,
        stance: AttackStance,
        actor_id: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> OracleOutcome:
        self._require_ready(state)
        actor = self._resolve_actor(state, actor_id)
        existing_encounter_active = state.encounter.active and self._has_active_enemies(
            state.encounter
        )
        encounter = self._ensure_encounter(
            state,
            player_input=f"Attack {target_name}",
            target_name=target_name,
            fallback_target_armor=target_armor,
            initiator=EncounterInitiator.PLAYER,
            cancel_token=cancel_token,
        )
        target = (
            self._require_target(encounter, target_name)
            if existing_encounter_active
            else self._resolve_opening_attack_target(encounter, target_name)
        )
        pending_advantage = self._consume_pending_advantage(encounter, actor, target)
        weapon = self._resolve_weapon(actor.sheet, weapon_item_id)
        if weapon is None and actor.sheet.cairn.primary_weapon_item_id is not None:
            message = (
                f"{actor.name}'s primary weapon is missing from inventory; "
                "repair or re-equip before resolving an attack."
            )
            raise ValueError(message)
        effective_stance = (
            AttackStance.ENHANCED
            if pending_advantage is not None
            and pending_advantage.payoff == EncounterAdvantagePayoff.ENHANCED_ATTACK
            else stance
        )
        base_die = self._attack_die(weapon, effective_stance)
        round_before = encounter.round_number
        weapon_name = weapon.name if weapon is not None else "Unarmed strike"
        resolved_resource_costs = (
            self._resolve_resource_costs(actor, weapon, weapon.cairn.attack_costs)
            if weapon is not None
            else []
        )
        resource_deltas: list[CairnResourceDelta] = []
        rolls: list[Roll] = []
        combat_started = encounter.round_number == 1 and encounter.first_round_dex_gate_pending
        player_acted = True
        initiative_target: int | None = None

        if encounter.first_round_dex_gate_pending:
            initiative_target = actor.sheet.cairn.dex_score
            initiative_roll = self._roll(D20_SIDES, "initiative")
            rolls.append(initiative_roll)
            player_acted = self._save_succeeds(initiative_roll.result, initiative_target)
            encounter.first_round_dex_gate_pending = False
        encounter.player_disengaged = False
        encounter.pursuit_active = False
        encounter.end_reason = None

        damage_roll = self._roll(base_die, "damage")
        target_hp_before = target.hp
        target_str_before = target.str_score
        target_defeated_before = target.defeated
        _morale_roll: Roll | None = None
        morale_target: int | None = None
        morale_success: bool | None = None
        defeated_ids: list[str] = []
        fled_ids: list[str] = []
        attack_rolls: list[Roll] = []

        if player_acted:
            if weapon is not None:
                resource_deltas = self._consume_resolved_resource_costs(
                    resolved_resource_costs,
                    actor=actor,
                    reason=CairnResourceDeltaReason.ATTACK,
                )
            rolls.append(damage_roll)
            damage_after_armor = max(0, damage_roll.result - target.armor)
            if (
                pending_advantage is not None
                and pending_advantage.payoff == EncounterAdvantagePayoff.DIRECT_STR_DAMAGE
            ):
                target_str_before = target.str_score
                target.str_score = max(0, target.str_score - damage_after_armor)
                save_roll = self._roll(D20_SIDES, "enemy_critical_damage")
                rolls.append(save_roll)
                target_defeated = not self._save_succeeds(save_roll.result, target.str_score)
                if target_defeated or target.str_score == 0:
                    target.defeated = True
                lone_zero_triggered = False
                damage_summary = (
                    f"{target.name} takes {damage_after_armor} direct STR damage"
                    f"{' and collapses' if target.defeated else ''}."
                )
                attack_rolls = []
            else:
                (
                    damage_summary,
                    attack_rolls,
                    target_defeated,
                    lone_zero_triggered,
                ) = self._apply_harm_to_combatant(target, damage_after_armor)
            if attack_rolls:
                rolls.extend(attack_rolls)
            if target_defeated and not target_defeated_before:
                defeated_ids.append(target.id)
            (
                _morale_roll,
                morale_target,
                morale_success,
                morale_fled_ids,
            ) = self._maybe_resolve_enemy_morale(
                encounter,
                lone_zero_triggered=lone_zero_triggered,
            )
            fled_ids.extend(morale_fled_ids)
            if target.id in morale_fled_ids:
                target.defeated = False
            if (
                pending_advantage is not None
                and pending_advantage.payoff == EncounterAdvantagePayoff.FORCE_MORALE
            ):
                (
                    _morale_roll,
                    morale_target,
                    morale_success,
                    morale_fled_ids,
                ) = self._resolve_enemy_morale(encounter)
                fled_ids.extend(morale_fled_ids)
            actor_prefix = "" if actor.is_player else f"{actor.name} "
            attack_summary = f"{actor_prefix}attacks {target.name}: {weapon_name}. {damage_summary}"
        else:
            damage_after_armor = 0
            actor_prefix = "You" if actor.is_player else actor.name
            attack_summary = (
                f"{actor_prefix} lost the first round and failed to act before "
                f"{target.name} could close."
            )

        if (
            pending_advantage is not None
            and pending_advantage.payoff == EncounterAdvantagePayoff.DENY_ENEMY_ACTION
        ):
            enemy_harm = self._empty_harm_application(
                state,
                source="Enemy action denied by advantage",
                defender=actor.sheet,
            )
        else:
            enemy_harm = self._resolve_enemy_turn(state, encounter, defender=actor.sheet)
        rolls.extend(enemy_harm.rolls)
        encounter.active = self._has_active_enemies(encounter)
        if encounter.active:
            encounter.round_number += 1
            encounter.end_reason = None
        elif fled_ids:
            encounter.end_reason = EncounterEndReason.ENEMY_ROUT
            encounter.notes = "The remaining enemies broke and fled."
        else:
            encounter.end_reason = EncounterEndReason.VICTORY
            encounter.notes = "No active foes remain."

        return OracleOutcome(
            kind=OracleKind.ATTACK,
            summary=self._attack_summary(
                attack_summary=attack_summary,
                enemy_summary=enemy_harm.summary,
                encounter=encounter,
            ),
            rolls=rolls,
            question=f"Attack {target.name}",
            chaos_factor=state.chaos_factor,
            cairn=CairnResolution(
                combat_round=round_before,
                combat_started=combat_started,
                combat_active=encounter.active,
                combat_initiator=encounter.initiator,
                player_acted=player_acted,
                initiative_target=initiative_target,
                advantage_id=None if pending_advantage is None else pending_advantage.id,
                advantage_setup=None if pending_advantage is None else pending_advantage.setup,
                advantage_payoff=None if pending_advantage is None else pending_advantage.payoff,
                advantage_target_name=None
                if pending_advantage is None
                else pending_advantage.target_name,
                advantage_applied=pending_advantage is not None,
                advantage_consumed=pending_advantage is not None,
                weakness=(
                    None
                    if pending_advantage is None or pending_advantage.weakness == ""
                    else pending_advantage.weakness
                ),
                actor_id=None if actor.is_player else actor.id,
                actor_name=None if actor.is_player else actor.name,
                weapon_item_id=weapon.id if weapon is not None else None,
                weapon_name=weapon_name,
                target_combatant_id=target.id,
                target_name=target.name,
                target_armor=target.armor,
                attack_stance=effective_stance,
                base_damage=damage_roll.result if player_acted else None,
                damage_after_armor=damage_after_armor,
                target_hp_before=target_hp_before,
                target_hp_after=target.hp,
                target_str_before=target_str_before,
                target_str_after=target.str_score,
                target_defeated=target.defeated,
                target_fled=target.fled,
                hp_before=enemy_harm.hp_before,
                hp_after=enemy_harm.hp_after,
                str_before=enemy_harm.str_before,
                str_after=enemy_harm.str_after,
                enemy_damage=enemy_harm.damage_after_armor,
                enemy_damage_source=enemy_harm.source if enemy_harm.damage_after_armor else None,
                morale_target=morale_target,
                morale_success=morale_success,
                defeated_combatant_ids=defeated_ids,
                fled_combatant_ids=fled_ids,
                scar_result=enemy_harm.scar_result,
                overloaded=actor.sheet.cairn.overloaded,
                resource_deltas=resource_deltas,
            ),
        )

    def resolve_coordinated_attack(  # noqa: C901, PLR0912, PLR0915
        self,
        state: GameState,
        *,
        target_name: str,
        target_armor: int,
        participants: tuple[AttackActor, ...],
        cancel_token: CancellationToken | None = None,
    ) -> OracleOutcome:
        self._require_ready(state)
        if len(participants) < 2:
            message = "Coordinated attacks require at least two participants."
            raise ValueError(message)
        existing_encounter_active = state.encounter.active and self._has_active_enemies(
            state.encounter
        )
        encounter = self._ensure_encounter(
            state,
            player_input=f"Coordinated attack {target_name}",
            target_name=target_name,
            fallback_target_armor=target_armor,
            initiator=EncounterInitiator.PLAYER,
            cancel_token=cancel_token,
        )
        target = (
            self._require_target(encounter, target_name)
            if existing_encounter_active
            else self._resolve_opening_attack_target(encounter, target_name)
        )
        round_before = encounter.round_number
        combat_started = encounter.round_number == 1 and encounter.first_round_dex_gate_pending
        player_acted = True
        initiative_target: int | None = None
        rolls: list[Roll] = []

        if encounter.first_round_dex_gate_pending:
            initiative_target = min(actor.sheet.cairn.dex_score for actor in participants)
            initiative_roll = self._roll(D20_SIDES, "initiative")
            rolls.append(initiative_roll)
            player_acted = self._save_succeeds(initiative_roll.result, initiative_target)
            encounter.first_round_dex_gate_pending = False
        encounter.player_disengaged = False
        encounter.pursuit_active = False
        encounter.end_reason = None

        participants_out: list[CoordinatedAttackParticipant] = []
        defeated_ids: list[str] = []
        fled_ids: list[str] = []
        morale_target: int | None = None
        morale_success: bool | None = None
        total_damage_after_armor = 0
        base_damage: int | None = None
        target_hp_before_all = target.hp
        target_str_before_all = target.str_score
        target_defeated_before = target.defeated
        target_defeated = target.defeated
        lone_zero_triggered = False
        attack_summaries: list[str] = []
        resource_deltas: list[CairnResourceDelta] = []
        preflight_resource_costs: list[list[ResolvedResourceCost]] = []
        preflight_actors: list[ResolvedActor] = []

        for participant in participants:
            preflight_actor = self._resolve_actor(state, participant.id)
            preflight_weapon = self._resolve_weapon(participant.sheet, participant.weapon_item_id)
            if (
                preflight_weapon is None
                and participant.sheet.cairn.primary_weapon_item_id is not None
            ):
                message = (
                    f"{participant.name}'s primary weapon is missing from inventory; "
                    "repair or re-equip before resolving an attack."
                )
                raise ValueError(message)
            preflight_actors.append(preflight_actor)
            preflight_resource_costs.append(
                self._resolve_resource_costs(
                    preflight_actor,
                    preflight_weapon,
                    preflight_weapon.cairn.attack_costs,
                )
                if preflight_weapon is not None
                else [],
            )

        for index, participant in enumerate(participants):
            weapon = self._resolve_weapon(participant.sheet, participant.weapon_item_id)
            if weapon is None and participant.sheet.cairn.primary_weapon_item_id is not None:
                message = (
                    f"{participant.name}'s primary weapon is missing from inventory; "
                    "repair or re-equip before resolving an attack."
                )
                raise ValueError(message)
            weapon_name = weapon.name if weapon is not None else "Unarmed strike"
            before_hp = target.hp
            before_str = target.str_score
            participant_base_damage: int | None = None
            participant_damage = 0

            if player_acted and not target.defeated and not target.fled:
                resolved_actor = preflight_actors[index]
                if weapon is not None:
                    resource_deltas.extend(
                        self._consume_resolved_resource_costs(
                            preflight_resource_costs[index],
                            actor=resolved_actor,
                            reason=CairnResourceDeltaReason.ATTACK,
                        ),
                    )
                damage_roll = self._roll(
                    self._attack_die(weapon, participant.stance),
                    f"damage_{participant.id or 'player'}",
                )
                rolls.append(damage_roll)
                participant_base_damage = damage_roll.result
                if base_damage is None:
                    base_damage = damage_roll.result
                participant_damage = max(0, damage_roll.result - target.armor)
                total_damage_after_armor += participant_damage
                (
                    damage_summary,
                    attack_rolls,
                    target_defeated,
                    participant_lone_zero,
                ) = self._apply_harm_to_combatant(target, participant_damage)
                if attack_rolls:
                    rolls.extend(attack_rolls)
                lone_zero_triggered = lone_zero_triggered or participant_lone_zero
                attack_summaries.append(
                    f"{participant.name} attacks {target.name}: {weapon_name}. {damage_summary}",
                )
            else:
                attack_summaries.append(
                    f"{participant.name} could not land their coordinated strike before "
                    f"{target.name} closed.",
                )

            participants_out.append(
                CoordinatedAttackParticipant(
                    actor_id=participant.id,
                    actor_name=participant.name,
                    weapon_item_id=weapon.id if weapon is not None else None,
                    weapon_name=weapon_name,
                    base_damage=participant_base_damage,
                    damage_after_armor=participant_damage,
                    target_hp_before=before_hp,
                    target_hp_after=target.hp,
                    target_str_before=before_str,
                    target_str_after=target.str_score,
                    target_defeated=target.defeated,
                    target_fled=target.fled,
                    acted=player_acted,
                ),
            )
            if target.defeated or target.fled:
                break

        if player_acted:
            if target_defeated and not target_defeated_before:
                defeated_ids.append(target.id)
            (
                _morale_roll,
                morale_target,
                morale_success,
                morale_fled_ids,
            ) = self._maybe_resolve_enemy_morale(
                encounter,
                lone_zero_triggered=lone_zero_triggered,
            )
            fled_ids.extend(morale_fled_ids)
            if target.id in morale_fled_ids:
                target.defeated = False
            attack_summary = " ".join(attack_summaries)
        else:
            attack_summary = (
                f"The coordinated attack failed the opening DEX gate; "
                f"{target.name} closed before Vrtanes or his companions could act."
            )

        enemy_harm = self._resolve_enemy_turn(state, encounter, defender=state.character)
        rolls.extend(enemy_harm.rolls)
        encounter.active = self._has_active_enemies(encounter)
        if encounter.active:
            encounter.round_number += 1
            encounter.end_reason = None
        elif fled_ids:
            encounter.end_reason = EncounterEndReason.ENEMY_ROUT
            encounter.notes = "The remaining enemies broke and fled."
        else:
            encounter.end_reason = EncounterEndReason.VICTORY
            encounter.notes = "No active foes remain."

        lead = participants_out[0]
        return OracleOutcome(
            kind=OracleKind.ATTACK,
            summary=self._attack_summary(
                attack_summary=attack_summary,
                enemy_summary=enemy_harm.summary,
                encounter=encounter,
            ),
            rolls=rolls,
            question=f"Coordinated attack {target.name}",
            chaos_factor=state.chaos_factor,
            cairn=CairnResolution(
                combat_round=round_before,
                combat_started=combat_started,
                combat_active=encounter.active,
                combat_initiator=encounter.initiator,
                player_acted=player_acted,
                initiative_target=initiative_target,
                actor_id=lead.actor_id,
                actor_name=None if lead.actor_id is None else lead.actor_name,
                weapon_item_id=lead.weapon_item_id,
                weapon_name=lead.weapon_name,
                target_combatant_id=target.id,
                target_name=target.name,
                target_armor=target.armor,
                attack_stance=participants[0].stance,
                base_damage=base_damage,
                damage_after_armor=total_damage_after_armor,
                target_hp_before=target_hp_before_all,
                target_hp_after=target.hp,
                target_str_before=target_str_before_all,
                target_str_after=target.str_score,
                target_defeated=target.defeated,
                target_fled=target.fled,
                hp_before=enemy_harm.hp_before,
                hp_after=enemy_harm.hp_after,
                str_before=enemy_harm.str_before,
                str_after=enemy_harm.str_after,
                enemy_damage=enemy_harm.damage_after_armor,
                enemy_damage_source=enemy_harm.source if enemy_harm.damage_after_armor else None,
                morale_target=morale_target,
                morale_success=morale_success,
                coordinated_attack=True,
                coordinated_participants=participants_out,
                resource_deltas=resource_deltas,
                defeated_combatant_ids=defeated_ids,
                fled_combatant_ids=fled_ids,
                scar_result=enemy_harm.scar_result,
                overloaded=state.character.cairn.overloaded,
            ),
        )

    def setup_advantage(  # noqa: PLR0913
        self,
        state: GameState,
        *,
        target_name: str,
        setup: str,
        payoff: EncounterAdvantagePayoff,
        actor_id: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> OracleOutcome:
        self._require_ready(state)
        actor = self._resolve_actor(state, actor_id)
        encounter = self._ensure_encounter(
            state,
            player_input=setup,
            target_name=target_name,
            fallback_target_armor=0,
            initiator=EncounterInitiator.PLAYER,
            cancel_token=cancel_token,
        )
        target = self._resolve_opening_attack_target(encounter, target_name)
        advantage = PendingEncounterAdvantage(
            actor_id=None if actor.is_player else actor.id,
            actor_name=None if actor.is_player else actor.name,
            target_combatant_id=target.id,
            target_name=target.name,
            setup=setup,
            payoff=payoff,
            weakness=target.weakness,
        )
        encounter.pending_advantages.append(advantage)
        if payoff == EncounterAdvantagePayoff.SKIP_DEX_GATE:
            encounter.first_round_dex_gate_pending = False
        summary = (
            f"Advantage set against {target.name}: {setup}. "
            f"Payoff: {payoff.value.replace('_', ' ')}."
        )
        return OracleOutcome(
            kind=OracleKind.PLAYER_ACTION,
            summary=summary,
            rolls=[],
            question=setup,
            chaos_factor=state.chaos_factor,
            cairn=CairnResolution(
                actor_id=None if actor.is_player else actor.id,
                actor_name=None if actor.is_player else actor.name,
                target_combatant_id=target.id,
                target_name=target.name,
                advantage_id=advantage.id,
                advantage_setup=setup,
                advantage_payoff=payoff,
                advantage_target_name=target.name,
                advantage_applied=True,
                advantage_consumed=False,
                weakness=advantage.weakness or None,
                combat_active=encounter.active,
                combat_initiator=encounter.initiator,
                combat_round=encounter.round_number,
                overloaded=actor.sheet.cairn.overloaded,
            ),
        )

    def begin_encounter(
        self,
        state: GameState,
        *,
        target_name: str,
        text: str,
        cancel_token: CancellationToken | None = None,
    ) -> OracleOutcome:
        self._require_ready(state)
        encounter = self._ensure_encounter(
            state,
            player_input=text,
            target_name=target_name,
            fallback_target_armor=0,
            initiator=EncounterInitiator.PLAYER,
            cancel_token=cancel_token,
        )
        encounter.active = self._has_active_enemies(encounter)
        encounter.player_disengaged = False
        encounter.pursuit_active = False
        encounter.end_reason = None if encounter.active else EncounterEndReason.VICTORY
        combatant_names = ", ".join(
            combatant.name
            for combatant in encounter.combatants
            if not combatant.defeated and not combatant.fled
        )
        summary = (
            f"Combat encounter started against {combatant_names or target_name}. "
            f"Round {encounter.round_number} is ready; no attack has been resolved yet."
        )
        return OracleOutcome(
            kind=OracleKind.PLAYER_ACTION,
            summary=summary,
            rolls=[],
            question=text,
            chaos_factor=state.chaos_factor,
            cairn=CairnResolution(
                combat_round=encounter.round_number,
                combat_started=True,
                combat_active=encounter.active,
                combat_initiator=encounter.initiator,
                player_acted=False,
                target_name=combatant_names or target_name,
                overloaded=state.character.cairn.overloaded,
            ),
        )

    def resolve_enemy_opener(
        self,
        state: GameState,
        *,
        source: str,
        text: str,
        cancel_token: CancellationToken | None = None,
    ) -> OracleOutcome:
        self._require_ready(state)
        encounter = self._ensure_encounter(
            state,
            player_input=text,
            target_name=source,
            fallback_target_armor=0,
            initiator=EncounterInitiator.ENEMY,
            cancel_token=cancel_token,
        )
        round_before = encounter.round_number
        combat_started = encounter.initiator == EncounterInitiator.ENEMY and round_before == 1
        encounter.first_round_dex_gate_pending = False
        encounter.player_disengaged = False
        encounter.pursuit_active = False
        encounter.end_reason = None

        enemy_harm = self._resolve_enemy_turn(
            state,
            encounter,
            preferred_attacker_name=source,
        )
        encounter.active = self._has_active_enemies(encounter)
        if encounter.active:
            encounter.round_number += 1
            encounter.end_reason = None
            summary = (
                f"{enemy_harm.source} seizes the initiative. {enemy_harm.summary} "
                f"Combat is active in round {encounter.round_number}."
            )
        else:
            encounter.end_reason = EncounterEndReason.VICTORY
            encounter.notes = "No active foes remain."
            summary = (
                f"{enemy_harm.source} struck first. {enemy_harm.summary} "
                "The immediate fight is no longer active."
            )

        return OracleOutcome(
            kind=OracleKind.HARM,
            summary=summary,
            rolls=enemy_harm.rolls,
            question=text,
            chaos_factor=state.chaos_factor,
            cairn=CairnResolution(
                combat_round=round_before,
                combat_started=combat_started,
                combat_active=encounter.active,
                combat_initiator=encounter.initiator,
                player_acted=False,
                target_name=enemy_harm.source,
                target_armor=enemy_harm.armor_value,
                damage_after_armor=enemy_harm.damage_after_armor,
                hp_before=enemy_harm.hp_before,
                hp_after=enemy_harm.hp_after,
                str_before=enemy_harm.str_before,
                str_after=enemy_harm.str_after,
                enemy_damage=enemy_harm.damage_after_armor,
                enemy_damage_source=enemy_harm.source if enemy_harm.damage_after_armor else None,
                scar_result=enemy_harm.scar_result,
                overloaded=state.character.cairn.overloaded,
            ),
        )

    def resolve_retreat(self, state: GameState, reason: str) -> OracleOutcome:
        self._require_ready(state)
        encounter = state.encounter
        if not encounter.active or not self._has_active_enemies(encounter):
            message = "No active encounter to retreat from."
            raise ValueError(message)

        round_before = encounter.round_number
        retreat_target = state.character.cairn.dex_score
        retreat_roll = self._roll(D20_SIDES, "retreat")
        rolls: list[Roll] = [retreat_roll]
        enemy_harm = self._empty_harm_application(state, source="No enemy harm")
        retreat_success = self._save_succeeds(retreat_roll.result, retreat_target)
        pursuit_target = self._highest_enemy_pursuit_target(encounter)
        retreat_outcome: RetreatOutcome
        encounter_end_reason: EncounterEndReason | None = None

        if not retreat_success:
            encounter.player_disengaged = False
            encounter.pursuit_active = False
            encounter.end_reason = None
            enemy_harm = self._resolve_enemy_turn(state, encounter)
            rolls.extend(enemy_harm.rolls)
            encounter.active = self._has_active_enemies(encounter)
            if encounter.active:
                encounter.round_number += 1
            encounter.notes = "Retreat failed; the enemy kept you pinned in the fight."
            retreat_outcome = RetreatOutcome.CAUGHT
            summary = f"Retreat failed: {reason}. {enemy_harm.summary}"
        else:
            pursuit_roll = self._roll(D20_SIDES, "pursuit")
            rolls.append(pursuit_roll)
            pursuers_close = self._save_succeeds(pursuit_roll.result, pursuit_target)
            if pursuers_close:
                encounter.player_disengaged = True
                encounter.pursuit_active = True
                encounter.active = True
                encounter.end_reason = None
                encounter.first_round_dex_gate_pending = False
                encounter.round_number += 1
                encounter.notes = "You broke contact, but the enemy remains in pursuit."
                retreat_outcome = RetreatOutcome.DISENGAGED
                summary = (
                    f"Retreat resolved: {reason}. You broke contact, but the enemy is "
                    "still in pursuit."
                )
            else:
                encounter.player_disengaged = False
                encounter.pursuit_active = False
                encounter.active = False
                encounter.first_round_dex_gate_pending = False
                encounter.end_reason = EncounterEndReason.PLAYER_ESCAPED
                encounter.notes = "You escaped the encounter."
                retreat_outcome = RetreatOutcome.ESCAPED
                encounter_end_reason = EncounterEndReason.PLAYER_ESCAPED
                summary = f"Retreat resolved: {reason}. You escaped the encounter."

        return OracleOutcome(
            kind=OracleKind.RETREAT,
            summary=summary,
            rolls=rolls,
            question=reason,
            chaos_factor=state.chaos_factor,
            cairn=CairnResolution(
                ability=CairnAbility.DEX,
                target=retreat_target,
                success=retreat_success,
                combat_round=round_before,
                combat_active=encounter.active,
                combat_initiator=encounter.initiator,
                hp_before=enemy_harm.hp_before,
                hp_after=enemy_harm.hp_after,
                str_before=enemy_harm.str_before,
                str_after=enemy_harm.str_after,
                enemy_damage=enemy_harm.damage_after_armor,
                enemy_damage_source=enemy_harm.source if enemy_harm.damage_after_armor else None,
                retreat_outcome=retreat_outcome,
                player_disengaged=encounter.player_disengaged,
                pursuit_active=encounter.pursuit_active,
                encounter_end_reason=encounter_end_reason,
                overloaded=state.character.cairn.overloaded,
            ),
        )

    def suffer_harm(  # noqa: PLR0913
        self,
        state: GameState,
        *,
        amount: int,
        source: str,
        in_combat: bool,
        armor_applies: bool,
        actor_id: str | None = None,
    ) -> OracleOutcome:
        self._require_ready(state)
        actor = self._resolve_actor(state, actor_id)
        applied = self._apply_harm_to_character(
            actor.sheet.cairn,
            amount=amount,
            source=source,
            in_combat=in_combat,
            armor_applies=armor_applies,
        )
        self._recompute_derived(actor.sheet)
        actor_prefix = "" if actor.is_player else f"{actor.name}: "
        return OracleOutcome(
            kind=OracleKind.HARM,
            summary=f"{actor_prefix}{applied.summary}",
            rolls=applied.rolls,
            question=source,
            chaos_factor=state.chaos_factor,
            cairn=CairnResolution(
                actor_id=None if actor.is_player else actor.id,
                actor_name=None if actor.is_player else actor.name,
                combat_initiator=(
                    state.encounter.initiator if in_combat and state.encounter.active else None
                ),
                target_name=source,
                target_armor=applied.armor_value,
                base_damage=amount,
                damage_after_armor=applied.damage_after_armor,
                hp_before=applied.hp_before,
                hp_after=actor.sheet.cairn.hp,
                str_before=applied.str_before,
                str_after=actor.sheet.cairn.str_score,
                scar_result=applied.scar_result,
                overloaded=actor.sheet.cairn.overloaded,
            ),
        )
