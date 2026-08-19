from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from deepeval.models import DeepEvalBaseLLM
from pydantic import BaseModel, Field, TypeAdapter
from pydantic_core import ValidationError

from dungeon_master.config import LLMConfig
from dungeon_master.models import GameState, OracleKind, OracleOutcome, OracleTables
from dungeon_master.narrative import (
    LITELLM_RETRYABLE_ERRORS,
    ChatMessage,
    CompletionRequest,
    EmptyNarrativeResponseError,
    _completion,
    complete_text,
    extract_json_object,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

type EvalReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "default"]
NO_REASONING: dict[str, object] = {"effort": "none"}


EVAL_DATA_PATH = Path("tests/eval_data/pre_compression_baseline.json")
LEGACY_EVAL_DATA_PATH = Path("tests/eval_data/baseline.json")
EVAL_USER_INPUTS: tuple[str, ...] = (
    "I swing my sword at the goblin.",
    "I look around the room for traps.",
    "I try to talk my way past the guard.",
)


class EvalBaselineRecord(BaseModel):
    route: str
    target_name: str | None = None
    routed_text: str
    narration: str = Field(min_length=1)


type EvalBaseline = dict[str, EvalBaselineRecord]


@dataclass(frozen=True)
class EvalCase:
    user_input: str
    outcome: OracleOutcome
    execution_context: str


def sample_eval_state() -> GameState:
    return GameState(
        current_scene="A dark dungeon room.",
        setting_notes="A compact dungeon used for prompt drift evaluation.",
        player_notes="A cautious adventurer with a sword.",
        oracle_tables=OracleTables(
            event_focus=[
                "NPC action",
                "New NPC",
                "Move toward thread",
                "Move away from thread",
                "Close thread",
                "Ambiguous event",
            ],
            event_actions=[
                "attack",
                "reveal",
                "betray",
                "pursue",
                "hide",
                "break",
                "guard",
                "signal",
            ],
            event_tones=[
                "grim",
                "quiet",
                "urgent",
                "strange",
                "tense",
                "hopeful",
                "cold",
                "bright",
            ],
            event_subjects=[
                "goblin",
                "door",
                "torch",
                "guard",
                "trap",
                "altar",
                "coin",
                "blade",
            ],
        ),
    )


def eval_case_for(user_input: str) -> EvalCase:
    return EvalCase(
        user_input=user_input,
        outcome=OracleOutcome(
            kind=OracleKind.PLAYER_ACTION,
            question=f"Does the player succeed at: {user_input}?",
            summary="Success",
            chaos_factor=5,
        ),
        execution_context="Steps executed successfully.",
    )


def load_baseline(path: Path = EVAL_DATA_PATH) -> EvalBaseline | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not payload:
        return None
    return TypeAdapter(EvalBaseline).validate_python(payload)


def write_baseline(baseline: EvalBaseline, path: Path = EVAL_DATA_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        user_input: record.model_dump(mode="json")
        for user_input, record in sorted(baseline.items())
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def eval_llm_config(config: LLMConfig | None = None) -> LLMConfig:
    base = config or LLMConfig.from_env()
    return replace(base, temperature=0.2)


class MissingEvalConfigError(RuntimeError):
    pass


class LiteLLMDeepEvalJudge(DeepEvalBaseLLM):  # type: ignore[no-untyped-call]
    def __init__(
        self,
        config: LLMConfig | None = None,
        *,
        temperature: float = 0.0,
        max_tokens: int = 900,
        reasoning_effort: EvalReasoningEffort = "none",
    ) -> None:
        self._config = config or LLMConfig.from_env()
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._reasoning_effort: EvalReasoningEffort = reasoning_effort
        super().__init__(model=self._config.model)

    def load_model(self) -> LiteLLMDeepEvalJudge:
        return self

    def generate(self, *args: object, **kwargs: object) -> str:
        prompt = _prompt_from_args(args)
        schema = _schema_from_kwargs(kwargs)
        if schema is None:
            return self._generate_text(prompt)
        last_error: Exception | None = None
        for attempt in range(self._config.max_retries + 1):
            try:
                raw_text = self._generate_text(prompt, expect_json=True)
                return schema.model_validate_json(_extract_json(raw_text)).model_dump_json()
            except (ValidationError, EmptyNarrativeResponseError, *LITELLM_RETRYABLE_ERRORS) as exc:
                last_error = exc
                if attempt < self._config.max_retries:
                    time.sleep(0.4 * (attempt + 1))
        msg = "DeepEval judge did not return valid structured JSON."
        raise ValueError(msg) from last_error

    async def a_generate(self, *args: object, **kwargs: object) -> str:
        return await asyncio.to_thread(self.generate, *args, **kwargs)

    def get_model_name(self) -> str:
        return str(self._config.model)

    def supports_json_mode(self) -> bool:
        return True

    def supports_temperature(self) -> bool:
        return True

    def _generate_text(
        self,
        prompt: str | Sequence[ChatMessage],
        *,
        expect_json: bool = False,
    ) -> str:
        if not self._config.is_usable():
            msg = (
                "DeepEval judge needs a usable LLM config. Configure the same provider "
                "credentials used by the app before running live drift evals."
            )
            raise MissingEvalConfigError(msg)
        messages = (
            [{"role": "user", "content": prompt}]
            if isinstance(prompt, str)
            else [dict(message) for message in prompt]
        )
        reasoning = (
            NO_REASONING
            if self._reasoning_effort == "none"
            else self._config.profiles.turn_router.reasoning(default_exclude=True)
        )
        request = CompletionRequest(
            model=self._config.model,
            messages=messages,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            timeout=self._config.timeout_seconds,
            stream=False,
            api_key=self._config.api_key,
            base_url=self._config.base_url,
            reasoning_effort=self._reasoning_effort,
            reasoning=reasoning,
            extra_headers=self._openrouter_headers(),
            response_format={"type": "json_object"} if expect_json else None,
            trace_route="eval.drift",
            trace_profile="deepeval_judge",
        )
        completed = complete_text(request, _completion)
        text = completed.content.strip() or completed.thinking.strip()
        if not text:
            raise EmptyNarrativeResponseError
        return text

    def _openrouter_headers(self) -> dict[str, str] | None:
        if not self._config.model.startswith("openrouter/"):
            return None
        headers: dict[str, str] = {}
        if self._config.site_url is not None:
            headers["HTTP-Referer"] = self._config.site_url
        if self._config.app_name is not None:
            headers["X-Title"] = self._config.app_name
        return headers or None


def _extract_json(text: str) -> str:
    return extract_json_object(text)


def _prompt_from_args(args: tuple[object, ...]) -> str | Sequence[ChatMessage]:
    if not args:
        msg = "DeepEval judge called without a prompt."
        raise ValueError(msg)
    prompt = args[0]
    if isinstance(prompt, str):
        return prompt
    if _is_chat_message_sequence(prompt):
        return cast("Sequence[ChatMessage]", prompt)
    msg = "DeepEval judge prompt must be text or chat messages."
    raise TypeError(msg)


def _schema_from_kwargs(kwargs: dict[str, object]) -> type[BaseModel] | None:
    schema = kwargs.get("schema")
    if schema is None:
        return None
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        return schema
    msg = "DeepEval judge schema must be a Pydantic BaseModel subclass."
    raise TypeError(msg)


def _is_chat_message_sequence(value: object) -> bool:
    if not isinstance(value, list | tuple):
        return False
    return all(_is_chat_message(item) for item in value)


def _is_chat_message(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    role = value.get("role")
    content = value.get("content")
    return isinstance(role, str) and isinstance(content, str)
