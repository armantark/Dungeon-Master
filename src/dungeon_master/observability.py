from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Literal, cast

from dungeon_master.cancel import CancellationToken

LOG_LEVELS = frozenset({"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"})
TRACE_LOGGER = logging.getLogger("dungeon_master.trace")

type LogLevel = Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"]


def log_level_from_env(*, default: LogLevel = "INFO") -> LogLevel:
    raw = os.getenv("DM_LOG_LEVEL", default).strip().upper()
    if raw in LOG_LEVELS:
        return cast("LogLevel", raw)
    return default


def request_id_from_cancel_token(cancel_token: CancellationToken | None) -> str | None:
    if cancel_token is None:
        return None
    return cancel_token.request_id


@dataclass(frozen=True)
class LLMCallRecord:
    route: str | None
    profile: str | None
    request_id: str | None
    model: str
    stream: bool
    duration_ms: int
    response: object


def log_llm_call(record: LLMCallRecord) -> None:
    prompt_tokens, completion_tokens = _usage_tokens(record.response)
    TRACE_LOGGER.info(
        "llm.call %s",
        _format_fields(
            {
                "route": record.route,
                "profile": record.profile,
                "request_id": record.request_id,
                "model": record.model,
                "stream": record.stream,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "duration_ms": record.duration_ms,
            },
        ),
    )


def log_decision(kind: str, **fields: object) -> None:
    TRACE_LOGGER.info("%s %s", kind, _format_fields(fields))


def _usage_tokens(response: object) -> tuple[int | None, int | None]:
    usage = _get_field(response, "usage")
    if usage is None:
        return (None, None)
    prompt_tokens = _coerce_int(_get_field(usage, "prompt_tokens"))
    completion_tokens = _coerce_int(_get_field(usage, "completion_tokens"))
    return (prompt_tokens, completion_tokens)


def _coerce_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    return None


def _get_field(obj: object, name: str) -> object | None:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _format_fields(fields: dict[str, object]) -> str:
    return " ".join(f"{key}={_format_value(value)}" for key, value in fields.items())


def _format_value(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return json.dumps(str(value))
