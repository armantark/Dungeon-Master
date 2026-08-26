from __future__ import annotations

import json
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from pydantic import Field, ValidationError, model_validator

from dungeon_master.application.cancellation import CancellationToken
from dungeon_master.domain.models import (
    CharacterSheet,
    GameState,
    InventoryItem,
    OracleOutcome,
    StrictModel,
)
from dungeon_master.llm.narration import (
    LITELLM_RETRYABLE_ERRORS,
    CompletionFunction,
    CompletionRequest,
    NarrativeConfig,
    _completion,
    complete_text,
    extract_json_object,
)
from dungeon_master.llm.prompt_fragments import (
    JSON_ONLY,
    NO_KEYWORD_TRIGGERS,
    no_invention_rule,
    render_updater_user_prompt,
)

INVENTORY_UPDATER_SYSTEM_PROMPT = f"""You extract durable carried-inventory canon from a
resolved solo tabletop RPG turn.

{JSON_ONLY}

Hard rules:
- Emit 0-4 ops total.
- Supported ops are only:
  - add_item
  - remove_item
- Only emit an op when the executed backend steps or final narration explicitly
  establish that an actor now personally carries, wears, keeps, or loses a
  durable item for future play.
- Treat ordinary clothing, accessories, containers, documents, tools, food,
  drinks, and other mundane personal effects as valid inventory when the text
  makes them part of the actor's ongoing carried or worn state.
- Do not emit scene dressing, furniture, architecture, scenery, or temporary
  props that are merely nearby.
- Do not emit add_item for something already represented in the current
  inventory.
- Do not emit remove_item for something the current inventory does not already
  contain.
- For remove_item, use the exact current inventory item name from the supplied
  actor inventory.
- For add_item, `item_name` should be a concise label and `item_text` should be
  one short factual sentence describing exactly that one item and how the actor
  now has it. The downstream inventory system will derive structured mechanics
  from that sentence.
- Use exact actor_id values from the supplied actor list. Use "player" for the
  protagonist.
- {NO_KEYWORD_TRIGGERS}
- {
    no_invention_rule(
        "actors, player input, oracle outcome, executed backend steps, and final narration"
    )
}
- If no durable carried-inventory change occurred, return an empty ops list.
"""

INVENTORY_UPDATER_USER_PROMPT_TEMPLATE = """Return JSON with this shape:
{
  "ops": [
    {
      "actor_id": "player or exact party member id from the supplied actor list",
      "kind": "add_item | remove_item",
      "item_name": "concise item label",
      "item_text": "one factual sentence for add_item, otherwise null",
      "reason": "short evidence from the supplied context"
    }
  ]
}

<<USER_PROMPT_BODY>>
"""

MAX_GENERATED_INVENTORY_OPS = 4


class InventoryUpdateKind(StrEnum):
    ADD_ITEM = "add_item"
    REMOVE_ITEM = "remove_item"


class GeneratedInventoryUpdateOp(StrictModel):
    actor_id: str = Field(default="player", min_length=1, max_length=80)
    kind: InventoryUpdateKind
    item_name: str = Field(min_length=1, max_length=120)
    item_text: str | None = Field(default=None, max_length=240)
    reason: str = Field(default="", max_length=240)

    @model_validator(mode="after")
    def validate_shape(self) -> GeneratedInventoryUpdateOp:
        cleaned_text = _clean_text(self.item_text)
        if self.kind is InventoryUpdateKind.ADD_ITEM and cleaned_text is None:
            message = "add_item requires item_text."
            raise ValueError(message)
        return self


class GeneratedInventoryUpdateBatch(StrictModel):
    ops: list[GeneratedInventoryUpdateOp] = Field(
        default_factory=list,
        max_length=MAX_GENERATED_INVENTORY_OPS,
    )


@dataclass(frozen=True)
class InventoryUpdateResult:
    changed: bool = False
    summaries: tuple[str, ...] = ()


