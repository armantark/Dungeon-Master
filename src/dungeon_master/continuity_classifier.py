from __future__ import annotations

import json
import re
import time
from enum import StrEnum

from dungeon_master.cancel import CancellationToken
from dungeon_master.models import GameState, OracleOutcome
from dungeon_master.narrative import (
    LITELLM_RETRYABLE_ERRORS,
    CompletionFunction,
    CompletionRequest,
    NarrativeConfig,
    _completion,
    complete_text,
)
from dungeon_master.observability import log_decision

CONTINUITY_CLASSIFIER_SYSTEM_PROMPT = """You decide whether a resolved turn is worth
running the expensive continuity updaters for.

Return exactly one lowercase token and nothing else:
- none
- threads
- npcs
- both

Choose:
- none: the turn is self-contained and very unlikely to create, advance, resolve,
  or clarify long-running threads or recurring NPCs
- threads: likely thread continuity only
- npcs: likely recurring-NPC continuity only
- both: both may matter, or there is enough uncertainty that skipping one would be risky

Be conservative.
If you are uncertain, return `both`.
Prefer `none` only when the turn looks obviously local/mechanical and not continuity-bearing.
"""

CONTINUITY_CLASSIFIER_USER_PROMPT_TEMPLATE = """Current scene:
<<CURRENT_SCENE>>

Player input:
<<PLAYER_INPUT>>

Resolved oracle outcome:
- kind: <<OUTCOME_KIND>>
- summary: <<OUTCOME_SUMMARY>>

Executed backend steps (may be empty):
<<EXECUTION_CONTEXT>>

Current threads:
<<THREADS>>

Visible recurring NPCs:
<<VISIBLE_NPCS>>

Hidden recurring NPCs:
<<HIDDEN_NPCS>>
"""

MAX_THREAD_LINES = 8
MAX_VISIBLE_NPC_LINES = 8
MAX_HIDDEN_NPC_LINES = 6
SCOPE_TOKEN_PATTERN = re.compile(r"\b(none|threads|npcs|both)\b")
SCOPE_VALUES = frozenset(("none", "threads", "npcs", "both"))


class ContinuityUpdateScope(StrEnum):
    NONE = "none"
    THREADS = "threads"
    NPCS = "npcs"
    BOTH = "both"

    def updates_threads(self) -> bool:
        return self in (ContinuityUpdateScope.THREADS, ContinuityUpdateScope.BOTH)

    def updates_npcs(self) -> bool:
        return self in (ContinuityUpdateScope.NPCS, ContinuityUpdateScope.BOTH)


class EmptyContinuityClassifierContentError(ValueError):
    pass


class UnsupportedContinuityScopeError(ValueError):
    pass


