from __future__ import annotations

import json
import time
from dataclasses import dataclass
from enum import StrEnum

from pydantic import Field, ValidationError

from dungeon_master.cancel import CancellationToken
from dungeon_master.models import (
    CharacterSheet,
    GameState,
    Likelihood,
    OracleKind,
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

CAPABILITY_ORACLE_GUARD_SYSTEM_PROMPT = """You protect a solo tabletop RPG from
unbounded ability-fishing via yes/no oracle questions.

Return only valid JSON.

Policy:
- Ordinary world uncertainty should pass through unchanged.
- Questions asking whether a character/NPC/party member has a specific spell,
  special ability, hidden power, affinity, training, item power, or similar
  capability are capability-discovery questions.
- Canonical character sheets, abilities, notes, and carried items are the
  source of truth. The oracle can clarify latent facts, but it is not a free
  skill generator.
- If canon already establishes the capability, choose `established_yes`.
- If canon already rules it out or a prior canonical answer already resolved the
  same capability negatively, choose `established_no`.
- If canon provides real support but not certainty (role, item, notes, existing
  adjacent ability, recent durable fact), choose `latent_roll`.
- If there is no meaningful support beyond the player's wish/question, choose
  `unsupported_no`.
- If the same capability question was already resolved recently, choose the
  established result rather than allowing a reroll.
- Never invent a new capability to justify a roll.

Use `reason` to cite the supplied sheet/item/history evidence briefly.
"""

CAPABILITY_ORACLE_GUARD_USER_PROMPT_TEMPLATE = """Return JSON with this shape:
{
  "decision": "ordinary | established_yes | established_no | latent_roll | unsupported_no",
  "actor_id": "player, party member id, visible npc id, or null",
  "capability": "short capability label or null",
  "reason": "brief evidence"
}

Question:
<<QUESTION>>

Requested likelihood:
<<LIKELIHOOD>>

Current scene:
<<CURRENT_SCENE>>

Actors and visible recurring figures:
<<ACTORS_JSON>>

Recent yes/no oracle history:
<<RECENT_ORACLES_JSON>>

Campaign directives:
<<DIRECTIVES>>
"""

MAX_REASON_LENGTH = 240
LATENT_CAPABILITY_LIKELIHOOD = Likelihood.UNLIKELY
UNSUPPORTED_CAPABILITY_LIKELIHOOD = Likelihood.IMPOSSIBLE


class CapabilityOracleDecisionKind(StrEnum):
    ORDINARY = "ordinary"
    ESTABLISHED_YES = "established_yes"
    ESTABLISHED_NO = "established_no"
    LATENT_ROLL = "latent_roll"
    UNSUPPORTED_NO = "unsupported_no"


class GeneratedCapabilityOracleDecision(StrictModel):
    decision: CapabilityOracleDecisionKind
    actor_id: str | None = Field(default=None, max_length=80)
    capability: str | None = Field(default=None, max_length=120)
    reason: str = Field(default="", max_length=MAX_REASON_LENGTH)


@dataclass(frozen=True)
class CapabilityOracleGuardResult:
    outcome: OracleOutcome | None = None
    likelihood: Likelihood | None = None
    execution_summary: str | None = None


class CapabilityOracleGuard:
    def __init__(
        self,
        *,
        config: NarrativeConfig | None = None,
        completion_function: CompletionFunction = _completion,
    ) -> None:
        self._config = config or NarrativeConfig.from_env()
        self._completion = completion_function

    def guard_yes_no(
        self,
        state: GameState,
        *,
        question: str,
        requested_likelihood: Likelihood,
        cancel_token: CancellationToken | None = None,
    ) -> CapabilityOracleGuardResult:
        generated = self._generate_decision(
            state,
            question=question,
            requested_likelihood=requested_likelihood,
            cancel_token=cancel_token,
        )
        if generated is None or generated.decision == CapabilityOracleDecisionKind.ORDINARY:
            return CapabilityOracleGuardResult(likelihood=requested_likelihood)
        if generated.decision == CapabilityOracleDecisionKind.LATENT_ROLL:
            likelihood = _minimum_likelihood(requested_likelihood, LATENT_CAPABILITY_LIKELIHOOD)
            return CapabilityOracleGuardResult(
                likelihood=likelihood,
                execution_summary=(
                    "Capability question constrained by canonical sheet context "
                    f"to {likelihood.value}: {_summary_reason(generated)}"
                ),
            )
        if generated.decision == CapabilityOracleDecisionKind.ESTABLISHED_YES:
            outcome = _established_outcome(
                state,
                question=question,
                answer="Yes",
                likelihood=Likelihood.NEARLY_CERTAIN,
                reason=_summary_reason(generated),
            )
            return CapabilityOracleGuardResult(
                outcome=outcome,
                execution_summary=f"Capability answered from canonical sheet: {outcome.summary}",
            )
        outcome = _established_outcome(
            state,
            question=question,
            answer="No",
            likelihood=UNSUPPORTED_CAPABILITY_LIKELIHOOD,
            reason=_summary_reason(generated),
        )
        summary_label = (
            "Capability answered from canonical sheet"
            if generated.decision == CapabilityOracleDecisionKind.ESTABLISHED_NO
            else "Capability rejected as unsupported by canonical sheet"
        )
        return CapabilityOracleGuardResult(
            outcome=outcome,
            execution_summary=f"{summary_label}: {outcome.summary}",
        )

    def _generate_decision(
        self,
        state: GameState,
        *,
        question: str,
        requested_likelihood: Likelihood,
        cancel_token: CancellationToken | None,
    ) -> GeneratedCapabilityOracleDecision | None:
        if not self._config.is_usable():
            return None
        profile = self._config.profiles.capability_oracle_guard
        request = CompletionRequest(
            model=self._config.model,
            messages=[
                {"role": "system", "content": CAPABILITY_ORACLE_GUARD_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": self._build_prompt(
                        state,
                        question=question,
                        requested_likelihood=requested_likelihood,
                    ),
                },
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
            trace_route="capability_oracle_guard",
            trace_profile="capability_oracle_guard",
        )
        try:
            payload = self._complete_json(request)
            return GeneratedCapabilityOracleDecision.model_validate_json(
                extract_json_object(payload),
            )
        except (ValidationError, json.JSONDecodeError, ValueError):
            return None

    def _build_prompt(
        self,
        state: GameState,
        *,
        question: str,
        requested_likelihood: Likelihood,
    ) -> str:
        replacements = {
            "<<QUESTION>>": question.strip(),
            "<<LIKELIHOOD>>": requested_likelihood.value,
            "<<CURRENT_SCENE>>": state.current_scene,
            "<<ACTORS_JSON>>": json.dumps(_actor_payloads(state), ensure_ascii=False),
            "<<RECENT_ORACLES_JSON>>": json.dumps(
                _recent_yes_no_oracles(state),
                ensure_ascii=False,
            ),
            "<<DIRECTIVES>>": _directives_prompt_block(state),
        }
        prompt = CAPABILITY_ORACLE_GUARD_USER_PROMPT_TEMPLATE
        for marker, value in replacements.items():
            prompt = prompt.replace(marker, value)
        return prompt

    def _complete_json(self, request: CompletionRequest) -> str:
        last_error: Exception | None = None
        for attempt in range(self._config.max_retries + 1):
            try:
                result = complete_text(request, self._completion)
                if result.content.strip():
                    return result.content
                message = "Capability oracle guard returned empty content."
                raise ValueError(message)
            except LITELLM_RETRYABLE_ERRORS as exc:
                last_error = exc
                if attempt < self._config.max_retries:
                    time.sleep(0.25 * (attempt + 1))
                    continue
            except (ValidationError, json.JSONDecodeError) as exc:
                last_error = exc
                break
        if last_error is not None:
            message = "Capability oracle guard failed."
            raise ValueError(message) from last_error
        message = "Capability oracle guard failed."
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


def _established_outcome(
    state: GameState,
    *,
    question: str,
    answer: str,
    likelihood: Likelihood,
    reason: str,
) -> OracleOutcome:
    summary = f"{answer}: {question} ({reason})"
    return OracleOutcome(
        kind=OracleKind.YES_NO,
        summary=summary,
        question=question,
        likelihood=likelihood,
        answer=answer,
        probability=99 if answer == "Yes" else 1,
        chaos_factor=state.chaos_factor,
    )


def _actor_payloads(state: GameState) -> list[dict[str, object]]:
    party_npc_ids = {
        member.npc_id
        for member in state.party_members
        if member.active and member.npc_id is not None
    }
    payloads = [_sheet_payload("player", state.character.name, state.character)]
    payloads.extend(
        _sheet_payload(member.id, member.display_label(), member.sheet)
        for member in state.party_members
        if member.active
    )
    payloads.extend(
        {
            "actor_id": npc.id,
            "name": npc.display_label(),
            "kind": "visible_npc",
            "role": npc.role,
            "disposition": npc.disposition,
        }
        for npc in state.npcs
        if npc.id not in party_npc_ids
    )
    return payloads


def _sheet_payload(actor_id: str, name: str, character: CharacterSheet) -> dict[str, object]:
    return {
        "actor_id": actor_id,
        "name": name,
        "kind": "character_sheet",
        "archetype": character.archetype,
        "epithet": character.epithet,
        "condition": character.condition,
        "cairn": {
            "abilities": character.cairn.abilities,
            "skills": character.cairn.skills,
            "notes": character.cairn.notes,
            "hp": [character.cairn.hp, character.cairn.max_hp],
            "wil": [character.cairn.wil_score, character.cairn.max_wil_score],
        },
        "inventory": [
            {
                "name": item.name,
                "details": item.details,
                "tags": [tag.value for tag in item.cairn.tags],
                "power": item.cairn.power.model_dump(mode="json"),
                "uses": item.cairn.uses,
            }
            for item in character.inventory[:8]
        ],
    }


def _recent_yes_no_oracles(state: GameState) -> list[dict[str, object]]:
    return [
        {
            "question": outcome.question,
            "answer": outcome.answer,
            "summary": outcome.summary,
            "likelihood": None if outcome.likelihood is None else outcome.likelihood.value,
        }
        for outcome in state.oracle_history[-12:]
        if outcome.kind == OracleKind.YES_NO
    ]


def _directives_prompt_block(state: GameState) -> str:
    lines: list[str] = []
    if state.directives.world_guidance.strip():
        lines.append(f"World guidance: {state.directives.world_guidance.strip()}")
    if state.directives.play_guidance.strip():
        lines.append(f"Play guidance: {state.directives.play_guidance.strip()}")
    return "\n".join(lines) or "(none)"


def _minimum_likelihood(left: Likelihood, right: Likelihood) -> Likelihood:
    order = (
        Likelihood.IMPOSSIBLE,
        Likelihood.VERY_UNLIKELY,
        Likelihood.UNLIKELY,
        Likelihood.EVEN,
        Likelihood.LIKELY,
        Likelihood.VERY_LIKELY,
        Likelihood.NEARLY_CERTAIN,
    )
    left_index = order.index(left)
    right_index = order.index(right)
    return order[min(left_index, right_index)]


def _summary_reason(generated: GeneratedCapabilityOracleDecision) -> str:
    parts = []
    if generated.capability:
        parts.append(generated.capability)
    if generated.reason:
        parts.append(generated.reason)
    if not parts:
        return "canonical capability policy"
    return "; ".join(parts)[:MAX_REASON_LENGTH]
