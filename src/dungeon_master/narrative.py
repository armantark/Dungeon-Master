"""Stable public facade for LLM completion and narration services."""

from __future__ import annotations

from typing import TYPE_CHECKING

from litellm import completion as litellm_completion

from dungeon_master.config import (
    DEFAULT_MODEL,
    DEFAULT_REASONING_POLICY,
    VALID_REASONING_POLICIES,
    ReasoningEffort,
    ReasoningPolicy,
)
from dungeon_master.config import LLMConfig as NarrativeConfig
from dungeon_master.llm.completion import contracts as _completion_contracts
from dungeon_master.llm.completion import transport as _completion_transport
from dungeon_master.llm.narration import engine as _narration

if TYPE_CHECKING:
    from litellm.types.utils import ModelResponse

ChatMessage = _completion_contracts.ChatMessage
CompletionDelta = _completion_contracts.CompletionDelta
CompletionFunction = _completion_contracts.CompletionFunction
CompletionRequest = _completion_contracts.CompletionRequest
CompletionText = _completion_contracts.CompletionText
NarrativeResult = _completion_contracts.NarrativeResult
StreamStageStatus = _completion_contracts.StreamStageStatus
StreamStageUpdate = _completion_contracts.StreamStageUpdate

LITELLM_RETRYABLE_ERRORS = _completion_transport.LITELLM_RETRYABLE_ERRORS
EmptyNarrativeResponseError = _completion_transport.EmptyNarrativeResponseError
complete_text = _completion_transport.complete_text
extract_json_object = _completion_transport.extract_json_object
iter_text_deltas = _completion_transport.iter_text_deltas
iterate_text_deltas = _completion_transport.iterate_text_deltas

OUTMATCHED_THREAT_MARGIN = _narration.OUTMATCHED_THREAT_MARGIN
PARTY_ADVANTAGE_THREAT_MARGIN = _narration.PARTY_ADVANTAGE_THREAT_MARGIN
SYSTEM_PROMPT = _narration.SYSTEM_PROMPT
TACTICALLY_DANGEROUS_THREAT_MARGIN = _narration.TACTICALLY_DANGEROUS_THREAT_MARGIN
TERMINAL_NARRATION_PROMPT = _narration.TERMINAL_NARRATION_PROMPT
NarrativeEngine = _narration.NarrativeEngine

__all__ = [
    "DEFAULT_MODEL",
    "DEFAULT_REASONING_POLICY",
    "VALID_REASONING_POLICIES",
    "NarrativeConfig",
    "ReasoningEffort",
    "ReasoningPolicy",
]


def _completion(request: CompletionRequest) -> ModelResponse:
    """Compatibility hook that keeps provider monkeypatching at this facade."""
    return _completion_transport.provider_completion(request, litellm_completion)
