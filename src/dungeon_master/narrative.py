from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Generator, Iterable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol, cast

from dotenv import load_dotenv
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
from dungeon_master.models import GameState, OracleKind, OracleOutcome

if TYPE_CHECKING:
    from litellm.types.utils import ModelResponse

type ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "default"]
type ReasoningPolicy = ReasoningEffort | Literal["auto"]
type ChatMessage = dict[str, str]

DEFAULT_MODEL = "openrouter/moonshotai/kimi-k2.6"
DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_REASONING_POLICY: ReasoningPolicy = "auto"
VALID_REASONING_EFFORTS: tuple[ReasoningEffort, ...] = (
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "default",
)
VALID_REASONING_POLICIES: tuple[ReasoningPolicy, ...] = (*VALID_REASONING_EFFORTS, "auto")
# Why we keep most narrative tasks at "low":
# Kimi K2.6 Thinking spends ~30-60s on reasoning at "low", and another
# 60-120s at "medium". For routine narration of player actions, oracle
# yes/no resolutions, and quick mechanical receipts, that extra latency
# does not buy enough fictional depth to justify the wait. We reserve
# "medium" for scene transitions and random events (which need
# cross-referencing of threads/NPCs to land cleanly) and never go higher
# at the per-turn level — campaign generation is the only "high" call.
REASONING_BY_TASK: dict[OracleKind, ReasoningEffort] = {
    OracleKind.YES_NO: "low",
    OracleKind.PLAYER_ACTION: "low",
    OracleKind.RANDOM_EVENT: "medium",
    OracleKind.SCENE_CHECK: "medium",
    OracleKind.SAVE: "low",
    OracleKind.ATTACK: "low",
    OracleKind.HARM: "low",
    OracleKind.RECOVERY: "low",
    OracleKind.RETREAT: "low",
}

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
- Treat item descriptions, atmospheric details, and latent threats as flavor,
  not as hardened present-tense facts, unless the oracle outcome or canonical
  state explicitly supports them.
- Do not manufacture urgency, consequences, or forced-choice branches unless
  the supplied outcome/state actually licenses them.
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


@dataclass(frozen=True)
class CompletionDelta:
    content: str = ""
    thinking: str = ""


@dataclass(frozen=True)
class CompletionText:
    content: str
    thinking: str = ""


@dataclass(frozen=True)
class NarrativeResult:
    content: str
    thinking: str = ""


