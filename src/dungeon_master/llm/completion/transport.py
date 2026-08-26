from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterable, Iterator
from typing import TYPE_CHECKING, cast

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
from dungeon_master.llm.completion.contracts import (
    CompletionDelta,
    CompletionFunction,
    CompletionRequest,
    CompletionText,
)
from dungeon_master.observability import (
    LLMCallRecord,
    log_llm_call,
    request_id_from_cancel_token,
)

if TYPE_CHECKING:
    from litellm.types.utils import ModelResponse


class EmptyNarrativeResponseError(ValueError):
    pass


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


def provider_completion(
    request: CompletionRequest,
    provider: Callable[..., object] = litellm_completion,
) -> ModelResponse:
    _raise_if_cancelled(request.cancel_token)
    reasoning_effort = None if "max_tokens" in request.reasoning else request.reasoning_effort
    started = time.perf_counter()
    response = provider(
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
    content, content_thinking = _extract_content_and_thinking(message)
    return CompletionText(
        content=content,
        thinking=_extract_text(
            _get_field(message, "reasoning_content")
            or _get_field(message, "reasoning")
            or _get_field(message, "thinking")
            or _provider_reasoning(message),
        )
        or content_thinking,
    )


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
            content, content_thinking = _extract_content_and_thinking(delta)
            thinking = (
                _extract_text(
                    _get_field(delta, "reasoning_content")
                    or _get_field(delta, "reasoning")
                    or _get_field(delta, "thinking")
                    or _provider_reasoning(delta)
                    or _provider_reasoning(choice)
                    or _provider_reasoning(chunk),
                )
                or content_thinking
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


def _extract_content_and_thinking(obj: object) -> tuple[str, str]:
    content = _get_field(obj, "content")
    if content is not None:
        return _extract_text_parts(content)
    return (_extract_text(_get_field(obj, "text")), "")


def _extract_text_parts(value: object) -> tuple[str, str]:
    if isinstance(value, list):
        content_parts: list[str] = []
        thinking_parts: list[str] = []
        for part in value:
            content, thinking = _extract_text_part(part)
            if content:
                content_parts.append(content)
            if thinking:
                thinking_parts.append(thinking)
        return ("".join(content_parts), "".join(thinking_parts))
    nested_parts = _get_field(value, "parts")
    if nested_parts is not None:
        return _extract_text_parts(nested_parts)
    return (_extract_text(value), "")


def _extract_text_part(part: object) -> tuple[str, str]:
    text = _extract_text(part)
    if not text:
        return ("", "")
    if _part_is_thought(part):
        return ("", text)
    return (text, "")


def _part_is_thought(part: object) -> bool:
    part_type = _get_field(part, "type")
    if isinstance(part_type, str) and part_type.lower() in {"thinking", "thought", "reasoning"}:
        return True
    return any(
        _get_field(part, field) is True
        for field in ("thought", "thinking", "is_thought", "isThinking")
    )


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
            or value.get("value"),
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
