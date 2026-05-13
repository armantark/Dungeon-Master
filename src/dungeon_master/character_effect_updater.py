from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from pydantic import Field, ValidationError, model_validator

from dungeon_master.cancel import CancellationToken
from dungeon_master.models import (
    CairnCharacterState,
    CharacterSheet,
    GameState,
    OracleOutcome,
    StrictModel,
)
from dungeon_master.narrative import (
    LITELLM_RETRYABLE_ERRORS,
    CompletionFunction,
    CompletionRequest,
    NarrativeConfig,
    _completion,
    complete_text,
    extract_json_object,
)

CHARACTER_EFFECT_SYSTEM_PROMPT = """You extract durable character-sheet effects from a
resolved solo tabletop RPG turn.

Return only valid JSON.

Hard rules:
- Emit only effects that the final narration explicitly makes real, or that the
  executed backend steps already establish.
- Do not infer consequences from genre color alone. Pain, fear, fatigue, vows,
  wounds, or ominous language are not mechanical changes unless the text says a
  durable sheet fact changed.
- Do not use keywords as triggers. Judge the whole context.
- Effects may target the protagonist or an active party member, but each op must
  use an exact actor_id from the supplied actor list. Use "player" for the
  protagonist.
- Supported mutations are intentionally narrow:
  - add_ability: a new permission/capability the character now has
  - remove_ability: a capability explicitly lost
  - adjust_max_hp: a lasting change to maximum HP
  - adjust_max_str: a lasting change to maximum STR
  - adjust_max_dex: a lasting change to maximum DEX
  - adjust_max_wil: a lasting change to maximum WIL
  - set_condition: a concise current condition sentence
  - append_note: a concise mechanical note
- For max-stat adjustments, use small signed integers. Costs should be negative.
- If an ability is granted by the fiction, use a concise title-case label such as
  "Telepathy"; do not bury it in prose.
- If no supported durable sheet effect occurred, return an empty ops list.
"""

CHARACTER_EFFECT_USER_PROMPT_TEMPLATE = """Return JSON with this shape:
{
  "ops": [
    {
      "actor_id": "player or exact party member id from the supplied actor list",
      "kind": "one supported mutation kind listed above",
      "value": "ability/condition/note text or null",
      "amount": -1,
      "reason": "short evidence from the supplied context"
    }
  ]
}

Current actors:
<<ACTORS_JSON>>

Current scene:
<<CURRENT_SCENE>>

Player input:
<<PLAYER_INPUT>>

Resolved oracle outcome:
- kind: <<OUTCOME_KIND>>
- summary: <<OUTCOME_SUMMARY>>

Executed backend steps (may be empty):
<<EXECUTION_CONTEXT>>

Final narration response:
<<NARRATIVE_TEXT>>
"""

MAX_GENERATED_EFFECT_OPS = 4
MAX_STAT_DELTA = 6


class CharacterEffectKind(StrEnum):
    ADD_ABILITY = "add_ability"
    REMOVE_ABILITY = "remove_ability"
    ADJUST_MAX_HP = "adjust_max_hp"
    ADJUST_MAX_STR = "adjust_max_str"
    ADJUST_MAX_DEX = "adjust_max_dex"
    ADJUST_MAX_WIL = "adjust_max_wil"
    SET_CONDITION = "set_condition"
    APPEND_NOTE = "append_note"


class GeneratedCharacterEffectOp(StrictModel):
    actor_id: str = Field(default="player", min_length=1, max_length=80)
    kind: CharacterEffectKind
    value: str | None = Field(default=None, max_length=240)
    amount: int | None = Field(default=None, ge=-MAX_STAT_DELTA, le=MAX_STAT_DELTA)
    reason: str = Field(default="", max_length=240)

    @model_validator(mode="after")
    def validate_value_shape(self) -> GeneratedCharacterEffectOp:
        text_ops = {
            CharacterEffectKind.ADD_ABILITY,
            CharacterEffectKind.REMOVE_ABILITY,
            CharacterEffectKind.SET_CONDITION,
            CharacterEffectKind.APPEND_NOTE,
        }
        stat_ops = {
            CharacterEffectKind.ADJUST_MAX_HP,
            CharacterEffectKind.ADJUST_MAX_STR,
            CharacterEffectKind.ADJUST_MAX_DEX,
            CharacterEffectKind.ADJUST_MAX_WIL,
        }
        cleaned = _clean_text(self.value)
        if self.kind in text_ops and cleaned is None:
            message = f"{self.kind.value} requires value."
            raise ValueError(message)
        if self.kind in stat_ops and self.amount is None:
            message = f"{self.kind.value} requires amount."
            raise ValueError(message)
        return self


