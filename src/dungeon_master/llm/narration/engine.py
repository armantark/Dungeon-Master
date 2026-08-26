from __future__ import annotations

import html
import json
import re
import time
from collections.abc import Generator

from dungeon_master.application.cancellation import CancellationToken
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
from dungeon_master.domain.models import (
    CairnCharacterState,
    CampaignStatus,
    EncounterThreatLevel,
    EnemyCombatant,
    GameState,
    OracleKind,
    OracleOutcome,
    PartyMember,
    SceneStatus,
)
from dungeon_master.llm.completion.contracts import (
    ChatMessage,
    CompletionDelta,
    CompletionFunction,
    CompletionRequest,
    NarrativeResult,
)
from dungeon_master.llm.completion.transport import (
    LITELLM_RETRYABLE_ERRORS,
    EmptyNarrativeResponseError,
    complete_text,
    iter_text_deltas,
    provider_completion,
)
from dungeon_master.llm.prompt_fragments import SEED_AUTHORITY

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

SYSTEM_PROMPT = f"""You are the narrative voice for a solo tabletop role-playing game.

Hard boundaries:
- You do not roll dice.
- You do not directly change chaos factor, threads, NPCs, inventory, or canonical state.
- You only narrate from the structured oracle outcome and state supplied by the app.
- If mechanics are unclear, make the fiction tense but do not invent new mechanical facts.
- Canonical abilities and notes in `CHARACTER_JSON` are authoritative narrative
  permissions. Do not invent a narrower limitation.
- Do not invent a narrower limitation for an ability.
- When a turn contains multiple declared actions but the structured outcome
  resolves only one risk, scope success/failure to `ORACLE_OUTCOME_JSON.question`.
- A failed save creates trouble inside the attempted action; it is not permission
  to rewrite settled canon.
- Do not revoke established openings unless the structured outcome says so.
- Failed interaction saves should usually change the footing of the exchange
  rather than end it outright.
- Treat any irreparable break as an emergent conclusion, not a default.
- Scale consequences through the fiction and campaign seed.
- do not turn roll margin into a separate rule table.
- Scale consequences through the fiction and campaign seed: stakes, tone,
  danger profile, genre, actor boundaries, and the concrete oracle result.

Discipline:
- Use reasoning to reconcile continuity and constraints.
- The final user message is the only active request to answer; supplemental
  context is reference only.
- When a detail is ambiguous, especially a pronoun reference, resolve it
  against the immediately preceding scene transcript.
- Trust scene transcript and the most recent turn context for live referents.
- Do not reopen or re-answer earlier transcript questions unless the final
  user message explicitly asks you to.
- You may reveal new lore only when the outcome/state supports it.
- continuity reconciliation happens after your prose.
- Treat item descriptions and latent threats as flavor, not as hardened present-tense facts.
- For party members, the compact `party_members` JSON is the authority for
  names, roles, abilities, notes, armor, and carried gear.
- Static character facts, injuries, and recurring motifs are reference context,
  not mandatory prose beats.
- Carry older context silently unless the final user message needs it.
- Do not open narration by recapping older scenes or memories.
- Do not manufacture urgency, consequences, or forced-choice branches unless
  the supplied outcome/state licenses them.
- For interrupted scene checks, the oracle licenses an interruption before
  the expected scene; it does not by itself license teleporting an older threat.
- When the supplied threat appraisal says the active danger is beyond the
  party's direct-fight footing, telegraph that **inside the fiction**. Do not say
  "your level is too low" or give out-of-character warnings.

Tone:
- {SEED_AUTHORITY}
- The campaign seed and setting notes are the tone authority.
- Keep prose vivid, concrete, playable, and not novelistic.
- usually one paragraph, at most two.
- Mirror the player's declared action before extending the scene.
- Address the player-character in second person.
"""

TERMINAL_NARRATION_PROMPT = """Terminal campaign exception:
- The campaign is already marked ended in canonical state.
- Do not end with a next-action prompt, menu, or new-character suggestion.
- Do not ask "what do you do?" or invite the player to continue the ended run.
- Write closure for the final beat only; the application UI owns archive and
  new-campaign calls to action.
"""


