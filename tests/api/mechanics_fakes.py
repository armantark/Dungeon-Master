"""Integration tests for the FastAPI surface.

These tests don't go to the network: a `FakeNarrative` and
`FakeCampaignGenerator` replace LiteLLM, so we exercise the routing,
serialization, and state-mutation contracts without spending tokens.
"""

from __future__ import annotations

from collections.abc import Callable

from dungeon_master.cairn import AttackActor, SurvivalUpdate
from dungeon_master.cancel import CancellationToken
from dungeon_master.models import (
    AttackStance,
    CairnAbility,
    CairnCharacterState,
    CairnDayPhase,
    CairnItemState,
    CairnItemTag,
    CairnMechanicsSource,
    CairnResolution,
    CairnRestKind,
    CairnSurvivalAction,
    CairnTimeAdvance,
    CampaignSeed,
    CampaignStatus,
    CharacterSheet,
    EncounterAdvantagePayoff,
    EncounterInitiator,
    EncounterState,
    EnemyCombatant,
    GameState,
    InventoryItem,
    OracleKind,
    OracleOutcome,
    RetreatOutcome,
)
from dungeon_master.npc_updater import (
    GeneratedNPCUpdateBatch,
    LegacyNPCRosterRepairResult,
    NPCUpdateResult,
)
from dungeon_master.thread_updater import GeneratedThreadUpdateBatch, ThreadUpdateResult
from tests.api.narrative_fakes import FakeCharacterGenerator
from tests.factories import sample_state


class SetupCharacterGenerator(FakeCharacterGenerator):
    def setup_state(self, seed: CampaignSeed | None = None) -> GameState:
        state = sample_state()
        if seed is not None:
            state.campaign_seed = seed
        state.campaign_status = CampaignStatus.CHARACTER_CREATION
        state.threads = []
        state.npcs = []
        state.action_log = []
        state.oracle_history = []
        return state


