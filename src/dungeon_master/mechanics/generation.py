from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

from pydantic import ValidationError

from dungeon_master.campaign import render_creative_direction
from dungeon_master.cancel import CancellationToken
from dungeon_master.llm.completion import (
    LITELLM_RETRYABLE_ERRORS,
    CompletionFunction,
    CompletionRequest,
    complete_text,
    extract_json_object,
)
from dungeon_master.mechanics.combat import EncounterScalingPolicy
from dungeon_master.mechanics.generation_contracts import (
    ALLOWED_WEAPON_DICE,
    BACKPACK_SLOTS,
    CAIRN_ACQUISITION_SYSTEM_PROMPT,
    CAIRN_ACQUISITION_USER_PROMPT_TEMPLATE,
    CAIRN_BACKFILL_SYSTEM_PROMPT,
    CAIRN_BACKFILL_USER_PROMPT_TEMPLATE,
    CAIRN_ENCOUNTER_SYSTEM_PROMPT,
    CAIRN_ENCOUNTER_USER_PROMPT_TEMPLATE,
    COMFORTABLE_SLOTS,
    CURRENT_BACKFILL_VERSION,
    FULL_INVENTORY_SLOTS,
    _raise_empty_backfill_content_error,
)
from dungeon_master.mechanics.generation_contracts import (
    BackfillFunction as _BackfillFunction,
)
from dungeon_master.mechanics.generation_contracts import (
    EmptyBackfillContentError as _EmptyBackfillContentError,
)
from dungeon_master.mechanics.generation_contracts import (
    GeneratedCairnBackfill as _GeneratedCairnBackfill,
)
from dungeon_master.mechanics.generation_contracts import (
    GeneratedCairnItemProfile as _GeneratedCairnItemProfile,
)
from dungeon_master.mechanics.generation_contracts import (
    GeneratedEncounterCombatant as _GeneratedEncounterCombatant,
)
from dungeon_master.mechanics.generation_contracts import (
    GeneratedEncounterSeed as _GeneratedEncounterSeed,
)
from dungeon_master.mechanics.generation_contracts import (
    GeneratedInventoryAcquisition as _GeneratedInventoryAcquisition,
)
from dungeon_master.mechanics.inventory import ResolvedActor
from dungeon_master.models import (
    CairnCharacterState,
    CairnItemState,
    CairnItemTag,
    CairnMechanicsSource,
    CharacterSheet,
    EncounterInitiator,
    EncounterState,
    EncounterThreatLevel,
    EnemyCombatant,
    GameState,
    InventoryItem,
)
from dungeon_master.narrative import NarrativeConfig

BackfillFunction = _BackfillFunction
EmptyBackfillContentError = _EmptyBackfillContentError
GeneratedCairnBackfill = _GeneratedCairnBackfill
GeneratedCairnItemProfile = _GeneratedCairnItemProfile
GeneratedEncounterCombatant = _GeneratedEncounterCombatant
GeneratedEncounterSeed = _GeneratedEncounterSeed
GeneratedInventoryAcquisition = _GeneratedInventoryAcquisition