class NarrativeEngine:
    def __init__(
        self,
        config: NarrativeConfig | None = None,
        completion_function: CompletionFunction | None = None,
    ) -> None:
        self._config = config or NarrativeConfig.from_env()
        self._completion = completion_function or provider_completion

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
            "<CAMPAIGN_SEED>",
            self._xml_escape(state.campaign_seed.model_dump_json()),
            "</CAMPAIGN_SEED>",
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
            "<SCENE_INTERRUPTION_CONSTRAINTS>",
            self._xml_escape(self._scene_interruption_constraints(state, outcome)),
            "</SCENE_INTERRUPTION_CONSTRAINTS>",
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
        shared_output_instruction = (
            "FOR THE FINAL NATIVE USER MESSAGE ONLY: write 1-2 compact paragraphs "
            "{goal}, usually 1. "
            "Treat the transcript above as resolved history; answer only the "
            "final user message unless it explicitly reopens an earlier question. "
            "Do not reopen or re-answer earlier transcript questions. "
            "Use second person (`you`) for the player-character. "
            "Mirror the player's declared action before extending the scene. "
            "Do not open by recapping older scenes or memories. "
            "Do not repeatedly restate unchanged character motifs. "
            "Avoid repeating the same static motif, injury, location, or "
            "prior event across consecutive responses. "
            "When recent scene context and older campaign memory differ, "
            "trust the most recent scene transcript and latest turn context; "
            "scene transcript and the most recent turn win. "
            "Only harden facts that are supported by the supplied outcome/state. "
            "For weapons/items, follow the structured outcome first, then "
            "the actor's canonical primary/equipped inventory."
            "{ending}"
        )
        if state.campaign_status == CampaignStatus.ENDED:
            output_instruction = shared_output_instruction.format(
                goal="of terminal closure",
                ending=" Do not end with a next-action prompt, menu, or new-character suggestion.",
            )
        else:
            output_instruction = shared_output_instruction.format(
                goal="of playable narration", ending=" End with one concrete prompt for action."
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
                "World guidance: " + self._clip_prompt_text(state.directives.world_guidance, 350),
            )
        if state.directives.play_guidance.strip():
            lines.append(
                "Play guidance: " + self._clip_prompt_text(state.directives.play_guidance, 350),
            )
        return "\n".join(lines) or "(none)"

    def _scene_interruption_constraints(
        self,
        state: GameState,
        outcome: OracleOutcome,
    ) -> str:
        if (
            outcome.kind != OracleKind.SCENE_CHECK
            or outcome.scene_status != SceneStatus.INTERRUPTED
        ):
            return "No special scene-interruption constraint for this outcome."

        pursuing_foes = [
            foe
            for foe in state.encounter.combatants
            if state.encounter.active
            and state.encounter.pursuit_active
            and not foe.defeated
            and not foe.fled
        ]
        if pursuing_foes:
            foe_names = ", ".join(foe.name for foe in pursuing_foes[:3])
            return "\n".join(
                [
                    "Interrupted scene check with canonical active pursuit.",
                    f"Pursuing threat(s): {foe_names}.",
                    (
                        "A direct stalker-style complication may involve these threat(s), "
                        "but only in a physically plausible way. Preserve mobility, scale, "
                        "route knowledge, and recent geography; if those are unsupported, "
                        "use traces, blocked routes, collateral damage, witnesses, minions, "
                        "or time pressure instead of immediate bodily reappearance."
                    ),
                ],
            )

        return (
            "Interrupted scene check without canonical active pursuit.\n"
            "The interruption should be a local or indirect complication before "
            "the expected scene: suspicious guards, a locked or watched entrance, "
            "a rival arrival, collapsing masonry, a bad omen, a hard choice, "
            "lost time, or another plausible obstacle.\n"
            "Do not make an earlier escaped boss, major quest threat, or established "
            "monster physically reappear, stalk the player, or block the destination "
            "unless the latest user message or oracle outcome explicitly establishes "
            "that direct pursuit. Older memory can color the pressure through echoes, "
            "damage, cult rumors, distant noise, residue, or consequences."
        )

    def _threat_appraisal(self, state: GameState) -> str:
        if not state.encounter.active:
            return "No active combat threat is currently being appraised."
        active_foes = [
            foe for foe in state.encounter.combatants if not foe.defeated and not foe.fled
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
                "abilities": cairn.abilities,
                "notes": self._clip_prompt_text(cairn.notes, 240),
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
                "abilities": cairn.abilities,
                "notes": self._clip_prompt_text(cairn.notes, 180),
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