@dataclass(frozen=True)
class NarrativeConfig:
    model: str
    api_key: str | None
    base_url: str | None
    reasoning_policy: ReasoningPolicy = DEFAULT_REASONING_POLICY
    # We default to STREAMING the reasoning back to the client because Kimi
    # K2.6 typically spends 60-180s thinking before the first content token
    # arrives. Without thinking deltas the user stares at a frozen UI for
    # minutes; with them, the UI can show a collapsed "thinking..." chip
    # that progresses in real time. Set LITELLM_EXCLUDE_REASONING=true to
    # opt out (e.g. for cheaper unit-test runs).
    exclude_reasoning: bool = False
    temperature: float = 0.85
    # Kimi K2.6 Thinking burns ~2-3k reasoning tokens regardless of `effort`,
    # so anything below ~4k starves the actual narration of completion-token
    # budget and produces empty content (which forces the fallback narration).
    # 4500 leaves ~1.5-2k for prose after thinking, which is plenty for the
    # compact 1-2 paragraph narration we ask for.
    max_tokens: int = 4500
    timeout_seconds: float = 180.0
    max_retries: int = 2
    app_name: str | None = None
    site_url: str | None = None

    @classmethod
    def from_env(cls) -> NarrativeConfig:
        load_dotenv()
        return cls(
            model=os.getenv("LITELLM_MODEL", DEFAULT_MODEL),
            api_key=os.getenv("OPENROUTER_API_KEY") or os.getenv("LITELLM_API_KEY") or None,
            base_url=os.getenv("OPENROUTER_API_BASE", DEFAULT_OPENROUTER_BASE_URL).rstrip("/"),
            reasoning_policy=_reasoning_policy_from_env(),
            exclude_reasoning=_env_bool("LITELLM_EXCLUDE_REASONING", default=False),
            temperature=_env_float("LITELLM_TEMPERATURE", default=0.85),
            max_tokens=_env_int("LITELLM_MAX_TOKENS", default=4500),
            timeout_seconds=_env_float("LITELLM_TIMEOUT_SECONDS", default=180.0),
            max_retries=_env_int("LITELLM_MAX_RETRIES", default=2),
            app_name=os.getenv("OR_APP_NAME") or "Dungeon Master",
            site_url=os.getenv("OR_SITE_URL") or None,
        )

    def is_usable(self) -> bool:
        if not self.model:
            return False
        if self.model.startswith("openrouter/"):
            return self.api_key is not None
        return True


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
        cancel_token: CancellationToken | None = None,
    ) -> str:
        return self.generate_result(
            state,
            outcome,
            player_input,
            execution_context=execution_context,
            memory_context=memory_context,
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

    def _reasoning_effort_for(self, outcome: OracleOutcome) -> ReasoningEffort:
        if self._config.reasoning_policy != "auto":
            return self._config.reasoning_policy
        return REASONING_BY_TASK[outcome.kind]

    def _build_request(  # noqa: PLR0913
        self,
        state: GameState,
        outcome: OracleOutcome,
        player_input: str,
        *,
        execution_context: str | None = None,
        memory_context: str | None = None,
        stream: bool,
        cancel_token: CancellationToken | None = None,
    ) -> CompletionRequest:
        prompt = self._build_user_prompt(
            state,
            outcome,
            player_input,
            execution_context=execution_context,
            memory_context=memory_context,
        )
        messages: list[ChatMessage] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        # Cap reasoning per task: routine narration (player_action / yes_no
        # / save / attack / harm / recovery) gets ~1500 reasoning tokens,
        # cross-referencing tasks (random_event / scene_check) get ~3000.
        # Without these caps Kimi K2.6 frequently reasons 60-180s and pushes
        # per-turn latency well past 5 minutes. OpenRouter forbids combining
        # `effort` and `max_tokens` in the reasoning dict, so we use
        # `max_tokens` (more deterministic) and let `reasoning_effort`
        # remain as a top-level OpenAI-compatible alias for providers that
        # do not understand `max_tokens` and would otherwise default to
        # `medium`.
        effort = self._reasoning_effort_for(outcome)
        reasoning_max_tokens = 3000 if effort in ("medium", "high") else 1500
        reasoning: dict[str, object] = {
            "max_tokens": reasoning_max_tokens,
            "exclude": self._config.exclude_reasoning,
        }
        return CompletionRequest(
            model=self._config.model,
            messages=messages,
            temperature=self._config.temperature,
            max_tokens=self._config.max_tokens,
            timeout=self._config.timeout_seconds,
            stream=stream,
            api_key=self._config.api_key,
            base_url=self._config.base_url,
            reasoning_effort=self._reasoning_effort_for(outcome),
            reasoning=reasoning,
            extra_headers=self._openrouter_headers(),
            response_format=None,
            cancel_token=cancel_token,
        )

    def _build_user_prompt(
        self,
        state: GameState,
        outcome: OracleOutcome,
        player_input: str,
        *,
        execution_context: str | None = None,
        memory_context: str | None = None,
    ) -> str:
        lines = [
            f"Player input: {player_input}",
            f"Current scene: {state.current_scene}",
            f"Scene status: {state.scene_status.value}",
            f"Chaos factor: {state.chaos_factor}",
            f"Character JSON: {self._compact_character_json(state)}",
            f"Setting notes: {self._clip_prompt_text(state.setting_notes, 500)}",
            f"Player notes: {self._clip_prompt_text(state.player_notes, 350)}",
            f"Oracle outcome JSON: {self._compact_outcome_json(outcome)}",
        ]
        if memory_context:
            lines.extend(
                [
                    "Bounded memory context:",
                    memory_context,
                ],
            )
        if execution_context:
            lines.extend(
                [
                    "Executed backend steps:",
                    execution_context.removeprefix("Executed backend steps:\n"),
                ],
            )
        lines.extend(
            [
                "",
                (
                    "Write 1-2 compact paragraphs of playable narration, usually 1. "
                    "Use second person (`you`) for the player-character. "
                    "Mirror the player's action before extending the fiction. "
                    "Only harden facts that are supported by the supplied outcome/state. "
                    "End with one concrete prompt for action."
                ),
            ],
        )
        return "\n".join(lines)

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
                    "name": item.name,
                    "details": self._clip_prompt_text(item.details, 90),
                    "equipped": item.cairn.equipped,
                    "tags": [tag.value for tag in item.cairn.tags],
                    "uses": item.cairn.uses,
                    "damage_die": item.cairn.weapon_damage_die,
                    "armor_bonus": item.cairn.armor_bonus,
                    "slots": item.cairn.slots,
                }
                for item in character.inventory[:8]
            ],
        }
        return json.dumps(payload, separators=(",", ":"))

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
    # We pass both `reasoning_effort` (OpenAI-style alias) and `reasoning`
    # (OpenRouter-native nested config) because LiteLLM normalizes them
    # differently per provider. `drop_params=True` makes LiteLLM silently
    # drop whichever the chosen provider does not accept, instead of
    # raising `UnsupportedParamsError` and forcing us to branch by model.
    response = litellm_completion(
        model=request.model,
        messages=request.messages,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
        timeout=request.timeout,
        stream=request.stream,
        api_key=request.api_key,
        base_url=request.base_url,
        reasoning_effort=request.reasoning_effort,
        reasoning=request.reasoning,
        extra_headers=request.extra_headers,
        response_format=request.response_format,
        drop_params=True,
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
    stream = iter(cast("Iterable[object]", response))
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


def _env_bool(name: str, *, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, *, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _env_int(name: str, *, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _reasoning_policy_from_env() -> ReasoningPolicy:
    value = os.getenv("LITELLM_REASONING_EFFORT", DEFAULT_REASONING_POLICY)
    if value in VALID_REASONING_POLICIES:
        return value
    return DEFAULT_REASONING_POLICY
