from __future__ import annotations

import json
import time
from collections.abc import Generator
from dataclasses import dataclass

from dungeon_master.cancel import CancellationToken
from dungeon_master.models import GameState, OracleOutcome
from dungeon_master.narrative import (
    LITELLM_RETRYABLE_ERRORS,
    CompletionDelta,
    CompletionFunction,
    CompletionRequest,
    NarrativeConfig,
    _completion,
    complete_text,
    iter_text_deltas,
)

EXPLAINER_SYSTEM_PROMPT = """You are an out-of-character rules explainer for this specific game app.

Hard boundaries:
- You are NOT the narrator. Do not answer in-fiction.
- You do not advance play, roll dice, or mutate canon.
- You explain the mechanics and current state of THIS app as implemented, not generic D&D.
- If the app differs from tabletop defaults, prefer the app's behavior.
- If the answer is uncertain from the supplied state/context, say what is known and what is not.

Answer style:
- Be concise, practical, and plainspoken.
- Use short paragraphs or bullets when helpful.
- When relevant, connect the answer to the current state, latest receipt, or active encounter.
- Call out missing UI affordances honestly (for example when a mechanic exists
  in the backend but is not surfaced as an explicit command/control).
"""

IMPLEMENTED_MECHANICS_SUMMARY = """Implemented mechanics summary:
- This app is Cairn-inspired, not generic D&D.
- Core tracked stats are STR, DEX, WIL, HP, armor, fatigue, burden/slots,
  statuses, and inventory tags.
- Deterministic oracle operations include yes/no questions, random events, and scene checks.
- Natural-language turns may be routed into deterministic mechanics like save,
  attack, harm, recovery, equip, retreat, inspect inventory, search scene,
  acquire item, use item, and drop item.
- Spellbooks, scrolls, relics, and holy relics are item-bound powers with typed
  effects, limited uses or consumption when applicable, recharge text when
  known, spellbook Fatigue, and WIL-save risk under danger/deprivation.
- Plain prayer is not a generic buff command. Prayer can matter mechanically
  when it is routed through a carried holy relic/icon, an oracle/save, or
  another surfaced Cairn mechanism.
- Combat is tracked canonically, including enemy-opened ambushes and retreat outcomes.
- Mechanics live in Python and receipts; narration is downstream of the deterministic result.
"""


@dataclass(frozen=True)
class ExplanationResult:
    answer: str
    thinking: str = ""


