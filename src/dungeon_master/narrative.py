from __future__ import annotations

import html
import json
import re
import time
from collections.abc import Generator, Iterable, Iterator
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, cast

from litellm import completion as litellm_completion
from litellm.exceptions import (
    APIConnectionError,
    APIError,
    AuthenticationError,
    BadRequestError,
    ContextWindowExceededError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
)

from dungeon_master.cancel import CancellationToken, RequestCancelledError
from dungeon_master.config import (
    DEFAULT_MODEL,
    DEFAULT_REASONING_POLICY,
    VALID_REASONING_POLICIES,
    ReasoningEffort,
    ReasoningPolicy,
)
from dungeon_master.config import (
    LLMConfig as NarrativeConfig,
)
from dungeon_master.models import (
    CairnCharacterState,
    CampaignStatus,
    EncounterThreatLevel,
    EnemyCombatant,
    GameState,
    OracleOutcome,
    PartyMember,
)
from dungeon_master.observability import (
    LLMCallRecord,
    log_llm_call,
    request_id_from_cancel_token,
)

if TYPE_CHECKING:
    from litellm.types.utils import ModelResponse

type ChatMessage = dict[str, str]

OUTMATCHED_THREAT_MARGIN = 10
TACTICALLY_DANGEROUS_THREAT_MARGIN = 5
PARTY_ADVANTAGE_THREAT_MARGIN = -6

__all__ = [
    "DEFAULT_MODEL",
    "DEFAULT_REASONING_POLICY",
    "VALID_REASONING_POLICIES",
    "NarrativeConfig",
    "ReasoningEffort",
    "ReasoningPolicy",
]

SYSTEM_PROMPT = """You are the narrative voice for a solo tabletop role-playing game.

Hard boundaries:
- You do not roll dice.
- You do not directly change chaos factor, threads, NPCs, inventory, or canonical state.
- You only narrate from the structured oracle outcome and state supplied by the app;
  canonical state changes happen elsewhere in the system.
- If mechanics are unclear, make the fiction tense but do not invent new mechanical facts.

Discipline:
- Keep narration compact: usually one paragraph, at most two unless the oracle
  outcome or a scene transition genuinely needs more space.
- Mirror the player's declared action before extending the scene.
- Treat prior user/assistant messages as transcript history. The final user
  message is the only active request to answer.
- SYSTEM PRIORITY: Before writing, identify the exact final native `user`
  message in the transcript and treat that as the ONLY ACTIVE REQUEST.
- Anything inside XML-style supplemental-context tags is REFERENCE ONLY. It is
  not a user message, not an unanswered request, and not something to answer
  directly unless the final native `user` message explicitly asks for it.
- Do not reopen or re-answer earlier transcript questions unless the final user
  message explicitly asks to revisit them.
- You may reveal new lore, names, local history, or scene geography when it
  directly serves the player's current question or action. Keep such
  revelations grounded in the supplied state, memory, and tone; durable
  continuity reconciliation happens after your prose.
- Use reasoning to reconcile continuity and constraints, not to pre-draft the
  final narration before you write it once.
- When a detail is ambiguous, especially a pronoun reference, resolve it
  against the immediately preceding scene transcript and the most recent
  scene turns first; only fall back to older campaign memory if recent
  context does not answer it.
- Treat item descriptions, atmospheric details, and latent threats as flavor,
  not as hardened present-tense facts, unless the oracle outcome or canonical
  state explicitly supports them.
- If a mechanical outcome names an actor's weapon or item, narrate that exact
  item and do not substitute a different weapon from older prose. If no weapon
  is named in the outcome, use the actor's primary/equipped weapon from
  canonical inventory.
- Static character facts, injuries, and recurring motifs are reference context,
  not mandatory prose beats; mention them only when they materially affect the
  immediate action or scene.
- Do not open narration by recapping
  scenes, memories, motifs, or prior concerns unless the final user message
  directly asks about them or the current scene context is actually relevant
  to it. Carry older context silently when it is only
  background, and begin with the current action instead.
- Avoid repeating the same static motif, injury, location, or prior event
  across consecutive responses unless it materially changes this beat.
- Do not manufacture urgency, consequences, or forced-choice branches unless
  the supplied outcome/state actually licenses them.
- When the supplied threat appraisal says the active danger is beyond the
  party's direct-fight footing, telegraph that **inside the fiction**: weight,
  footing, exhaustion, impossible reach, companions hesitating, the foe's mass
  or weapon eclipsing theirs, and obvious prep/escape vectors. Do not say
  "your level is too low", "not intended", "mechanically too hard", or any
  other out-of-character warning.
- End on one concrete prompt for the next action; prefer a tight follow-up
  question over a menu of dramatic options.

Tone:
Gritty, traditional dark fantasy with historically grounded detail. Avoid modern idioms,
meta-commentary, culture-war references, and cozy wish fulfillment. Keep prose vivid,
concrete, playable, and not novelistic.

Voice:
- Address the player-character in second person (`you`), not third person,
  unless directly quoting diegetic speech or text.
"""