class GenerationSupport:
    _config: NarrativeConfig
    _completion: CompletionFunction
    _backfill_function: BackfillFunction | None

    if TYPE_CHECKING:

        def _recompute_derived(self, character: CharacterSheet) -> None: ...

        def _require_ready(self, state: GameState) -> None: ...

        def _resolve_actor(self, state: GameState, actor_id: str | None) -> ResolvedActor: ...

        def _has_active_enemies(self, encounter: EncounterState) -> bool: ...

    def ensure_character_state(
        self,
        state: GameState,
        *,
        allow_backfill: bool,
        cancel_token: CancellationToken | None = None,
    ) -> bool:
        character = state.character
        if character.cairn.source == CairnMechanicsSource.UNSET:
            if not allow_backfill:
                return False
            self._backfill_character(state, cancel_token=cancel_token)
            return True

        if (
            character.cairn.source == CairnMechanicsSource.NARRATIVE_BACKFILL
            and character.cairn.backfill_version < CURRENT_BACKFILL_VERSION
            and allow_backfill
        ):
            self._backfill_character(state, cancel_token=cancel_token)
            return True

        self._recompute_derived(character)
        return False

    def acquire_items(
        self,
        state: GameState,
        *,
        text: str,
        actor_id: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> str:
        self._require_ready(state)
        actor = self._resolve_actor(state, actor_id)
        cleaned = text.strip()
        if not cleaned:
            message = "Acquisition text cannot be empty."
            raise ValueError(message)

        generated: GeneratedInventoryAcquisition | None = None
        if self._config.is_usable():
            prompt = self._build_acquisition_prompt(state, cleaned, actor=actor)
            acquisition_profile = self._config.profiles.cairn_acquisition
            request = CompletionRequest(
                model=self._config.model,
                messages=[
                    {"role": "system", "content": CAIRN_ACQUISITION_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=acquisition_profile.temperature,
                max_tokens=acquisition_profile.max_tokens,
                timeout=self._config.timeout_seconds,
                stream=True,
                api_key=self._config.api_key,
                base_url=self._config.base_url,
                reasoning_effort=acquisition_profile.reasoning_effort,
                reasoning=acquisition_profile.reasoning(
                    default_exclude=self._config.exclude_reasoning,
                ),
                extra_headers=self._openrouter_headers(),
                response_format=None,
                cancel_token=cancel_token,
                trace_route="cairn.acquisition",
                trace_profile="cairn_acquisition",
            )
            try:
                payload = self._complete_json(request)
                generated = GeneratedInventoryAcquisition.model_validate_json(
                    extract_json_object(payload),
                )
            except ValueError:
                generated = None

        if generated is None:
            generated = self._fallback_inventory_acquisition(cleaned)

        acquired = self._inventory_items_from_profiles(
            generated.items,
            source=CairnMechanicsSource.EXPLICIT,
        )
        actor.sheet.inventory.extend(acquired)
        self._normalize_newly_equipped_weapons(actor.sheet, acquired)
        self._recompute_derived(actor.sheet)
        return self._inventory_acquisition_summary(acquired, actor=actor)

    def backfill_companion_sheet(
        self,
        state: GameState,
        authored: CharacterSheet,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> CharacterSheet:
        if self._backfill_function is not None:
            draft_state = state.model_copy(deep=True)
            draft_state.character = authored
            sheet = self._backfill_function(draft_state)
            self._recompute_derived(sheet)
            return sheet

        if not self._config.is_usable():
            self._recompute_derived(authored)
            return authored

        draft_state = state.model_copy(deep=True)
        draft_state.character = authored
        prompt = self._build_backfill_prompt(draft_state)
        backfill_profile = self._config.profiles.cairn_backfill
        request = CompletionRequest(
            model=self._config.model,
            messages=[
                {"role": "system", "content": CAIRN_BACKFILL_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=backfill_profile.temperature,
            max_tokens=backfill_profile.max_tokens,
            timeout=self._config.timeout_seconds,
            stream=False,
            api_key=self._config.api_key,
            base_url=self._config.base_url,
            reasoning_effort=backfill_profile.reasoning_effort,
            reasoning=backfill_profile.reasoning(default_exclude=self._config.exclude_reasoning),
            extra_headers=self._openrouter_headers(),
            response_format=None,
            cancel_token=cancel_token,
            trace_route="cairn.companion_backfill",
            trace_profile="cairn_backfill",
        )
        payload = self._complete_json(request)
        generated = GeneratedCairnBackfill.model_validate_json(extract_json_object(payload))
        sheet = self._apply_generated_backfill(authored, generated)
        self._recompute_derived(sheet)
        return sheet

    def _backfill_character(
        self,
        state: GameState,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> None:
        if self._backfill_function is not None:
            state.character = self._backfill_function(state)
            self._recompute_derived(state.character)
            return

        if not self._config.is_usable():
            message = "Cairn backfill requires a configured model."
            raise ValueError(message)

        prompt = self._build_backfill_prompt(state)
        backfill_profile = self._config.profiles.cairn_backfill
        request = CompletionRequest(
            model=self._config.model,
            messages=[
                {"role": "system", "content": CAIRN_BACKFILL_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=backfill_profile.temperature,
            max_tokens=backfill_profile.max_tokens,
            timeout=self._config.timeout_seconds,
            stream=False,
            api_key=self._config.api_key,
            base_url=self._config.base_url,
            reasoning_effort=backfill_profile.reasoning_effort,
            reasoning=backfill_profile.reasoning(default_exclude=self._config.exclude_reasoning),
            extra_headers=self._openrouter_headers(),
            response_format=None,
            cancel_token=cancel_token,
            trace_route="cairn.backfill",
            trace_profile="cairn_backfill",
        )
        payload = self._complete_json(request)
        generated = GeneratedCairnBackfill.model_validate_json(extract_json_object(payload))
        state.character = self._apply_generated_backfill(state.character, generated)
        self._recompute_derived(state.character)

    def _apply_generated_backfill(
        self,
        authored: CharacterSheet,
        generated: GeneratedCairnBackfill,
    ) -> CharacterSheet:
        inventory = self._inventory_items_from_profiles(
            generated.inventory,
            source=CairnMechanicsSource.NARRATIVE_BACKFILL,
            backfill_version=CURRENT_BACKFILL_VERSION,
        )
        return authored.model_copy(
            update={
                "inventory": inventory,
                "cairn": CairnCharacterState(
                    source=CairnMechanicsSource.NARRATIVE_BACKFILL,
                    backfill_version=CURRENT_BACKFILL_VERSION,
                    skills=generated.skills,
                    abilities=generated.abilities,
                    str_score=generated.str_score,
                    dex_score=generated.dex_score,
                    wil_score=generated.wil_score,
                    max_str_score=generated.str_score,
                    max_dex_score=generated.dex_score,
                    max_wil_score=generated.wil_score,
                    hp=generated.max_hp,
                    max_hp=generated.max_hp,
                    armor=0,
                    fatigue=generated.fatigue,
                    deprived=generated.deprived,
                    critically_wounded=generated.critically_wounded,
                    doomed=generated.doomed,
                    paralyzed=generated.paralyzed,
                    delirious=generated.delirious,
                    dead=generated.dead,
                    slots_total=FULL_INVENTORY_SLOTS,
                    backpack_slots=BACKPACK_SLOTS,
                    comfortable_slots=COMFORTABLE_SLOTS,
                    notes=generated.notes,
                ),
            },
            deep=True,
        )

    def _inventory_items_from_profiles(
        self,
        profiles: list[GeneratedCairnItemProfile],
        *,
        source: CairnMechanicsSource,
        backfill_version: int = 0,
    ) -> list[InventoryItem]:
        return [
            InventoryItem(
                name=profile.name,
                details=profile.details,
                cairn=CairnItemState(
                    source=source,
                    backfill_version=backfill_version,
                    tags=profile.tags,
                    slots=profile.slots,
                    weapon_damage_die=profile.weapon_damage_die,
                    armor_bonus=profile.armor_bonus,
                    uses=profile.uses,
                    resources=profile.resources,
                    attack_costs=profile.attack_costs,
                    use_costs=profile.use_costs,
                    equipped=profile.equipped,
                    power=profile.power,
                ),
            )
            for profile in profiles
        ]

    def _normalize_newly_equipped_weapons(
        self,
        character: CharacterSheet,
        acquired: list[InventoryItem],
    ) -> None:
        equipped_weapon = next(
            (
                item
                for item in acquired
                if CairnItemTag.WEAPON in item.cairn.tags and item.cairn.equipped
            ),
            None,
        )
        if equipped_weapon is None:
            return
        for item in character.inventory:
            if CairnItemTag.WEAPON in item.cairn.tags:
                item.cairn.equipped = item.id == equipped_weapon.id

    def _build_acquisition_prompt(
        self,
        state: GameState,
        text: str,
        *,
        actor: ResolvedActor,
    ) -> str:
        return (
            CAIRN_ACQUISITION_USER_PROMPT_TEMPLATE.replace("<<ACQUISITION>>", text)
            .replace("<<CURRENT_SCENE>>", state.current_scene)
            .replace("<<SETTING_NOTES>>", self._prompt_setting_context(state))
            .replace(
                "<<INVENTORY_JSON>>",
                json.dumps(
                    [item.model_dump(mode="json") for item in actor.sheet.inventory],
                    indent=2,
                ),
            )
            .replace(
                "<<CHARACTER_NOTES>>",
                f"Actor: {actor.name}\n{actor.sheet.cairn.notes or '(none)'}",
            )
        )

    def _fallback_inventory_acquisition(self, text: str) -> GeneratedInventoryAcquisition:
        return GeneratedInventoryAcquisition(
            items=[
                GeneratedCairnItemProfile(
                    name="Acquired gear",
                    details=f"Taken during play: {text}",
                    tags=[CairnItemTag.UTILITY],
                    slots=1,
                    weapon_damage_die=None,
                    armor_bonus=0,
                    uses=None,
                    equipped=False,
                ),
            ],
        )

    def _inventory_acquisition_summary(
        self,
        acquired: list[InventoryItem],
        *,
        actor: ResolvedActor,
    ) -> str:
        names = ", ".join(item.name for item in acquired)
        equipped = [
            item.name
            for item in acquired
            if item.cairn.equipped
            and (
                CairnItemTag.WEAPON in item.cairn.tags
                or CairnItemTag.ARMOR in item.cairn.tags
                or CairnItemTag.SHIELD in item.cairn.tags
            )
        ]
        actor_prefix = "" if actor.is_player else f"{actor.name} acquired "
        if equipped:
            equipped_names = ", ".join(equipped)
            if actor.is_player:
                return f"Acquired {names}. Readied: {equipped_names}."
            return f"{actor_prefix}{names}. Readied: {equipped_names}."
        if actor.is_player:
            return f"Acquired {names}."
        return f"{actor_prefix}{names}."

    def _build_backfill_prompt(self, state: GameState) -> str:
        return (
            CAIRN_BACKFILL_USER_PROMPT_TEMPLATE.replace(
                "<<CHARACTER_JSON>>",
                state.character.model_dump_json(indent=2),
            )
            .replace("<<CAMPAIGN_SEED>>", render_creative_direction(state.campaign_seed))
            .replace("<<CURRENT_SCENE>>", state.current_scene)
            .replace("<<SETTING_NOTES>>", self._prompt_setting_context(state))
            .replace(
                "<<THREAD_TITLES>>", ", ".join(thread.title for thread in state.threads) or "(none)"
            )
            .replace(
                "<<NPC_NAMES>>",
                ", ".join(npc.display_label() for npc in state.npcs) or "(none)",
            )
        )

    def _complete_json(self, request: CompletionRequest) -> str:
        last_error: Exception | None = None
        for attempt in range(self._config.max_retries + 1):
            try:
                completed = complete_text(request, self._completion)
                content_json = completed.content
                if not content_json:
                    _raise_empty_backfill_content_error()
            except (
                *LITELLM_RETRYABLE_ERRORS,
                ValidationError,
                json.JSONDecodeError,
                EmptyBackfillContentError,
                ValueError,
            ) as exc:
                last_error = exc
                if attempt < self._config.max_retries:
                    time.sleep(0.4 * (attempt + 1))
            else:
                return content_json
        message = str(last_error) if last_error else "Cairn backfill failed."
        raise ValueError(message)

    def _openrouter_headers(self) -> dict[str, str] | None:
        if not self._config.model.startswith("openrouter/"):
            return None
        headers: dict[str, str] = {}
        if self._config.site_url is not None:
            headers["HTTP-Referer"] = self._config.site_url
        if self._config.app_name is not None:
            headers["X-Title"] = self._config.app_name
        return headers or None

    def _ensure_encounter(  # noqa: PLR0913
        self,
        state: GameState,
        *,
        player_input: str,
        target_name: str,
        fallback_target_armor: int,
        initiator: EncounterInitiator,
        cancel_token: CancellationToken | None = None,
    ) -> EncounterState:
        encounter = state.encounter
        if encounter.active and self._has_active_enemies(encounter):
            return encounter

        state.encounter = self._seed_encounter(
            state,
            player_input=player_input,
            target_name=target_name,
            fallback_target_armor=fallback_target_armor,
            initiator=initiator,
            cancel_token=cancel_token,
        )
        return state.encounter

    def _seed_encounter(  # noqa: PLR0913
        self,
        state: GameState,
        *,
        player_input: str,
        target_name: str,
        fallback_target_armor: int,
        initiator: EncounterInitiator,
        cancel_token: CancellationToken | None = None,
    ) -> EncounterState:
        generated: GeneratedEncounterSeed | None = None
        if self._config.is_usable():
            prompt = self._build_encounter_prompt(
                state,
                player_input=player_input,
                target_name=target_name,
                initiator=initiator,
            )
            encounter_profile = self._config.profiles.cairn_encounter_seed
            request = CompletionRequest(
                model=self._config.model,
                messages=[
                    {"role": "system", "content": CAIRN_ENCOUNTER_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=encounter_profile.temperature,
                max_tokens=encounter_profile.max_tokens,
                timeout=self._config.timeout_seconds,
                stream=True,
                api_key=self._config.api_key,
                base_url=self._config.base_url,
                reasoning_effort=encounter_profile.reasoning_effort,
                # Cap reasoning to keep encounter seeding under ~30s wallclock.
                # The fallback seed (`_fallback_encounter_seed`) is a perfectly
                # serviceable single-foe encounter, so we'd rather time out
                # the LLM than make the player wait minutes for richer stats.
                # We keep this as a bounded budget profile for the same reason.
                reasoning=encounter_profile.reasoning(
                    default_exclude=self._config.exclude_reasoning
                ),
                extra_headers=self._openrouter_headers(),
                response_format=None,
                cancel_token=cancel_token,
                trace_route="cairn.encounter_seed",
                trace_profile="cairn_encounter_seed",
            )
            try:
                payload = self._complete_json(request)
                generated = GeneratedEncounterSeed.model_validate_json(extract_json_object(payload))
            except ValueError:
                generated = None

        policy = EncounterScalingPolicy.for_danger(state.campaign_seed.danger_profile)
        if generated is None:
            generated = self._fallback_encounter_seed(
                target_name=target_name,
                target_armor=fallback_target_armor,
            )
        generated = self._scaled_encounter_seed(generated, policy)

        return EncounterState(
            active=True,
            round_number=1,
            first_round_dex_gate_pending=True,
            initiator=initiator,
            combatants=[
                EnemyCombatant(
                    name=combatant.name,
                    description=combatant.description,
                    hp=combatant.hp,
                    max_hp=combatant.hp,
                    str_score=combatant.str_score,
                    dex_score=combatant.dex_score,
                    wil_score=combatant.wil_score,
                    armor=combatant.armor,
                    weapon_name=combatant.weapon_name,
                    weapon_damage_die=combatant.weapon_damage_die,
                    threat_level=combatant.threat_level,
                    weakness=combatant.weakness,
                    tactics=combatant.tactics,
                    leader=combatant.leader,
                    notes=combatant.notes,
                )
                for combatant in generated.combatants
            ],
            notes=generated.notes,
        )

    def _build_encounter_prompt(
        self,
        state: GameState,
        *,
        player_input: str,
        target_name: str,
        initiator: EncounterInitiator,
    ) -> str:
        return (
            CAIRN_ENCOUNTER_USER_PROMPT_TEMPLATE.replace("<<CURRENT_SCENE>>", state.current_scene)
            .replace("<<SETTING_NOTES>>", self._prompt_setting_context(state))
            .replace(
                "<<NPC_NAMES>>",
                ", ".join(npc.display_label() for npc in state.npcs) or "(none)",
            )
            .replace("<<CHARACTER_JSON>>", state.character.model_dump_json(indent=2))
            .replace("<<PLAYER_INPUT>>", player_input)
            .replace("<<ENCOUNTER_INITIATOR>>", initiator.value)
            .replace("<<TARGET_NAME>>", target_name)
        )

    def _prompt_setting_context(self, state: GameState) -> str:
        if not state.directives.has_content():
            return state.setting_notes
        directive_lines: list[str] = []
        if state.directives.world_guidance.strip():
            directive_lines.append(f"World guidance: {state.directives.world_guidance.strip()}")
        if state.directives.play_guidance.strip():
            directive_lines.append(f"Play guidance: {state.directives.play_guidance.strip()}")
        return state.setting_notes + "\n\nCampaign directives:\n" + "\n".join(directive_lines)

    def _fallback_encounter_seed(
        self,
        *,
        target_name: str,
        target_armor: int,
    ) -> GeneratedEncounterSeed:
        return GeneratedEncounterSeed(
            notes=(
                "Fallback encounter seed created because no combat seed model response was "
                "available."
            ),
            combatants=[
                GeneratedEncounterCombatant(
                    name=target_name.strip() or "Hostile foe",
                    description="A hostile figure drawn into the fight by the current scene.",
                    hp=3,
                    str_score=10,
                    dex_score=10,
                    wil_score=8,
                    armor=target_armor,
                    weapon_name="Weathered weapon",
                    weapon_damage_die=6,
                    threat_level=EncounterThreatLevel.ORDINARY,
                    leader=True,
                    notes="Fallback combatant.",
                ),
            ],
        )

    def _scaled_encounter_seed(
        self,
        seed: GeneratedEncounterSeed,
        policy: EncounterScalingPolicy,
    ) -> GeneratedEncounterSeed:
        combatants = [
            self._scaled_combatant(combatant, policy)
            for combatant in seed.combatants[: policy.max_combatants]
        ]
        if not any(combatant.leader for combatant in combatants):
            first = combatants[0]
            combatants[0] = first.model_copy(update={"leader": True})
        return GeneratedEncounterSeed(notes=seed.notes, combatants=combatants)

    def _scaled_combatant(
        self,
        combatant: GeneratedEncounterCombatant,
        policy: EncounterScalingPolicy,
    ) -> GeneratedEncounterCombatant:
        threat_level = combatant.threat_level
        hp = max(1, min(combatant.hp, policy.hp_cap_for(threat_level)))
        armor = max(0, min(combatant.armor, policy.armor_cap_for(threat_level)))
        die = combatant.weapon_damage_die
        if die not in ALLOWED_WEAPON_DICE:
            die = min(ALLOWED_WEAPON_DICE, key=lambda side: abs(side - die))
        return combatant.model_copy(
            update={
                "hp": hp,
                "armor": armor,
                "weapon_damage_die": die,
            },
        )
