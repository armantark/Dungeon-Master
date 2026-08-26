from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from dungeon_master.cancel import CancellationToken
from dungeon_master.config import ReasoningEffort

if TYPE_CHECKING:
    from litellm.types.utils import ModelResponse

type ChatMessage = dict[str, str]


class CompletionFunction(Protocol):
    def __call__(self, request: CompletionRequest) -> ModelResponse:
        raise NotImplementedError


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