TERMINAL_NARRATION_PROMPT = """Terminal campaign exception:
- The campaign is already marked ended in canonical state.
- Do not end with a next-action prompt, menu, or new-character suggestion.
- Do not ask "what do you do?" or invite the player to continue the ended run.
- Write closure for the final beat only; the application UI owns archive and
  new-campaign calls to action.
"""


class CompletionFunction(Protocol):
    def __call__(self, request: CompletionRequest) -> ModelResponse:
        raise NotImplementedError


class EmptyNarrativeResponseError(ValueError):
    pass


@dataclass(frozen=True)
class CompletionRequest:
    model: str
    messages: list[ChatMessage]
    temperature: float
    max_tokens: int
    timeout: float
    stream: bool
    api_key: str | None
    base_url: str | None
    reasoning_effort: ReasoningEffort
    reasoning: dict[str, object]
    extra_headers: dict[str, str] | None
    response_format: dict[str, object] | None = None
    cancel_token: CancellationToken | None = None
    trace_route: str | None = None
    trace_profile: str | None = None


class StreamStageStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    DONE = "done"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class StreamStageUpdate:
    stage_id: str
    label: str
    status: StreamStageStatus


@dataclass(frozen=True)
class CompletionDelta:
    content: str = ""
    thinking: str = ""
    stage: StreamStageUpdate | None = None


@dataclass(frozen=True)
class CompletionText:
    content: str
    thinking: str = ""


@dataclass(frozen=True)
class NarrativeResult:
    content: str
    thinking: str = ""