class FakeCairnEngine:
    def ensure_character_state(
        self,
        state: GameState,
        *,
        allow_backfill: bool,
        cancel_token: CancellationToken | None = None,
    ) -> bool:
        del cancel_token
        if state.character.cairn.source != CairnMechanicsSource.UNSET:
            return False
        if not allow_backfill:
            return False
        state.character.cairn = CairnCharacterState(
            source=CairnMechanicsSource.NARRATIVE_BACKFILL,
            backfill_version=3,
            skills=["Shrine lore"],
            abilities=["Condemn sorcery"],
            str_score=14,
            dex_score=12,
            wil_score=15,
            max_str_score=14,
            max_dex_score=12,
            max_wil_score=15,
            hp=4,
            max_hp=4,
            primary_weapon_item_id=state.character.inventory[0].id,
        )
        for item in state.character.inventory:
            item.cairn = CairnItemState(
                source=CairnMechanicsSource.NARRATIVE_BACKFILL,
                backfill_version=3,
                tags=[CairnItemTag.WEAPON] if item == state.character.inventory[0] else [],
                weapon_damage_die=6 if item == state.character.inventory[0] else None,
                equipped=item == state.character.inventory[0],
            )
        state.character.cairn.slots_used = len(state.character.inventory)
        return True

    def set_item_equipped(
        self,
        state: GameState,
        *,
        item_id: str,
        equipped: bool,
        actor_id: str | None = None,
    ) -> None:
        del actor_id
        for item in state.character.inventory:
            item.cairn.equipped = item.id == item_id if equipped else False
        if equipped:
            state.character.cairn.primary_weapon_item_id = item_id

    def acquire_items(
        self,
        state: GameState,
        *,
        text: str,
        actor_id: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> str:
        del actor_id, cancel_token
        lantern = InventoryItem(
            name="Pilgrim lantern",
            details="Taken during play.",
            cairn=CairnItemState(
                source=CairnMechanicsSource.EXPLICIT,
                tags=[CairnItemTag.LIGHT, CairnItemTag.UTILITY],
                slots=1,
                uses=3,
                equipped="ready" in text.lower(),
            ),
        )
        purse = InventoryItem(
            name="Purse of old silver",
            details="A small bundle of spendable coin.",
            cairn=CairnItemState(
                source=CairnMechanicsSource.EXPLICIT,
                tags=[CairnItemTag.PETTY, CairnItemTag.UTILITY],
                slots=0,
            ),
        )
        state.character.inventory.extend([lantern, purse])
        state.character.cairn.slots_used = sum(
            item.cairn.slots for item in state.character.inventory
        )
        return "Acquired Pilgrim lantern, Purse of old silver."

    def use_item(
        self,
        state: GameState,
        *,
        item_id: str,
        intent: str,
        actor_id: str | None = None,
    ) -> OracleOutcome:
        del actor_id
        for item in list(state.character.inventory):
            if item.id != item_id:
                continue
            if item.cairn.uses is None:
                summary = f"Used {item.name}: {intent}. No limited uses were consumed."
                return OracleOutcome(
                    kind=OracleKind.PLAYER_ACTION,
                    summary=summary,
                    chaos_factor=state.chaos_factor,
                    cairn=CairnResolution(item_id=item.id, item_name=item.name),
                )
            remaining = item.cairn.uses - 1
            if remaining <= 0:
                state.character.inventory = [
                    candidate for candidate in state.character.inventory if candidate.id != item_id
                ]
                summary = f"Used {item.name}: final use spent, item exhausted and removed."
                return OracleOutcome(
                    kind=OracleKind.PLAYER_ACTION,
                    summary=summary,
                    chaos_factor=state.chaos_factor,
                    cairn=CairnResolution(
                        item_id=item.id,
                        item_name=item.name,
                        uses_before=item.cairn.uses,
                        uses_after=None,
                    ),
                )
            item.cairn.uses = remaining
            summary = f"Used {item.name}: {remaining} uses remain."
            return OracleOutcome(
                kind=OracleKind.PLAYER_ACTION,
                summary=summary,
                chaos_factor=state.chaos_factor,
                cairn=CairnResolution(
                    item_id=item.id,
                    item_name=item.name,
                    uses_before=remaining + 1,
                    uses_after=remaining,
                ),
            )
        message = f"Unknown inventory item: {item_id}"
        raise ValueError(message)

    def drop_item(
        self,
        state: GameState,
        *,
        item_id: str,
        actor_id: str | None = None,
    ) -> str:
        del actor_id
        for item in list(state.character.inventory):
            if item.id != item_id:
                continue
            state.character.inventory = [
                candidate for candidate in state.character.inventory if candidate.id != item_id
            ]
            return f"Dropped {item.name}."
        message = f"Unknown inventory item: {item_id}"
        raise ValueError(message)

    def transfer_item(
        self,
        state: GameState,
        *,
        item_id: str,
        source_actor_id: str | None,
        target_actor_id: str | None,
    ) -> str:
        def actor_sheet(actor_id: str | None) -> CharacterSheet:
            if actor_id is None:
                return state.character
            member = next(
                (candidate for candidate in state.party_members if candidate.id == actor_id),
                None,
            )
            if member is None:
                message = f"Unknown actor: {actor_id}"
                raise ValueError(message)
            return member.sheet

        source = actor_sheet(source_actor_id)
        target = actor_sheet(target_actor_id)
        item = next((candidate for candidate in source.inventory if candidate.id == item_id), None)
        if item is None:
            message = f"Unknown inventory item: {item_id}"
            raise ValueError(message)
        source.inventory = [candidate for candidate in source.inventory if candidate.id != item_id]
        item.cairn.equipped = False
        target.inventory.append(item)
        return f"Transferred {item.name}."

    def backfill_companion_sheet(
        self,
        state: GameState,
        authored: CharacterSheet,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> CharacterSheet:
        del state, cancel_token
        return authored

    def resolve_retreat(self, state: GameState, reason: str) -> OracleOutcome:
        state.encounter.active = False
        state.encounter.notes = "You escaped the encounter."
        return OracleOutcome(
            kind=OracleKind.RETREAT,
            summary=f"Retreat resolved: {reason}",
            chaos_factor=state.chaos_factor,
            cairn=CairnResolution(
                ability=CairnAbility.DEX,
                target=12,
                success=True,
                retreat_outcome=RetreatOutcome.ESCAPED,
                combat_active=False,
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
        del state, actor_id, cancel_token
        return OracleOutcome(
            kind=OracleKind.PLAYER_ACTION,
            summary=f"Setup advantage against {target_name}: {setup}",
            chaos_factor=5,
            cairn=CairnResolution(
                target_name=target_name,
                advantage_setup=setup,
                advantage_payoff=payoff,
                advantage_target_name=target_name,
                advantage_applied=True,
                advantage_consumed=False,
            ),
        )


class FakePlayableCairnEngine(FakeCairnEngine):
    def resolve_save(
        self,
        state: GameState,
        ability: CairnAbility,
        reason: str,
        *,
        actor_id: str | None = None,
    ) -> OracleOutcome:
        del actor_id
        return OracleOutcome(
            kind=OracleKind.SAVE,
            summary=f"{ability.value} save passed: {reason}",
            chaos_factor=state.chaos_factor,
            cairn=CairnResolution(ability=ability, target=12, success=True),
        )

    def resolve_attack(  # noqa: PLR0913
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
        del actor_id, cancel_token
        return OracleOutcome(
            kind=OracleKind.ATTACK,
            summary=f"Attack against {target_name}.",
            chaos_factor=state.chaos_factor,
            cairn=CairnResolution(
                weapon_item_id=weapon_item_id,
                target_name=target_name,
                target_armor=target_armor,
                attack_stance=stance,
                base_damage=5,
                damage_after_armor=max(0, 5 - target_armor),
            ),
        )

    def resolve_coordinated_attack(
        self,
        state: GameState,
        *,
        target_name: str,
        target_armor: int,
        participants: tuple[AttackActor, ...],
        cancel_token: CancellationToken | None = None,
    ) -> OracleOutcome:
        del cancel_token
        actor_names = ", ".join(participant.name for participant in participants)
        return OracleOutcome(
            kind=OracleKind.ATTACK,
            summary=f"Coordinated attack against {target_name} by {actor_names}.",
            chaos_factor=state.chaos_factor,
            cairn=CairnResolution(
                target_name=target_name,
                target_armor=target_armor,
                coordinated_attack=True,
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
        del actor_id, in_combat, armor_applies
        state.character.cairn.hp = max(0, state.character.cairn.hp - amount)
        return OracleOutcome(
            kind=OracleKind.HARM,
            summary=f"Harm from {source}.",
            chaos_factor=state.chaos_factor,
            cairn=CairnResolution(
                target_name=source,
                base_damage=amount,
                damage_after_armor=amount,
                hp_before=4,
                hp_after=state.character.cairn.hp,
                str_before=state.character.cairn.max_str_score,
                str_after=state.character.cairn.str_score,
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
        del cancel_token
        state.encounter = EncounterState(
            active=True,
            round_number=2,
            first_round_dex_gate_pending=False,
            initiator=EncounterInitiator.ENEMY,
            combatants=[EnemyCombatant(name=source, hp=4, max_hp=4)],
            notes="A hostile foe seized the initiative.",
        )
        state.character.cairn.hp = max(0, state.character.cairn.hp - 1)
        return OracleOutcome(
            kind=OracleKind.HARM,
            summary=f"{source} struck first: {text}",
            chaos_factor=state.chaos_factor,
            cairn=CairnResolution(
                combat_round=1,
                combat_started=True,
                combat_active=True,
                combat_initiator=EncounterInitiator.ENEMY,
                player_acted=False,
                target_name=source,
                damage_after_armor=1,
                hp_before=4,
                hp_after=state.character.cairn.hp,
                str_before=state.character.cairn.max_str_score,
                str_after=state.character.cairn.str_score,
                enemy_damage=1,
                enemy_damage_source=source,
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
        del text, cancel_token
        state.encounter = EncounterState(
            active=True,
            round_number=1,
            first_round_dex_gate_pending=True,
            initiator=EncounterInitiator.PLAYER,
            combatants=[EnemyCombatant(name=target_name, hp=4, max_hp=4)],
            notes="Fake encounter started.",
        )
        return OracleOutcome(
            kind=OracleKind.PLAYER_ACTION,
            summary=f"Encounter started against {target_name}.",
            chaos_factor=state.chaos_factor,
            cairn=CairnResolution(
                combat_round=1,
                combat_started=True,
                combat_active=True,
                combat_initiator=EncounterInitiator.PLAYER,
                player_acted=False,
                target_name=target_name,
            ),
        )

    def recover(
        self,
        state: GameState,
        kind: CairnRestKind,
        *,
        actor_id: str | None = None,
    ) -> OracleOutcome:
        del actor_id
        state.character.cairn.hp = state.character.cairn.max_hp
        return OracleOutcome(
            kind=OracleKind.RECOVERY,
            summary=f"Recovery: {kind.value}",
            chaos_factor=state.chaos_factor,
            cairn=CairnResolution(rest_kind=kind, hp_before=0, hp_after=state.character.cairn.hp),
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
        del actor_id
        survival = state.character.cairn.survival
        before_day = survival.day_number
        before_phase = survival.day_phase
        before_meal = survival.watches_since_meal
        before_sleep = survival.watches_since_sleep
        if time_advance == CairnTimeAdvance.WATCH:
            survival.watch_index = (survival.watch_index + 1) % 6
        elif time_advance == CairnTimeAdvance.DAY:
            survival.watch_index = (survival.watch_index + 3) % 6
        elif time_advance == CairnTimeAdvance.OVERNIGHT:
            survival.day_number += 1
            survival.watch_index = 0
        survival.day_number += extra_days
        if CairnSurvivalAction.EAT in actions:
            survival.watches_since_meal = 0
        if CairnSurvivalAction.SLEEP in actions:
            survival.watches_since_sleep = 0
        phase_after = CairnDayPhase.DAWN if survival.watch_index == 0 else before_phase
        return SurvivalUpdate(
            summary="Survival clock updated in fake engine.",
            resolution=CairnResolution(
                time_advance=time_advance,
                day_number_before=before_day,
                day_number_after=survival.day_number,
                day_phase_before=before_phase,
                day_phase_after=phase_after,
                watches_since_meal_before=before_meal,
                watches_since_meal_after=survival.watches_since_meal,
                watches_since_sleep_before=before_sleep,
                watches_since_sleep_after=survival.watches_since_sleep,
                deprived_before=False,
                deprived_after=False,
            ),
        )


class FatalPlayableCairnEngine(FakePlayableCairnEngine):
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
        del actor_id, in_combat, armor_applies
        state.character.cairn.hp = 0
        state.character.cairn.str_score = 0
        state.character.cairn.dead = True
        return OracleOutcome(
            kind=OracleKind.HARM,
            summary=f"Fatal harm from {source}.",
            chaos_factor=state.chaos_factor,
            cairn=CairnResolution(
                target_name=source,
                base_damage=amount,
                damage_after_armor=amount,
                hp_before=1,
                hp_after=0,
                str_before=1,
                str_after=0,
            ),
        )


class FakeThreadUpdater:
    def __init__(
        self,
        mutate: Callable[[GameState, OracleOutcome], tuple[str, ...]] | None = None,
    ) -> None:
        self._mutate = mutate

    def update_threads(  # noqa: PLR0913
        self,
        state: GameState,
        *,
        player_input: str,
        outcome: OracleOutcome,
        execution_context: str | None = None,
        narrative_text: str | None = None,
        memory_context: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> ThreadUpdateResult:
        generated = self.generate_thread_updates(
            state,
            player_input=player_input,
            outcome=outcome,
            execution_context=execution_context,
            narrative_text=narrative_text,
            memory_context=memory_context,
            cancel_token=cancel_token,
        )
        if generated is None:
            return ThreadUpdateResult()
        return self.apply_generated_updates(state, generated)

    def generate_thread_updates(  # noqa: PLR0913
        self,
        state: GameState,
        *,
        player_input: str,
        outcome: OracleOutcome,
        execution_context: str | None = None,
        narrative_text: str | None = None,
        memory_context: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> GeneratedThreadUpdateBatch | None:
        del (
            state,
            player_input,
            outcome,
            execution_context,
            narrative_text,
            memory_context,
            cancel_token,
        )
        return GeneratedThreadUpdateBatch()

    def apply_generated_updates(
        self,
        state: GameState,
        generated: GeneratedThreadUpdateBatch,
    ) -> ThreadUpdateResult:
        del generated
        latest_outcome = state.oracle_history[-1]
        if self._mutate is None:
            return ThreadUpdateResult()
        return ThreadUpdateResult(touched_thread_ids=self._mutate(state, latest_outcome))


class FakeNpcUpdater:
    def __init__(
        self,
        mutate: Callable[[GameState, OracleOutcome], tuple[str, ...]] | None = None,
        repair: LegacyNPCRosterRepairResult | None = None,
    ) -> None:
        self._mutate = mutate
        self._repair = repair

    def update_npcs(  # noqa: PLR0913
        self,
        state: GameState,
        *,
        player_input: str,
        outcome: OracleOutcome,
        execution_context: str | None = None,
        narrative_text: str | None = None,
        memory_context: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> NPCUpdateResult:
        generated = self.generate_npc_updates(
            state,
            player_input=player_input,
            outcome=outcome,
            execution_context=execution_context,
            narrative_text=narrative_text,
            memory_context=memory_context,
            cancel_token=cancel_token,
        )
        if generated is None:
            return NPCUpdateResult()
        return self.apply_generated_updates(state, generated)

    def generate_npc_updates(  # noqa: PLR0913
        self,
        state: GameState,
        *,
        player_input: str,
        outcome: OracleOutcome,
        execution_context: str | None = None,
        narrative_text: str | None = None,
        memory_context: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> GeneratedNPCUpdateBatch | None:
        del (
            state,
            player_input,
            outcome,
            execution_context,
            narrative_text,
            memory_context,
            cancel_token,
        )
        return GeneratedNPCUpdateBatch()

    def apply_generated_updates(
        self,
        state: GameState,
        generated: GeneratedNPCUpdateBatch,
    ) -> NPCUpdateResult:
        del generated
        latest_outcome = state.oracle_history[-1]
        if self._mutate is None:
            return NPCUpdateResult()
        return NPCUpdateResult(touched_npc_ids=self._mutate(state, latest_outcome))

    def reseed_legacy_roster(
        self,
        state: GameState,
        *,
        memory_context: str | None = None,
        cancel_token: CancellationToken | None = None,
        use_model: bool = False,
    ) -> LegacyNPCRosterRepairResult:
        del state, memory_context, cancel_token, use_model
        return self._repair or LegacyNPCRosterRepairResult()