class ExplainerEngine:
    def __init__(
        self,
        config: NarrativeConfig | None = None,
        completion_function: CompletionFunction | None = None,
    ) -> None:
        self._config = config or NarrativeConfig.from_env()
        self._completion = completion_function or _completion

    def generate_result(
        self,
        state: GameState,
        question: str,
        *,
        memory_context: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> ExplanationResult:
        if not self._config.is_usable():
            return ExplanationResult(
                answer=self._fallback_explanation(state, question),
            )

        request = self._build_request(
            state,
            question,
            memory_context=memory_context,
            stream=False,
            cancel_token=cancel_token,
        )

        last_error: Exception | None = None
        for attempt in range(self._config.max_retries + 1):
            try:
                generated = complete_text(request, self._completion)
                content = generated.content.strip()
                if content:
                    return ExplanationResult(
                        answer=content,
                        thinking=generated.thinking.strip(),
                    )
            except LITELLM_RETRYABLE_ERRORS as exc:
                last_error = exc
                if attempt < self._config.max_retries:
                    time.sleep(0.4 * (attempt + 1))

        fallback = self._fallback_explanation(state, question)
        if last_error is None:
            return ExplanationResult(answer=fallback)
        return ExplanationResult(answer=f"{fallback}\n\n[Explainer API unavailable: {last_error}]")

    def iter_stream(
        self,
        state: GameState,
        question: str,
        *,
        memory_context: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, ExplanationResult]:
        if not self._config.is_usable():
            fallback = self._fallback_explanation(state, question)
            yield CompletionDelta(content=fallback)
            return ExplanationResult(answer=fallback)

        request = self._build_request(
            state,
            question,
            memory_context=memory_context,
            stream=True,
            cancel_token=cancel_token,
        )

        last_error: Exception | None = None
        for attempt in range(self._config.max_retries + 1):
            content_parts: list[str] = []
            thinking_parts: list[str] = []
            try:
                for delta in iter_text_deltas(request, self._completion):
                    if delta.content:
                        content_parts.append(delta.content)
                    if delta.thinking:
                        thinking_parts.append(delta.thinking)
                    yield delta
                result = ExplanationResult(
                    answer="".join(content_parts).strip(),
                    thinking="".join(thinking_parts).strip(),
                )
                if result.answer:
                    return result
            except LITELLM_RETRYABLE_ERRORS as exc:
                last_error = exc
                if attempt < self._config.max_retries:
                    time.sleep(0.4 * (attempt + 1))

        fallback = self._fallback_explanation(state, question)
        if last_error is None:
            yield CompletionDelta(content=fallback)
            return ExplanationResult(answer=fallback)
        text = f"{fallback}\n\n[Explainer API unavailable: {last_error}]"
        yield CompletionDelta(content=text)
        return ExplanationResult(answer=text)

    def _build_request(
        self,
        state: GameState,
        question: str,
        *,
        memory_context: str | None,
        stream: bool,
        cancel_token: CancellationToken | None,
    ) -> CompletionRequest:
        profile = self._config.profiles.explainer
        messages = [
            {"role": "system", "content": EXPLAINER_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": self._build_user_prompt(
                    state,
                    question,
                    memory_context=memory_context,
                ),
            },
        ]
        return CompletionRequest(
            model=self._config.model,
            messages=messages,
            temperature=profile.temperature,
            max_tokens=profile.max_tokens,
            timeout=self._config.timeout_seconds,
            stream=stream,
            api_key=self._config.api_key,
            base_url=self._config.base_url,
            reasoning_effort=profile.reasoning_effort,
            reasoning=profile.reasoning(default_exclude=self._config.exclude_reasoning),
            extra_headers=self._openrouter_headers(),
            response_format=None,
            cancel_token=cancel_token,
            trace_route="explainer.answer",
            trace_profile="explainer",
        )

    def _build_user_prompt(
        self,
        state: GameState,
        question: str,
        *,
        memory_context: str | None,
    ) -> str:
        latest_outcome = state.oracle_history[-1] if state.oracle_history else None
        lines = [
            f"Player question: {question}",
            IMPLEMENTED_MECHANICS_SUMMARY,
            "Current state JSON:",
            self._compact_state_json(state),
        ]
        if state.directives.has_content():
            lines.extend(
                [
                    "Campaign directives:",
                    self._directives_prompt_block(state),
                ],
            )
        if latest_outcome is not None:
            lines.extend(
                [
                    "Latest oracle outcome JSON:",
                    self._compact_outcome_json(latest_outcome),
                ],
            )
        if memory_context:
            lines.extend(
                [
                    "Read-only continuity context:",
                    memory_context,
                ],
            )
        lines.extend(
            [
                "",
                (
                    "Answer the player's question in out-of-character terms. "
                    "Prefer this app's actual behavior over tabletop defaults. "
                    "If the state shows a concrete example, use it."
                ),
            ],
        )
        return "\n".join(lines)

    def _directives_prompt_block(self, state: GameState) -> str:
        lines: list[str] = []
        if state.directives.world_guidance.strip():
            lines.append(f"World guidance: {state.directives.world_guidance.strip()}")
        if state.directives.play_guidance.strip():
            lines.append(f"Play guidance: {state.directives.play_guidance.strip()}")
        return "\n".join(lines) or "(none)"

    def _compact_state_json(self, state: GameState) -> str:
        character = state.character
        cairn = character.cairn
        payload = {
            "campaign_status": state.campaign_status.value,
            "campaign_end_reason": (
                None if state.campaign_end_reason is None else state.campaign_end_reason.value
            ),
            "current_scene": self._clip(state.current_scene, 220),
            "scene_status": state.scene_status.value,
            "chaos_factor": state.chaos_factor,
            "character": {
                "name": character.name,
                "archetype": character.archetype,
                "drive": self._clip(character.drive, 140),
                "condition": self._clip(character.condition, 140),
                "cairn": {
                    "str": [cairn.str_score, cairn.max_str_score],
                    "dex": [cairn.dex_score, cairn.max_dex_score],
                    "wil": [cairn.wil_score, cairn.max_wil_score],
                    "hp": [cairn.hp, cairn.max_hp],
                    "armor": cairn.armor,
                    "fatigue": cairn.fatigue,
                    "burden": [cairn.slots_used, cairn.slots_total],
                    "survival": {
                        "day": cairn.survival.day_number,
                        "phase": cairn.survival.day_phase.value,
                        "watch_index": cairn.survival.watch_index,
                        "meal_pressure": cairn.survival.watches_since_meal,
                        "sleep_pressure": cairn.survival.watches_since_sleep,
                        "food_deprived": cairn.survival.food_deprived,
                        "sleep_deprived": cairn.survival.sleep_deprived,
                    },
                    "statuses": {
                        "deprived": cairn.deprived,
                        "critically_wounded": cairn.critically_wounded,
                        "doomed": cairn.doomed,
                        "paralyzed": cairn.paralyzed,
                        "delirious": cairn.delirious,
                        "dead": cairn.dead,
                        "overloaded": cairn.overloaded,
                    },
                    "skills": cairn.skills[:6],
                    "abilities": cairn.abilities[:6],
                    "primary_weapon_item_id": cairn.primary_weapon_item_id,
                },
                "inventory": [
                    {
                        "id": item.id,
                        "name": item.name,
                        "tags": [tag.value for tag in item.cairn.tags],
                        "slots": item.cairn.slots,
                        "weapon_damage_die": item.cairn.weapon_damage_die,
                        "armor_bonus": item.cairn.armor_bonus,
                        "uses": item.cairn.uses,
                        "equipped": item.cairn.equipped,
                    }
                    for item in character.inventory[:10]
                ],
            },
            "encounter": {
                "active": state.encounter.active,
                "round_number": state.encounter.round_number,
                "initiator": (
                    None if state.encounter.initiator is None else state.encounter.initiator.value
                ),
                "player_disengaged": state.encounter.player_disengaged,
                "combatants": [
                    {
                        "name": foe.name,
                        "hp": foe.hp,
                        "max_hp": foe.max_hp,
                        "armor": foe.armor,
                        "weapon_name": foe.weapon_name,
                        "weapon_damage_die": foe.weapon_damage_die,
                        "critically_wounded": foe.critically_wounded,
                        "defeated": foe.defeated,
                        "fled": foe.fled,
                    }
                    for foe in state.encounter.combatants[:6]
                ],
            },
            "recent_action_log": [
                {
                    "event_type": event.event_type.value,
                    "title": event.title,
                    "content": self._clip(event.content, 180),
                }
                for event in state.action_log[-6:]
            ],
        }
        return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))

    def _compact_outcome_json(self, outcome: OracleOutcome) -> str:
        payload = {
            "kind": outcome.kind.value,
            "summary": outcome.summary,
            "question": outcome.question,
            "answer": outcome.answer,
            "probability": outcome.probability,
            "scene_status": None if outcome.scene_status is None else outcome.scene_status.value,
            "event_focus": outcome.event_focus,
            "event_action": outcome.event_action,
            "event_subject": outcome.event_subject,
            "event_tone": outcome.event_tone,
            "cairn": None if outcome.cairn is None else outcome.cairn.model_dump(mode="json"),
        }
        return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))

    def _fallback_explanation(self, state: GameState, question: str) -> str:
        latest = state.oracle_history[-1] if state.oracle_history else None
        parts = [
            (
                "Out of character: the explainer model is not configured right now, "
                "so I can only give a deterministic fallback."
            ),
            f"You asked: {question}",
            (
                f"Current campaign status: {state.campaign_status.value}. "
                f"Chaos factor: {state.chaos_factor}."
            ),
        ]
        if state.encounter.active:
            parts.append(
                f"There is an active encounter in round {state.encounter.round_number} with "
                f"{len(state.encounter.combatants)} foe(s).",
            )
        if latest is not None:
            parts.append(
                f"The latest mechanical outcome was `{latest.kind.value}`: "
                f"{latest.summary}",
            )
        parts.append(
            (
                "This app uses Cairn-inspired mechanics with deterministic "
                "receipts; if you want a fuller answer, configure the model and "
                "ask again."
            ),
        )
        return "\n\n".join(parts)

    def _clip(self, text: str, limit: int) -> str:
        stripped = text.strip()
        if len(stripped) <= limit:
            return stripped
        return stripped[: limit - 3].rstrip() + "..."

    def _openrouter_headers(self) -> dict[str, str] | None:
        if not self._config.model.startswith("openrouter/"):
            return None
        headers: dict[str, str] = {}
        if self._config.site_url is not None:
            headers["HTTP-Referer"] = self._config.site_url
        if self._config.app_name is not None:
            headers["X-Title"] = self._config.app_name
        return headers or None