class InventoryMutationPort(Protocol):
    def acquire_items(
        self,
        state: GameState,
        *,
        text: str,
        actor_id: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> str:
        raise NotImplementedError

    def drop_item(
        self,
        state: GameState,
        *,
        item_id: str,
        actor_id: str | None = None,
    ) -> str:
        raise NotImplementedError


class InventoryUpdater:
    def __init__(
        self,
        *,
        cairn: InventoryMutationPort,
        config: NarrativeConfig | None = None,
        completion_function: CompletionFunction = _completion,
    ) -> None:
        self._cairn = cairn
        self._config = config or NarrativeConfig.from_env()
        self._completion = completion_function

    def update_inventory(  # noqa: PLR0913
        self,
        state: GameState,
        *,
        player_input: str,
        outcome: OracleOutcome,
        execution_context: str | None,
        narrative_text: str,
        cancel_token: CancellationToken | None = None,
    ) -> InventoryUpdateResult:
        generated = self.generate_inventory_updates(
            state,
            player_input=player_input,
            outcome=outcome,
            execution_context=execution_context,
            narrative_text=narrative_text,
            cancel_token=cancel_token,
        )
        if generated is None:
            return InventoryUpdateResult()
        return self.apply_generated_updates(
            state,
            generated,
            cancel_token=cancel_token,
        )

    def generate_inventory_updates(  # noqa: PLR0913
        self,
        state: GameState,
        *,
        player_input: str,
        outcome: OracleOutcome,
        execution_context: str | None,
        narrative_text: str,
        cancel_token: CancellationToken | None = None,
    ) -> GeneratedInventoryUpdateBatch | None:
        if not self._config.is_usable():
            return None

        prompt = self._build_prompt(
            state,
            player_input=player_input,
            outcome=outcome,
            execution_context=execution_context,
            narrative_text=narrative_text,
        )
        profile = self._config.profiles.inventory_updater
        request = CompletionRequest(
            model=self._config.model,
            messages=[
                {"role": "system", "content": INVENTORY_UPDATER_SYSTEM_PROMPT},
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
            trace_route="inventory_updater.apply",
            trace_profile="inventory_updater",
        )

        try:
            payload = self._complete_json(request)
            return GeneratedInventoryUpdateBatch.model_validate_json(extract_json_object(payload))
        except ValueError:
            return None

    def apply_generated_updates(
        self,
        state: GameState,
        generated: GeneratedInventoryUpdateBatch,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> InventoryUpdateResult:
        summaries: list[str] = []
        for op in generated.ops:
            summary = self._apply_op(state, op, cancel_token=cancel_token)
            if summary is not None:
                summaries.append(summary)
        return InventoryUpdateResult(changed=bool(summaries), summaries=tuple(summaries))

    def _build_prompt(
        self,
        state: GameState,
        *,
        player_input: str,
        outcome: OracleOutcome,
        execution_context: str | None,
        narrative_text: str,
    ) -> str:
        prompt = INVENTORY_UPDATER_USER_PROMPT_TEMPLATE
        body = render_updater_user_prompt(
            scene_text=state.current_scene,
            player_input=player_input,
            outcome_kind=outcome.kind.value,
            outcome_summary=outcome.summary,
            execution_context=execution_context,
            final_narration=narrative_text,
            actors=json.dumps(_actor_payloads(state), ensure_ascii=False),
        )
        return prompt.replace("<<USER_PROMPT_BODY>>\n", body)

    def _apply_op(
        self,
        state: GameState,
        op: GeneratedInventoryUpdateOp,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> str | None:
        target = _target_sheet(state, op.actor_id)
        if target is None:
            return None
        if op.kind is InventoryUpdateKind.ADD_ITEM:
            return self._apply_add_item(
                state,
                target,
                op,
                cancel_token=cancel_token,
            )
        return self._apply_remove_item(state, target, op)

    def _apply_add_item(
        self,
        state: GameState,
        sheet: CharacterSheet,
        op: GeneratedInventoryUpdateOp,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> str | None:
        item_name = _clean_text(op.item_name)
        item_text = _clean_text(op.item_text)
        if item_name is None or item_text is None:
            return None
        if _find_inventory_item(sheet.inventory, item_name) is not None:
            return None
        try:
            return self._cairn.acquire_items(
                state,
                text=item_text,
                actor_id=op.actor_id,
                cancel_token=cancel_token,
            )
        except ValueError:
            return None

    def _apply_remove_item(
        self,
        state: GameState,
        sheet: CharacterSheet,
        op: GeneratedInventoryUpdateOp,
    ) -> str | None:
        target = _find_inventory_item(sheet.inventory, op.item_name)
        if target is None:
            return None
        try:
            return self._cairn.drop_item(
                state,
                item_id=target.id,
                actor_id=op.actor_id,
            )
        except ValueError:
            return None

    def _complete_json(self, request: CompletionRequest) -> str:
        last_error: Exception | None = None
        for attempt in range(self._config.max_retries + 1):
            try:
                result = complete_text(request, self._completion)
                if result.content.strip():
                    return result.content
                message = "Inventory updater returned empty content."
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
            message = "Inventory updater failed."
            raise ValueError(message) from last_error
        message = "Inventory updater failed."
        raise ValueError(message)

    def _openrouter_headers(self) -> dict[str, str] | None:
        headers: dict[str, str] = {}
        if self._config.site_url:
            headers["HTTP-Referer"] = self._config.site_url
        if self._config.app_name:
            headers["X-Title"] = self._config.app_name
        return headers or None


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.split())
    return cleaned or None


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def _find_inventory_item(
    inventory: list[InventoryItem],
    candidate_name: str,
) -> InventoryItem | None:
    candidate = _clean_text(candidate_name)
    if candidate is None:
        return None
    normalized_candidate = _normalize(candidate)
    for item in inventory:
        normalized_existing = _normalize(item.name)
        if (
            normalized_existing == normalized_candidate
            or normalized_existing in normalized_candidate
            or normalized_candidate in normalized_existing
        ):
            return item
    return None


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
        "condition": sheet.condition,
        "inventory": [
            {
                "name": item.name,
                "details": item.details,
                "equipped": item.cairn.equipped,
                "tags": [tag.value for tag in item.cairn.tags],
            }
            for item in sheet.inventory
        ],
    }


def _target_sheet(state: GameState, actor_id: str) -> CharacterSheet | None:
    if actor_id == "player":
        return state.character
    for member in state.party_members:
        if member.active and member.id == actor_id:
            return member.sheet
    return None