class GeneratedCharacterEffectBatch(StrictModel):
    ops: list[GeneratedCharacterEffectOp] = Field(
        default_factory=list,
        max_length=MAX_GENERATED_EFFECT_OPS,
    )


@dataclass(frozen=True)
class CharacterEffectUpdateResult:
    changed: bool = False
    summaries: tuple[str, ...] = ()


class CharacterEffectUpdater:
    def __init__(
        self,
        *,
        config: NarrativeConfig | None = None,
        completion_function: CompletionFunction = _completion,
    ) -> None:
        self._config = config or NarrativeConfig.from_env()
        self._completion = completion_function

    def update_character_effects(  # noqa: PLR0913
        self,
        state: GameState,
        *,
        player_input: str,
        outcome: OracleOutcome,
        execution_context: str | None,
        narrative_text: str,
        cancel_token: CancellationToken | None = None,
    ) -> CharacterEffectUpdateResult:
        generated = self.generate_character_effects(
            state,
            player_input=player_input,
            outcome=outcome,
            execution_context=execution_context,
            narrative_text=narrative_text,
            cancel_token=cancel_token,
        )
        if generated is None:
            return CharacterEffectUpdateResult()
        return self.apply_generated_effects(state, generated)

    def generate_character_effects(  # noqa: PLR0913
        self,
        state: GameState,
        *,
        player_input: str,
        outcome: OracleOutcome,
        execution_context: str | None,
        narrative_text: str,
        cancel_token: CancellationToken | None = None,
    ) -> GeneratedCharacterEffectBatch | None:
        if not self._config.is_usable():
            return None

        prompt = self._build_prompt(
            state,
            player_input=player_input,
            outcome=outcome,
            execution_context=execution_context,
            narrative_text=narrative_text,
        )
        profile = self._config.profiles.character_effect_updater
        request = CompletionRequest(
            model=self._config.model,
            messages=[
                {"role": "system", "content": CHARACTER_EFFECT_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=profile.temperature,
            max_tokens=profile.max_tokens,
            timeout=self._config.timeout_seconds,
            stream=True,
            api_key=self._config.api_key,
            base_url=self._config.base_url,
            reasoning_effort=profile.reasoning_effort,
            reasoning=profile.reasoning(default_exclude=self._config.exclude_reasoning),
            extra_headers=self._openrouter_headers(),
            response_format=None,
            cancel_token=cancel_token,
            trace_route="character_effect_updater.apply",
            trace_profile="character_effect_updater",
        )

        try:
            payload = self._complete_json(request)
            return GeneratedCharacterEffectBatch.model_validate_json(extract_json_object(payload))
        except ValueError:
            return None

    def apply_generated_effects(
        self,
        state: GameState,
        generated: GeneratedCharacterEffectBatch,
    ) -> CharacterEffectUpdateResult:
        summaries: list[str] = []
        for op in generated.ops:
            summary = self._apply_op(state, op)
            if summary is not None:
                summaries.append(summary)
        return CharacterEffectUpdateResult(changed=bool(summaries), summaries=tuple(summaries))

    def _build_prompt(
        self,
        state: GameState,
        *,
        player_input: str,
        outcome: OracleOutcome,
        execution_context: str | None,
        narrative_text: str,
    ) -> str:
        actors_json = json.dumps(_actor_payloads(state), ensure_ascii=False)
        replacements = {
            "<<ACTORS_JSON>>": actors_json,
            "<<CURRENT_SCENE>>": state.current_scene,
            "<<PLAYER_INPUT>>": player_input,
            "<<OUTCOME_KIND>>": outcome.kind.value,
            "<<OUTCOME_SUMMARY>>": outcome.summary,
            "<<EXECUTION_CONTEXT>>": execution_context or "(none)",
            "<<NARRATIVE_TEXT>>": narrative_text,
        }
        prompt = CHARACTER_EFFECT_USER_PROMPT_TEMPLATE
        for marker, value in replacements.items():
            prompt = prompt.replace(marker, value)
        return prompt

    def _apply_op(self, state: GameState, op: GeneratedCharacterEffectOp) -> str | None:
        target = _target_sheet(state, op.actor_id)
        if target is None:
            return None
        handlers: dict[CharacterEffectKind, _EffectHandler] = {
            CharacterEffectKind.ADD_ABILITY: self._apply_add_ability,
            CharacterEffectKind.REMOVE_ABILITY: self._apply_remove_ability,
            CharacterEffectKind.ADJUST_MAX_HP: self._apply_adjust_max_hp,
            CharacterEffectKind.ADJUST_MAX_STR: self._apply_adjust_max_str,
            CharacterEffectKind.ADJUST_MAX_DEX: self._apply_adjust_max_dex,
            CharacterEffectKind.ADJUST_MAX_WIL: self._apply_adjust_max_wil,
            CharacterEffectKind.SET_CONDITION: self._apply_set_condition,
            CharacterEffectKind.APPEND_NOTE: self._apply_append_note,
        }
        return handlers[op.kind](target, op)

    def _apply_add_ability(
        self,
        sheet: CharacterSheet,
        op: GeneratedCharacterEffectOp,
    ) -> str | None:
        cairn = sheet.cairn
        ability = _clean_text(op.value)
        if ability is None or _contains_normalized(cairn.abilities, ability):
            return None
        cairn.abilities.append(ability)
        return f"{sheet.name} gained ability: {ability}."

    def _apply_remove_ability(
        self,
        sheet: CharacterSheet,
        op: GeneratedCharacterEffectOp,
    ) -> str | None:
        cairn = sheet.cairn
        ability = _clean_text(op.value)
        if ability is None:
            return None
        before = len(cairn.abilities)
        cairn.abilities = [
            existing
            for existing in cairn.abilities
            if _normalize(existing) != _normalize(ability)
        ]
        if len(cairn.abilities) == before:
            return None
        return f"{sheet.name} lost ability: {ability}."

    def _apply_adjust_max_hp(
        self,
        sheet: CharacterSheet,
        op: GeneratedCharacterEffectOp,
    ) -> str | None:
        cairn = sheet.cairn
        return _adjust_max_stat(
            label=f"{sheet.name} Max HP",
            amount=op.amount,
            current=cairn.hp,
            maximum=cairn.max_hp,
            set_values=_max_hp_setter(cairn),
        )

    def _apply_adjust_max_str(
        self,
        sheet: CharacterSheet,
        op: GeneratedCharacterEffectOp,
    ) -> str | None:
        cairn = sheet.cairn
        return _adjust_max_stat(
            label=f"{sheet.name} Max STR",
            amount=op.amount,
            current=cairn.str_score,
            maximum=cairn.max_str_score,
            set_values=_max_str_setter(cairn),
        )

    def _apply_adjust_max_dex(
        self,
        sheet: CharacterSheet,
        op: GeneratedCharacterEffectOp,
    ) -> str | None:
        cairn = sheet.cairn
        return _adjust_max_stat(
            label=f"{sheet.name} Max DEX",
            amount=op.amount,
            current=cairn.dex_score,
            maximum=cairn.max_dex_score,
            set_values=_max_dex_setter(cairn),
        )

    def _apply_adjust_max_wil(
        self,
        sheet: CharacterSheet,
        op: GeneratedCharacterEffectOp,
    ) -> str | None:
        cairn = sheet.cairn
        return _adjust_max_stat(
            label=f"{sheet.name} Max WIL",
            amount=op.amount,
            current=cairn.wil_score,
            maximum=cairn.max_wil_score,
            set_values=_max_wil_setter(cairn),
        )

    def _apply_set_condition(
        self,
        sheet: CharacterSheet,
        op: GeneratedCharacterEffectOp,
    ) -> str | None:
        condition = _clean_text(op.value)
        if condition is None or sheet.condition == condition:
            return None
        sheet.condition = condition
        return f"{sheet.name} condition updated: {condition}"

    def _apply_append_note(
        self,
        sheet: CharacterSheet,
        op: GeneratedCharacterEffectOp,
    ) -> str | None:
        cairn = sheet.cairn
        note = _clean_text(op.value)
        if note is None or note in cairn.notes:
            return None
        separator = "\n" if cairn.notes else ""
        cairn.notes = f"{cairn.notes}{separator}{note}"
        return f"{sheet.name} character note added: {note}"

    def _complete_json(self, request: CompletionRequest) -> str:
        last_error: Exception | None = None
        for attempt in range(self._config.max_retries + 1):
            try:
                result = complete_text(request, self._completion)
                if result.content.strip():
                    return result.content
                message = "Character effect updater returned empty content."
                raise ValueError(message)
            except LITELLM_RETRYABLE_ERRORS as exc:
                last_error = exc
                if attempt < self._config.max_retries:
                    time.sleep(0.4 * (attempt + 1))
                    continue
            except (ValidationError, json.JSONDecodeError) as exc:
                last_error = exc
                break
        if last_error is not None:
            message = "Character effect updater failed."
            raise ValueError(message) from last_error
        message = "Character effect updater failed."
        raise ValueError(message)

    def _openrouter_headers(self) -> dict[str, str] | None:
        headers: dict[str, str] = {}
        if self._config.site_url:
            headers["HTTP-Referer"] = self._config.site_url
        if self._config.app_name:
            headers["X-Title"] = self._config.app_name
        return headers or None


def _adjust_max_stat(
    *,
    label: str,
    amount: int | None,
    current: int,
    maximum: int,
    set_values: _StatSetter,
) -> str | None:
    if amount is None or amount == 0:
        return None
    updated_max = max(0, maximum + amount)
    updated_current = min(max(0, current + amount), updated_max)
    if updated_max == maximum and updated_current == current:
        return None
    set_values(updated_current, updated_max)
    sign = "+" if amount > 0 else ""
    return f"{label} {sign}{amount}: {maximum} -> {updated_max}."


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.split())
    return cleaned or None


def _contains_normalized(values: list[str], candidate: str) -> bool:
    normalized = _normalize(candidate)
    return any(_normalize(value) == normalized for value in values)


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def _actor_payloads(state: GameState) -> list[dict[str, object]]:
    return [
        _actor_payload("player", state.character),
        *(
            _actor_payload(member.id, member.sheet)
            for member in state.party_members
            if member.active
        ),
    ]


def _actor_payload(actor_id: str, sheet: CharacterSheet) -> dict[str, object]:
    return {
        "actor_id": actor_id,
        "name": sheet.name,
        "archetype": sheet.archetype,
        "epithet": sheet.epithet,
        "condition": sheet.condition,
        "cairn": {
            "hp": sheet.cairn.hp,
            "max_hp": sheet.cairn.max_hp,
            "str_score": sheet.cairn.str_score,
            "max_str_score": sheet.cairn.max_str_score,
            "dex_score": sheet.cairn.dex_score,
            "max_dex_score": sheet.cairn.max_dex_score,
            "wil_score": sheet.cairn.wil_score,
            "max_wil_score": sheet.cairn.max_wil_score,
            "abilities": sheet.cairn.abilities,
            "notes": sheet.cairn.notes,
        },
    }


def _target_sheet(state: GameState, actor_id: str) -> CharacterSheet | None:
    if actor_id == "player":
        return state.character
    for member in state.party_members:
        if member.active and member.id == actor_id:
            return member.sheet
    return None


def _max_hp_setter(cairn: CairnCharacterState) -> _StatSetter:
    def set_values(current: int, maximum: int) -> None:
        cairn.hp = current
        cairn.max_hp = maximum

    return set_values


def _max_str_setter(cairn: CairnCharacterState) -> _StatSetter:
    def set_values(current: int, maximum: int) -> None:
        cairn.str_score = current
        cairn.max_str_score = maximum

    return set_values


def _max_dex_setter(cairn: CairnCharacterState) -> _StatSetter:
    def set_values(current: int, maximum: int) -> None:
        cairn.dex_score = current
        cairn.max_dex_score = maximum

    return set_values


def _max_wil_setter(cairn: CairnCharacterState) -> _StatSetter:
    def set_values(current: int, maximum: int) -> None:
        cairn.wil_score = current
        cairn.max_wil_score = maximum

    return set_values


type _StatSetter = Callable[[int, int], None]
type _EffectHandler = Callable[[CharacterSheet, GeneratedCharacterEffectOp], str | None]