class ContinuityClassifier:
    def __init__(
        self,
        *,
        config: NarrativeConfig | None = None,
        completion_function: CompletionFunction = _completion,
    ) -> None:
        self._config = config or NarrativeConfig.from_env()
        self._completion = completion_function

    def classify_update_scope(
        self,
        state: GameState,
        *,
        player_input: str,
        outcome: OracleOutcome,
        execution_context: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> ContinuityUpdateScope:
        if not self._config.is_usable():
            scope = ContinuityUpdateScope.BOTH
            self._log_scope(scope, source="no_model")
            return scope

        prompt = self._build_prompt(
            state,
            player_input=player_input,
            outcome=outcome,
            execution_context=execution_context,
        )
        profile = self._config.profiles.continuity_classifier
        request = CompletionRequest(
            model=self._config.model,
            messages=[
                {"role": "system", "content": CONTINUITY_CLASSIFIER_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
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
            trace_route="continuity_classifier.scope",
            trace_profile="continuity_classifier",
        )

        try:
            content = self._complete_keyword(request)
            scope = self._parse_scope(content)
            self._log_scope(scope, source="model")
        except ValueError:
            scope = ContinuityUpdateScope.BOTH
            self._log_scope(scope, source="fallback")
            return scope
        else:
            return scope

    def _build_prompt(
        self,
        state: GameState,
        *,
        player_input: str,
        outcome: OracleOutcome,
        execution_context: str | None,
    ) -> str:
        return (
            CONTINUITY_CLASSIFIER_USER_PROMPT_TEMPLATE.replace(
                "<<CURRENT_SCENE>>",
                state.current_scene,
            )
            .replace("<<PLAYER_INPUT>>", player_input.strip())
            .replace("<<OUTCOME_KIND>>", outcome.kind.value)
            .replace("<<OUTCOME_SUMMARY>>", outcome.summary)
            .replace("<<EXECUTION_CONTEXT>>", execution_context or "(none)")
            .replace("<<THREADS>>", _render_threads(state))
            .replace("<<VISIBLE_NPCS>>", _render_visible_npcs(state))
            .replace("<<HIDDEN_NPCS>>", _render_hidden_npcs(state))
        )

    def _complete_keyword(self, request: CompletionRequest) -> str:
        last_error: Exception | None = None
        for attempt in range(self._config.max_retries + 1):
            try:
                completed = complete_text(request, self._completion)
                content = completed.content.strip()
                if content:
                    return content
                _raise_empty_continuity_classifier_content_error()
            except (
                *LITELLM_RETRYABLE_ERRORS,
                EmptyContinuityClassifierContentError,
                UnsupportedContinuityScopeError,
                ValueError,
            ) as exc:
                last_error = exc
                if attempt < self._config.max_retries:
                    time.sleep(0.25 * (attempt + 1))
        message = str(last_error) if last_error else "Continuity classification failed."
        raise ValueError(message)

    def _parse_scope(self, content: str) -> ContinuityUpdateScope:
        normalized = " ".join(content.strip().lower().split())
        if normalized in SCOPE_VALUES:
            return ContinuityUpdateScope(normalized)
        if normalized.startswith("{"):
            parsed = json.loads(normalized)
            if isinstance(parsed, dict):
                raw_scope = parsed.get("scope")
                if isinstance(raw_scope, str):
                    collapsed_scope = " ".join(raw_scope.strip().lower().split())
                    if collapsed_scope in SCOPE_VALUES:
                        return ContinuityUpdateScope(collapsed_scope)
        match = SCOPE_TOKEN_PATTERN.search(normalized)
        if match is not None:
            return ContinuityUpdateScope(match.group(1))
        _raise_unsupported_continuity_scope_error(content)
        return ContinuityUpdateScope.BOTH

    def _openrouter_headers(self) -> dict[str, str] | None:
        if not self._config.model.startswith("openrouter/"):
            return None
        headers: dict[str, str] = {}
        if self._config.site_url is not None:
            headers["HTTP-Referer"] = self._config.site_url
        if self._config.app_name is not None:
            headers["X-Title"] = self._config.app_name
        return headers or None

    def _log_scope(self, scope: ContinuityUpdateScope, *, source: str) -> None:
        log_decision(
            "continuity.classifier",
            scope=scope.value,
            source=source,
        )


def _render_threads(state: GameState) -> str:
    if not state.threads:
        return "(none)"
    lines = [
        f"- [{thread.status.value}] {thread.title}"
        for thread in state.threads[:MAX_THREAD_LINES]
    ]
    remaining = len(state.threads) - len(lines)
    if remaining > 0:
        lines.append(f"- ... {remaining} more")
    return "\n".join(lines)


def _render_visible_npcs(state: GameState) -> str:
    if not state.npcs:
        return "(none)"
    lines = [
        f"- [{npc.status.value}] {npc.display_label()} ({npc.role or 'no role'})"
        for npc in state.npcs[:MAX_VISIBLE_NPC_LINES]
    ]
    remaining = len(state.npcs) - len(lines)
    if remaining > 0:
        lines.append(f"- ... {remaining} more")
    return "\n".join(lines)


def _render_hidden_npcs(state: GameState) -> str:
    if not state.hidden_npcs:
        return "(none)"
    lines = [
        f"- [{npc.status.value}] {npc.name} ({npc.role or 'no role'})"
        for npc in state.hidden_npcs[:MAX_HIDDEN_NPC_LINES]
    ]
    remaining = len(state.hidden_npcs) - len(lines)
    if remaining > 0:
        lines.append(f"- ... {remaining} more")
    return "\n".join(lines)


def _raise_empty_continuity_classifier_content_error() -> None:
    message = "Continuity classifier returned empty content."
    raise EmptyContinuityClassifierContentError(message)


def _raise_unsupported_continuity_scope_error(content: str) -> None:
    message = f"Unsupported continuity scope: {content}"
    raise UnsupportedContinuityScopeError(message)