class NarrativeEngine:
    def __init__(
        self,
        config: NarrativeConfig | None = None,
        completion_function: CompletionFunction | None = None,
    ) -> None:
        self._config = config or NarrativeConfig.from_env()
        self._completion = completion_function or _completion

    def generate(  # noqa: PLR0913
        self,
        state: GameState,
        outcome: OracleOutcome,
        player_input: str,
        *,
        execution_context: str | None = None,
        memory_context: str | None = None,
        scene_messages: list[ChatMessage] | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> str:
        return self.generate_result(
            state,
            outcome,
            player_input,
            execution_context=execution_context,
            memory_context=memory_context,
            scene_messages=scene_messages,
            cancel_token=cancel_token,
        ).content

    def generate_result(  # noqa: PLR0913
        self,
        state: GameState,
        outcome: OracleOutcome,
        player_input: str,
        *,
        execution_context: str | None = None,
        memory_context: str | None = None,
        scene_messages: list[ChatMessage] | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> NarrativeResult:
        if not self._config.is_usable():
            return NarrativeResult(content=self._fallback_narration(state, outcome, player_input))

        request = self._build_request(
            state,
            outcome,
            player_input,
            execution_context=execution_context,
            memory_context=memory_context,
            scene_messages=scene_messages,
            stream=False,
            cancel_token=cancel_token,
        )

        last_error: Exception | None = None
        for attempt in range(self._config.max_retries + 1):
            try:
                generated = complete_text(request, self._completion)
                if generated.content:
                    return NarrativeResult(
                        content=generated.content.strip(),
                        thinking=generated.thinking.strip(),
                    )
                raise EmptyNarrativeResponseError
            except LITELLM_RETRYABLE_ERRORS as exc:
                last_error = exc
                if attempt < self._config.max_retries:
                    time.sleep(0.4 * (attempt + 1))

        fallback = self._fallback_narration(state, outcome, player_input)
        if last_error is None:
            return NarrativeResult(content=fallback)
        return NarrativeResult(content=f"{fallback}\n\n[Narrative API unavailable: {last_error}]")

    def stream(  # noqa: PLR0913
        self,
        state: GameState,
        outcome: OracleOutcome,
        player_input: str,
        *,
        execution_context: str | None = None,
        memory_context: str | None = None,
        scene_messages: list[ChatMessage] | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> tuple[list[CompletionDelta], NarrativeResult]:
        if not self._config.is_usable():
            fallback = self._fallback_narration(state, outcome, player_input)
            return ([CompletionDelta(content=fallback)], NarrativeResult(content=fallback))

        request = self._build_request(
            state,
            outcome,
            player_input,
            execution_context=execution_context,
            memory_context=memory_context,
            scene_messages=scene_messages,
            stream=True,
            cancel_token=cancel_token,
        )
        content_parts: list[str] = []
        thinking_parts: list[str] = []
        deltas: list[CompletionDelta] = []
        last_error: Exception | None = None

        for attempt in range(self._config.max_retries + 1):
            try:
                for delta in iter_text_deltas(request, self._completion):
                    if delta.content:
                        content_parts.append(delta.content)
                    if delta.thinking:
                        thinking_parts.append(delta.thinking)
                    deltas.append(delta)
                break
            except LITELLM_RETRYABLE_ERRORS as exc:
                last_error = exc
                content_parts.clear()
                thinking_parts.clear()
                deltas.clear()
                if attempt < self._config.max_retries:
                    time.sleep(0.4 * (attempt + 1))
        else:
            fallback = self._fallback_narration(state, outcome, player_input)
            if last_error is None:
                return ([CompletionDelta(content=fallback)], NarrativeResult(content=fallback))
            text = f"{fallback}\n\n[Narrative API unavailable: {last_error}]"
            return ([CompletionDelta(content=text)], NarrativeResult(content=text))

        result = NarrativeResult(
            content="".join(content_parts).strip(),
            thinking="".join(thinking_parts).strip(),
        )
        if not result.content:
            fallback = self._fallback_narration(state, outcome, player_input)
            return ([CompletionDelta(content=fallback)], NarrativeResult(content=fallback))
        return (deltas, result)

    def iter_stream(  # noqa: PLR0913
        self,
        state: GameState,
        outcome: OracleOutcome,
        player_input: str,
        *,
        execution_context: str | None = None,
        memory_context: str | None = None,
        scene_messages: list[ChatMessage] | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, NarrativeResult]:
        if not self._config.is_usable():
            fallback = self._fallback_narration(state, outcome, player_input)
            yield CompletionDelta(content=fallback)
            return NarrativeResult(content=fallback)

        request = self._build_request(
            state,
            outcome,
            player_input,
            execution_context=execution_context,
            memory_context=memory_context,
            scene_messages=scene_messages,
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
                result = NarrativeResult(
                    content="".join(content_parts).strip(),
                    thinking="".join(thinking_parts).strip(),
                )
                if result.content:
                    return result
            except LITELLM_RETRYABLE_ERRORS as exc:
                last_error = exc
                if attempt < self._config.max_retries:
                    time.sleep(0.4 * (attempt + 1))

        fallback = self._fallback_narration(state, outcome, player_input)
        if last_error is None:
            yield CompletionDelta(content=fallback)
            return NarrativeResult(content=fallback)
        text = f"{fallback}\n\n[Narrative API unavailable: {last_error}]"
        yield CompletionDelta(content=text)
        return NarrativeResult(content=text)

    def _openrouter_headers(self) -> dict[str, str] | None:
        if not self._config.model.startswith("openrouter/"):
            return None

        headers: dict[str, str] = {}
        if self._config.site_url is not None:
            headers["HTTP-Referer"] = self._config.site_url
        if self._config.app_name is not None:
            headers["X-Title"] = self._config.app_name
        return headers or None

    def _build_request(  # noqa: PLR0913
        self,
        state: GameState,
        outcome: OracleOutcome,
        player_input: str,
        *,
        execution_context: str | None = None,
        memory_context: str | None = None,
        scene_messages: list[ChatMessage] | None = None,
        stream: bool,
        cancel_token: CancellationToken | None = None,
    ) -> CompletionRequest:
        terminal_prompt = state.campaign_status == CampaignStatus.ENDED
        system_prompt = (
            SYSTEM_PROMPT
            if not terminal_prompt
            else f"{SYSTEM_PROMPT}\n\n{TERMINAL_NARRATION_PROMPT}"
        )
        runtime_context = self._build_runtime_context(
            state,
            outcome,
            player_input=player_input,
            execution_context=execution_context,
            memory_context=memory_context,
        )
        messages: list[ChatMessage] = [
            {"role": "system", "content": f"{system_prompt}\n\n{runtime_context}"},
            *(scene_messages or []),
            {"role": "user", "content": player_input},
        ]
        profile = self._config.profiles.narration_for(
            kind=outcome.kind,
            reasoning_policy=self._config.reasoning_policy,
        )
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
            trace_route=f"narration.{outcome.kind.value}",
            trace_profile=f"narration.{outcome.kind.value}",
        )

    def _build_runtime_context(
        self,
        state: GameState,
        outcome: OracleOutcome,
        *,
        player_input: str,
        execution_context: str | None = None,
        memory_context: str | None = None,
    ) -> str:
        lines = [
            "<NARRATION_SYSTEM_FOCUS>",
            "ONLY ACTIVE REQUEST = THE FINAL NATIVE `user` MESSAGE IN THE CHAT TRANSCRIPT.",
            "TREAT ALL XML-TAGGED CONTEXT BELOW AS SUPPLEMENTAL REFERENCE, NOT AS USER INPUT.",
            (
                '<ACTIVE_REQUEST_FOCUS REFERENCE_ONLY="true" '
                'NOTE="THIS IS AN EMPHASIS COPY, NOT A SECOND USER MESSAGE">'
            ),
            "<LATEST_USER_MESSAGE>",
            self._xml_escape(player_input),
            "</LATEST_USER_MESSAGE>",
            "</ACTIVE_REQUEST_FOCUS>",
            "</NARRATION_SYSTEM_FOCUS>",
            "",
            '<SUPPLEMENTAL_CONTEXT REFERENCE_ONLY="true" NOT_CHAT_TRANSCRIPT="true">',
            "<AUTHORITATIVE_RUNTIME_STATE>",
            f"<CURRENT_SCENE>{self._xml_escape(state.current_scene)}</CURRENT_SCENE>",
            f"<SCENE_STATUS>{state.scene_status.value}</SCENE_STATUS>",
            f"<CHAOS_FACTOR>{state.chaos_factor}</CHAOS_FACTOR>",
            "<CHARACTER_JSON>",
            self._xml_escape(self._compact_character_json(state)),
            "</CHARACTER_JSON>",
            "<SETTING_NOTES>",
            self._xml_escape(self._clip_prompt_text(state.setting_notes, 500)),
            "</SETTING_NOTES>",
            "<PLAYER_NOTES>",
            self._xml_escape(self._clip_prompt_text(state.player_notes, 350)),
            "</PLAYER_NOTES>",
            "<ORACLE_OUTCOME_JSON>",
            self._xml_escape(self._compact_outcome_json(outcome)),
            "</ORACLE_OUTCOME_JSON>",
            "<DIEGETIC_THREAT_APPRAISAL>",
            self._xml_escape(self._threat_appraisal(state)),
            "</DIEGETIC_THREAT_APPRAISAL>",
            "</AUTHORITATIVE_RUNTIME_STATE>",
        ]
        if state.directives.has_content():
            lines.extend(
                [
                    "<CAMPAIGN_DIRECTIVES>",
                    self._xml_escape(self._directives_prompt_block(state)),
                    "</CAMPAIGN_DIRECTIVES>",
                ],
            )
        if memory_context:
            lines.extend(
                [
                    "<BOUNDED_MEMORY_CONTEXT>",
                    self._xml_escape(memory_context),
                    "</BOUNDED_MEMORY_CONTEXT>",
                ],
            )
        if execution_context:
            lines.extend(
                [
                    "<EXECUTED_BACKEND_STEPS>",
                    self._xml_escape(
                        execution_context.removeprefix("Executed backend steps:\n"),
                    ),
                    "</EXECUTED_BACKEND_STEPS>",
                ],
            )
        output_instruction = (
            (
                "FOR THE FINAL NATIVE USER MESSAGE ONLY: write 1-2 compact paragraphs "
                "of terminal closure, usually 1. "
                "Treat the transcript above as resolved history; answer only the "
                "final user message unless it explicitly reopens an earlier question. "
                "Use second person (`you`) for the player-character. "
                "Mirror the player's action before extending the fiction. "
                "Do not repeatedly restate unchanged character motifs or injuries "
                "unless they materially affect this beat. "
                "Do not open by recapping older "
                "scenes or memories unless the final user message directly asks "
                "about them or it is materially relevant to the current scene. "
                "Avoid repeating the same static motif, location, or "
                "prior event across consecutive responses unless it materially "
                "changes this beat. "
                "Use reasoning for continuity and constraint resolution."
                "When recent scene context and older campaign memory differ, trust the "
                "most recent scene transcript and latest turn context. "
                "Only harden facts that are supported by the supplied outcome/state. "
                "For weapons/items, follow the structured outcome first, then "
                "the actor's canonical primary/equipped inventory; do not "
                "substitute conflicting older prose. "
                "Do not end with a next-action prompt, menu, or new-character suggestion."
            )
            if state.campaign_status == CampaignStatus.ENDED
            else (
                "FOR THE FINAL NATIVE USER MESSAGE ONLY: write 1-2 compact paragraphs "
                "of playable narration, usually 1. "
                "Treat the transcript above as resolved history; answer only the "
                "final user message unless it explicitly reopens an earlier question. "
                "Use second person (`you`) for the player-character. "
                "Mirror the player's action before extending the fiction. "
                "Do not repeatedly restate unchanged character motifs or injuries "
                "unless they materially affect this beat. "
                "Do not open by recapping older "
                "scenes or memories unless the final user message directly asks "
                "about them or it is materially relevant to the current scene. "
                "Avoid repeating the same static motif, location, or "
                "prior event across consecutive responses unless it materially "
                "changes this beat. "
                "Use reasoning for continuity and constraint resolution."
                "When recent scene context and older campaign memory differ, trust the "
                "most recent scene transcript and latest turn context. "
                "Only harden facts that are supported by the supplied outcome/state. "
                "For weapons/items, follow the structured outcome first, then "
                "the actor's canonical primary/equipped inventory; do not "
                "substitute conflicting older prose. "
                "End with one concrete prompt for action."
            )
        )
        lines.extend(
            [
                "</SUPPLEMENTAL_CONTEXT>",
                "",
                "<OUTPUT_INSTRUCTIONS>",
                output_instruction,
                "</OUTPUT_INSTRUCTIONS>",
            ],
        )
        return "\n".join(lines)

    def _directives_prompt_block(self, state: GameState) -> str:
        lines: list[str] = []
        if state.directives.world_guidance.strip():
            lines.append(
                "World guidance: "
                + self._clip_prompt_text(state.directives.world_guidance, 350),
            )
        if state.directives.play_guidance.strip():
            lines.append(
                "Play guidance: "
                + self._clip_prompt_text(state.directives.play_guidance, 350),
            )
        return "\n".join(lines) or "(none)"

    def _threat_appraisal(self, state: GameState) -> str:
        if not state.encounter.active:
            return "No active combat threat is currently being appraised."
        active_foes = [
            foe
            for foe in state.encounter.combatants
            if not foe.defeated and not foe.fled
        ]
        if not active_foes:
            return "The immediate combat threat has broken or been neutralized."

        party = [
            state.character,
            *(member.sheet for member in state.party_members if member.active),
        ]
        party_score = sum(self._combatant_capacity(sheet.cairn) for sheet in party)
        threat_score = sum(self._foe_pressure(foe) for foe in active_foes)
        margin = threat_score - party_score
        if margin >= OUTMATCHED_THREAT_MARGIN:
            verdict = (
                "Outmatched in a direct fight. The prose should make this feel like a "
                "danger to escape, delay, trap, weaken, or return to with allies/tools, "
                "unless the player has already earned a decisive fictional advantage."
            )
        elif margin >= TACTICALLY_DANGEROUS_THREAT_MARGIN:
            verdict = (
                "Dangerous but possible only with strong positioning, preparation, "
                "morale pressure, direct weakness exploitation, or retreat discipline."
            )
        elif margin <= PARTY_ADVANTAGE_THREAT_MARGIN:
            verdict = "The party appears to have the upper hand if they act decisively."
        else:
            verdict = "A fair but dangerous fight; keep risk present without over-warning."

        foe_lines = [
            (
                f"- {foe.name}: {foe.threat_level.value}, "
                f"HP {foe.hp}/{foe.max_hp}, STR {foe.str_score}, armor {foe.armor}, "
                f"damage d{foe.weapon_damage_die}"
                + (f", weakness: {foe.weakness}" if foe.weakness.strip() else "")
            )
            for foe in active_foes[:4]
        ]
        party_lines = [
            (
                f"- {sheet.name or 'Unnamed actor'}: HP {sheet.cairn.hp}/{sheet.cairn.max_hp}, "
                f"STR {sheet.cairn.str_score}/{sheet.cairn.max_str_score}, "
                f"armor {sheet.cairn.armor}"
            )
            for sheet in party[:4]
        ]
        return "\n".join(
            [
                verdict,
                f"Pressure score: foes {threat_score} vs party {party_score}.",
                "Active foes:",
                *foe_lines,
                "Party footing:",
                *party_lines,
                (
                    "Instruction: weave this appraisal into sensory, tactical narration only; "
                    "never as explicit game-balance advice."
                ),
            ],
        )

    def _combatant_capacity(self, cairn: CairnCharacterState) -> int:
        score = cairn.hp + max(0, cairn.str_score // 2) + cairn.armor * 2
        if cairn.deprived:
            score -= 2
        if cairn.critically_wounded or cairn.doomed:
            score -= 3
        if cairn.paralyzed or cairn.delirious:
            score -= 4
        if cairn.dead:
            return 0
        return max(0, score)

    def _foe_pressure(self, foe: EnemyCombatant) -> int:
        threat_bonus = {
            EncounterThreatLevel.ORDINARY: 0,
            EncounterThreatLevel.HARDIER: 3,
            EncounterThreatLevel.SERIOUS: 7,
        }.get(foe.threat_level, 0)
        return (
            foe.hp
            + max(0, foe.str_score // 3)
            + foe.armor * 2
            + max(0, (foe.weapon_damage_die - 4) // 2)
            + threat_bonus
        )

    def _compact_character_json(self, state: GameState) -> str:
        character = state.character
        cairn = character.cairn
        payload = {
            "name": character.name,
            "archetype": character.archetype,
            "epithet": self._clip_prompt_text(character.epithet, 160),
            "drive": self._clip_prompt_text(character.drive, 160),
            "flaw": self._clip_prompt_text(character.flaw, 160),
            "condition": self._clip_prompt_text(character.condition, 160),
            "backstory": self._clip_prompt_text(character.backstory, 220),
            "cairn": {
                "str": [cairn.str_score, cairn.max_str_score],
                "dex": [cairn.dex_score, cairn.max_dex_score],
                "wil": [cairn.wil_score, cairn.max_wil_score],
                "hp": [cairn.hp, cairn.max_hp],
                "armor": cairn.armor,
                "fatigue": cairn.fatigue,
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
            },
            "inventory": [
                {
                    "id": item.id,
                    "name": item.name,
                    "details": self._clip_prompt_text(item.details, 90),
                    "equipped": item.cairn.equipped,
                    "primary_weapon": item.id == cairn.primary_weapon_item_id,
                    "tags": [tag.value for tag in item.cairn.tags],
                    "uses": item.cairn.uses,
                    "damage_die": item.cairn.weapon_damage_die,
                    "armor_bonus": item.cairn.armor_bonus,
                    "slots": item.cairn.slots,
                }
                for item in character.inventory[:8]
            ],
            "party_members": [
                self._compact_party_member_json(member)
                for member in state.party_members
                if member.active
            ],
        }
        return json.dumps(payload, separators=(",", ":"))

    def _compact_party_member_json(self, member: PartyMember) -> dict[str, object]:
        sheet = member.sheet
        cairn = sheet.cairn
        return {
            "id": member.id,
            "name": member.display_label(),
            "archetype": sheet.archetype,
            "condition": self._clip_prompt_text(sheet.condition, 120),
            "cairn": {
                "hp": [cairn.hp, cairn.max_hp],
                "str": [cairn.str_score, cairn.max_str_score],
                "dex": [cairn.dex_score, cairn.max_dex_score],
                "wil": [cairn.wil_score, cairn.max_wil_score],
                "armor": cairn.armor,
                "primary_weapon_item_id": cairn.primary_weapon_item_id,
            },
            "inventory": [
                {
                    "id": item.id,
                    "name": item.name,
                    "details": self._clip_prompt_text(item.details, 80),
                    "equipped": item.cairn.equipped,
                    "primary_weapon": item.id == cairn.primary_weapon_item_id,
                    "tags": [tag.value for tag in item.cairn.tags],
                    "damage_die": item.cairn.weapon_damage_die,
                    "armor_bonus": item.cairn.armor_bonus,
                    "uses": item.cairn.uses,
                }
                for item in sheet.inventory[:8]
            ],
        }

    def _xml_escape(self, text: str) -> str:
        return html.escape(text, quote=False)

    def _compact_outcome_json(self, outcome: OracleOutcome) -> str:
        return outcome.model_dump_json(
            exclude_none=True,
            exclude_defaults=True,
            exclude_unset=True,
        )

    def _clip_prompt_text(self, text: str, limit: int) -> str:
        compact = re.sub(r"\s+", " ", text).strip()
        if len(compact) <= limit:
            return compact
        return f"{compact[: limit - 3].rstrip()}..."

    def _fallback_narration(
        self,
        state: GameState,
        outcome: OracleOutcome,
        player_input: str,
    ) -> str:
        thread_hint = state.threads[0].title if state.threads else "the unresolved matter"
        return (
            f"The oracle answers through the present scene: {outcome.summary}. "
            f"The road of consequences bends back toward {thread_hint}. "
            f"Your declared intent was: {player_input}\n\n"
            "No model is configured, so this is deterministic placeholder narration. "
            "Choose the next action, ask the oracle, or check whether the scene changes."
        )


LITELLM_RETRYABLE_ERRORS = (
    APIConnectionError,
    APIError,
    AuthenticationError,
    BadRequestError,
    ContextWindowExceededError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
    EmptyNarrativeResponseError,
)


def _completion(request: CompletionRequest) -> ModelResponse:
    _raise_if_cancelled(request.cancel_token)
    # OpenRouter rejects/ignores useful budget control when both the
    # top-level effort alias and nested `reasoning.max_tokens` are present.
    # Prefer the deterministic token cap when we have one; otherwise keep the
    # effort alias for providers that only understand that shape.
    reasoning_effort = (
        None if "max_tokens" in request.reasoning else request.reasoning_effort
    )
    started = time.perf_counter()
    response = litellm_completion(
        model=request.model,
        messages=request.messages,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
        timeout=request.timeout,
        stream=request.stream,
        api_key=request.api_key,
        base_url=request.base_url,
        reasoning_effort=reasoning_effort,
        reasoning=request.reasoning,
        extra_headers=request.extra_headers,
        response_format=request.response_format,
        drop_params=True,
    )
    duration_ms = int((time.perf_counter() - started) * 1000)
    log_llm_call(
        LLMCallRecord(
            route=request.trace_route,
            profile=request.trace_profile,
            request_id=request_id_from_cancel_token(request.cancel_token),
            model=request.model,
            stream=request.stream,
            duration_ms=duration_ms,
            response=response,
        ),
    )
    return cast("ModelResponse", response)


def complete_text(
    request: CompletionRequest,
    completion_function: CompletionFunction,
) -> CompletionText:
    _raise_if_cancelled(request.cancel_token)
    response = completion_function(request)
    _raise_if_cancelled(request.cancel_token)
    if request.stream:
        content_parts: list[str] = []
        thinking_parts: list[str] = []
        for delta in _iter_stream_response(response, request.cancel_token):
            if delta.content:
                content_parts.append(delta.content)
            if delta.thinking:
                thinking_parts.append(delta.thinking)
        return CompletionText(
            content="".join(content_parts),
            thinking="".join(thinking_parts),
        )

    message = response.choices[0].message
    return CompletionText(
        content=_extract_text(_get_field(message, "content")),
        thinking=_extract_text(
            _get_field(message, "reasoning_content")
            or _get_field(message, "reasoning")
            or _get_field(message, "thinking")
            or _provider_reasoning(message),
        ),
    )


# Why we extract instead of relying on `response_format={"type":"json_object"}`:
# Kimi K2.6 Thinking on OpenRouter routinely burns 200-300+ seconds of internal
# reasoning when the request specifies `response_format=json_object` -- it appears
# to treat structured-output mode as a hint to over-deliberate. Empirically we
# measured 335s with `json_object` vs ~30s without it for the same prompt. We
# therefore drop the parameter and instruct the model to emit JSON via the system
# prompt; this helper tolerates the small amount of slop (markdown fences, leading
# prose) that may occasionally surface as a result.
_JSON_FENCE_PATTERN = re.compile(
    r"^\s*```(?:json|JSON)?\s*(?P<body>.*?)\s*```\s*$",
    re.DOTALL,
)


def extract_json_object(content: str) -> str:
    if not content:
        return ""
    fenced = _JSON_FENCE_PATTERN.match(content)
    if fenced is not None:
        content = fenced.group("body")
    stripped = content.strip()
    if not stripped:
        return ""
    if stripped.startswith("{"):
        return _balanced_json_slice(stripped) or stripped
    start = stripped.find("{")
    if start == -1:
        return stripped
    candidate = stripped[start:]
    return _balanced_json_slice(candidate) or candidate


def _balanced_json_slice(text: str) -> str | None:
    depth = 0
    in_string = False
    escape = False
    for index, char in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[: index + 1]
    return None


def iterate_text_deltas(
    request: CompletionRequest,
    completion_function: CompletionFunction,
) -> list[CompletionDelta]:
    return list(iter_text_deltas(request, completion_function))


def iter_text_deltas(
    request: CompletionRequest,
    completion_function: CompletionFunction,
) -> Iterator[CompletionDelta]:
    _raise_if_cancelled(request.cancel_token)
    response = completion_function(request)
    _raise_if_cancelled(request.cancel_token)
    return _iter_stream_response(response, request.cancel_token)


def _iter_stream_response(
    response: object,
    cancel_token: CancellationToken | None = None,
) -> Iterator[CompletionDelta]:
    streamable: Iterable[object] = cast("Iterable[object]", response)
    stream = iter(streamable)
    try:
        for chunk in stream:
            _raise_if_cancelled(cancel_token)
            choice = _first_choice(chunk)
            if choice is None:
                continue
            delta = _get_field(choice, "delta") or _get_field(choice, "message") or choice
            content = _extract_text(
                _get_field(delta, "content")
                or _get_field(delta, "text")
            )
            thinking = _extract_text(
                _get_field(delta, "reasoning_content")
                or _get_field(delta, "reasoning")
                or _get_field(delta, "thinking")
                or _provider_reasoning(delta)
                or _provider_reasoning(choice)
                or _provider_reasoning(chunk)
            )
            if content or thinking:
                yield CompletionDelta(content=content, thinking=thinking)
    except RequestCancelledError:
        _close_stream(response)
        raise


def _raise_if_cancelled(cancel_token: CancellationToken | None) -> None:
    if cancel_token is not None:
        cancel_token.raise_if_cancelled()


def _close_stream(response: object) -> None:
    closer = getattr(response, "close", None)
    if callable(closer):
        closer()


def _first_choice(response: object) -> object | None:
    choices = _get_field(response, "choices")
    if isinstance(choices, list) and choices:
        return cast("object", choices[0])
    return None


def _provider_reasoning(obj: object) -> object | None:
    provider_fields = _get_field(obj, "provider_specific_fields")
    if isinstance(provider_fields, dict):
        return (
            provider_fields.get("reasoning_content")
            or provider_fields.get("reasoning")
            or provider_fields.get("thinking")
        )
    return None


def _get_field(obj: object, name: str) -> object | None:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return cast("object | None", getattr(obj, name, None))


def _extract_text(value: object) -> str:  # noqa: PLR0911
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_extract_text(part) for part in value)
    if isinstance(value, dict):
        return _extract_text(
            value.get("text")
            or value.get("content")
            or value.get("output_text")
            or value.get("value")
        )
    text = getattr(value, "text", None)
    if text is not None:
        return _extract_text(text)
    content = getattr(value, "content", None)
    if content is not None:
        return _extract_text(content)
    output_text = getattr(value, "output_text", None)
    if output_text is not None:
        return _extract_text(output_text)
    return ""
