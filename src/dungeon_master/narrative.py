from __future__ import annotations

import os
import time
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
REASONING_BY_TASK: dict[OracleKind, ReasoningEffort] = {
    OracleKind.YES_NO: "medium",
    OracleKind.PLAYER_ACTION: "medium",
    OracleKind.RANDOM_EVENT: "high",
    OracleKind.SCENE_CHECK: "high",
}

SYSTEM_PROMPT = """You are the narrative voice for a solo tabletop role-playing game.

Hard boundaries:
- You do not roll dice.
- You do not change chaos factor, threads, NPCs, inventory, or canonical state.
- You only narrate from the structured oracle outcome and state supplied by the app.
- If mechanics are unclear, make the fiction tense but do not invent new mechanical facts.

Tone:
Gritty, traditional dark fantasy with historically grounded detail. Avoid modern idioms,
meta-commentary, culture-war references, and cozy wish fulfillment. Keep prose vivid,
concrete, and playable.
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


@dataclass(frozen=True)
class NarrativeConfig:
    model: str
    api_key: str | None
    base_url: str | None
    reasoning_policy: ReasoningPolicy = DEFAULT_REASONING_POLICY
    exclude_reasoning: bool = True
    temperature: float = 0.85
    max_tokens: int = 1800
    timeout_seconds: float = 90.0
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
            exclude_reasoning=_env_bool("LITELLM_EXCLUDE_REASONING", default=True),
            temperature=_env_float("LITELLM_TEMPERATURE", default=0.85),
            max_tokens=_env_int("LITELLM_MAX_TOKENS", default=1800),
            timeout_seconds=_env_float("LITELLM_TIMEOUT_SECONDS", default=90.0),
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

    def generate(self, state: GameState, outcome: OracleOutcome, player_input: str) -> str:
        if not self._config.is_usable():
            return self._fallback_narration(state, outcome, player_input)

        prompt = self._build_user_prompt(state, outcome, player_input)
        messages: list[ChatMessage] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        reasoning: dict[str, object] = {
            "effort": self._reasoning_effort_for(outcome),
            "exclude": self._config.exclude_reasoning,
        }
        request = CompletionRequest(
            model=self._config.model,
            messages=messages,
            temperature=self._config.temperature,
            max_tokens=self._config.max_tokens,
            timeout=self._config.timeout_seconds,
            stream=False,
            api_key=self._config.api_key,
            base_url=self._config.base_url,
            reasoning_effort=self._reasoning_effort_for(outcome),
            reasoning=reasoning,
            extra_headers=self._openrouter_headers(),
            response_format=None,
        )

        last_error: Exception | None = None
        for attempt in range(self._config.max_retries + 1):
            try:
                response = self._completion(request)
                content = response.choices[0].message.content
                if content:
                    return content.strip()
                raise EmptyNarrativeResponseError
            except LITELLM_RETRYABLE_ERRORS as exc:
                last_error = exc
                if attempt < self._config.max_retries:
                    time.sleep(0.4 * (attempt + 1))

        fallback = self._fallback_narration(state, outcome, player_input)
        if last_error is None:
            return fallback
        return f"{fallback}\n\n[Narrative API unavailable: {last_error}]"

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

    def _build_user_prompt(
        self,
        state: GameState,
        outcome: OracleOutcome,
        player_input: str,
    ) -> str:
        return "\n".join(
            [
                f"Player input: {player_input}",
                f"Current scene: {state.current_scene}",
                f"Scene status: {state.scene_status.value}",
                f"Chaos factor: {state.chaos_factor}",
                f"Setting notes: {state.setting_notes}",
                f"Player notes: {state.player_notes}",
                f"Oracle outcome JSON: {outcome.model_dump_json()}",
                "",
                (
                    "Write 1-3 paragraphs of playable narration. "
                    "End with a concrete prompt for action."
                ),
            ],
        )

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
